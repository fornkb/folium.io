export function highlightOpacity(value){
  const number=value===null||value===''?NaN:Number(value);
  return Number.isFinite(number)?Math.max(5,Math.min(70,Math.round(number))):24;
}
export function applyHighlightOpacity(value){
  const opacity=highlightOpacity(value);
  document.documentElement.style.setProperty('--mark-opacity',String(opacity/100));
  return opacity;
}
export function highlightSettings(value){
  const opacity=highlightOpacity(value);
  return `<div class="settings-divider"></div><div class="highlight-setting"><div class="row between"><label for="highlight-opacity">Highlight opacity</label><output for="highlight-opacity" id="highlight-opacity-value">${opacity}%</output></div><input id="highlight-opacity" type="range" min="5" max="70" step="1" value="${opacity}" aria-describedby="highlight-opacity-hint"><p id="highlight-opacity-hint">Adjust the color behind your text. Underlines stay crisp.</p><div class="highlight-preview" aria-label="Highlight preview">A little <span>clarity</span> goes a long way.</div></div>`;
}
