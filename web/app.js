import * as UI from './ui.js';
const {esc,icon,link,enc}=UI;
const $=(s,root=document)=>root.querySelector(s);
const $$=(s,root=document)=>[...root.querySelectorAll(s)];
const state={courses:[],settings:{has_key:false,model:'gemini-3.8-flash',interval:6},view:'graph',zoom:1,
  files:[],draft:[],draftCid:null,review:null,quizzes:{},theme:localStorage.getItem('folium-theme')||'light',
  current:{},allowPrepared:null,previousRoute:'',notesPending:null};
let toastTimer,notesTimer,lastFocus;

async function api(path,body){
  const options=body===undefined?{}:body instanceof FormData?{method:'POST',body}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  let response;
  try{response=await fetch('/api'+path,options);}catch{throw new Error('The local app could not be reached. Check that Folium is still running.');}
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||'Something could not be saved. Please try again.');
  return value;
}
function updateCourse(c){const index=state.courses.findIndex(x=>x.id===c.id);if(index<0)state.courses.unshift(c);else state.courses[index]=c;}
function toast(text,error=false){const el=$('#toast');clearTimeout(toastTimer);el.textContent=text;el.className='visible'+(error?' error':'');toastTimer=setTimeout(()=>el.className='',error?6500:3400);}
function route(){return (location.hash.replace(/^#\/?/,'')||'').split('/').map(decodeURIComponent);}
function goto(path){if(location.hash===path){render();window.scrollTo(0,0);}else location.hash=path;}
const quizKey=(c,m)=>`${c.id}:${m.id}`;
function getQuiz(c,m){const key=quizKey(c,m);if(!state.quizzes[key]){try{state.quizzes[key]=JSON.parse(sessionStorage.getItem('folium-quiz-'+key))||{answers:{}};}catch{state.quizzes[key]={answers:{}};}}return state.quizzes[key];}
function saveQuiz(c,m){sessionStorage.setItem('folium-quiz-'+quizKey(c,m),JSON.stringify(state.quizzes[quizKey(c,m)]));}
function brand(){return `<a class="brand" href="#/" aria-label="Folium home"><svg class="brand-mark" viewBox="0 0 32 36" fill="none" aria-hidden="true"><path d="M5 31V15C5 6 14 2 29 3 28 17 20 24 9 24M9 23 23 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span class="brand-word">folium<span>.</span></span></a>`;}
function shell(body,pageTitle='My courses',active='courses',cid=null){
  const due=UI.dueCards(state.courses).length;
  return `<div class="shell"><aside class="sidebar" id="sidebar">${brand()}<div class="space-label">YOUR WORKSPACE</div><nav aria-label="Main navigation"><a class="nav-item ${active==='courses'?'active':''}" href="#/">${icon('grid')}My courses</a><a class="nav-item ${active==='revision'?'active':''}" href="#/revision">${icon('cards')}Revision${due?`<span class="count">${due}</span>`:''}</a><a class="nav-item ${active==='saved'?'active':''}" href="#/saved">${icon('bookmark')}Saved</a></nav><div class="sidebar-divider"></div><div class="row between"><div class="space-label" style="margin-bottom:0">YOUR COURSES</div><a class="text-btn" href="#/new" aria-label="Create a course" style="margin-right:10px">${icon('plus')}</a></div><div style="margin-top:10px">${state.courses.slice(0,6).map(c=>`<a class="side-course ${cid===c.id?'current':''}" href="${link(c.id)}"><span class="dot"></span><span class="name">${esc(c.title)}</span></a>`).join('')}</div><div class="sidebar-bottom"><div class="local-card">${icon('shield')}<strong>Your space. Your pace.</strong>Prepared once.<br>Always here to return to.</div><a class="nav-item ${active==='settings'?'active':''}" style="padding-left:0" href="#/settings">${icon('settings')}Settings</a><div class="sidebar-divider" style="margin:13px 0"></div><div class="profile"><span class="avatar">Y</span><span>Your workspace<small>LOCAL & PERSONAL</small></span></div></div></aside><div class="mobile-shade" data-action="close-sidebar"></div><div class="main-shell"><header class="topbar"><button class="icon-btn mobile-menu" data-action="sidebar" aria-label="Open navigation">${icon('menu')}</button><div class="breadcrumb"><a href="#/">Workspace</a>${icon('chevron')}<span class="current">${esc(pageTitle)}</span></div><div class="top-actions"><button class="search-trigger" data-action="search">${icon('search')}Find an idea <kbd>Ctrl K</kbd></button><span class="saved-status">${icon('shield')}Saved on your computer</span></div></header><main class="content" id="main" tabindex="-1">${body}</main></div></div>`;
}

function render(){
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
          if(tab==='cards'){
            const key=`${c.id}:${m.id}`;
            if(state.review?.key!==key)state.review={key,cards:UI.dueCards(state.courses,c.id,m.id,true),pos:0,flipped:false};
            body+=UI.flashcard(state.review);
          }
        }
      }else if(r[2]==='setup'||c.status!=='ready'&&state.allowPrepared!==c.id){
        if(state.draftCid!==c.id){state.draft=structuredClone(c.modules);state.draftCid=c.id;}
        body=UI.setupView(c,state.draft,state.settings);
      }else{body=UI.courseView(c,state.view,state.zoom);}
    }
  }else{body=UI.library(state.courses);}
  document.title=`${title} — Folium`;
  $('#app').innerHTML=shell(body,title,active,cid);
  if(r[0]==='new')renderFiles();
}

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
  }
}
async function saveOutline(){captureDraft();const c=state.current.c;const saved=await api(`/courses/${c.id}/outline`,{modules:state.draft});updateCourse(saved);state.draft=structuredClone(saved.modules);return saved;}
async function prepare(action){const c=state.current.c;const saved=await api(`/courses/${c.id}/prepare`,{action});updateCourse(saved);render();}
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
  openModal(`<section class="modal source-modal" role="dialog" aria-modal="true" aria-labelledby="source-title"><div class="modal-head"><div><span class="eyebrow">YOUR ORIGINAL SOURCE</span><h2 id="source-title">${esc(d.name)}</h2></div><button class="icon-btn" data-action="close-modal" aria-label="Close source viewer">${icon('close')}</button></div><div class="source-toolbar"><label>PDF page <input id="source-page" type="number" min="1" max="${d.page_count}" value="${page}" data-doc="${d.id}"> of ${d.page_count}</label><button class="text-btn" data-action="source-text">Read extracted text</button><a class="text-btn" id="source-external" href="/api/documents/${d.id}#page=${page}" target="_blank" rel="noopener">Open original PDF ${icon('external')}</a></div><div class="source-viewport"><p id="source-loading" class="source-loading" role="status">Opening the saved page…</p><img class="source-page-image" id="source-image" src="/api/documents/${d.id}/pages/${page}.png" alt="${esc(d.name)}, physical PDF page ${page}"><div id="source-text" class="source-text hidden" role="region" aria-label="Extracted source page text"></div></div></section>`,'[data-action="close-modal"]');
}
function changeSourcePage(input,clamp=false){
  let page=Number(input.value);
  if(clamp){page=Math.max(1,Math.min(Number(input.max),Math.floor(page)||1));input.value=page;}
  if(!Number.isInteger(page)||page<1||page>Number(input.max))return;
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
  clearTimeout(notesTimer);if(!state.notesPending)return;
  const pending=state.notesPending;state.notesPending=null;
  try{const value=await api(`/courses/${pending.cid}/modules/${enc(pending.mid)}/progress`,{notes:pending.text});updateCourse(value.course);if($('#notes-status'))$('#notes-status').textContent='Saved on this computer';}
  catch(error){state.notesPending=pending;if($('#notes-status'))$('#notes-status').textContent='Not saved — try Save notes';throw error;}
}

