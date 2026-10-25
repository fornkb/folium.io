import {escapeText as esc,renderText} from './reader.js';

const sessions=new Map();
const id=()=>crypto.randomUUID().replaceAll('-','');
const pendingKey=key=>'folium-tutor-pending-'+key;
const pendingRequest=key=>{try{return JSON.parse(sessionStorage.getItem(pendingKey(key)));}catch{return null;}};
const storePending=(key,value)=>{try{if(value)sessionStorage.setItem(pendingKey(key),JSON.stringify(value));else sessionStorage.removeItem(pendingKey(key));}catch{}};
const chatIcon='<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18 3 21V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2Z"/><path d="M7 8h10M7 12h6"/></svg>';
export function tutorSettings(settings){
  const connected=settings.groq_has_key;
  const source=settings.groq_key_source==='env_file'?'Connected from .env':settings.groq_key_source==='environment'?'Connected from environment':connected?'Key saved':'Not connected';
  return `<div class="settings-divider"></div><h2>Lesson tutor</h2><p class="muted">Ask questions beside your saved lesson. Only sending a question contacts Groq.</p><div class="field"><label for="groq-api-key">Groq API key <span class="pill ${connected?'green':''}">${source}</span></label><input id="groq-api-key" name="groq_api_key" type="password" autocomplete="off" placeholder="${connected?'Connected. Leave blank to keep it.':'Paste your Groq API key'}"><small>Optional. You can also set GROQ_API_KEY in .env. Keys are never included in course exports.</small>${settings.groq_has_saved_key?'<button type="button" class="text-btn" data-action="clear-groq-key">Remove saved Groq key</button>':''}</div><div class="field"><label for="groq-model">Tutor model</label><input id="groq-model" name="groq_model" value="${esc(settings.groq_model||'openai/gpt-oss-120b')}" required maxlength="100"><small>Use a chat model available to your Groq account. There is no automatic provider fallback.</small></div><p class="small-text muted">Your question, selected passage, relevant lesson text, and recent conversation are sent to Groq. Replies and history are saved on this computer. Provider limits and account charges may apply.</p>`;
}

export function lessonOptions(module){
  const result=[];
  for(const section of module.package.sections){const lid=section.lesson_id||'module';if(!result.some(l=>l.id===lid))result.push({id:lid,title:section.lesson_title||module.title});}
  return result;
}

