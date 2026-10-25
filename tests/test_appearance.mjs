import assert from 'node:assert/strict';
import {highlightOpacity,applyHighlightOpacity,highlightSettings} from '../web/appearance.js';
import {folioIcon,FOLIO_CHARACTERS,FOLIO_SPROUT_MOTIONS} from '../web/folio-icons.js';

for(const value of [null,undefined,'',NaN,'invalid','<script>'])assert.equal(highlightOpacity(value),24);
assert.equal(highlightOpacity(-10),5);assert.equal(highlightOpacity(99),70);assert.equal(highlightOpacity('37.2'),37);
const properties=[];globalThis.document={documentElement:{style:{setProperty:(...args)=>properties.push(args)}}};
assert.equal(applyHighlightOpacity('38'),38);
assert.deepEqual(properties,[['--mark-opacity','0.38']]);
assert.match(highlightSettings(38),/value="38"/);
assert.doesNotMatch(highlightSettings('<img onerror=evil()>'),/<img/);
for(const kind of FOLIO_CHARACTERS){assert.match(folioIcon(kind),/aria-hidden="true"/);assert.match(folioIcon(kind),new RegExp('folio-'+kind));}
assert.equal(folioIcon('<script>'),folioIcon('sprout'));
for(const motion of FOLIO_SPROUT_MOTIONS)assert.match(folioIcon('sprout',motion),new RegExp('folio-sprout-'+motion));
assert.equal(folioIcon('sprout','"><script>'),folioIcon('sprout','curious'));
console.log('Highlight opacity stays bounded, changes only paint alpha, and Folio character selection is safe.');
