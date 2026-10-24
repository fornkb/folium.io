"""Synthetic scans and logo/diagram fixtures; all provider calls are simulated."""
import copy
import hashlib
import io
import json
import unittest
import threading
import urllib.request
import urllib.error
import time
from pathlib import Path
from functools import lru_cache
from unittest.mock import patch

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject, NumberObject

from core import Store
from app import create_server
from configuration import Settings
from generation import Jobs, Gemini, ProviderError, VISUAL_SCOPE, scoped_excerpts
from scope import records_for, coverage
from visual import (inspect_documents, select_pages, analysis_batches, validate_visual_response,
                    recognized_sources, page_results, validate_saved_visual)
from fixtures import pdf_fixture, lesson_fixture, TEST_MODULES
from test_scope import ScopeProvider
from test_core import test_directory


def raster(number=1):
    image=Image.new("RGB",(600,800),"white");draw=ImageDraw.Draw(image)
    for i,line in enumerate([f"SCANNED LESSON {number}","Eigenvalues and eigenvectors","Find roots of det(A - lambda I).","Keep sign conventions consistent."]):
        draw.text((35,90+i*60),line,fill="black")
    draw.rectangle((50,400,200,500),outline="black",width=3)
    draw.line((200,450,350,450),fill="black",width=3)
    draw.rectangle((350,400,500,500),outline="black",width=3)
    return image


@lru_cache(maxsize=8)
def scanned_pdf(count=2):
    images=[raster(i+1) for i in range(count)];out=io.BytesIO()
    try:images[0].save(out,format="PDF",save_all=True,append_images=images[1:],resolution=100)
    finally:
        for image in images:image.close()
    return out.getvalue()


def add_image(writer,page,image,name,box):
    stream=DecodedStreamObject();stream.set_data(image.tobytes())
    stream.update({NameObject("/Type"):NameObject("/XObject"),NameObject("/Subtype"):NameObject("/Image"),
                   NameObject("/Width"):NumberObject(image.width),NameObject("/Height"):NumberObject(image.height),
                   NameObject("/ColorSpace"):NameObject("/DeviceRGB"),NameObject("/BitsPerComponent"):NumberObject(8)})
    resources=page["/Resources"]
    if "/XObject" not in resources:resources[NameObject("/XObject")]=DictionaryObject()
    resources["/XObject"][NameObject('/'+name)]=writer._add_object(stream.flate_encode())
    x,y,w,h=box;contents=page.get_contents();old=contents.get_data() if contents is not None else b''
    commands=DecodedStreamObject();commands.set_data(old+f'\nq {w} 0 0 {h} {x} {y} cm /{name} Do Q'.encode())
    page[NameObject("/Contents")]=writer._add_object(commands)


@lru_cache(maxsize=2)
def mixed_pdf(diagram=False):
    writer=PdfWriter();writer.append(PdfReader(io.BytesIO(pdf_fixture())))
    logo=Image.new("RGB",(80,40),"darkgreen");ImageDraw.Draw(logo).text((5,12),"INSTITUTE",fill="white")
    for page in writer.pages:add_image(writer,page,logo,"Logo",(530,800,36,24))
    logo.close()
    if diagram:
        image=raster(9);add_image(writer,writer.pages[2],image,"Diagram",(60,250,420,400));image.close()
    out=io.BytesIO();writer.write(out);return out.getvalue()


class VisualProvider(ScopeProvider):
    def __init__(self,store,doc_id=None):
        super().__init__(doc_id);self.settings=Settings(store.root,env_file=store.root/'absent.env')
        self.settings.save(dict(vision_model="gemini-vision-test"));self.pdfs=[]

    def generate(self,prompt,schema,validator,**kwargs):
        if schema!=VISUAL_SCOPE:return super().generate(prompt,schema,validator)
        self.calls.append((schema,prompt));self.pdfs.append(kwargs["pdf"])
        if len(self.calls)==self.fail_at:raise ProviderError("Quota pause")
        pages=PdfReader(io.BytesIO(kwargs["pdf"])).pages
        return validator(dict(pages=[dict(index=i+1,status="mapped",reason="",recognized_text="Complexity scanned text with eigenvalue conventions.",
            visual_description="A teaching flow diagram connects two states.",records=[dict(title="Eigenvalues",subtopics=["Characteristic equation"],depth="Compute eigenvalues and interpret the diagram.",methods=["Characteristic roots"],conventions=["Check the sign in A - lambda I"],uncertainties=[])]) for i in range(len(pages))]))


