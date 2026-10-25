// Personal text ranges are painted over the reader; lesson HTML stays untouched.
export const COLORS = ['amber','sage','blue','rose'];
const names = {amber:'Amber',sage:'Sage',blue:'Blue',rose:'Rose'};
const styles = ['highlight','underline'];
const key = (style,color)=>`folium-${style}-${color}`;

export function signature(text){
  let hash=2166136261;
  for(let i=0;i<text.length;i++){hash^=text.charCodeAt(i);hash=Math.imul(hash,16777619);}
  return `${text.length}:${(hash>>>0).toString(16).padStart(8,'0')}`;
}

export function anchorFor(text,block,start,end){
  while(start<end&&/\s/.test(text[start]))start++;
  while(end>start&&/\s/.test(text[end-1]))end--;
  if(start===end)return null;
  return {block,start,end,exact:text.slice(start,end),prefix:[...text.slice(0,start)].slice(-32).join(''),
    suffix:[...text.slice(end)].slice(0,32).join(''),signature:signature(text)};
}

export function resolveAnchor(text,anchor){
  if(!anchor?.exact)return null;
  const matches=at=>text.slice(at,at+anchor.exact.length)===anchor.exact&&
    (anchor.prefix?text.slice(0,at).endsWith(anchor.prefix):at===0)&&
    (anchor.suffix?text.slice(at+anchor.exact.length).startsWith(anchor.suffix):at+anchor.exact.length===text.length);
  if(signature(text)===anchor.signature&&matches(anchor.start))return [anchor.start,anchor.end];
  const found=[];
  for(let at=text.indexOf(anchor.exact);at>=0;at=text.indexOf(anchor.exact,at+1)){
    if(matches(at))found.push(at);
    if(found.length>1)return null;
  }
  return found.length===1?[found[0],found[0]+anchor.exact.length]:null;
}

function textIndex(element){
  const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT,{acceptNode(node){
    // KaTeX includes a hidden MathML transcript alongside its visible HTML.
    return !node.data||node.parentElement.closest('.katex-mathml,script,style,[hidden],button,input,textarea,select')?
      NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT;
  }});
  const nodes=[];let text='',node;
  while((node=walker.nextNode())){nodes.push({node,start:text.length,end:text.length+node.length});text+=node.data;}
  return {element,text,nodes};
}

function textRange(index,start,end){
  const a=index.nodes.find(n=>n.end>start),b=index.nodes.find(n=>n.end>=end);
  if(!a||!b)return null;
  const range=document.createRange();range.setStart(a.node,start-a.start);range.setEnd(b.node,end-b.start);return range;
}

function rangeSegments(range,indexes){
  const segments=[];
  for(const [block,index] of indexes){
    let start=null,end=null;
    for(const item of index.nodes){
      if(!range.intersectsNode(item.node))continue;
      const a=range.startContainer===item.node?range.startOffset:0;
      const b=range.endContainer===item.node?range.endOffset:item.node.length;
      if(a===b)continue;
      if(start===null)start=item.start+a;end=item.start+b;
    }
    if(start!==null){const anchor=anchorFor(index.text,block,start,end);if(anchor)segments.push(anchor);}
  }
  return segments;
}

const element=(tag,className,text)=>{const node=document.createElement(tag);node.className=className;if(text!==undefined)node.textContent=text;return node;};
const sameSegments=(a,b)=>JSON.stringify(a.map(s=>[s.block,s.start,s.end,s.exact]))===JSON.stringify(b.map(s=>[s.block,s.start,s.end,s.exact]));