// Fetch streams may split UTF-8 characters or JSON records at any byte boundary.
export async function readTutorStream(response,onEvent){
  if(!response.ok){let value;try{value=await response.json();}catch{}const error=new Error(value?.error||'The tutor could not be reached.');error.beforeStream=true;throw error;}
  if(!response.body||!response.headers.get('Content-Type')?.includes('application/x-ndjson'))throw new Error('The tutor returned an unexpected response. Reload the conversation to check for a saved reply.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let pending='',done=false;
  try{
    for(;;){
      const chunk=await reader.read();pending+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});
      if(pending.length>200000)throw new Error('The tutor response was too large.');
      let at;
      while((at=pending.indexOf('\n'))>=0){
        const line=pending.slice(0,at);pending=pending.slice(at+1);if(!line.trim())continue;
        const value=JSON.parse(line);
        if(!['start','delta','done'].includes(value.event)||value.event==='delta'&&typeof value.text!=='string'||value.event!=='delta'&&(!value.turn||typeof value.turn.answer!=='string'))throw new Error('The tutor returned an invalid response.');
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
  return `<article class="tutor-turn" data-tutor-turn="${esc(turn.id)}"><div class="tutor-message tutor-question"><span class="tutor-speaker">You</span>${turn.selection?`<blockquote class="tutor-quoted">${esc(turn.selection)}</blockquote>`:''}<p>${esc(turn.question)}</p></div><div class="tutor-message tutor-answer"><span class="tutor-speaker">${chatIcon} Folium tutor <span>AI</span></span><div class="prose" data-tutor-answer>${turn.status==='streaming'?`<p class="tutor-stream-text">${esc(turn.answer||'Thinking through your question…')}</p>`:renderText(turn.answer||'')}</div>${turn.status==='complete'?'<button type="button" class="text-btn" data-tutor-note="'+esc(turn.id)+'">Save to notes</button>':''}${turn.status!=='streaming'&&turn.status!=='complete'?`<p class="tutor-error">${esc(turn.error||'This reply was interrupted. Any partial text is saved.')}</p><button type="button" class="text-btn" data-tutor-retry="${esc(turn.id)}">Ask again</button>`:''}${refs.length?`<details class="tutor-references"><summary>Lesson context${turn.context.complete?'':' · partial'}</summary><p>Sections supplied to the tutor. These links do not verify its answer.</p>${refs.map(r=>`<button type="button" class="text-btn" data-tutor-section="${r.index}">${esc(r.title)}${r.excerpt?' · excerpt':''}</button>`).join('')}</details>`:''}</div></article>`;
}

export function mountTutor(layout,{course,module,settings,api,onNote,onError}){
  const key=course.id+':'+module.id,available=lessonOptions(module),sidebar=layout.querySelector('.lesson-toc'),paper=layout.querySelector('.lesson-paper');
  if(!sidebar||!available.length)return {destroy(){}};
  let s=sessions.get(key);
  if(!s){s={mode:'contents',collapsed:false,lesson:available[0].id,thread:null,threads:[],turns:[],question:'',selection:null,busy:false,loading:false,error:'',loaded:false,revision:0,pending:pendingRequest(key),listeners:new Set()};sessions.set(key,s);}
  if(s.pending&&!s.loaded){const pending=s.pending;if(available.some(l=>l.id===pending.lesson_id)){s.lesson=pending.lesson_id;s.question=pending.question;s.selection=pending.section_index===null?null:{index:pending.section_index,text:pending.selection};s.mode='chat';}}
  const abort=new AbortController(),listen=(target,event,fn,opts={})=>target.addEventListener(event,fn,{...opts,signal:abort.signal});
  let live=true,mobileOpen=false,returnFocus=null,pendingSelection=null,refreshTimer;
  const contents=document.createElement('div');contents.className='tutor-contents';
  while(sidebar.firstChild)contents.append(sidebar.firstChild);
  sidebar.classList.add('tutor-sidebar');sidebar.setAttribute('aria-label','Lesson tools');
  sidebar.innerHTML=`<div class="tutor-panel-top"><div class="tutor-tabs" role="tablist" aria-label="Lesson tools"><button type="button" role="tab" id="contents-tab" data-tutor-mode="contents" aria-controls="contents-panel">Contents</button><button type="button" role="tab" id="tutor-tab" data-tutor-mode="chat" aria-controls="tutor-panel">${chatIcon}Ask tutor</button></div><button type="button" class="icon-btn tutor-collapse" aria-label="Collapse lesson tools" title="Collapse lesson tools">‹</button></div><div id="contents-panel" role="tabpanel" aria-labelledby="contents-tab" tabindex="0"></div><section id="tutor-panel" role="tabpanel" aria-labelledby="tutor-tab" hidden><div class="tutor-controls"><label for="tutor-lesson">ASK ABOUT</label><select id="tutor-lesson">${available.map(l=>`<option value="${esc(l.id)}">${esc(l.title)}</option>`).join('')}</select><div class="tutor-history-row"><select aria-label="Saved tutor conversations" data-tutor-history></select><button type="button" class="text-btn" data-tutor-reload aria-label="Reload saved conversation" title="Reload saved conversation">↻</button><button type="button" class="text-btn" data-tutor-new>＋ New chat</button></div></div><div class="tutor-messages" tabindex="0" aria-label="Tutor conversation"></div><div class="tutor-shortcuts"><button type="button" data-tutor-prompt="Explain this topic simply, with an intuitive explanation.">Explain simply</button><button type="button" data-tutor-prompt="Walk me through the worked example step by step. If there is more than one, ask which one.">Walk through example</button><button type="button" data-tutor-prompt="Give me a fresh worked example at this lesson’s level.">Another example</button><button type="button" data-tutor-prompt="Ask me one question to check my understanding. Wait for my answer before explaining the solution.">Quiz me</button></div><div class="tutor-selection" hidden></div><form class="tutor-compose"><label class="sr-only" for="tutor-question">Your question about this lesson</label><textarea id="tutor-question" rows="3" maxlength="4000" placeholder="What would you like to understand?"></textarea><div class="tutor-compose-bottom"><span>Ctrl + Enter to send</span><button type="submit" class="btn primary sm">Send ↑</button></div></form><p class="tutor-status" role="status" aria-live="polite"></p><p class="tutor-privacy">${settings.groq_has_key?'Sent to Groq only when you ask.':'<a href="#/settings">Connect Groq in Settings</a> to ask a question.'} Saved replies work offline.</p></section><button type="button" class="icon-btn tutor-expand" aria-label="Open lesson tools" title="Open lesson tools" hidden>${chatIcon}</button>`;
  sidebar.querySelector('#contents-panel').append(contents);
  const $=selector=>sidebar.querySelector(selector),messages=$('.tutor-messages'),textarea=$('#tutor-question'),status=$('.tutor-status');
  const launcher=document.createElement('div');launcher.className='tutor-mobile-launcher';launcher.innerHTML=`<button type="button" class="btn sm" data-open-mode="contents">Contents</button><button type="button" class="btn sm" data-open-mode="chat">${chatIcon}Ask tutor</button>`;layout.before(launcher);
  const shade=document.createElement('div');shade.className='tutor-shade';shade.hidden=true;layout.append(shade);
  const ask=document.createElement('button');ask.type='button';ask.className='text-btn tutor-selection-button';ask.innerHTML=chatIcon+' Ask tutor';ask.title='Select a passage to attach it, or ask about this lesson';const readerTools=paper.querySelector('.reader-mark-header>div');if(readerTools)readerTools.append(ask);else{ask.classList.add('tutor-reader-ask');paper.prepend(ask);}
  for(const [index,section] of [...paper.querySelectorAll('.lesson-section')].entries()){
    const button=document.createElement('button');button.type='button';button.className='text-btn tutor-section-ask';button.dataset.tutorAskSection=String(index);button.textContent='Ask about this section';section.append(button);
  }
  const notify=()=>{for(const callback of s.listeners)callback();};
  function setMobile(open){
    mobileOpen=open;sidebar.classList.toggle('tutor-drawer-open',open);shade.hidden=!open;
    if(open&&matchMedia('(max-width: 1120px)').matches){returnFocus=document.activeElement;sidebar.setAttribute('role','dialog');sidebar.setAttribute('aria-modal','true');}
    else{sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');}
  }
  function focusQuestion(){requestAnimationFrame(()=>{if(live)textarea.focus({preventScroll:true});});}
  function show(mode,focus=false){s.mode=mode;s.collapsed=false;setMobile(true);update();const opened=mode==='chat'&&!s.loaded&&!s.loading&&!s.busy?load():Promise.resolve();if(focus&&mode==='chat')opened.then(focusQuestion);else if(focus)$(`[data-tutor-mode="${mode}"]`).focus();}
  function close(){s.collapsed=true;setMobile(false);update();if(returnFocus?.isConnected)returnFocus.focus({preventScroll:true});else launcher.querySelector('[data-open-mode="chat"]').focus({preventScroll:true});}
  function update(){
    if(!live)return;
    layout.classList.toggle('tutor-chat-open',s.mode==='chat'&&!s.collapsed);
    layout.classList.toggle('tutor-is-collapsed',s.collapsed);
    sidebar.classList.toggle('tutor-chat-active',s.mode==='chat');sidebar.classList.toggle('tutor-collapsed',s.collapsed);
    $('#contents-panel').hidden=s.mode!=='contents'||s.collapsed;$('#tutor-panel').hidden=s.mode!=='chat'||s.collapsed;
    $('.tutor-panel-top').hidden=s.collapsed;$('.tutor-expand').hidden=!s.collapsed;
    for(const tab of sidebar.querySelectorAll('[data-tutor-mode]')){const selected=tab.dataset.tutorMode===s.mode;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;}
    $('#tutor-lesson').value=s.lesson;$('#tutor-lesson').disabled=s.busy||s.loading;
    const history=$('[data-tutor-history]');history.innerHTML=`${!s.thread||!s.threads.some(t=>t.id===s.thread)?'<option value="">New conversation</option>':''}${s.threads.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join('')}`;history.value=s.thread||'';history.disabled=s.busy||s.loading;
    $('[data-tutor-new]').disabled=s.busy||s.loading;
    $('[data-tutor-reload]').disabled=s.busy||s.loading;
    if(textarea.value!==s.question)textarea.value=s.question;
    textarea.disabled=s.busy||s.loading;
    const send=$('button[type="submit"]');send.disabled=s.busy||s.loading||!s.question.trim()||!settings.groq_has_key;send.textContent=s.busy?'Replying…':'Send ↑';
    const selection=$('.tutor-selection');selection.hidden=!s.selection;selection.innerHTML=s.selection?`<div><span class="eyebrow">SELECTED PASSAGE</span><button type="button" class="text-btn" data-tutor-remove-selection aria-label="Remove selected passage">×</button></div><blockquote>${esc(s.selection.text||module.package.sections[s.selection.index]?.title||'Selected section')}</blockquote>`:'';
    status.textContent=s.error||(s.loading?'Opening saved conversation…':s.busy?'Replying…':s.turns.length?'Saved on this computer. AI explanations may contain mistakes.':'');status.classList.toggle('error',!!s.error);
    const bottom=messages.scrollHeight-messages.scrollTop-messages.clientHeight<70;
    messages.innerHTML=s.turns.length?s.turns.map(t=>turnView(t,module)).join(''):`<div class="tutor-welcome"><span class="tutor-welcome-icon">${chatIcon}</span><h3>A little clarity,<br>right where you need it.</h3><p>Ask about an idea, unpack a worked example, or select a passage in your lesson.</p><small>Your saved lesson sets the context. The tutor can add fresh explanations and examples.</small></div>`;
    if(bottom||s.busy)messages.scrollTop=messages.scrollHeight;
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
    if(!settings.groq_has_key){s.error='Connect Groq in Settings to ask the tutor.';notify();return;}
    s.busy=true;s.error='';const selection=retry?{text:retry.selection,index:retry.section_index}:s.selection;
    let request={request_id:id(),thread_id:s.thread||id(),lesson_id:s.lesson,question:question.trim(),selection:selection?.text||'',section_index:selection?.index??null};
    if(!retry&&s.pending&&['lesson_id','question','selection','section_index'].every(k=>s.pending[k]===request[k]))request=s.pending;
    s.pending=request;storePending(key,request);
    const draft=question;let started=false;
    s.question='';notify();
    try{
      const response=await fetch(`/api/courses/${course.id}/modules/${encodeURIComponent(module.id)}/tutor`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
      await readTutorStream(response,event=>{
        if(event.event==='start'){
          started=true;s.thread=event.turn.thread_id;s.turns.push(event.turn);s.selection=null;
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
      s.error=error.message||'The tutor could not be reached. Reload the conversation to check for a saved reply.';
      s.question=draft;
      s.selection=request.section_index===null?null:{index:request.section_index,text:request.selection};
      if(started){const turn=s.turns.find(t=>t.id===request.request_id);if(turn?.status==='streaming'){turn.status='interrupted';turn.error=s.error;}}
    }finally{s.busy=false;s.loaded=true;notify();}
  }
  function captureSelection(){
    const selection=window.getSelection();if(!selection?.rangeCount||selection.isCollapsed)return;
    const range=selection.getRangeAt(0),start=range.startContainer.nodeType===1?range.startContainer:range.startContainer.parentElement,end=range.endContainer.nodeType===1?range.endContainer:range.endContainer.parentElement;
    const section=start.closest('.lesson-section');
    if(!section||!paper.contains(section)||end.closest('.lesson-section')!==section)return;
    const index=Number(section.id.replace('section-','')),text=selection.toString().trim();
    if(text&&text.length<=4000){pendingSelection={text,index};ask.textContent='Ask about selection';}
  }
  function attach(index,selected=null){
    if(s.busy||s.loading)return;
    const section=module.package.sections[index],lid=section.lesson_id||'module';
    if(s.lesson!==lid){s.lesson=lid;s.thread=null;s.turns=[];s.threads=[];s.loaded=false;s.question='';}
    s.selection={index,text:selected?.text||''};pendingSelection=null;ask.innerHTML=chatIcon+' Ask tutor';show('chat',true);
  }
  listen(document,'selectionchange',captureSelection);
  listen(ask,'pointerdown',event=>event.preventDefault());
  listen(ask,'click',()=>{if(pendingSelection)attach(pendingSelection.index,pendingSelection);else show('chat',true);});
  listen(paper,'click',event=>{const button=event.target.closest('[data-tutor-ask-section]');if(button)attach(Number(button.dataset.tutorAskSection));});
  listen(launcher,'click',event=>{const button=event.target.closest('[data-open-mode]');if(button)show(button.dataset.openMode,true);});
  listen(shade,'click',close);
  listen(window,'resize',()=>{if(!matchMedia('(max-width: 1120px)').matches){sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');shade.hidden=true;}else if(mobileOpen){setMobile(true);}});
  listen(sidebar,'click',async event=>{
    const el=event.target.closest('button');if(!el)return;
    if(el.dataset.tutorMode)show(el.dataset.tutorMode);
    if(el.classList.contains('tutor-collapse'))close();
    if(el.classList.contains('tutor-expand'))show('chat',true);
    if(el.hasAttribute('data-tutor-reload'))load();
    if(el.hasAttribute('data-tutor-new')&&!s.busy){s.thread=null;s.turns=[];s.question='';s.selection=null;s.error='';s.loaded=true;update();focusQuestion();}
    if(el.hasAttribute('data-tutor-remove-selection')){s.selection=null;pendingSelection=null;ask.innerHTML=chatIcon+' Ask tutor';update();}
    if(el.dataset.tutorPrompt){s.question=el.dataset.tutorPrompt;update();focusQuestion();}
    if(el.dataset.tutorRetry){const turn=s.turns.find(t=>t.id===el.dataset.tutorRetry);if(turn)send(turn.question,turn);}
    if(el.dataset.tutorSection){
      const target=paper.querySelector('#section-'+Number(el.dataset.tutorSection));
      if(target){if(matchMedia('(max-width: 1120px)').matches){setMobile(false);}target.scrollIntoView({behavior:'smooth',block:'start'});target.tabIndex=-1;target.focus({preventScroll:true});}
    }
    if(el.dataset.tutorNote){
      const turn=s.turns.find(t=>t.id===el.dataset.tutorNote);if(!turn)return;el.disabled=true;
      try{await onNote(`\n\n### Tutor: ${turn.question}\n\n${turn.answer}\n\n_AI tutor explanation · ${available.find(l=>l.id===turn.lesson_id)?.title||module.title}._`);el.textContent='Saved to notes';}catch(error){onError(error);}finally{el.disabled=false;}
    }
    if(el.dataset.action==='scroll-section'&&matchMedia('(max-width: 1120px)').matches)setMobile(false);
  });
  listen($('#tutor-lesson'),'change',()=>{s.lesson=$('#tutor-lesson').value;s.thread=null;s.selection=null;s.turns=[];s.question='';s.loaded=false;load();});
  listen($('[data-tutor-history]'),'change',()=>{const value=$('[data-tutor-history]').value;if(value)load(value);});
  listen(textarea,'input',()=>{s.question=textarea.value;const button=$('button[type="submit"]');button.disabled=!s.question.trim()||s.busy||!settings.groq_has_key;});
  listen($('.tutor-compose'),'submit',event=>{event.preventDefault();event.stopPropagation();send();});
  listen(sidebar,'keydown',event=>{
    if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&event.target===textarea){event.preventDefault();send();}
    if(event.target.matches('[role="tab"]')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();show(event.key==='Home'?'contents':event.key==='End'?'chat':s.mode==='chat'?'contents':'chat');$(`[data-tutor-mode="${s.mode}"]`).focus();}
    if(event.key==='Escape'&&mobileOpen){event.preventDefault();event.stopPropagation();close();}
    if(event.key==='Tab'&&mobileOpen&&matchMedia('(max-width: 1120px)').matches){
      const nodes=[...sidebar.querySelectorAll('button:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  update();if(s.mode==='chat'&&!s.loaded&&!s.busy)load();
  return {destroy(){live=false;abort.abort();s.listeners.delete(update);launcher.remove();shade.remove();ask.remove();paper.querySelectorAll('[data-tutor-ask-section]').forEach(n=>n.remove());}};
}