document.addEventListener('click',async event=>{
  const closeLink=event.target.closest('[data-close-modal]');if(closeLink)closeModal();
  if(event.target.matches('.overlay[data-dismiss]')){closeModal();return;}
  const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
  const action=el.dataset.action;let busy=false;
  try{
    const {c,m}=state.current;
    if(action==='skip-content'){event.preventDefault();$('#main').focus();$('#main').scrollIntoView();}
    if(['prepare-outline','resume','generate-course','save-outline','save-notes','submit-quiz','rate-card','clear-key','bookmark','mark-read'].includes(action)){busy=true;el.disabled=true;}
    if(action==='sidebar'){$('#sidebar').classList.add('open');$('.mobile-shade').classList.add('open');}
    if(action==='close-sidebar'){$('#sidebar').classList.remove('open');$('.mobile-shade').classList.remove('open');}
    if(action==='import')$('#import-input').click();
    if(action==='search')searchModal();
    if(action==='close-modal')closeModal();
    if(action==='source')source(el.dataset.doc,el.dataset.page);
    if(action==='source-text'){
      const input=$('#source-page'),text=$('#source-text'),image=$('#source-image');
      if(text.classList.contains('hidden')){const data=await api(`/documents/${input.dataset.doc}/pages/${input.value}`);text.textContent=data.text||'No readable text was found on this page.';text.classList.remove('hidden');image.classList.add('hidden');el.textContent='View original page';}
      else{text.classList.add('hidden');image.classList.remove('hidden');el.textContent='Read extracted text';}
    }
    if(action==='course-view'){state.view=el.dataset.view;render();}
    if(action==='zoom-in'||action==='zoom-out'||action==='zoom-fit'){
      const oldScroll=$('.graph-scroll'),left=oldScroll?.scrollLeft||0,top=oldScroll?.scrollTop||0;
      state.zoom=action==='zoom-fit'?1:Math.min(1.5,Math.max(.55,state.zoom+(action==='zoom-in'?.15:-.15)));render();
      if($('.graph-scroll')){$('.graph-scroll').scrollLeft=left;$('.graph-scroll').scrollTop=top;}
    }
    if(action==='bookmark'){await flushNotes();await progress({bookmarked:!m.bookmarked});const y=scrollY;render();scrollTo(0,y);toast(m.bookmarked?'Removed from saved modules.':'Saved for another look.');}
    if(action==='mark-read'){await flushNotes();await progress({read:!m.read});const y=scrollY;render();scrollTo(0,y);toast(m.read?'Marked as not yet studied.':'A little more understanding. Progress saved.');}
    if(action==='scroll-section')$('#section-'+el.dataset.index)?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    if(action==='reveal'){const target=$('#'+el.dataset.target);target.classList.toggle('hidden');el.innerHTML=(target.classList.contains('hidden')?'Reveal solution':'Hide solution')+' '+icon('down');}
    if(action==='submit-quiz'){
      const q=getQuiz(c,m),value=await api(`/courses/${c.id}/modules/${enc(m.id)}/quiz`,{answers:q.answers});updateCourse(value.course);q.result=value.result;saveQuiz(c,m);render();window.scrollTo({top:0,behavior:'smooth'});toast('Practice saved. Your course map is up to date.');
    }
    if(action==='reset-quiz'){state.quizzes[quizKey(c,m)]={answers:{}};saveQuiz(c,m);render();window.scrollTo(0,0);}
    if(action==='save-notes'){await flushNotes();toast('Your notes are saved.');}
    if(action==='remove-file'){state.files.splice(Number(el.dataset.index),1);renderFiles();}
    if(action==='prepare-outline')await prepare('outline');
    if(action==='save-outline'){await saveOutline();render();toast('Course outline saved.');}
    if(action==='add-module'){captureDraft();if(state.draft.length>=20)throw new Error('Keep this course to 20 modules or fewer.');state.draft.push({id:'m'+Date.now(),title:'New module',description:'',topics:['New topic'],prerequisites:[]});render();}
    if(action==='remove-module'){captureDraft();const removed=state.draft.splice(Number(el.dataset.index),1)[0];state.draft.forEach(x=>x.prerequisites=x.prerequisites.filter(id=>id!==removed.id));render();}
    if(action==='generate-course'){await saveOutline();await prepare('generate');}
    if(action==='resume')await prepare(c.modules.length?'generate':'outline');
    if(action==='open-prepared'){state.allowPrepared=c.id;goto(link(c.id));}
    if(action==='start-review')startReview(el.dataset.course);
    if(action==='flip-card'){if(state.review){state.review.flipped=!state.review.flipped;const y=scrollY;render();scrollTo(0,y);}}
    if(action==='rate-card'){
      const session=state.review,item=session.cards[session.pos];
      const value=await api(`/courses/${item.cid}/modules/${enc(item.mid)}/review`,{index:item.index,rating:el.dataset.rating});updateCourse(value.course);session.pos++;session.flipped=false;render();
    }
    if(action==='theme'){state.theme=el.dataset.theme;localStorage.setItem('folium-theme',state.theme);render();}
    if(action==='clear-key'){state.settings=await api('/settings',{clear_key:true});render();toast('Saved key removed.');}
  }catch(error){toast(error.message,true);}finally{if(busy&&el.isConnected)el.disabled=false;}
});

