import * as UI from './ui.js';
const {esc,icon,link,enc}=UI;
const $=(s,root=document)=>root.querySelector(s);
const $$=(s,root=document)=>[...root.querySelectorAll(s)];
const state={courses:[],settings:{has_key:false,model:'gemini-3.8-flash',task_model:'gemini-3.5-flash-lite',vision_model:'gemini-3.5-flash-lite',interval:6},view:'graph',zoom:null,
  files:[],draft:[],draftCid:null,scopeExclusions:[],scopeGapsAccepted:false,review:null,quizzes:{},theme:localStorage.getItem('folium-theme')||'light',
  current:{},allowPrepared:null,previousRoute:'',notesPending:null,lastDeletion:null};
let toastTimer,notesTimer,lastFocus,notesFlight=null;

async function api(path,body){
  const options=body===undefined?{}:body instanceof FormData?{method:'POST',body}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  let response;
  try{response=await fetch('/api'+path,options);}catch{throw new Error('The local app could not be reached. Check that Folium is still running.');}
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'Something could not be saved. Please try again.');
  return value;
}
function updateCourse(c){
  const index=state.courses.findIndex(x=>x.id===c.id);
  if(c.study_patch){
    const current=state.courses[index];if(!current)return;
    for(const patch of c.modules){const target=current.modules.find(m=>m.id===patch.id);if(target)Object.assign(target,patch);}
    current.updated=c.updated;current.reviews={...current.reviews,...c.reviews};c=current;
  }else if(index<0)state.courses.unshift(c);else state.courses[index]=c;
  const pending=state.notesPending||state.notesSaving;
  if(pending?.cid===c.id){const module=c.modules.find(m=>m.id===pending.mid);if(module)module.notes=pending.text;}
  return c;
}
async function loadRouteCourse(){
  const r=route();if(r[0]!=='course')return;
  const c=state.courses.find(c=>c.id===r[1]);
  if(c?.summary){render();updateCourse(await api('/courses/'+c.id));}
}
function toast(text,error=false){const el=$('#toast');clearTimeout(toastTimer);el.textContent=text;el.className='visible'+(error?' error':'');toastTimer=setTimeout(()=>el.className='',error?6500:3400);}
function route(){return (location.hash.replace(/^#\/?/,'')||'').split('/').map(decodeURIComponent);}
function goto(path){if(location.hash===path){render();window.scrollTo(0,0);}else location.hash=path;}
const quizKey=(c,m)=>`${c.id}:${m.id}`;
function shuffle(items){const result=[...items];for(let i=result.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[result[i],result[j]]=[result[j],result[i]];}return result;}
function newQuiz(m,topic=''){
  const bank=m.package.questions.filter(q=>q.type==='objective'&&(!topic||q.topic===topic));
  return {answers:{},topic,signature:JSON.stringify(m.package.questions),order:shuffle(bank.map(q=>q.id)),options:Object.fromEntries(bank.map(q=>[q.id,shuffle(q.options.map((_,i)=>i))]))};
}
function getQuiz(c,m){
  const key=quizKey(c,m);
  if(!state.quizzes[key]){try{state.quizzes[key]=JSON.parse(sessionStorage.getItem('folium-quiz-'+key));}catch{}}
  if(!state.quizzes[key]||state.quizzes[key].signature!==JSON.stringify(m.package.questions))state.quizzes[key]=newQuiz(m);
  return state.quizzes[key];
}
function saveQuiz(c,m){sessionStorage.setItem('folium-quiz-'+quizKey(c,m),JSON.stringify(state.quizzes[quizKey(c,m)]));}
function brand(){return `<a class="brand" href="#/" aria-label="Folium home"><svg class="brand-mark" viewBox="0 0 32 36" fill="none" aria-hidden="true"><path d="M5 31V15C5 6 14 2 29 3 28 17 20 24 9 24M9 23 23 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="brand-word">folium<span>.</span></span></a>`;}
function shell(body,pageTitle='My courses',active='courses',cid=null){
  const due=UI.dueCards(state.courses).length;
  return `<div class="shell"><aside class="sidebar" id="sidebar">${brand()}<div class="space-label">YOUR WORKSPACE</div><nav aria-label="Main navigation"><a class="nav-item ${active==='courses'?'active':''}" href="#/">${icon('grid')}My courses</a><a class="nav-item ${active==='revision'?'active':''}" href="#/revision">${icon('cards')}Revision${due?`<span class="count">${due}</span>`:''}</a><a class="nav-item ${active==='saved'?'active':''}" href="#/saved">${icon('bookmark')}Saved</a></nav><div class="sidebar-divider"></div><div class="row between"><div class="space-label" style="margin-bottom:0">YOUR COURSES</div><a class="text-btn" href="#/new" aria-label="Create a course" style="margin-right:10px">${icon('plus')}</a></div><div style="margin-top:10px">${state.courses.slice(0,6).map(c=>`<a class="side-course ${cid===c.id?'current':''}" href="${link(c.id)}"><span class="dot"></span><span class="name">${esc(c.title)}</span></a>`).join('')}</div><div class="sidebar-bottom"><div class="local-card">${icon('shield')}<strong>Your space. Your pace.</strong>Prepared once.<br>Always here to return to.</div><a class="nav-item ${active==='settings'?'active':''}" style="padding-left:0" href="#/settings">${icon('settings')}Settings</a><div class="sidebar-divider" style="margin:13px 0"></div><div class="profile"><span class="avatar">Y</span><span>Your workspace<small>LOCAL & PERSONAL</small></span></div></div></aside><div class="mobile-shade" data-action="close-sidebar"></div><div class="main-shell"><header class="topbar"><button class="icon-btn mobile-menu" data-action="sidebar" aria-label="Open navigation">${icon('menu')}</button><div class="breadcrumb"><a href="#/">Workspace</a>${icon('chevron')}<span class="current">${esc(pageTitle)}</span></div><div class="top-actions"><button class="search-trigger" data-action="search">${icon('search')}Find an idea <kbd>Ctrl K</kbd></button><span class="saved-status">${icon('shield')}Saved on your computer</span></div></header><main class="content" id="main" tabindex="-1">${body}</main></div></div>`;
}

function render(){
  const openScopeDetails=$$('details[data-scope-detail][open]').map(d=>d.dataset.scopeDetail);
  const r=route();let body,title='My courses',active='courses',cid=null;
  state.current={};document.body.classList.toggle('dark',state.theme==='dark');
  if(r[0]==='settings'){body=UI.settingsView(state.settings,state.theme);title='Settings';active='settings';}
  else if(r[0]==='new'){body=UI.createView();title='Create a course';}
  else if(r[0]==='revision'){
    active='revision';title='Revision';body=r[1]==='review'?UI.flashcard(state.review):UI.revision(state.courses);
    if(r[1]==='review'&&!state.review)body=UI.empty('Ready when you are.','Choose a course or start your daily review.','cards','<a class="btn primary" href="#/revision">Open revision '+icon('arrow')+'</a>');
  }else if(r[0]==='saved'){body=UI.saved(state.courses);active='saved';title='Saved modules';}
  else if(r[0]==='course'){
    const c=state.courses.find(x=>x.id===r[1]);cid=c?.id;
    if(!c){body=UI.empty('This course isn’t here.','Return to your library or import a saved course package.','book','<a class="btn primary" href="#/">My courses '+icon('arrow')+'</a>');}
    else if(c.summary){title=c.title;body=UI.empty('Opening your saved course…','Loading its lessons from this computer.','clock');}
    else{
      title=c.title;state.current.c=c;
      if(r[2]==='module'){
        const m=c.modules.find(x=>x.id===r[3]),tab=['study','practice','pyqs','cards','notes'].includes(r[4])?r[4]:'study';
        state.current={c,m,tab};
        if(!m){body=UI.empty('This module isn’t here.','Return to the course map to choose another module.','book',`<a class="btn primary" href="${link(c.id)}">Course map ${icon('arrow')}</a>`);}
        else if(!m.package){body=UI.studyHeader(c,m,tab)+UI.empty('This module is still taking shape.','Its lesson hasn’t been prepared yet. Resume course preparation to save the remaining material.','clock',`<a class="btn primary" href="${link(c.id)}/setup">Continue preparation ${icon('arrow')}</a>`);}
        else{
          body=UI.studyHeader(c,m,tab);
          if(tab==='study')body+=UI.studyGuide(c,m);
          if(tab==='practice')body+=UI.practice(c,m,getQuiz(c,m));
          if(tab==='pyqs')body+=UI.pastPapers(c,m);
          if(tab==='notes')body+=UI.notes(m);
          if(tab==='cards'&&m.package.assessment_status==='missing')body+=UI.preparePractice(c,m);
          else if(tab==='cards'){
            const key=`${c.id}:${m.id}`;
            if(state.review?.key!==key)state.review={key,cards:UI.dueCards(state.courses,c.id,m.id,true),pos:0,flipped:false};
            body+=UI.flashcard(state.review);
          }
        }
      }else if(r[2]==='setup'||c.status!=='ready'&&r[2]!=='explore'&&state.allowPrepared!==c.id){
        if(state.draftCid!==c.id){state.draft=structuredClone(c.modules);state.scopeExclusions=structuredClone(c.scope_exclusions||[]);state.scopeGapsAccepted=!!c.scope_review;state.draftCid=c.id;}
        body=UI.setupView(c,state.draft,state.settings,state.scopeExclusions,state.scopeGapsAccepted);
      }else{body=UI.courseView(c,state.view,state.zoom||1);}
      if(r[2]!=='setup'&&(r[2]==='module'||r[2]==='explore'||c.status==='ready'||state.allowPrepared===c.id))body=`<div id="preparation-status">${UI.preparationNotice(c)}</div>`+body;
    }
  }else{body=(state.lastDeletion?UI.deletionReceipt(state.lastDeletion):'')+UI.library(state.courses);}
  document.title=`${title} — Folium`;
  $('#app').innerHTML=shell(body,title,active,cid);
  for(const id of openScopeDetails){const detail=$(`details[data-scope-detail="${CSS.escape(id)}"]`);if(detail)detail.open=true;}
  document.body.classList.remove('map-open');
  requestAnimationFrame(applyGraphZoom);
  if(r[0]==='new')renderFiles();
}

function applyGraphZoom(){
  const stage=$('.graph-stage'),scroll=$('.graph-scroll');if(!stage||!scroll)return;
  const width=Number(stage.dataset.width),height=Number(stage.dataset.height);
  const scale=state.zoom??Math.min(1,(scroll.clientWidth-24)/width,(scroll.clientHeight-24)/height);
  stage.style.transform=`scale(${scale})`;stage.parentElement.style.width=`${width*scale}px`;stage.parentElement.style.height=`${height*scale}px`;
  stage.dataset.scale=scale;
}
window.addEventListener('resize',()=>{if(state.zoom===null)applyGraphZoom();});
function toggleMap(){const panel=$('.map-panel');if(!panel)return;const expanded=panel.classList.toggle('expanded');document.body.classList.toggle('map-open',expanded);const button=$('[data-action="map-expand"]');button.setAttribute('aria-label',expanded?'Close expanded map':'Expand map');button.setAttribute('aria-pressed',expanded);if(expanded){panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label','Expanded course map');}else{panel.removeAttribute('role');panel.removeAttribute('aria-modal');panel.removeAttribute('aria-label');}state.zoom=null;applyGraphZoom();}
let drag=null;
document.addEventListener('pointerdown',event=>{
  const scroll=event.target.closest('.graph-scroll');
  if(!scroll||event.target.closest('a,button')||event.button!==0)return;
  drag={scroll,x:event.clientX,y:event.clientY,left:scroll.scrollLeft,top:scroll.scrollTop};scroll.setPointerCapture(event.pointerId);
});
document.addEventListener('pointermove',event=>{if(drag){drag.scroll.scrollLeft=drag.left+drag.x-event.clientX;drag.scroll.scrollTop=drag.top+drag.y-event.clientY;}});
document.addEventListener('pointerup',()=>{drag=null;});
document.addEventListener('pointercancel',()=>{drag=null;});

function renderFiles(){if($('#upload-files'))$('#upload-files').innerHTML=UI.uploadFileList(state.files);}
function addFiles(files){
  for(const file of files){
    if(!file.name.toLowerCase().endsWith('.pdf')){toast('Choose PDF files for your course.',true);continue;}
    if(file.size>25*1024*1024){toast(`${file.name} is larger than 25 MB. Split it before uploading.`,true);continue;}
    if(state.files.length>=30){toast('Use up to 30 documents in one course.',true);break;}
    if(state.files.some(x=>x.file.name===file.name&&x.file.size===file.size))continue;
    const role=/syllabus|outline/i.test(file.name)?'syllabus':/pyq|exam|question.paper|past.paper/i.test(file.name)?'pyq':'material';
    state.files.push({file,role});
  }
  renderFiles();
}
function captureDraft(){
  for(const m of state.draft){
    const title=$('[data-draft-title="'+CSS.escape(m.id)+'"]'),topics=$('[data-draft-topics="'+CSS.escape(m.id)+'"]');
    if(title)m.title=title.value.trim();if(topics)m.topics=topics.value.split('\n').map(x=>x.trim()).filter(Boolean);
    m.prerequisites=$$('[data-draft-parent="'+CSS.escape(m.id)+'"]:checked').map(x=>x.value);
    if(state.current.c?.scope_records){
      m.scope_ids=$$('[data-draft-scope="'+CSS.escape(m.id)+'"]:checked').map(x=>x.value);
      m.source_ranges=$$('[data-range-doc="'+CSS.escape(m.id)+'"]').map(x=>({doc_id:x.value,start_page:Number($(`[data-range-start="${CSS.escape(m.id)}"][data-index="${x.dataset.index}"]`).value),end_page:Number($(`[data-range-end="${CSS.escape(m.id)}"][data-index="${x.dataset.index}"]`).value)}));
      m.scope_notes=$('[data-draft-scope-notes="'+CSS.escape(m.id)+'"]')?.value||'';
    }
  }
  state.scopeExclusions=$$('[data-scope-exclusion]').filter(x=>x.value.trim()).map(x=>({scope_id:x.dataset.scopeExclusion,reason:x.value.trim()}));
  state.scopeGapsAccepted=!!$('#acknowledge-scope-gaps')?.checked||!!state.current.c?.scope_review;
}
async function saveOutline(){captureDraft();const c=state.current.c;const saved=await api(`/courses/${c.id}/outline`,{modules:state.draft,scope_exclusions:state.scopeExclusions,acknowledge_gaps:state.scopeGapsAccepted});updateCourse(saved);state.draft=structuredClone(saved.modules);return saved;}
function addScopeRanges(module,records){
  const pairs=new Map();
  for(const r of module.source_ranges||[])for(let page=r.start_page;page<=r.end_page;page++)pairs.set(`${r.doc_id}:${page}`,{doc_id:r.doc_id,page});
  for(const r of records)for(const page of r.pages)pairs.set(`${r.doc_id}:${page}`,{doc_id:r.doc_id,page});
  const sorted=[...pairs.values()].sort((a,b)=>a.doc_id.localeCompare(b.doc_id)||a.page-b.page),ranges=[];
  for(const r of sorted){const last=ranges.at(-1);if(last?.doc_id===r.doc_id&&last.end_page===r.page-1)last.end_page=r.page;else ranges.push({doc_id:r.doc_id,start_page:r.page,end_page:r.page});}
  module.source_ranges=ranges;
}
async function prepare(action,module_id=null){const c=state.current.c;const saved=await api(`/courses/${c.id}/prepare`,{action,module_id});updateCourse(saved);render();}
async function saveVisual(extra=null,skip=false){
  const c=state.current.c,selected=skip?[]:$$('[data-visual-doc]:checked').map(x=>({doc_id:x.dataset.visualDoc,page:Number(x.dataset.visualPage)}));
  if(extra&&!selected.some(r=>r.doc_id===extra.doc_id&&r.page===extra.page))selected.push(extra);
  const saved=await api(`/courses/${c.id}/visual`,{selected});updateCourse(saved);return saved;
}
async function progress(body){
  const {c,m}=state.current;
  if(!c||!m)throw new Error('Choose a module first.');
  const value=await api(`/courses/${c.id}/modules/${enc(m.id)}/progress`,body);updateCourse(value.course);return value.course;
}

function openModal(html,focusSelector){
  lastFocus=document.activeElement;$('#overlay-root').innerHTML=`<div class="overlay" data-dismiss="true">${html}</div>`;document.body.style.overflow='hidden';
  requestAnimationFrame(()=>$(focusSelector||'button,input,a',document.getElementById('overlay-root'))?.focus());
}
function closeModal(){
  $('#overlay-root').innerHTML='';document.body.style.overflow='';lastFocus?.focus();
}
function source(docId,page=1){
  const d=state.courses.flatMap(c=>c.documents).find(x=>x.id===docId);if(!d)throw new Error('This source document is not available.');
  page=Math.max(1,Math.min(d.page_count,Number(page)||1));
  openModal(`<section class="modal source-modal" role="dialog" aria-modal="true" aria-labelledby="source-title"><div class="modal-head"><div><span class="eyebrow">YOUR ORIGINAL SOURCE</span><h2 id="source-title">${esc(d.name)}</h2></div><button class="icon-btn" data-action="close-modal" aria-label="Close source viewer">${icon('close')}</button></div><div class="source-toolbar"><label>PDF page <input id="source-page" type="number" min="1" max="${d.page_count}" value="${page}" data-doc="${d.id}"> of ${d.page_count}</label><button class="text-btn" data-action="source-text">Read extracted text</button><a class="text-btn" id="source-external" href="/api/documents/${d.id}#page=${page}" target="_blank" rel="noopener">Open original PDF ${icon('external')}</a></div><div id="source-annotation" class="source-annotation hidden"></div><div class="source-viewport"><p id="source-loading" class="source-loading" role="status">Opening the saved page…</p><img class="source-page-image" id="source-image" src="/api/documents/${d.id}/pages/${page}.png" alt="${esc(d.name)}, physical PDF page ${page}"><div id="source-text" class="source-text hidden" role="region" aria-label="Extracted source page text"></div></div></section>`,'[data-action="close-modal"]');
  sourceAnnotation(d,page);
}
function sourceAnnotation(doc,page){
  const target=$('#source-annotation'),notes=(doc.annotations||[]).filter(n=>n.page===page);
  target.classList.toggle('hidden',!notes.length);
  target.innerHTML=notes.map(n=>`<strong>Reviewed source clarification</strong><p>${esc(n.message)}</p>${/^https?:\/\//.test(n.url||'')?`<a class="text-btn" href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">Supporting reference ${icon('external')}</a>`:''}`).join('');
}
function changeSourcePage(input,clamp=false){
  let page=Number(input.value);
  if(clamp){page=Math.max(1,Math.min(Number(input.max),Math.floor(page)||1));input.value=page;}
  if(!Number.isInteger(page)||page<1||page>Number(input.max))return;
  const doc=state.courses.flatMap(c=>c.documents).find(d=>d.id===input.dataset.doc);if(doc)sourceAnnotation(doc,page);
  const path=`/api/documents/${input.dataset.doc}/pages/${page}.png`;
  if($('#source-image').getAttribute('src')===path)return;
  $('#source-loading').textContent='Opening the saved page…';$('#source-loading').classList.remove('hidden');$('.source-viewport').scrollTop=0;
  $('#source-image').src=path;$('#source-image').classList.remove('hidden');$('#source-image').alt=`Source document, physical PDF page ${page}`;$('#source-text').classList.add('hidden');$('[data-action="source-text"]').textContent='Read extracted text';$('#source-external').href=`/api/documents/${input.dataset.doc}#page=${page}`;
}
function searchModal(){
  openModal(`<section class="modal search-modal" role="dialog" aria-modal="true" aria-label="Find an idea"><div class="search-input-row">${icon('search')}<input id="search-input" placeholder="Search modules, topics, or courses…" autocomplete="off" aria-label="Search courses and topics"><button class="icon-btn" data-action="close-modal" aria-label="Close search">${icon('close')}</button></div><div id="search-results" class="search-results"></div><div class="search-footer">Your saved course material · Esc to close</div></section>`,'#search-input');
  searchResults('');
}
function searchResults(query){
  query=query.trim().toLowerCase();const results=[];
  for(const c of state.courses){if(!query||c.title.toLowerCase().includes(query))results.push({title:c.title,detail:'Course workspace',href:link(c.id),ico:'graph'});for(const m of c.modules){if(query&&[m.title,...m.topics].join(' ').toLowerCase().includes(query))results.push({title:m.title,detail:c.title,href:link(c.id,m.id),ico:'book'});}}
  $('#search-results').innerHTML=results.slice(0,15).map(r=>`<a class="search-result" data-close-modal href="${r.href}"><div class="aside-icon">${icon(r.ico)}</div><div><strong>${esc(r.title)}</strong><small>${esc(r.detail)}</small></div><span class="spacer"></span>${icon('chevron')}</a>`).join('')||'<div class="modal-body muted small-text">No matches yet. Try another topic name.</div>';
}
function startReview(cid=null){
  let cards=UI.dueCards(state.courses,cid);if(!cards.length&&cid)cards=UI.dueCards(state.courses,cid,null,true);
  if(!cards.length){toast('No cards are due right now.');return;}
  state.review={key:'daily',cards,pos:0,flipped:false};goto('#/revision/review');
}
async function flushNotes(){
  clearTimeout(notesTimer);
  if(notesFlight){await notesFlight;return flushNotes();}
  if(!state.notesPending)return;
  const pending=state.notesPending;state.notesPending=null;state.notesSaving=pending;
  notesFlight=(async()=>{
    try{const value=await api(`/courses/${pending.cid}/modules/${enc(pending.mid)}/progress`,{notes:pending.text});updateCourse(value.course);if($('#notes-status'))$('#notes-status').textContent=state.notesPending?'Saving…':'Saved on this computer';}
    catch(error){if(!state.notesPending)state.notesPending=pending;if($('#notes-status'))$('#notes-status').textContent='Not saved — try Save notes';throw error;}
  })();
  try{await notesFlight;}finally{notesFlight=null;state.notesSaving=null;}
  if(state.notesPending)return flushNotes();
}

document.addEventListener('click',async event=>{
  const closeLink=event.target.closest('[data-close-modal]');if(closeLink)closeModal();
  if(event.target.matches('.overlay[data-dismiss]')){closeModal();return;}
  const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
  const action=el.dataset.action;let busy=false;
  try{
    const {c,m}=state.current;
    if(action==='skip-content'){event.preventDefault();$('#main').focus();$('#main').scrollIntoView();}
    if(['prepare-outline','inspect-visual','analyze-visual','save-visual','skip-visual','include-visual-page','resume','generate-course','generate-practice','generate-papers','save-outline','save-notes','submit-quiz','rate-card','clear-key','bookmark','mark-read','confirm-delete-course'].includes(action)){busy=true;el.disabled=true;}
    if(action==='sidebar'){$('#sidebar').classList.add('open');$('.mobile-shade').classList.add('open');}
    if(action==='close-sidebar'){$('#sidebar').classList.remove('open');$('.mobile-shade').classList.remove('open');}
    if(action==='import')$('#import-input').click();
    if(action==='search')searchModal();
    if(action==='close-modal')closeModal();
    if(action==='dismiss-deletion'){state.lastDeletion=null;render();}
    if(action==='delete-course'){
      const target=state.courses.find(c=>c.id===el.dataset.course);
      if(target)openModal(UI.deleteCourseDialog(target),'[data-action="close-modal"]');
    }
    if(action==='confirm-delete-course'){
      const cid=el.dataset.course;
      await flushNotes();
      const receipt=await api(`/courses/${cid}/delete`,{confirm:cid});
      state.courses=state.courses.filter(c=>c.id!==cid);state.lastDeletion=receipt;
      for(const key of Object.keys(state.quizzes))if(key.startsWith(cid+':'))delete state.quizzes[key];
      for(const key of Object.keys(sessionStorage))if(key.startsWith('folium-quiz-'+cid+':'))sessionStorage.removeItem(key);
      if(state.draftCid===cid){state.draftCid=null;state.draft=[];}
      if(state.allowPrepared===cid)state.allowPrepared=null;
      if(state.review?.cards.some(card=>card.cid===cid))state.review=null;
      closeModal();goto('#/');toast('Course deleted. Your recovery copy is saved.');
    }
    if(action==='source')source(el.dataset.doc,el.dataset.page);
    if(action==='source-text'){
      const input=$('#source-page'),text=$('#source-text'),image=$('#source-image');
      if(text.classList.contains('hidden')){const data=await api(`/documents/${input.dataset.doc}/pages/${input.value}`);text.textContent=(data.warning?data.warning+'\n\n':'')+('NATIVE PDF TEXT\n'+(data.text||'No native text is available.')+(data.recognized_text?'\n\nRECOGNIZED IMAGE TEXT · UNVERIFIED\n'+data.recognized_text:'')+(data.visual_description?'\n\nVISUAL INTERPRETATION · UNVERIFIED\n'+data.visual_description:''));$('#source-loading').classList.add('hidden');text.classList.remove('hidden');image.classList.add('hidden');el.textContent='View original page';}
      else{text.classList.add('hidden');image.classList.remove('hidden');el.textContent='Read extracted text';}
    }
    if(action==='course-view'){state.view=el.dataset.view;state.zoom=null;render();}
    if(action==='map-expand')toggleMap();
    if(action==='zoom-in'||action==='zoom-out'||action==='zoom-fit'){
      const current=Number($('.graph-stage')?.dataset.scale)||1;
      state.zoom=action==='zoom-fit'?null:Math.min(2,Math.max(.2,current+(action==='zoom-in'?.15:-.15)));applyGraphZoom();
      if(action==='zoom-fit'){$('.graph-scroll').scrollLeft=0;$('.graph-scroll').scrollTop=0;}
    }
    if(action==='bookmark'){await flushNotes();const bookmarked=!m.bookmarked;await progress({bookmarked});const y=scrollY;render();scrollTo(0,y);toast(bookmarked?'Saved for another look.':'Removed from saved modules.');}
    if(action==='mark-read'){await flushNotes();const read=!m.read;await progress({read});const y=scrollY;render();scrollTo(0,y);toast(read?'A little more understanding. Progress saved.':'Marked as not yet studied.');}
    if(action==='scroll-section')$('#section-'+el.dataset.index)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    if(action==='reveal'){const target=$('#'+el.dataset.target);target.classList.toggle('hidden');el.innerHTML=(target.classList.contains('hidden')?'Reveal solution':'Hide solution')+' '+icon('down');}
    if(action==='submit-quiz'){
      const q=getQuiz(c,m),value=await api(`/courses/${c.id}/modules/${enc(m.id)}/quiz`,{answers:q.answers,question_ids:q.order});updateCourse(value.course);q.result=value.result;saveQuiz(c,m);render();window.scrollTo({top:0,behavior:'smooth'});toast('Practice saved. Your course map is up to date.');
    }
    if(action==='reset-quiz'){state.quizzes[quizKey(c,m)]=newQuiz(m,getQuiz(c,m).topic);saveQuiz(c,m);render();window.scrollTo(0,0);}
    if(action==='extend-course'){
      openModal(`<section class="modal extend-modal" role="dialog" aria-modal="true" aria-labelledby="extend-title"><div class="modal-head"><h2 id="extend-title">Make room for a missing topic.</h2><button class="icon-btn" data-action="close-modal" aria-label="Close">${icon('close')}</button></div><form id="extend-form" class="modal-body"><p class="muted">Add a module from your existing materials. Your saved modules stay available, and a backup is created before the addition.</p><div class="field"><label for="extend-title-input">Module title</label><input id="extend-title-input" name="title" required maxlength="150"></div><div class="field"><label for="extend-topics">Topics · one per line</label><textarea id="extend-topics" name="topics" required></textarea></div>${c.scope_records?`<div class="field"><label>Reviewed source scope for the new module</label>${c.scope_records.map(r=>`<label class="scope-choice"><input type="checkbox" name="scope_ids" value="${esc(r.id)}"><span>${esc(r.title)}<small>${esc(r.depth)}</small></span></label>`).join('')}</div><div class="field"><label for="extend-scope-notes">Scope and depth clarifications</label><textarea id="extend-scope-notes" name="scope_notes" maxlength="12000"></textarea></div>`:''}<div class="field"><label>Prerequisites</label><div class="prereq-select">${c.modules.map(m=>`<label><input type="checkbox" name="parents" value="${esc(m.id)}">${esc(m.title)}</label>`).join('')}</div></div><p class="small-text muted">Adding a module uses no AI calls. Starting preparation uses one plan call, then one call per lesson.</p><button class="btn primary" type="submit">Save missing module ${icon('arrow')}</button></form></section>`,'#extend-title-input');
    }
    if(action==='save-notes'){await flushNotes();toast('Your notes are saved.');}
    if(action==='remove-file'){state.files.splice(Number(el.dataset.index),1);renderFiles();}
    if(action==='prepare-outline')await prepare('outline');
    if(action==='inspect-visual')await prepare('inspect');
    if(action==='save-visual'){await saveVisual();render();toast('Visual page selection saved.');}
    if(action==='include-visual-page'){await saveVisual({doc_id:$('#visual-manual-doc').value,page:Number($('#visual-manual-page').value)});render();}
    if(action==='skip-visual'){await saveVisual(null,true);render();toast('Visual analysis excluded. Any missing visual scope will stay visible for review.');}
    if(action==='analyze-visual'){await saveVisual();await prepare('visual');}
    if(action==='save-outline'){await saveOutline();render();toast('Course outline saved.');}
    if(action==='add-module'){captureDraft();if(state.draft.length>=20)throw new Error('Keep this course to 20 modules or fewer.');state.draft.push({id:'m'+Date.now(),title:'New module',description:'',topics:['New topic'],prerequisites:[],scope_ids:[],source_ranges:[],scope_notes:''});render();}
    if(action==='add-range'){captureDraft();const m=state.draft.find(m=>m.id===el.dataset.module),doc=c.documents.find(d=>d.role!=='pyq');if(doc){m.source_ranges.push({doc_id:doc.id,start_page:1,end_page:1});render();}}
    if(action==='remove-range'){captureDraft();state.draft.find(m=>m.id===el.dataset.module).source_ranges.splice(Number(el.dataset.index),1);render();}
    if(action==='remove-module'){captureDraft();const removed=state.draft.splice(Number(el.dataset.index),1)[0];state.draft.forEach(x=>x.prerequisites=x.prerequisites.filter(id=>id!==removed.id));render();}
    if(action==='generate-practice'){await flushNotes();await prepare('practice',m.id);render();}
    if(action==='generate-papers'){await flushNotes();await prepare('papers');render();}
    if(action==='generate-course'){await saveOutline();await prepare('generate');}
    if(action==='resume')await prepare(['practice','papers'].includes(c.job?.action)?c.job.action:c.modules.length?'generate':['inspect','visual','visual_render'].includes(c.job?.stage)?(c.job.stage==='inspect'?'inspect':'visual'):'outline',c.job?.module_id||null);
    if(action==='open-prepared'){state.allowPrepared=c.id;goto(link(c.id)+'/explore');}
    if(action==='start-review')startReview(el.dataset.course);
    if(action==='flip-card'){if(state.review){state.review.flipped=!state.review.flipped;const y=scrollY;render();scrollTo(0,y);}}
    if(action==='rate-card'){
      const session=state.review,item=session.cards[session.pos];
      const value=await api(`/courses/${item.cid}/modules/${enc(item.mid)}/review`,{index:item.index,rating:el.dataset.rating});updateCourse(value.course);session.pos++;session.flipped=false;render();
    }
    if(action==='theme'){state.theme=el.dataset.theme;localStorage.setItem('folium-theme',state.theme);render();}
    if(action==='clear-key'){
      const slot=Number(el.dataset.slot||1),field=slot===1?'clear_key':`clear_key_${slot}`;
      state.settings=await api('/settings',{[field]:true});render();toast(`Saved key ${slot} removed.`);
    }
  }catch(error){toast(error.message,true);}finally{if(busy&&el.isConnected)el.disabled=false;}
});

document.addEventListener('submit',async event=>{
  if(!['settings-form','create-form','extend-form'].includes(event.target.id))return;
  event.preventDefault();const form=event.target,button=$('button[type="submit"]',form);button.disabled=true;const old=button.innerHTML;
  try{
    if(form.id==='extend-form'){
      const data=new FormData(form),c=state.current.c;
      const module={id:'m'+Date.now(),title:data.get('title'),topics:String(data.get('topics')).split('\n').map(t=>t.trim()).filter(Boolean),prerequisites:data.getAll('parents')};
      if(c.scope_records){module.scope_ids=data.getAll('scope_ids');module.scope_notes=String(data.get('scope_notes')||'');addScopeRanges(module,c.scope_records.filter(r=>module.scope_ids.includes(r.id)));}
      const saved=await api(`/courses/${c.id}/extend`,{modules:[module]});
      updateCourse(saved);state.allowPrepared=null;closeModal();goto(link(c.id)+'/setup');toast('Module added. Ready to prepare only the missing content.');
    }else if(form.id==='settings-form'){
      const data=new FormData(form);state.settings=await api('/settings',{api_key:data.get('api_key'),api_key_2:data.get('api_key_2'),api_key_3:data.get('api_key_3'),model:data.get('model'),task_model:data.get('task_model'),vision_model:data.get('vision_model'),interval:Number(data.get('interval'))});render();toast('Your connection settings are saved.');
    }else{
      if(!state.files.length)throw new Error('Add at least one course PDF.');
      if(state.files.every(f=>f.role==='pyq'))throw new Error('Add a syllabus or learning material alongside your past papers.');
      if(state.files.reduce((n,f)=>n+f.file.size,0)>75*1024*1024)throw new Error('Keep this upload below 75 MB in total.');
      button.innerHTML='<span class="spinner"></span>Reading your PDFs…';
      const data=new FormData();data.append('title',$('#course-title').value);data.append('roles',JSON.stringify(state.files.map(f=>f.role)));state.files.forEach(f=>data.append('files',f.file));
      const course=await api('/courses',data);updateCourse(course);state.files=[];state.draftCid=null;goto(link(course.id)+'/setup');toast('Your materials are saved. Ready for the next step.');
    }
  }catch(error){const target=$('#create-error');if(target)target.textContent=error.message;else toast(error.message,true);}
  finally{if(button.isConnected){button.disabled=false;button.innerHTML=old;}}
});

document.addEventListener('change',async event=>{
  const el=event.target;
  if(el.dataset.visualDoc){const button=$('[data-action="analyze-visual"]');if(button)button.disabled=!$$('[data-visual-doc]:checked').length;}
  if(el.dataset.draftScope){
    captureDraft();const m=state.draft.find(m=>m.id===el.dataset.draftScope),y=scrollY;
    addScopeRanges(m,state.current.c.scope_records.filter(r=>m.scope_ids.includes(r.id)));
    const mapped=new Set(state.draft.flatMap(m=>m.scope_ids||[]));state.scopeExclusions=state.scopeExclusions.filter(r=>!mapped.has(r.scope_id));
    render();scrollTo(0,y);
  }
  if(el.id==='practice-topic'){
    const {c,m}=state.current;state.quizzes[quizKey(c,m)]=newQuiz(m,el.value);saveQuiz(c,m);const y=scrollY;render();scrollTo(0,y);
  }
  if(el.id==='pdf-input'){addFiles(el.files);el.value='';}
  if(el.dataset.fileRole!==undefined)state.files[Number(el.dataset.fileRole)].role=el.value;
  if(el.dataset.question){
    const {c,m}=state.current,q=getQuiz(c,m);q.answers[el.dataset.question]=Number(el.value);saveQuiz(c,m);
    $$('.question-options').forEach(group=>$$('.option',group).forEach(label=>label.classList.toggle('selected',!!$('input',label)?.checked)));
    const total=q.order.length,count=Object.keys(q.answers).length;
    $('#answered-count').textContent=`${count} of ${total} answered`;$('[data-action="submit-quiz"]').disabled=count<total;
  }
  if(el.id==='source-page'){
    changeSourcePage(el,true);
  }
  if(el.id==='import-input'){
    const file=el.files[0];el.value='';if(!file)return;
    try{toast('Opening your saved course…');const data=new FormData();data.append('file',file);const c=await api('/import',data);updateCourse(c);goto(link(c.id));toast('Course imported. Welcome back.');}catch(error){toast(error.message,true);}
  }
});
document.addEventListener('input',event=>{
  if(event.target.id==='source-page')changeSourcePage(event.target);
  if(event.target.id==='search-input')searchResults(event.target.value);
  if(event.target.id==='module-notes'){
    const {c,m}=state.current,text=event.target.value;m.notes=text;state.notesPending={cid:c.id,mid:m.id,text};$('#notes-status').textContent='Saving…';clearTimeout(notesTimer);notesTimer=setTimeout(()=>flushNotes().catch(e=>toast(e.message,true)),900);
  }
});
document.addEventListener('load',event=>{if(event.target.id==='source-image')$('#source-loading')?.classList.add('hidden');},true);
document.addEventListener('error',event=>{if(event.target.id==='source-image'&&$('#source-loading'))$('#source-loading').textContent='The page preview could not load. You can read the extracted text or open the original PDF.';},true);
document.addEventListener('dragover',event=>{const zone=event.target.closest('#dropzone');if(zone){event.preventDefault();zone.classList.add('dragover');}});
document.addEventListener('dragleave',event=>event.target.closest('#dropzone')?.classList.remove('dragover'));
document.addEventListener('drop',event=>{const zone=event.target.closest('#dropzone');if(zone){event.preventDefault();zone.classList.remove('dragover');addFiles(event.dataTransfer.files);}});
document.addEventListener('keydown',event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();searchModal();}
  if(event.key==='Escape'){if($('.map-panel.expanded'))toggleMap();closeModal();$('#sidebar')?.classList.remove('open');$('.mobile-shade')?.classList.remove('open');}
  if(event.target.id==='dropzone'&&['Enter',' '].includes(event.key)){event.preventDefault();$('#pdf-input').click();}
  if(event.key==='Tab'&&$('.map-panel.expanded')){
    const nodes=$$('a[href],button,[tabindex="0"]',$('.map-panel.expanded')).filter(x=>x.getClientRects().length),first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
  if(event.key==='Tab'&&$('#overlay-root .modal')){
    const nodes=$$('a[href],button:not(:disabled),input,select,textarea,iframe',[...$('#overlay-root').children][0]).filter(x=>x.getClientRects().length),first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});

let positionTimer;
window.addEventListener('scroll',()=>{clearTimeout(positionTimer);positionTimer=setTimeout(()=>{const {c,m,tab}=state.current;if(c&&m&&tab==='study')localStorage.setItem(`folium-position-${c.id}-${m.id}`,String(scrollY));},200);},{passive:true});
window.addEventListener('hashchange',async()=>{
  try{await flushNotes();await loadRouteCourse();}catch(error){toast(error.message,true);}
  closeModal();render();const {c,m,tab}=state.current;
  if(c&&m&&tab==='study')window.scrollTo(0,Number(localStorage.getItem(`folium-position-${c.id}-${m.id}`)||0));else window.scrollTo(0,0);
});
window.addEventListener('beforeunload',()=>{
  if(state.notesPending||state.notesSaving){const p=state.notesPending||state.notesSaving;fetch(`/api/courses/${p.cid}/modules/${enc(p.mid)}/progress`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:p.text}),keepalive:true}).catch(()=>{});}
});

let polling=false;
async function pollCourses(){
  if(polling)return;const active=state.courses.filter(c=>c.job?.state==='running');if(!active.length)return;
  polling=true;
  try{
    for(const old of active){let c;
      try{c=await api('/courses/'+old.id+'/status');}catch(error){if(!state.courses.some(c=>c.id===old.id))continue;throw error;}
      if(!state.courses.some(c=>c.id===old.id))continue;
      const packageState=x=>JSON.stringify(x.modules.map(m=>[m.id,!!m.package,m.package?.assessment_status]));
      if(!old.summary){
        if(c.job?.state!=='running'||packageState(c)!==packageState(old))c=await api('/courses/'+old.id);
        else{old.job=c.job;old.status=c.status;old.updated=c.updated;c=old;}
      }
      if(!state.courses.some(c=>c.id===old.id))continue;
      updateCourse(c);if(c.job?.state==='complete'&&c.modules.length)state.draftCid=null;
      const r=route();if(r[0]==='course'&&r[1]===c.id&&r[2]!=='module'){
        if(c.status==='ready'){state.allowPrepared=null;goto(link(c.id));}else render();
      }else if(r[0]==='course'&&r[1]===c.id&&r[2]==='module'){
        const previous=state.current.m;
        state.current.c=c;state.current.m=c.modules.find(m=>m.id===r[3]);
        const banner=$('#preparation-status'),html=UI.preparationNotice(c);
        if(banner&&banner.innerHTML!==html)banner.innerHTML=html;
        if(!previous?.package&&state.current.m?.package)render();
        else if(['practice','cards','pyqs'].includes(r[4])&&['practice','papers'].includes(c.job?.action)){
          if(c.job.state==='complete')state.review=null;render();
        }
      }else if(!r[0])render();
    }
  }catch(error){toast(error.message,true);}finally{polling=false;}
}
setInterval(pollCourses,2500);

async function init(){
  try{[state.courses,state.settings]=await Promise.all([api('/courses'),api('/settings')]);await loadRouteCourse();render();const {c,m,tab}=state.current;if(c&&m&&tab==='study')requestAnimationFrame(()=>scrollTo(0,Number(localStorage.getItem(`folium-position-${c.id}-${m.id}`)||0)));
  }
  catch(error){$('#app').innerHTML=`<div class="fatal"><span class="eyebrow">FOLIUM</span><h1>A little reconnection.</h1><p>${esc(error.message)}</p><button class="btn primary" id="reconnect">Try again ${icon('refresh')}</button></div>`;$('#reconnect').addEventListener('click',init);}
}
init();