export function mountAnnotations(root,{annotations=[],save,onError}){
  const supported=!!globalThis.CSS?.highlights&&typeof globalThis.Highlight==='function';
  const abort=new AbortController(),listen=(target,event,fn,options={})=>target.addEventListener(event,fn,{...options,signal:abort.signal});
  const indexes=new Map([...root.querySelectorAll('[data-annotation-block]')].map(el=>[el.dataset.annotationBlock,textIndex(el)]));
  const panel=root.querySelector('[data-marks-panel]'),listRoot=root.querySelector('[data-marks-list]');
  const toggle=root.querySelector('[data-marks-toggle]'),openButton=root.querySelector('[data-mark-selection]');
  const status=root.querySelector('[data-marks-status]');
  let marks=annotations,painted=[],pending=[],editing=null,draftId=null,style='highlight',color='amber',busy=false,live=true,pointer=false,timer,statusTimer,lastRect=null;
  const toolbar=element('div','annotation-toolbar');toolbar.hidden=true;toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','Text marking tools');
  const modes=element('div','annotation-modes');
  for(const type of styles){const button=element('button','annotation-mode',type==='highlight'?'Highlight':'Underline');button.type='button';button.dataset.markStyle=type;modes.append(button);}
  const close=element('button','annotation-close','×');close.type='button';close.setAttribute('aria-label','Close text marking tools');modes.append(close);
  const palette=element('div','annotation-palette');
  for(const shade of COLORS){const button=element('button',`annotation-swatch ${shade}`);button.type='button';button.dataset.markColor=shade;button.title=names[shade];button.append(element('span',''));palette.append(button);}
  const remove=element('button','annotation-remove','Remove');remove.type='button';palette.append(remove);
  toolbar.append(modes,palette);document.body.append(toolbar);
  if(!supported){openButton.hidden=true;root.querySelector('[data-mark-help]').textContent='Saved marks are listed below. Update your browser to mark lesson text.';}

  function announce(text,error=false){if(!live)return;clearTimeout(statusTimer);status.textContent=text;status.classList.toggle('error',error);if(!error)statusTimer=setTimeout(()=>{if(live)status.textContent='';},3500);}
  function dismiss(focus=false){toolbar.hidden=true;editing=null;draftId=null;pending=[];if(focus){root.tabIndex=-1;root.focus({preventScroll:true});}}
  function position(rect=lastRect){
    if(!rect||toolbar.hidden)return;lastRect=rect;
    const width=toolbar.offsetWidth,height=toolbar.offsetHeight,viewport=window.visualViewport;
    const left=viewport?.offsetLeft||0,top=viewport?.offsetTop||0,w=viewport?.width||innerWidth,h=viewport?.height||innerHeight;
    toolbar.style.left=`${Math.max(left+8,Math.min(left+w-width-8,rect.left+rect.width/2-width/2))}px`;
    const y=rect.top-height-10>=top+8?rect.top-height-10:rect.bottom+10;
    toolbar.style.top=`${Math.max(top+8,Math.min(top+h-height-8,y))}px`;
  }
  function controls(){
    for(const button of toolbar.querySelectorAll('button'))button.disabled=busy;
    for(const button of modes.querySelectorAll('[data-mark-style]'))button.setAttribute('aria-pressed',String(button.dataset.markStyle===style));
    for(const button of palette.querySelectorAll('[data-mark-color]')){
      button.setAttribute('aria-pressed',String(button.dataset.markColor===color));
      button.setAttribute('aria-label',`${names[button.dataset.markColor]} ${style}`);
    }
    remove.hidden=!editing;
  }
  function show(segments,rect,mark=null,focus=false){
    if(!supported||busy||!segments.length)return;
    if(!sameSegments(pending,segments))draftId=null;
    pending=segments;editing=mark;if(mark)draftId=mark.id;
    if(mark){style=mark.style;color=mark.color;}
    controls();toolbar.hidden=false;position(rect);
    if(focus)modes.querySelector(`[data-mark-style="${style}"]`).focus({preventScroll:true});
  }
  function selected(focus=false){
    if(!supported||busy)return false;
    if(document.activeElement?.closest('input,textarea,[contenteditable="true"]'))return false;
    const selection=getSelection();
    if(!selection?.rangeCount||selection.isCollapsed)return false;
    const range=selection.getRangeAt(0);
    if(!root.contains(range.startContainer)||!root.contains(range.endContainer))return false;
    const segments=rangeSegments(range,indexes);
    if(!segments.length)return false;
    if(segments.length>16||segments.reduce((n,s)=>n+s.exact.length,0)>12000){announce('Select a shorter passage to mark.',true);return false;}
    const existing=[...marks].reverse().find(mark=>sameSegments(mark.segments,segments));
    const rects=[...range.getClientRects()].filter(r=>r.width&&r.height),rect=rects.find(r=>r.bottom>0&&r.top<innerHeight)||range.getBoundingClientRect();
    show(segments,rect,existing,focus);return true;
  }
  function markRanges(mark){
    const result=[];
    for(const segment of mark.segments){const index=indexes.get(segment.block),resolved=index&&resolveAnchor(index.text,segment);
      if(!resolved)return [];const range=textRange(index,...resolved);if(!range)return [];result.push({range,block:segment.block});}
    return result;
  }
  function paint(){
    painted=[];
    if(supported)for(const type of styles)for(const shade of COLORS)CSS.highlights.delete(key(type,shade));
    const groups=new Map();
    for(const mark of marks){const ranges=markRanges(mark);painted.push({mark,ranges});
      if(!supported)continue;const name=key(mark.style,mark.color);if(!groups.has(name))groups.set(name,[]);groups.get(name).push(...ranges.map(r=>r.range));}
    if(supported)for(const [name,ranges] of groups)CSS.highlights.set(name,new Highlight(...ranges));
    toggle.querySelector('span').textContent=String(marks.length);
    listRoot.replaceChildren();
    if(!marks.length){listRoot.append(element('p','muted','Your highlights and underlines will appear here.'));return;}
    for(const {mark,ranges} of painted){
      const row=element('div','annotation-list-item'),preview=element('button','annotation-preview');preview.type='button';
      preview.append(element('span',`annotation-label ${mark.color}`,`${names[mark.color]} ${mark.style}`),element('span','annotation-quote',mark.segments.map(s=>s.exact).join(' … ')));
      preview.disabled=!supported||!ranges.length;preview.setAttribute('aria-label',`Edit ${mark.color} ${mark.style}: ${mark.segments.map(s=>s.exact).join(' ').slice(0,100)}`);
      if(!ranges.length)row.append(element('p','annotation-unplaced','Original text changed. This mark is kept here for reference.'));
      const trash=element('button','text-btn annotation-list-remove','Remove');trash.type='button';trash.setAttribute('aria-label',`Remove ${mark.color} ${mark.style}`);
      preview.addEventListener('click',()=>{const index=indexes.get(mark.segments[0].block);index.element.scrollIntoView({block:'center',behavior:'instant'});show(mark.segments,ranges[0].range.getBoundingClientRect(),mark,true);},{signal:abort.signal});
      trash.addEventListener('click',()=>removeMark(mark),{signal:abort.signal});row.prepend(preview);row.append(trash);listRoot.append(row);
    }
  }
  async function persist(operation){
    if(busy)return;const listFocus=listRoot.contains(document.activeElement),toolbarFocus=toolbar.contains(document.activeElement);busy=true;controls();announce('Saving mark…');
    try{const saved=await save(operation);if(!live)return;marks=saved;paint();getSelection()?.removeAllRanges();
      if(operation.operation==='delete'){dismiss(toolbarFocus);if(listFocus)toggle.focus({preventScroll:true});}
      else{editing=marks.find(m=>m.id===operation.annotation.id);pending=editing?.segments||[];toolbar.hidden=false;const range=painted.find(p=>p.mark.id===editing?.id)?.ranges[0]?.range;position(range?.getBoundingClientRect());}
      announce(operation.operation==='delete'?'Mark removed.':'Mark saved.');}
    catch(error){announce('Your mark could not be saved. Try again.',true);onError(error);}
    finally{busy=false;if(live){controls();if(toolbarFocus&&!toolbar.hidden)modes.querySelector(`[data-mark-style="${style}"]`).focus({preventScroll:true});}}
  }
  function apply(type=style,shade=color){
    if(!pending.length||busy)return;style=type;color=shade;
    const id=editing?.id||(draftId??=crypto.randomUUID().replaceAll('-',''));
    return persist({operation:'upsert',annotation:{id,style,color,segments:pending}});
  }
  function removeMark(mark=editing){if(mark&&!busy)return persist({operation:'delete',id:mark.id});}
  listen(toolbar,'pointerdown',event=>event.preventDefault());
  listen(openButton,'pointerdown',event=>event.preventDefault());
  listen(openButton,'click',()=>{if(!selected(true))announce('Select some lesson text first, then choose Mark selection.',true);});
  listen(toolbar,'click',event=>{const button=event.target.closest('button');if(!button)return;
    if(button===close)dismiss(true);else if(button===remove)removeMark();
    else if(button.dataset.markStyle)apply(button.dataset.markStyle);else if(button.dataset.markColor)apply(style,button.dataset.markColor);
  });
  listen(toggle,'click',()=>{panel.hidden=!panel.hidden;toggle.setAttribute('aria-expanded',String(!panel.hidden));});
  listen(root,'pointerdown',()=>{pointer=true;});
  listen(document,'pointerup',event=>{const wasPointer=pointer;pointer=false;
    if(!wasPointer||busy)return;
    if(selected())return;
    const block=event.target.closest?.('[data-annotation-block]')?.dataset.annotationBlock;
    const hit=[...painted].reverse().find(item=>item.ranges.some(({range,block:id})=>id===block&&[...range.getClientRects()].some(r=>event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top&&event.clientY<=r.bottom)));
    if(hit){getSelection()?.removeAllRanges();show(hit.mark.segments,hit.ranges[0].range.getBoundingClientRect(),hit.mark);}else dismiss();
  });
  listen(document,'selectionchange',()=>{
    clearTimeout(timer);if(pointer||busy||toolbar.contains(document.activeElement)||(editing&&!toolbar.hidden&&getSelection()?.isCollapsed))return;
    timer=setTimeout(()=>{if(!selected()&&!toolbar.contains(document.activeElement))dismiss();},120);
  });
  listen(document,'pointerdown',event=>{if(!root.contains(event.target)&&!toolbar.contains(event.target))dismiss();});
  listen(document,'keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k')dismiss();
    if(event.key==='Escape'&&!toolbar.hidden){event.preventDefault();dismiss(true);}
    if(event.key==='Tab'&&!toolbar.hidden&&toolbar.contains(document.activeElement)){
      const buttons=[...toolbar.querySelectorAll('button')].filter(b=>!b.hidden&&!b.disabled),at=buttons.indexOf(document.activeElement);
      if(!event.shiftKey&&at===buttons.length-1){event.preventDefault();buttons[0].focus();}else if(event.shiftKey&&at===0){event.preventDefault();buttons.at(-1).focus();}
    }
    if(event.altKey&&event.shiftKey&&['h','u'].includes(event.key.toLowerCase())&&!event.target.closest('input,textarea,[contenteditable="true"]')){
      if(selected()){event.preventDefault();apply(event.key.toLowerCase()==='h'?'highlight':'underline');}
    }
  });
  listen(window,'resize',()=>{if(!toolbar.hidden)position();});
  listen(window,'scroll',()=>{if(!toolbar.hidden)dismiss();},{passive:true});
  paint();
  return {refresh(value){if(live){marks=value||[];paint();}},destroy(){live=false;abort.abort();clearTimeout(timer);clearTimeout(statusTimer);toolbar.remove();if(supported)for(const type of styles)for(const shade of COLORS)CSS.highlights.delete(key(type,shade));}};
}
