import {escapeText as esc,renderText} from './reader.js';
import {folioIcon} from './folio-icons.js';

const sessions=new Map();
const id=()=>crypto.randomUUID().replaceAll('-','');
const pendingKey=key=>'folium-tutor-pending-'+key;
const pendingRequest=key=>{try{return JSON.parse(sessionStorage.getItem(pendingKey(key)));}catch{return null;}};
const storePending=(key,value)=>{try{if(value)sessionStorage.setItem(pendingKey(key),JSON.stringify(value));else sessionStorage.removeItem(pendingKey(key));}catch{}};
const chatIcon=folioIcon();
export function tutorSettings(settings){
  const connected=settings.groq_has_key;
  const source=settings.groq_key_source==='env_file'?'Connected from .env':settings.groq_key_source==='environment'?'Connected from environment':connected?'Key saved':'Not connected';
  return `<div class="settings-divider"></div><h2>Folio</h2><p class="muted">Your study companion, a click away. Only sending a question contacts Groq.</p><div class="field"><label for="groq-api-key">Groq API key <span class="pill ${connected?'green':''}">${source}</span></label><input id="groq-api-key" name="groq_api_key" type="password" autocomplete="off" placeholder="${connected?'Connected. Leave blank to keep it.':'Paste your Groq API key'}"><small>Optional. You can also set GROQ_API_KEY in .env. Keys are never included in course exports.</small>${settings.groq_has_saved_key?'<button type="button" class="text-btn" data-action="clear-groq-key">Remove saved Groq key</button>':''}</div><div class="field"><label for="groq-model">Folio model</label><input id="groq-model" name="groq_model" value="${esc(settings.groq_model||'openai/gpt-oss-120b')}" required maxlength="100"><small>Use a chat model available to your Groq account. There is no automatic provider fallback.</small></div><p class="small-text muted">Your question, selected passage, relevant lesson text, and recent conversation are sent to Groq. Replies and history are saved on this computer. Provider limits and account charges may apply.</p>`;
}

export function lessonOptions(module){
  const result=[];
  for(const section of module.package.sections){const lid=section.lesson_id||'module';if(!result.some(l=>l.id===lid))result.push({id:lid,title:section.lesson_title||module.title});}
  return result;
}

// Fetch streams may split UTF-8 characters or JSON records at any byte boundary.
export async function readTutorStream(response,onEvent){
  if(!response.ok){let value;try{value=await response.json();}catch{}const error=new Error(value?.error||'Folio could not be reached.');error.beforeStream=true;throw error;}
  if(!response.body||!response.headers.get('Content-Type')?.includes('application/x-ndjson'))throw new Error('Folio returned an unexpected response. Reload the conversation to check for a saved reply.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let pending='',done=false;
  try{
    for(;;){
      const chunk=await reader.read();pending+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});
      if(pending.length>200000)throw new Error('Folio response was too large.');
      let at;
      while((at=pending.indexOf('\n'))>=0){
        const line=pending.slice(0,at);pending=pending.slice(at+1);if(!line.trim())continue;
        const value=JSON.parse(line);
        if(!['start','delta','done'].includes(value.event)||value.event==='delta'&&typeof value.text!=='string'||value.event!=='delta'&&(!value.turn||typeof value.turn.answer!=='string'))throw new Error('Folio returned an invalid response.');
        if(value.event==='done')done=true;
        onEvent(value);
      }
      if(chunk.done)break;
    }
    if(!done||pending.trim())throw new Error('The connection ended early. Reload the conversation to check for a saved or partial reply.');
  }finally{reader.releaseLock();}
}

export function turnView(turn,module){
  const refs=(turn.context?.sections||[]).filter(r=>Number.isInteger(r.index)&&module.package.sections[r.index]?.title===r.title).slice(0,3);
  return `<article class="tutor-turn" data-tutor-turn="${esc(turn.id)}"><div class="tutor-message tutor-question"><span class="tutor-speaker">You</span>${turn.selection?`<blockquote class="tutor-quoted">${esc(turn.selection)}</blockquote>`:''}<p>${esc(turn.question)}</p></div><div class="tutor-message tutor-answer"><span class="tutor-speaker">${chatIcon} Folio <span>AI</span></span><div class="prose" data-tutor-answer>${turn.status==='streaming'?`<p class="tutor-stream-text">${esc(turn.answer||'Folio is thinking…')}</p>`:renderText(turn.answer||'')}</div>${turn.status==='complete'?'<button type="button" class="text-btn" data-tutor-note="'+esc(turn.id)+'">Save to notes</button>':''}${turn.status!=='streaming'&&turn.status!=='complete'?`<p class="tutor-error">${esc(turn.error||'This reply was interrupted. Any partial text is saved.')}</p><button type="button" class="text-btn" data-tutor-retry="${esc(turn.id)}">Ask again</button>`:''}${refs.length?`<details class="tutor-references"><summary>Lesson context${turn.context.complete?'':' · partial'}</summary><p>Sections supplied to Folio. These links do not verify its answer.</p>${refs.map(r=>`<button type="button" class="text-btn" data-tutor-section="${r.index}">${esc(r.title)}${r.excerpt?' · excerpt':''}</button>`).join('')}</details>`:''}</div></article>`;
}

