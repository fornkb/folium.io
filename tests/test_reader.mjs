import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {renderText,inlineText} from '../web/reader.js';
import {practice} from '../web/ui.js';
const require=createRequire(import.meta.url);
globalThis.katex=require('../web/vendor/katex/katex.min.js');

const rendered=renderText('### A heading\nA paragraph\n* First\n* Second\n\n1. One\n2. Two');
assert.match(rendered,/<h3>A heading<\/h3>/);
assert.match(rendered,/<ul><li>First<\/li><li>Second<\/li><\/ul>/);
assert.match(rendered,/<ol start="1">/);
assert.match(renderText('| Term | Meaning |\n| --- | --- |\n| X | Flip |'),/<table>/);
assert.match(renderText('Step 1: Initial state. Step 2: Apply X.'),/<strong>Step 2:<\/strong>/);
assert.match(renderText('\\[\\frac{1}{\\sqrt{2}}\\begin{pmatrix}1\\\\1\\end{pmatrix}\\]'),/katex-display/);
assert.match(inlineText('State \\( |\\psi\\rangle \\)'),/katex/);
for(const text of ['<img src=x onerror=alert(1)>','**<script>evil()</script>**','`<iframe>`']){
  assert.doesNotMatch(renderText(text),/<(?:img|script|iframe)/);
}
assert.doesNotMatch(inlineText('\\(\\href{javascript:alert(1)}{click}\\)'),/href="javascript:/);

const questions=[{id:'q1',type:'objective',question:'Pick',options:['Zero','One'],correct_index:0,solution:'Zero',topic:'A'}];
const module={topics:['A'],package:{questions},evidence:{}};
const quiz={answers:{q1:0},order:['q1'],options:{q1:[1,0]}};
const view=practice({demo:false},module,quiz);
assert.match(view,/value="1"[^>]*>.*?option-letter">A<\/span><span>One/s);
assert.match(view,/value="0"[^>]*checked[^>]*>.*?option-letter">B<\/span><span>Zero/s);
console.log('Reader safety, Markdown, offline math, and shuffled canonical options passed.');
