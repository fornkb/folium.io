"""Lesson tutor boundaries, durable turns, backup recovery and provider streaming."""
import copy
import io
import json
import threading
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import Mock, patch

from app import create_server
from configuration import Settings
from core import Store
from fixtures import seed_test_course
from test_core import test_directory
from tutor import Groq, Tutor, context_for, export_turns, validate_backup


class TutorTests(unittest.TestCase):
    def setUp(self):
        self.temp=test_directory()
        self.server=create_server(self.temp.name,0,env_file=self.temp.name+'/.env')
        self.store=self.server.store
        self.course=seed_test_course(self.store)
        self.server.settings.save(dict(groq_api_key='synthetic-groq-key'))
        self.provider=Mock()
        self.provider.stream.return_value=iter([dict(text='A fresh '),dict(text='explanation with \\(x^2\\).'),dict(usage=dict(total_tokens=42))])
        self.server.tutor.provider=self.provider
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.path=f"/api/courses/{self.course['id']}/modules/m1/tutor"

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.store.close();self.temp.cleanup()

    def body(self,**changes):
        return dict(request_id=uuid.uuid4().hex,thread_id=uuid.uuid4().hex,lesson_id='module',question='Explain the core concept.',selection='',section_index=0,**changes)

    def request(self,path,body=None):
        req=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:
            if response.headers.get('Content-Type','').startswith('application/x-ndjson'):
                return [json.loads(line) for line in response if line.strip()]
            return json.load(response)

    def test_stream_is_saved_before_done_and_duplicate_request_reuses_answer(self):
        before=copy.deepcopy(self.store.course(self.course['id']))
        body=self.body()
        events=self.request(self.path,body)
        self.assertEqual(['start','delta','delta','done'],[e['event'] for e in events])
        turn=events[-1]['turn'];self.assertEqual('complete',turn['status'])
        self.assertEqual(42,turn['usage']['total_tokens'])
        history=self.request(self.path)
        self.assertEqual(turn,history['turns'][0])
        self.assertEqual(before,self.store.course(self.course['id']),'Chat must not rewrite saved teaching or study state.')
        again=self.request(self.path,body)
        self.assertTrue(again[0]['reused']);self.assertEqual(turn,again[0]['turn'])
        self.provider.stream.assert_called_once()
        self.assertNotIn('synthetic-groq-key',json.dumps(events))
        body['question']='A different question'
        with self.assertRaises(urllib.error.HTTPError) as error:self.request(self.path,body)
        self.assertEqual(400,error.exception.code)

    def test_offline_history_and_study_never_call_provider(self):
        with patch('generation.Gemini.generate',side_effect=AssertionError('Offline study')):
            self.request(self.path)
            self.request('/api/courses')
            self.request(f"/api/courses/{self.course['id']}")
            self.request(self.path.replace('/tutor','/progress'),dict(read=True,notes='My notes'))
        self.provider.stream.assert_not_called()
        self.server.settings.save(dict(clear_groq_key=True))
        self.assertEqual([],self.request(self.path)['turns'])
        with self.assertRaises(urllib.error.HTTPError) as error:self.request(self.path,self.body())
        self.assertIn('Groq key',error.exception.read().decode())
        self.provider.stream.assert_not_called()

    def test_partial_failure_is_saved_and_explicit_retry_needs_a_new_id(self):
        def failed(*args):
            yield dict(text='A partial thought')
            raise ValueError('Groq returned HTTP 429. Wait before trying again.')
        self.provider.stream.side_effect=failed
        body=self.body();events=self.request(self.path,body)
        self.assertEqual('error',events[-1]['turn']['status'])
        self.assertEqual('A partial thought',self.request(self.path)['turns'][0]['answer'])
        self.request(self.path,body);self.assertEqual(1,self.provider.stream.call_count)
        body['request_id']=uuid.uuid4().hex
        self.request(self.path,body);self.assertEqual(2,self.provider.stream.call_count)

    def test_inflight_request_cannot_be_sent_twice(self):
        body=self.body();generator=self.server.tutor.answer(self.course['id'],'m1',body)
        self.assertEqual('start',next(generator)['event'])
        with self.assertRaisesRegex(ValueError,'still being saved'):
            next(self.server.tutor.answer(self.course['id'],'m1',body))
        other=self.body();other['thread_id']=body['thread_id']
        with self.assertRaisesRegex(ValueError,'current reply'):
            next(self.server.tutor.answer(self.course['id'],'m1',other))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(f"/api/courses/{self.course['id']}/delete",dict(confirm=self.course['id']))
        self.assertIn('tutor reply',error.exception.read().decode())
        generator.close()
        self.assertEqual('interrupted',self.request(self.path)['turns'][0]['status'])
        self.provider.stream.assert_not_called()

    def test_recent_history_and_selected_text_are_sent_as_reference_data(self):
        body=self.body();body['selection']='Synthetic explanation'
        self.request(self.path,body)
        follow=self.body();follow['thread_id']=body['thread_id'];follow['question']='Why?'
        self.provider.stream.return_value=iter([dict(text='Because of the definition.')])
        self.request(self.path,follow)
        _,_,messages=self.provider.stream.call_args.args
        self.assertEqual('system',messages[0]['role'])
        data=json.loads(messages[1]['content'].split('\n',1)[1])
        self.assertTrue(data['lesson_context_complete'])
        self.assertEqual(3,len(data['sections']))
        self.assertNotIn('doc_id',json.dumps(data))
        self.assertIn('Synthetic explanation',messages[2]['content'])
        self.assertEqual('assistant',messages[3]['role'])
        self.assertEqual('Why?',messages[-1]['content'])

    def test_cross_lesson_context_and_invalid_inputs_are_rejected_before_provider(self):
        course=self.store.course(self.course['id'])
        sections=course['modules'][0]['package']['sections']
        sections[0].update(lesson_id='l1',lesson_title='First lesson')
        sections[1].update(lesson_id='l2',lesson_title='Second lesson')
        sections[2].update(lesson_id='l2',lesson_title='Second lesson')
        self.store.save(course)
        bads=[dict(lesson_id='l1',section_index=1),dict(lesson_id='missing'),dict(section_index=True),dict(question='x'*4001),dict(selection='x',section_index=None),dict(request_id='bad')]
        for change in bads:
            body=self.body();body.update(lesson_id='l1');body.update(change)
            with self.subTest(change=change),self.assertRaises(urllib.error.HTTPError):self.request(self.path,body)
        self.provider.stream.assert_not_called()
        body=self.body();body.update(lesson_id='l1',section_index=0)
        self.request(self.path,body)
        other=self.body();other.update(thread_id=body['thread_id'],lesson_id='l2',section_index=1)
        with self.assertRaises(urllib.error.HTTPError):self.request(self.path,other)
        _,_,messages=self.provider.stream.call_args.args
        self.assertNotIn('Formal definition',messages[1]['content'])

    def test_large_lesson_context_is_bounded_and_finds_late_selected_example(self):
        module=copy.deepcopy(self.course['modules'][0]);module['package']['sections'][0]['body']='Filler '*10000+'LATE EXAMPLE '+('Tail '*10000)
        data,meta=context_for(self.course,module,'module','Explain the example',0,'LATE EXAMPLE')
        self.assertLess(len(json.dumps(data)),44000)
        self.assertIn('LATE EXAMPLE',data['sections'][0]['body'])
        self.assertFalse(meta['complete']);self.assertTrue(data['sections'][0]['excerpt'])

    def test_backup_round_trip_remaps_conversations_and_deletion_recovery(self):
        self.request(self.path,self.body())
        archive=self.store.export(self.course['id'])
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertNotIn('synthetic-groq-key',z.read('folium.json').decode())
        restored=self.store.import_course(archive)
        turns=export_turns(self.store,restored['id'])
        original=export_turns(self.store,self.course['id'])[0]
        self.assertEqual(original['answer'],turns[0]['answer'])
        self.assertEqual(original['context'],turns[0]['context'])
        self.assertNotEqual(original['id'],turns[0]['id'])
        self.assertNotEqual(original['thread_id'],turns[0]['thread_id'])
        self.assertEqual(1,len(self.server.tutor.history(restored['id'],'m1')['turns']))
        info=self.server.jobs.delete_course(self.course['id'])
        self.assertEqual([],export_turns(self.store,self.course['id']))
        recovered=self.store.import_course((self.store.root/'backups'/info['recovery_backup']).read_bytes())
        self.assertEqual(original['answer'],export_turns(self.store,recovered['id'])[0]['answer'])

    def test_invalid_backup_tutor_anchors_are_rejected_before_creating_course(self):
        self.request(self.path,self.body())
        row=export_turns(self.store,self.course['id'])[0]
        for change in (dict(module_id='missing'),dict(lesson_id='missing'),dict(answer='x'*24001),dict(context=dict(teaching_hash='f'*64,complete=True,sections=[dict(index=999,title='Fake',excerpt=False)]))):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_backup([dict(row,**change)],self.course['modules'])
        row['section_index']=999
        archive=self.store.export(self.course['id']);altered=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(archive)) as source,zipfile.ZipFile(altered,'w') as target:
            for name in source.namelist():
                raw=source.read(name)
                if name=='folium.json':
                    manifest=json.loads(raw);manifest['tutor']=[row];raw=json.dumps(manifest).encode()
                target.writestr(name,raw)
        before=len(self.store.courses())
        with self.assertRaises(ValueError):self.store.import_course(altered.getvalue())
        self.assertEqual(before,len(self.store.courses()))

    def test_restart_preserves_completed_turns_and_marks_unfinished_reply(self):
        self.request(self.path,self.body())
        turn=export_turns(self.store,self.course['id'])[0]
        turn.update(status='streaming');self.server.tutor._save(turn)
        reopened=Store(self.temp.name)
        try:
            tutor=Tutor(reopened,self.server.settings,self.provider)
            recovered=tutor.history(self.course['id'],'m1')['turns'][0]
            self.assertEqual('interrupted',recovered['status']);self.assertEqual(turn['answer'],recovered['answer'])
        finally:reopened.close()