document.addEventListener('submit',async event=>{
  if(!['settings-form','create-form'].includes(event.target.id))return;
  event.preventDefault();const form=event.target,button=$('button[type="submit"]',form);button.disabled=true;const old=button.innerHTML;
  try{
    if(form.id==='settings-form'){
      const data=new FormData(form);state.settings=await api('/settings',{api_key:data.get('api_key'),model:data.get('model'),interval:Number(data.get('interval'))});render();toast('Your connection settings are saved.');
    }else{
      if(!state.files.length)throw new Error('Add at least one readable course PDF.');
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
  if(el.id==='pdf-input'){addFiles(el.files);el.value='';}
  if(el.dataset.fileRole!==undefined)state.files[Number(el.dataset.fileRole)].role=el.value;
  if(el.dataset.question){
    const {c,m}=state.current,q=getQuiz(c,m);q.answers[el.dataset.question]=Number(el.value);saveQuiz(c,m);
    $$('.question-options').forEach(group=>$$('.option',group).forEach(label=>label.classList.toggle('selected',!!$('input',label)?.checked)));
    const total=m.package.questions.filter(x=>x.type==='objective').length,count=Object.keys(q.answers).length;
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
  if(event.key==='Escape'){closeModal();$('#sidebar')?.classList.remove('open');$('.mobile-shade')?.classList.remove('open');}
  if(event.target.id==='dropzone'&&['Enter',' '].includes(event.key)){event.preventDefault();$('#pdf-input').click();}
  if(event.key==='Tab'&&$('#overlay-root .modal')){
    const nodes=$$('a[href],button:not(:disabled),input,select,textarea,iframe',[...$('#overlay-root').children][0]).filter(x=>x.getClientRects().length),first=nodes[0],last=nodes[nodes.length-1];
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});

let positionTimer;
window.addEventListener('scroll',()=>{clearTimeout(positionTimer);positionTimer=setTimeout(()=>{const {c,m,tab}=state.current;if(c&&m&&tab==='study')localStorage.setItem(`folium-position-${c.id}-${m.id}`,String(scrollY));},200);},{passive:true});
window.addEventListener('hashchange',async()=>{
  try{await flushNotes();}catch(error){toast(error.message,true);}
  closeModal();render();const {c,m,tab}=state.current;
  if(c&&m&&tab==='study')window.scrollTo(0,Number(localStorage.getItem(`folium-position-${c.id}-${m.id}`)||0));else window.scrollTo(0,0);
});
window.addEventListener('beforeunload',()=>{
  if(state.notesPending){const p=state.notesPending;fetch(`/api/courses/${p.cid}/modules/${enc(p.mid)}/progress`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:p.text}),keepalive:true}).catch(()=>{});}
});

let polling=false;
setInterval(async()=>{
  if(polling)return;const active=state.courses.filter(c=>c.job?.state==='running');if(!active.length)return;
  polling=true;
  try{
    for(const old of active){const c=await api('/courses/'+old.id);updateCourse(c);if(c.job?.state==='complete'&&c.modules.length)state.draftCid=null;
      const r=route();if(r[0]==='course'&&r[1]===c.id&&r[2]!=='module'){
        if(c.status==='ready'){state.allowPrepared=null;goto(link(c.id));}else render();
      }else if(!r[0])render();
    }
  }catch(error){toast(error.message,true);}finally{polling=false;}
},2500);

async function init(){
  try{[state.courses,state.settings]=await Promise.all([api('/courses'),api('/settings')]);render();const {c,m,tab}=state.current;if(c&&m&&tab==='study')requestAnimationFrame(()=>scrollTo(0,Number(localStorage.getItem(`folium-position-${c.id}-${m.id}`)||0)));
  }
  catch(error){$('#app').innerHTML=`<div class="fatal"><span class="eyebrow">FOLIUM</span><h1>A little reconnection.</h1><p>${esc(error.message)}</p><button class="btn primary" id="reconnect">Try again ${icon('refresh')}</button></div>`;$('#reconnect').addEventListener('click',init);}
}
init();
