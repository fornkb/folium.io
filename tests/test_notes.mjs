import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Run the real save function with controlled network completion order.
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const start=source.indexOf('async function flushNotes()');
const end=source.indexOf("document.addEventListener('click'",start);
const state={notesPending:{cid:'course',mid:'module',text:'Earlier note'}};
const requests=[],saved=[];
const api=(path,body)=>new Promise(resolve=>requests.push({body,resolve}));
const updateCourse=course=>saved.push(course.notes);
const flush=new Function('state','api','updateCourse','$','clearTimeout','enc',`let notesFlight=null,notesTimer;${source.slice(start,end)};return flushNotes;`)(state,api,updateCourse,()=>null,()=>{},encodeURIComponent);
const earlier=flush();
state.notesPending={cid:'course',mid:'module',text:'Latest note'};
const latest=flush();
if(requests.length===2){
  requests[1].resolve({course:{notes:requests[1].body.notes}});
  await latest;
  requests[0].resolve({course:{notes:requests[0].body.notes}});
}else{
  requests[0].resolve({course:{notes:requests[0].body.notes}});
  for(let i=0;i<20&&requests.length<2;i++)await Promise.resolve();
  assert.equal(requests.length,2,'The latest pending edit must also be saved.');
  let completed=false;latest.then(()=>completed=true);
  for(let i=0;i<5;i++)await Promise.resolve();
  assert.equal(completed,false,'Leaving the editor must wait for its latest edit.');
  requests[1].resolve({course:{notes:requests[1].body.notes}});
}
await Promise.all([earlier,latest]);
assert.equal(saved.at(-1),'Latest note','An earlier response must not overwrite newer notes.');
assert.equal(state.notesPending,null);
console.log('Concurrent note saves preserve the latest edit.');
