// Small local vector characters; no image downloads or animation libraries.
export const FOLIO_CHARACTERS=['sprout','bookling','acorn'];
export const FOLIO_SPROUT_MOTIONS=['hop','curious','leafcopter'];
export function folioIcon(character='sprout',motion='curious'){
  const face='<g class="folio-face"><g class="folio-eyes"><ellipse cx="25" cy="36" rx="1.6" ry="2.2"/><ellipse cx="38" cy="36" rx="1.6" ry="2.2"/></g><path class="folio-smile" d="M28 42q3.5 3 7 0"/><circle class="folio-cheek" cx="20" cy="40" r="2.3"/><circle class="folio-cheek" cx="43" cy="40" r="2.3"/></g>';
  const shapes={
    bookling:`<g class="folio-body"><path class="folio-paper" d="M12 12h30l10 9v32H15a5 5 0 0 1-5-5V17a5 5 0 0 1 2-5Z"/><path class="folio-soft" d="M12 12h7v41h-4a5 5 0 0 1-5-5V17a5 5 0 0 1 2-5Z"/><path class="folio-fold" d="M41 12v10h11"/><path class="folio-ribbon" d="M25 12h8v13l-4-3-4 3Z"/>${face}</g>`,
    acorn:`<g class="folio-body"><path class="folio-soft" d="M15 26h34v8c0 14-8 23-17 25-9-2-17-11-17-25Z"/><path class="folio-leaf" d="M10 26c1-12 10-18 22-18s21 6 22 18q-22 7-44 0Z"/><path class="folio-vein" d="M31 9q-2-5 3-7M18 17l3 6m8-8 1 8m10-8-1 8m8-6-3 6"/>${face}</g>`
  };
  const kind=FOLIO_CHARACTERS.includes(character)?character:'sprout';
  if(kind==='sprout'){
    const mood=FOLIO_SPROUT_MOTIONS.includes(motion)?motion:'curious';
    return `<svg class="folio-character folio-sprout folio-sprout-${mood}" viewBox="0 0 80 80" fill="none" aria-hidden="true">
      <ellipse class="folio-ground" cx="40" cy="73" rx="18" ry="3"/>
      <g class="folio-lift"><g class="folio-sprout-body">
        <g class="folio-foot folio-foot-left"><path class="folio-soft" d="M28 61q-7 6-3 8t11-5Z"/></g>
        <g class="folio-foot folio-foot-right"><path class="folio-soft" d="M47 61q8 4 7 7t-12-3Z"/></g>
        <g class="folio-arm folio-arm-left"><path class="folio-soft" d="M25 44q-10-8-12-3t11 13"/></g>
        <g class="folio-arm folio-arm-right"><path class="folio-soft" d="M55 44q9-12 12-8t-10 19"/></g>
        <path class="folio-soft" d="M20 47c0-13 7-23 20-23s21 10 21 23c0 14-9 20-21 20S20 60 20 47Z"/>
        <path class="folio-belly" d="M26 54q3 9 14 9t15-9q-15 5-29 0Z"/>
        <g class="folio-crown"><path class="folio-vein" d="M40 30V20"/>
          <g class="folio-sprout-leaf folio-sprout-leaf-left"><path class="folio-leaf" d="M40 25C26 27 19 18 21 9c11-1 20 5 19 16Z"/><path class="folio-leaf-detail" d="M39 24 27 15"/></g>
          <g class="folio-sprout-leaf folio-sprout-leaf-right"><path class="folio-leaf" d="M40 25C39 13 49 6 61 10c-1 12-10 18-21 15Z"/><path class="folio-leaf-detail" d="m41 24 13-9"/></g>
        </g>
        <g class="folio-sprout-face"><g class="folio-face">
          <g class="folio-eyes"><g class="folio-eye-left"><ellipse cx="32" cy="44" rx="2.6" ry="3.6"/><circle class="folio-eye-glint" cx="32.8" cy="42.8" r=".8"/></g><g class="folio-eye-right"><ellipse cx="48" cy="44" rx="2.6" ry="3.6"/><circle class="folio-eye-glint" cx="48.8" cy="42.8" r=".8"/></g></g>
          <path class="folio-smile folio-happy-mouth" d="M36 52q4 5 8 0"/><ellipse class="folio-surprised-mouth" cx="40" cy="53" rx="2" ry="2.8"/>
          <ellipse class="folio-cheek" cx="26.5" cy="50" rx="3.6" ry="2.2"/><ellipse class="folio-cheek" cx="53.5" cy="50" rx="3.6" ry="2.2"/>
        </g></g>
      </g></g>
      <g class="folio-curiosity"><path class="folio-smile" d="M65 15c0-5 8-5 8 0 0 3-4 3-4 6"/><circle class="folio-face" cx="69" cy="25" r="1"/></g>
      <g class="folio-sparkles"><path d="m11 22 1-4 1 4 4 1-4 1-1 4-1-4-4-1Zm55 37 1-3 1 3 3 1-3 1-1 3-1-3-3-1Z"/></g>
      <g class="folio-breeze"><path d="M11 56h8m-4 5h6m40-5h8m-10 5h6"/></g>
    </svg>`;
  }
  return `<svg class="folio-character folio-${kind}" viewBox="0 0 64 64" fill="none" aria-hidden="true">${shapes[kind]}</svg>`;
}