export function mountTutor(layout,{course,module,settings,api,onNote,onError}){
  const key=course.id+':'+module.id,available=lessonOptions(module),paper=layout.querySelector('.lesson-paper');
  if(!paper||!available.length)return {attachSelection(){},destroy(){}};
  let s=sessions.get(key);
  if(!s){s={open:false,lesson:available[0].id,thread:null,threads:[],turns:[],question:'',selection:null,busy:false,loading:false,error:'',loaded:false,revision:0,pending:pendingRequest(key),listeners:new Set()};sessions.set(key,s);}
  if(s.pending&&!s.loaded){const pending=s.pending;if(available.some(l=>l.id===pending.lesson_id)){s.lesson=pending.lesson_id;s.question=pending.question;s.selection=pending.section_index===null?null:{index:pending.section_index,text:pending.selection};}}
  const abort=new AbortController(),listen=(target,event,fn,opts={})=>target.addEventListener(event,fn,{...opts,signal:abort.signal});
  let live=true,returnFocus=null,refreshTimer;
  const launcher=document.createElement('button');launcher.type='button';launcher.className='folio-launcher';launcher.setAttribute('aria-label','Open Folio');launcher.setAttribute('aria-controls','folio-panel');launcher.title='Ask Folio';launcher.innerHTML=folioIcon();
  const sidebar=document.createElement('section');sidebar.className='folio-window';sidebar.id='folio-panel';sidebar.hidden=true;sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-labelledby','folio-title');
  sidebar.innerHTML=`<header class="folio-header"><span class="folio-header-icon">${folioIcon()}</span><div><h2 id="folio-title">Folio</h2><p>Your study companion</p></div><button type="button" class="icon-btn folio-close" aria-label="Close Folio">×</button></header><div class="tutor-controls"><label class="sr-only" for="tutor-lesson">Lesson context</label><select id="tutor-lesson">${available.map(l=>`<option value="${esc(l.id)}">${esc(l.title)}</option>`).join('')}</select><details class="folio-history"><summary>Conversations</summary><div class="tutor-history-row"><select aria-label="Saved Folio conversations" data-tutor-history></select><button type="button" class="text-btn" data-tutor-reload aria-label="Reload saved conversation" title="Reload saved conversation">↻</button><button type="button" class="text-btn" data-tutor-new>＋ New</button></div></details></div><div class="tutor-messages" tabindex="0" aria-label="Folio conversation"></div><form class="tutor-compose"><div class="tutor-selection" hidden></div><label class="sr-only" for="tutor-question">Your question for Folio</label><textarea id="tutor-question" rows="3" maxlength="4000" placeholder="What would you like to understand?"></textarea><div class="tutor-compose-bottom"><span>Ctrl + Enter to send</span><button type="submit" class="btn primary sm">Send ↑</button></div></form><p class="tutor-status" role="status" aria-live="polite"></p><p class="tutor-privacy">${settings.groq_has_key?'Sent to Groq when you ask.':'<a href="#/settings">Connect Groq in Settings</a> to ask Folio.'} Replies are saved locally.</p>`;
  const shade=document.createElement('div');shade.className='folio-shade';shade.hidden=true;
  document.body.append(shade,sidebar,launcher);
  const $=selector=>sidebar.querySelector(selector),messages=$('.tutor-messages'),textarea=$('#tutor-question'),status=$('.tutor-status');
  const notify=()=>{for(const callback of s.listeners)callback();};
  const mobile=()=>matchMedia('(max-width: 650px)').matches;
  function focusQuestion(){requestAnimationFrame(()=>{if(live&&s.open)textarea.focus({preventScroll:true});});}
  function show(focus=true){
    if(!s.open)returnFocus=document.activeElement;
    s.open=true;update();
    const opened=!s.loaded&&!s.loading&&!s.busy?load():Promise.resolve();
    if(focus)opened.then(focusQuestion);
  }
  function close(){s.open=false;update();if(returnFocus?.isConnected&&returnFocus.getClientRects().length)returnFocus.focus({preventScroll:true});else launcher.focus({preventScroll:true});}
  function update(){
    if(!live)return;
    sidebar.hidden=!s.open;launcher.hidden=s.open;shade.hidden=!s.open||!mobile();launcher.setAttribute('aria-expanded',String(s.open));
    if(s.open&&mobile())sidebar.setAttribute('aria-modal','true');else sidebar.removeAttribute('aria-modal');
    document.body.classList.toggle('folio-dialog-open',s.open&&mobile());
    $('#tutor-lesson').value=s.lesson;$('#tutor-lesson').disabled=s.busy||s.loading;
    const history=$('[data-tutor-history]');history.innerHTML=`${!s.thread||!s.threads.some(t=>t.id===s.thread)?'<option value="">New conversation</option>':''}${s.threads.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')}`;history.value=s.thread||'';history.disabled=s.busy||s.loading;
    $('[data-tutor-new]').disabled=s.busy||s.loading;$('[data-tutor-reload]').disabled=s.busy||s.loading;
    if(textarea.value!==s.question)textarea.value=s.question;
    textarea.disabled=s.busy||s.loading;
    const send=$('button[type="submit"]');send.disabled=s.busy||s.loading||!s.question.trim()||!settings.groq_has_key;send.textContent=s.busy?'Replying…':'Send ↑';
    const selection=$('.tutor-selection');selection.hidden=!s.selection;
    selection.innerHTML=s.selection?`<div><span>Selected from your lesson</span><button type="button" class="text-btn" data-tutor-remove-selection aria-label="Remove selected text">×</button></div><blockquote>${esc(s.selection.text)}</blockquote>`:'';
    status.textContent=s.error||(s.loading?'Opening saved conversation…':s.busy?'Folio is thinking…':'');status.classList.toggle('error',!!s.error);
    const bottom=messages.scrollHeight-messages.scrollTop-messages.clientHeight<70;
    messages.innerHTML=s.turns.length?s.turns.map(t=>turnView(t,module)).join(''):`<div class="tutor-welcome">${s.selection?'<h3>What shall we explore?</h3><p>Add your question below. I’ll use the selected passage as extra context.</p>':`<span class="tutor-welcome-icon">${folioIcon()}</span><h3>Let’s untangle it.</h3><p>Ask about an idea, work through an example, or select a passage and choose <strong>Ask Folio</strong>.</p>`}</div>`;
    if(bottom)messages.scrollTop=messages.scrollHeight;
  }
  s.listeners.add(update);
  async function load(thread=null){
    const revision=++s.revision;s.loading=true;s.error='';notify();
    try{
      const value=await api(`/courses/${course.id}/modules/${encodeURIComponent(module.id)}/tutor?lesson=${encodeURIComponent(s.lesson)}${thread?'&thread='+encodeURIComponent(thread):''}`);
      if(revision!==s.revision)return;
      s.thread=value.thread_id;s.threads=value.threads;s.turns=value.turns;s.loaded=true;
      if(s.pending&&s.turns.some(t=>t.id===s.pending.request_id&&t.status!=='streaming')){if(s.question===s.pending.question)s.question='';s.pending=null;storePending(key,null);}
    }catch(error){if(revision===s.revision)s.error=error.message;}
    finally{if(revision===s.revision){s.loading=false;notify();}}
  }
  async function send(question=s.question,retry=null){
    if(s.busy||s.loading||!question.trim())return;
    if(!settings.groq_has_key){s.error='Connect Groq in Settings to ask Folio.';notify();return;}
    s.busy=true;s.error='';const attached=s.selection;const selection=retry?{text:retry.selection,index:retry.section_index}:s.selection;
    let request={request_id:id(),thread_id:s.thread||id(),lesson_id:s.lesson,question:question.trim(),selection:selection?.text||'',section_index:selection?.index??null};
    if(!retry&&s.pending&&['lesson_id','question','selection','section_index'].every(k=>s.pending[k]===request[k]))request=s.pending;
    s.pending=request;storePending(key,request);
    const draft=question;let started=false;
    s.question='';notify();
    try{
      const response=await fetch(`/api/courses/${course.id}/modules/${encodeURIComponent(module.id)}/tutor`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
      await readTutorStream(response,event=>{
        if(event.event==='start'){
          started=true;s.thread=event.turn.thread_id;s.turns.push(event.turn);if(s.selection===attached)s.selection=null;
          if(!s.threads.some(t=>t.id===s.thread))s.threads.unshift({id:s.thread,title:event.turn.question.slice(0,70)});
        }else if(event.event==='delta'){
          const turn=s.turns.find(t=>t.id===request.request_id);if(turn)turn.answer+=event.text;
        }else if(event.event==='done'){
          s.pending=null;storePending(key,null);
          const at=s.turns.findIndex(t=>t.id===event.turn.id);if(at<0)s.turns.push(event.turn);else s.turns[at]=event.turn;
          s.thread=event.turn.thread_id;
        }
        // Throttle Markdown/DOM work while deltas arrive rapidly.
        if(!refreshTimer)refreshTimer=setTimeout(()=>{refreshTimer=null;notify();},80);
      });
    }catch(error){
      if(error.beforeStream){s.pending=null;storePending(key,null);}
      s.error=error.message||'Folio could not be reached. Reload the conversation to check for a saved reply.';
      s.question=draft;
      s.selection=request.section_index===null?null:{index:request.section_index,text:request.selection};
      if(started){const turn=s.turns.find(t=>t.id===request.request_id);if(turn?.status==='streaming'){turn.status='interrupted';turn.error=s.error;}}
    }finally{s.busy=false;s.loaded=true;notify();}
  }
  function attachSelection({text,index}){
    if(s.busy)throw new Error('Folio is finishing this reply. Try the selection again in a moment.');
    if(typeof text!=='string'||!text.trim()||text.length>4000)throw new Error('Select up to 4,000 characters to ask Folio.');
    const section=module.package.sections[index];
    if(!Number.isInteger(index)||!section)throw new Error('Choose some lesson text to ask Folio.');
    const lid=section.lesson_id||'module';
    if(s.lesson!==lid){s.revision++;s.loading=false;s.lesson=lid;s.thread=null;s.turns=[];s.threads=[];s.loaded=false;}
    s.selection={index,text:text.trim()};show(true);
  }
  listen(launcher,'click',()=>show());listen($('.folio-close'),'click',close);listen(shade,'click',close);
  listen(window,'resize',()=>{if(live){shade.hidden=!s.open||!mobile();if(s.open&&mobile())sidebar.setAttribute('aria-modal','true');else sidebar.removeAttribute('aria-modal');document.body.classList.toggle('folio-dialog-open',s.open&&mobile());}});
  listen(sidebar,'click',async event=>{
    const el=event.target.closest('button');if(!el||el.disabled)return;
    if(el.hasAttribute('data-tutor-reload'))load();
    if(el.hasAttribute('data-tutor-new')&&!s.busy){s.thread=null;s.turns=[];s.question='';s.selection=null;s.error='';s.loaded=true;update();focusQuestion();}
    if(el.hasAttribute('data-tutor-remove-selection')){s.selection=null;update();focusQuestion();}
    if(el.dataset.tutorRetry){const turn=s.turns.find(t=>t.id===el.dataset.tutorRetry);if(turn)send(turn.question,turn);}
    if(el.dataset.tutorSection){const target=paper.querySelector('#section-'+Number(el.dataset.tutorSection));if(target){if(mobile())close();target.scrollIntoView({behavior:'smooth',block:'start'});target.tabIndex=-1;target.focus({preventScroll:true});}}
    if(el.dataset.tutorNote){const turn=s.turns.find(t=>t.id===el.dataset.tutorNote);if(!turn)return;el.disabled=true;
      try{await onNote(`\n\n### Folio: ${turn.question}\n\n${turn.answer}\n\n_AI explanation · ${available.find(l=>l.id===turn.lesson_id)?.title||module.title}._`);el.textContent='Saved to notes';}catch(error){onError(error);}finally{el.disabled=false;}}
  });
  listen($('#tutor-lesson'),'change',()=>{s.lesson=$('#tutor-lesson').value;s.thread=null;s.selection=null;s.turns=[];s.question='';s.loaded=false;load();});
  listen($('[data-tutor-history]'),'change',()=>{const value=$('[data-tutor-history]').value;if(value)load(value);});
  listen(textarea,'input',()=>{s.question=textarea.value;const button=$('button[type="submit"]');button.disabled=!s.question.trim()||s.busy||!settings.groq_has_key;});
  listen($('.tutor-compose'),'submit',event=>{event.preventDefault();event.stopPropagation();send();});
  listen(sidebar,'keydown',event=>{
    if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&event.target===textarea){event.preventDefault();send();}
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}
    if(event.key==='Tab'&&s.open&&mobile()){
      const nodes=[...sidebar.querySelectorAll('button:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  update();if(s.open&&!s.loaded&&!s.busy)load();
  return {attachSelection,destroy(){live=false;abort.abort();s.listeners.delete(update);launcher.remove();shade.remove();sidebar.remove();document.body.classList.remove('folio-dialog-open');}};
}