class GroqStreamTests(unittest.TestCase):
    def response(self,packets):
        value=io.BytesIO(b''.join(('data: '+(p if isinstance(p,str) else json.dumps(p))+'\n\n').encode() for p in packets))
        value.headers={'Content-Type':'text/event-stream'}
        return value

    def test_valid_stream_and_usage_without_exposing_reasoning(self):
        packets=[dict(choices=[dict(delta=dict(reasoning='internal',content='Hello λ'),finish_reason=None)]),dict(choices=[dict(delta={},finish_reason='stop')]),dict(choices=[],usage=dict(total_tokens=12)), '[DONE]']
        with patch('tutor.urllib.request.urlopen',return_value=self.response(packets)) as call:
            self.assertEqual([dict(text='Hello λ'),dict(usage=dict(total_tokens=12))],list(Groq().stream('secret','openai/gpt-oss-120b',[dict(role='user',content='Hello')])) )
        self.assertEqual(120,call.call_args.kwargs['timeout'])
        request=call.call_args.args[0];self.assertEqual('https://api.groq.com/openai/v1/chat/completions',request.full_url)

    def test_truncated_malformed_and_unfinished_streams_are_errors(self):
        for packets in ([dict(choices=[dict(delta=dict(content='Partial'),finish_reason='length')]),'[DONE]'],['{bad json}'],[dict(choices=[dict(delta=dict(content='Partial'),finish_reason=None)])]):
            with self.subTest(packets=packets),patch('tutor.urllib.request.urlopen',return_value=self.response(packets)),self.assertRaises(ValueError):list(Groq().stream('secret','model',[]))

    def test_http_error_never_exposes_provider_body_or_key(self):
        error=urllib.error.HTTPError('https://api.groq.com',429,'secret-key-in-body',{},io.BytesIO(b'secret-key-in-body'))
        with patch('tutor.urllib.request.urlopen',side_effect=error),self.assertRaisesRegex(ValueError,'HTTP 429') as caught:list(Groq().stream('secret-key-in-body','model',[]))
        self.assertNotIn('secret',str(caught.exception))


class GroqSettingsTests(unittest.TestCase):
    def test_groq_environment_key_is_private_and_separate_from_gemini(self):
        with test_directory() as directory,patch('configuration.environment_values',return_value={}):
            from pathlib import Path
            root=Path(directory);env=root/'.env';env.write_text('GROQ_API_KEY=environment-secret\nGROQ_MODEL=openai/gpt-oss-20b\n')
            settings=Settings(root,env_file=env)
            self.assertFalse(settings.public()['has_key']);self.assertTrue(settings.public()['groq_has_key'])
            self.assertEqual('env_file',settings.public()['groq_key_source'])
            settings.save(dict(interval=12,groq_api_key=''))
            self.assertNotIn('environment-secret',settings.path.read_text())
            self.assertNotIn('environment-secret',json.dumps(settings.public()))
            settings.save(dict(groq_api_key='saved-secret'))
            self.assertEqual('saved-secret',settings.get()['groq_api_key'])
            settings.save(dict(clear_groq_key=True))
            self.assertEqual('environment-secret',settings.get()['groq_api_key'])
            with self.assertRaises(ValueError):settings.save(dict(groq_model='https://evil.test?key=secret'))


if __name__=='__main__':unittest.main()
