import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as UI from '../web/ui.js';

const module=(id,ready)=>({id,title:id,description:'A topic',topics:['A'],prerequisites:[],state:'unseen',...(ready?{package:{sections:[],flashcards:[],assessment_status:'missing'}}:{})});
const course=()=>({id:'course',title:'Course',description:'Topics',status:'outline',warnings:[],documents:[],pyqs:[],modules:[module('m1',true),module('m2',false),module('m3',false)],job:{state:'running',action:'generate',message:'Writing m2',done:1,total:3}});
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8').replace(/\r\n/g,'\n');
const updateStart=source.indexOf('function updateCourse(');
const updateSource=source.slice(updateStart,source.indexOf('\n}\n',updateStart)+3);
const pollStart=source.indexOf('let polling=false;');
const pollSource=source.slice(pollStart,source.indexOf('setInterval(pollCourses',pollStart));

function harness(old, responses, routeModule='m1',tab='notes'){
  const state={courses:[old],current:{c:old,m:old.modules.find(m=>m.id===routeModule)},notesPending:{cid:'course',mid:'m1',text:'Latest unsaved note'}};
  const calls=[],renders=[],navigations=[],errors=[],banner={innerHTML:''};
  const api=async path=>{calls.push(path);const response=responses.shift();return typeof response==='function'?response():structuredClone(response);};
  const updateCourse=new Function('state',updateSource+'return updateCourse;')(state);
  const poll=new Function('state','api','updateCourse','route','render','goto','UI','$','toast','link',pollSource+'return pollCourses;')(
    state,api,updateCourse,()=>['course','course','module',routeModule,tab],()=>renders.push(true),p=>navigations.push(p),UI,()=>banner,e=>errors.push(e),UI.link);
  return {state,calls,renders,navigations,errors,banner,poll};
}

// A second module arriving updates status and current references, preserving the
// mounted reader/notes DOM, its selection and scroll position.
const old=course(),next=course();next.modules[1]=module('m2',true);
const h=harness(old,[{...next,summary:true},next]);
await h.poll();
assert.deepEqual(h.calls,['/courses/course/status','/courses/course']);
assert.equal(h.renders.length,0);
assert.equal(h.navigations.length,0);
assert.equal(h.state.current.m.notes,'Latest unsaved note');
assert.match(h.banner.innerHTML,/2 of 3 modules ready/);

const complete=course();complete.modules=complete.modules.map(m=>module(m.id,true));complete.status='ready';complete.job={state:'complete',action:'generate'};
const finished=harness(course(),[{...complete,summary:true},complete],'m1','study');
await finished.poll();
assert.equal(finished.renders.length,0);
assert.equal(finished.navigations.length,0);
assert.equal(finished.banner.innerHTML,'');

const placeholder=harness(course(),[{...next,summary:true},next],'m2','study');
await placeholder.poll();
assert.equal(placeholder.renders.length,1,'A waiting module opens when its package arrives.');

let resolveStatus;
const deleted=harness(course(),[()=>new Promise(resolve=>resolveStatus=resolve)]);
const pending=deleted.poll();deleted.state.courses=[];resolveStatus({...next,summary:true});await pending;
assert.equal(deleted.state.courses.length,0,'An in-flight poll must not resurrect a deleted course.');
assert.equal(deleted.errors.length,0);

const c=course(),setup=UI.setupView(c,c.modules,{has_key:true});
assert.match(setup,/data-action="open-prepared"/);
assert.doesNotMatch(setup,/data-action="resume"/);
assert.match(setup,/Preparation continues while you read/);
assert.equal(UI.courseLink(c),'#/course/course/explore');
assert.match(UI.studyHeader(c,c.modules[0],'study'),/href="#\/course\/course\/explore"/);
const map=UI.courseView(c,'outline');
assert.match(map,/href="#\/course\/course\/module\/m1\/study"/);
assert.match(map,/href="#\/course\/course\/setup" aria-label="Preparing m2"/);
const unsafe={...c,title:'<img src=x onerror=evil()>',job:{state:'paused',message:'<script>evil()</script>'}};
assert.doesNotMatch(UI.deleteCourseDialog(unsafe),/<img/);
assert.doesNotMatch(UI.preparationNotice(unsafe),/<script>/);
assert.match(UI.deleteCourseDialog(c),/data-action="confirm-delete-course"[^>]*disabled/);
assert.match(UI.library([c]),/Explore ready modules/);
assert.match(UI.library([c]),/data-action="delete-course"/);
console.log('Background generation preserves readers and notes; ready-module navigation and deletion controls passed.');
