// Small local vector characters; no image downloads or animation libraries.
export const FOLIO_CHARACTERS=['sprout','bookling','acorn'];
export function folioIcon(character='sprout'){
  const face='<g class="folio-face"><g class="folio-eyes"><ellipse cx="25" cy="36" rx="1.6" ry="2.2"/><ellipse cx="38" cy="36" rx="1.6" ry="2.2"/></g><path class="folio-smile" d="M28 42q3.5 3 7 0"/><circle class="folio-cheek" cx="20" cy="40" r="2.3"/><circle class="folio-cheek" cx="43" cy="40" r="2.3"/></g>';
  const shapes={
    sprout:`<g class="folio-body"><path class="folio-soft" d="M13 32c0-11 9-18 20-18 13 0 20 8 20 20 0 15-10 22-22 22S13 47 13 32Z"/><path class="folio-leaf" d="M32 19C22 20 17 14 18 7c9-1 16 4 14 12Z"/><path class="folio-leaf folio-leaf-right" d="M32 19C32 8 41 4 49 7c-1 9-8 14-17 12Z"/><path class="folio-vein" d="m32 23 0-9m0 5L24 12m8 6 10-7"/>${face}</g>`,
    bookling:`<g class="folio-body"><path class="folio-paper" d="M12 12h30l10 9v32H15a5 5 0 0 1-5-5V17a5 5 0 0 1 2-5Z"/><path class="folio-soft" d="M12 12h7v41h-4a5 5 0 0 1-5-5V17a5 5 0 0 1 2-5Z"/><path class="folio-fold" d="M41 12v10h11"/><path class="folio-ribbon" d="M25 12h8v13l-4-3-4 3Z"/>${face}</g>`,
    acorn:`<g class="folio-body"><path class="folio-soft" d="M15 26h34v8c0 14-8 23-17 25-9-2-17-11-17-25Z"/><path class="folio-leaf" d="M10 26c1-12 10-18 22-18s21 6 22 18q-22 7-44 0Z"/><path class="folio-vein" d="M31 9q-2-5 3-7M18 17l3 6m8-8 1 8m10-8-1 8m8-6-3 6"/>${face}</g>`
  };
  const kind=FOLIO_CHARACTERS.includes(character)?character:'sprout';
  return `<svg class="folio-character folio-${kind}" viewBox="0 0 64 64" fill="none" aria-hidden="true">${shapes[kind]}</svg>`;
}