class VisualTests(unittest.TestCase):
    def setup_course(self,folder,raw,name="scanned.pdf"):
        store=Store(folder);course=store.create("Visual test");doc=store.add_pdf(course["id"],name,"material",raw)
        return store,course,doc

    def test_scanned_upload_is_saved_without_native_text(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf())
            self.assertTrue(all(not t.strip() for t in doc["pages"]))
            self.assertEqual(hashlib.sha256(scanned_pdf()).hexdigest(),doc["digest"]);store.close()

    def test_logos_on_readable_pages_do_not_select_them_for_recognition(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,mixed_pdf())
            self.assertTrue(all("Complexity" in text for text in doc["pages"]))
            visual=inspect_documents(store.docs(c["id"]),lambda did:store.document(did)[0])
            self.assertFalse(any(r["selected"] for r in visual["pages"]))
            self.assertTrue(all(r["ignored_images"]==1 and len(r["masks"])==1 for r in visual["pages"]))
            self.assertTrue(visual["selection_reviewed"]);store.close()

    def test_mixed_diagram_is_selected_without_selecting_logo_only_pages(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,mixed_pdf(True))
            visual=inspect_documents(store.docs(c["id"]),lambda did:store.document(did)[0])
            self.assertEqual([3],[r["page"] for r in visual["pages"] if r["selected"]])
            self.assertFalse(visual["selection_reviewed"]);store.close()

    def test_combined_pdf_spans_documents_and_maps_originals(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf(1))
            second=store.add_pdf(c["id"],"other.pdf","material",scanned_pdf(2))
            docs=store.docs(c["id"]);visual=inspect_documents(docs,lambda did:store.document(did)[0])
            batches=analysis_batches(visual,docs,lambda did:store.document(did)[0],store.root/'analysis')
            self.assertEqual(1,len(batches));batch=batches[0]
            self.assertEqual(2,len(PdfReader(batch["path"]).pages))
            aliases=[a for m in batch["manifest"] for a in m["aliases"]]
            self.assertEqual({(doc["id"],1),(second["id"],1),(second["id"],2)}, {(a["doc_id"],a["page"]) for a in aliases})
            self.assertEqual(3,len(aliases));store.close()

    def test_manual_selection_checks_page_identity_and_keeps_exclusions_explicit(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,mixed_pdf())
            visual=inspect_documents(store.docs(c["id"]),lambda did:store.document(did)[0])
            with self.assertRaises(ValueError):select_pages(visual,[dict(doc_id=doc["id"],page=999)])
            select_pages(visual,[dict(doc_id=doc["id"],page=2)])
            self.assertEqual([2],[r["page"] for r in visual["pages"] if r["selected"]])
            self.assertTrue(visual["selection_reviewed"]);store.close()

    def test_outline_waits_for_explicit_visual_analysis(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf())
            fake=VisualProvider(store,doc["id"]);jobs=Jobs(store,fake)
            with self.assertRaisesRegex(ValueError,"Review visual pages"):jobs._outline(c["id"])
            self.assertEqual([],fake.calls);self.assertFalse(store.course(c["id"])["visual"]["selection_reviewed"]);store.close()

    def prepare(self,store,c,fake):
        jobs=Jobs(store,fake);visual=jobs._inspect(c["id"])
        selected=[dict(doc_id=r["doc_id"],page=r["page"]) for r in visual["pages"] if r["selected"]]
        select_pages(visual,selected);store.update(c["id"],lambda course:course.update(visual=visual))
        jobs._visual(c["id"]);return jobs

    def test_visual_scope_merges_into_outline_without_second_scope_analysis(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf())
            fake=VisualProvider(store,doc["id"]);jobs=self.prepare(store,c,fake);jobs._outline(c["id"])
            c=store.course(c["id"])
            self.assertEqual(2,len(records_for(c["scope"])))
            self.assertEqual(2,coverage(c["scope"])["processed_pages"])
            self.assertEqual([],coverage(c["scope"])["unresolved"])
            self.assertEqual(2,len(fake.calls)) # one visual batch + one outline
            self.assertEqual(2,len(c["modules"][0]["scope_ids"]))
            self.assertTrue(all(r["origin"]=="visual_interpretation" for r in records_for(c["scope"])));store.close()

    def test_native_and_visual_scope_are_both_preserved(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,mixed_pdf(True))
            fake=VisualProvider(store,doc["id"]);jobs=self.prepare(store,c,fake);jobs._outline(c["id"])
            records=records_for(store.course(c["id"])["scope"])
            self.assertTrue(any(r.get("origin")=="visual_interpretation" for r in records))
            self.assertTrue(any(not r.get("origin") for r in records));store.close()

    def test_visual_batches_resume_after_quota_without_repeating_completed_pages(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf(5));fake=VisualProvider(store,doc["id"]);fake.fail_at=2
            with self.assertRaises(ProviderError):self.prepare(store,c,fake)
            saved=store.course(c["id"])["visual"]
            self.assertEqual(1,len(saved["batches"]));self.assertEqual(4,len(page_results(saved)))
            store.close();store=Store(folder);fresh=VisualProvider(store,doc["id"])
            fresh.settings.save(dict(vision_model="gemini-3.5-flash-lite"))
            with patch.object(fresh,"generate",wraps=fresh.generate) as generate:
                Jobs(store,fresh)._visual(c["id"])
            self.assertEqual("gemini-3.5-flash-lite",generate.call_args.kwargs["model"])
            for key,batch in saved["batches"].items():
                self.assertEqual(batch,store.course(c["id"])["visual"]["batches"][key])
            self.assertEqual(1,len(fresh.calls));self.assertEqual(5,len(page_results(store.course(c["id"])["visual"])));store.close()

    def test_backup_remaps_visual_sources_and_reuses_successful_analysis(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf());fake=VisualProvider(store,doc["id"])
            jobs=self.prepare(store,c,fake);restored=store.import_course(store.export(c["id"]))
            new_id=store.docs(restored["id"])[0]["id"]
            self.assertNotEqual(doc["id"],new_id)
            self.assertEqual({(new_id,1),(new_id,2)},set(page_results(restored["visual"])))
            fresh=VisualProvider(store,new_id)
            with patch('visual.render_selected',side_effect=AssertionError('Completed pages must not be rendered again')):
                Jobs(store,fresh)._visual(restored["id"])
            self.assertEqual([],fresh.calls)
            Jobs(store,fresh)._outline(restored["id"])
            twice=store.import_course(store.export(restored["id"]))
            self.assertEqual(2,len(records_for(twice["scope"])));store.close()

    def test_visual_response_cannot_invent_a_combined_page(self):
        batch=dict(id="batch",manifest=[dict(index=1,image_hash="a"*64,aliases=[dict(doc_id="a",page=3,role="material",digest="d")])])
        with self.assertRaisesRegex(ValueError,"every combined"):validate_visual_response(dict(pages=[dict(index=9)]),batch)

    def test_unverified_text_is_retrievable_without_overwriting_native_text(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf());fake=VisualProvider(store,doc["id"]);self.prepare(store,c,fake)
            visual=store.course(c["id"])["visual"];docs=store.docs(c["id"]);combined=recognized_sources(docs,visual)
            self.assertEqual("",docs[0]["pages"][0]);self.assertIn("scanned text",combined[0]["pages"][0])
            excerpts=scoped_excerpts(combined,dict(source_ranges=[dict(doc_id=doc["id"],start_page=1,end_page=2)]),"Complexity")
            self.assertTrue(excerpts);self.assertTrue(all(p["recognized"] for p in excerpts));store.close()

    def test_multimodal_provider_uses_selected_model_and_binary_cache_identity(self):
        with test_directory() as folder:
            store=Store(folder);settings=Settings(store.root,env_file=store.root/'absent.env');settings.save(dict(api_key="fake-private"))
            provider=Gemini(store,settings);raw=json.dumps(dict(candidates=[dict(content=dict(parts=[dict(text='{"ok":true}')]))])).encode()
            requests=[]
            def respond(request,timeout):requests.append(request);return io.BytesIO(raw)
            with patch("generation.urllib.request.urlopen",side_effect=respond),patch("generation.time.sleep"):
                provider.generate("visual",{},pdf=scanned_pdf(1),model="gemini-vision-test")
                provider.generate("visual",{},pdf=scanned_pdf(1),model="gemini-vision-test")
                provider.generate("visual",{},pdf=scanned_pdf(2),model="gemini-vision-test")
            self.assertEqual(2,len(requests));self.assertIn("gemini-vision-test:",requests[0].full_url)
            payload=json.loads(requests[0].data);parts=payload["contents"][0]["parts"]
            self.assertEqual("application/pdf",parts[1]["inlineData"]["mimeType"])
            self.assertNotIn("fake-private",requests[0].full_url+json.dumps(payload));store.close()

    def test_blank_and_vector_pages_are_classified_without_an_ai_call(self):
        writer=PdfWriter();writer.add_blank_page(width=595,height=842)
        page=writer.add_blank_page(width=595,height=842)
        commands=DecodedStreamObject();commands.set_data(b'80 300 100 100 re S 240 300 100 100 re S 80 500 100 100 re S 240 500 100 100 re S')
        page[NameObject('/Contents')]=writer._add_object(commands);output=io.BytesIO();writer.write(output)
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,output.getvalue());visual=inspect_documents(store.docs(c['id']),lambda did:store.document(did)[0])
            self.assertEqual(['blank','candidate'],[r['state'] for r in visual['pages']]);store.close()

    def test_vector_header_logo_does_not_trigger_recognition(self):
        writer=PdfWriter();writer.append(PdfReader(io.BytesIO(pdf_fixture())))
        for page in writer.pages:
            commands=DecodedStreamObject();commands.set_data(page.get_contents().get_data()+b'\n50 780 90 40 re S 150 780 90 40 re S 250 780 90 40 re S 350 780 90 40 re S')
            page[NameObject('/Contents')]=writer._add_object(commands)
        output=io.BytesIO();writer.write(output)
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,output.getvalue());visual=inspect_documents(store.docs(c['id']),lambda did:store.document(did)[0])
            self.assertFalse(any(r['selected'] for r in visual['pages']));store.close()

    def test_partial_visual_analysis_keeps_a_visible_gap_and_scope_warning(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf(1));fake=VisualProvider(store,doc['id']);self.prepare(store,c,fake)
            visual=store.course(c['id'])['visual'];key,batch=next(iter(visual['batches'].items()))
            raw=dict(pages=copy.deepcopy(batch['pages']));raw['pages'][0].update(status='partial',reason='A subscript remains unreadable.')
            visual['batches'][key]=validate_visual_response(raw,dict(id=key,manifest=batch['manifest']))
            store.update(c['id'],lambda course:course.update(visual=visual));Jobs(store,fake)._outline(c['id'])
            c=store.course(c['id']);self.assertIn('subscript',coverage(c['scope'])['unresolved'][0]['reason'])
            self.assertIn('subscript',records_for(c['scope'])[0]['visual_warning']);store.close()

    def test_skipped_visual_candidates_are_not_silently_counted_as_complete(self):
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,mixed_pdf(True));fake=VisualProvider(store,doc['id']);jobs=Jobs(store,fake)
            visual=jobs._inspect(c['id']);select_pages(visual,[]);store.update(c['id'],lambda course:course.update(visual=visual))
            jobs._outline(c['id']);stats=coverage(store.course(c['id'])['scope'])
            self.assertEqual([3],[r['page'] for r in stats['unresolved']]);self.assertFalse(fake.pdfs);store.close()

    def test_recognized_text_cannot_be_presented_as_verified_original_quote(self):
        class Misquoted(VisualProvider):
            def generate(self,prompt,schema,validator,**kwargs):
                if 'sections' in schema.get('properties',{}):
                    pkg=lesson_fixture(TEST_MODULES[0],self.doc_id,1)
                    for section in pkg['sections']:section.update(provenance='generated',sources=[])
                    pkg['sections'][0].update(provenance='source_excerpt',body='Complexity scanned text with eigenvalue conventions.',sources=[dict(doc_id=self.doc_id,page=1)])
                    return validator(pkg)
                return super().generate(prompt,schema,validator,**kwargs)
        with test_directory() as folder:
            store,c,doc=self.setup_course(folder,scanned_pdf(1));fake=Misquoted(store,doc['id']);jobs=self.prepare(store,c,fake);jobs._outline(c['id'])
            with self.assertRaisesRegex(ValueError,'match the supplied original'):jobs._packages(c['id'])
            store.close()


class VisualHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=test_directory();cls.server=create_server(cls.temp.name,0,env_file=Path(cls.temp.name)/'absent.env')
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.server.store.close();cls.temp.cleanup()

    def request(self,path,body=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:return json.load(response)

    def wait(self,cid):
        for _ in range(240):
            c=self.request('/api/courses/'+cid)
            if c['job']['state']!='running':return c
            time.sleep(.03)
        self.fail('Visual preparation did not finish.')

    def test_scan_to_saved_scope_and_offline_source_access(self):
        store=self.server.store;c=store.create('HTTP scan');doc=store.add_pdf(c['id'],'scan.pdf','material',scanned_pdf())
        fake=VisualProvider(store,doc['id']);self.server.jobs.provider=fake;cid=c['id']
        self.request(f'/api/courses/{cid}/prepare',dict(action='inspect'));c=self.wait(cid)
        self.assertEqual('complete',c['job']['state']);self.assertEqual([],fake.calls)
        selected=[dict(doc_id=r['doc_id'],page=r['page']) for r in c['visual']['pages'] if r['selected']]
        self.request(f'/api/courses/{cid}/visual',dict(selected=selected))
        self.request(f'/api/courses/{cid}/prepare',dict(action='visual'));c=self.wait(cid)
        self.assertEqual('complete',c['job']['state']);self.assertEqual(1,len(fake.calls))
        key=c['visual']['batch_ids'][0]
        with urllib.request.urlopen(self.url+f'/api/courses/{cid}/visual/batches/{key}.pdf') as response:self.assertTrue(response.read().startswith(b'%PDF-'))
        page=self.request(f'/api/documents/{doc["id"]}/pages/1')
        self.assertEqual('',page['text']);self.assertIn('scanned text',page['recognized_text'])
        self.assertEqual(1,len(fake.calls))
        self.request(f'/api/courses/{cid}/prepare',dict(action='outline'));c=self.wait(cid)
        self.assertEqual('outline',c['status']);self.assertEqual(2,len(fake.calls))
        with self.assertRaises(urllib.error.HTTPError):self.request(f'/api/courses/{cid}/visual',dict(selected=[]))

    def test_visual_model_is_separate_and_invalid_selection_is_rejected(self):
        store=self.server.store;c=store.create('Selection');doc=store.add_pdf(c['id'],'scan.pdf','material',scanned_pdf(1));cid=c['id']
        fake=VisualProvider(store,doc['id']);self.server.jobs.provider=fake
        self.request(f'/api/courses/{cid}/prepare',dict(action='inspect'));self.wait(cid)
        with self.assertRaises(urllib.error.HTTPError):self.request(f'/api/courses/{cid}/visual',dict(selected=[dict(doc_id=doc['id'],page=9)]))
        settings=self.request('/api/settings',dict(vision_model='gemini-visual-test',model='gemini-teach-test'))
        self.assertEqual('gemini-visual-test',settings['vision_model']);self.assertEqual('gemini-teach-test',settings['model'])
        self.assertEqual([],fake.calls)
