// Only our Markdown vocabulary and KaTeX's untrusted-input renderer produce HTML.
export const escapeText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Legacy Symbol/Wingdings glyphs in native PDF text. Keep this a display-only,
// explicit map: unknown private-use characters and saved quotations stay intact.
const sourceGlyphs={'\uf06e':'•','\uf0d8':'¬','\uf0de':'⇒','\uf0d9':'∧','\uf0da':'∨','\uf0db':'⇔','\uf022':'∀','\uf024':'∃'};
export function sourceText(text){
  return String(text??'').replace(/[\uf06e\uf0d8-\uf0db\uf0de\uf022\uf024]/g,char=>sourceGlyphs[char]);
}
export function renderSourceText(text){
  // Native PDF lines can wrap midway through a bullet, or flatten several
  // bullets together. Group by the actual slide marker, keeping wrapped words.
  const parts=String(text??'').split('\uf06e'),intro=renderText(sourceText(parts.shift()));
  if(!parts.length)return intro;
  return intro+`<ul>${parts.filter(part=>part.trim()).map(part=>{
    let content=renderText(sourceText(part.trim()));
    if(/^<p>(?:(?!<p>|<\/p>)[\s\S])*<\/p>$/.test(content))content=content.slice(3,-4);
    return `<li>${content}</li>`;
  }).join('')}</ul>`;
}

function legacySteps(text){
  const steps=[...text.matchAll(/(?:^|\s+)Step ([1-9]\d*):(?=\s)/g)];
  if(steps.length<2||steps[0].index!==0||text.includes('`')||text.includes('\\(')||
      !steps.every((step,i)=>Number(step[1])===i+1))return null;
  return steps.map((step,i)=>`<p><strong>Step ${step[1]}:</strong> ${inlineText(text.slice(step.index+step[0].length,steps[i+1]?.index).trim())}</p>`).join('');
}

export function math(text, display=false){
  if(!globalThis.katex || text.length>20000)return `<code class="math-fallback">${escapeText(text)}</code>`;
  try{return globalThis.katex.renderToString(text,{displayMode:display,throwOnError:true,trust:false,strict:'ignore',maxExpand:500,maxSize:10,output:'htmlAndMathml'});}
  catch{return `<code class="math-fallback" title="View the original source for exact notation">${escapeText(text)}</code>`;}
}

export function inlineText(text,depth=0){
  if(depth>12)return escapeText(text);
  // Scan formatting tokens BEFORE escaping, and escape every ordinary text fragment.
  const tokens=/\\\(([\s\S]*?)\\\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
  let out='',pos=0;
  for(const match of String(text??'').matchAll(tokens)){
    out+=escapeText(String(text).slice(pos,match.index));
    if(match[1]!==undefined)out+=math(match[1]);
    else if(match[2]!==undefined)out+=`<code>${escapeText(match[2])}</code>`;
    else if(match[3]!==undefined)out+=`<strong>${inlineText(match[3],depth+1)}</strong>`;
    else out+=`<em>${inlineText(match[4],depth+1)}</em>`;
    pos=match.index+match[0].length;
  }
  return out+escapeText(String(text??'').slice(pos));
}

export function renderText(text,depth=0){
  if(depth>12)return `<p>${escapeText(text)}</p>`;
  text=String(text||'').replace(/\r\n?/g,'\n');
  const lines=text.split('\n');let out='',i=0;
  const bullet=line=>/^\s*(?:[-*•]|\d+[.)])\s+/.test(line);
  const special=line=>/^\s*(?:#{1,6}\s|```|>|\\\[|\$\$)/.test(line)||bullet(line);
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(s=>s.trim().replace(/\\\|/g,'|'));
  while(i<lines.length){
    const line=lines[i].trim();
    if(!line){i++;continue;}
    if(line.startsWith('```')){
      const lang=line.slice(3).trim();const body=[];i++;
      while(i<lines.length&&!lines[i].trim().startsWith('```'))body.push(lines[i++]);
      i++;
      out+=/^(math|latex|tex)$/.test(lang)?math(body.join('\n'),true):`<pre><code>${escapeText(body.join('\n'))}</code></pre>`;continue;
    }
    if(line.startsWith('\\[')||line.startsWith('$$')){
      const open=line.startsWith('\\[')?'\\[':'$$',end=open==='\\['?'\\]':'$$';let body=line.slice(open.length);i++;
      while(!body.includes(end)&&i<lines.length)body+='\n'+lines[i++];
      if(body.includes(end)){
        const at=body.indexOf(end),rest=body.slice(at+end.length).trim();out+=math(body.slice(0,at),true);
        if(rest)out+=`<p>${inlineText(rest)}</p>`;
      }else out+=`<p>${escapeText(open+body)}</p>`;
      continue;
    }
    if(/^#{1,6}\s/.test(line)){
      const level=Math.min(5,Math.max(3,line.match(/^#+/)[0].length));
      out+=`<h${level}>${inlineText(line.replace(/^#+\s/,''))}</h${level}>`;i++;continue;
    }
    if(i+1<lines.length&&line.includes('|')&&/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i+1])){
      const headings=cells(line);i+=2;const rows=[];
      while(i<lines.length&&lines[i].includes('|')&&lines[i].trim())rows.push(cells(lines[i++]));
      out+=`<div class="table-scroll"><table><thead><tr>${headings.map(s=>`<th>${inlineText(s)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${headings.map((_,j)=>`<td>${inlineText(row[j]||'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;continue;
    }
    if(bullet(line)){
      const ordered=/^\d/.test(line),tag=ordered?'ol':'ul',items=[];
      const start=ordered?Number(line.match(/^\d+/)[0]):1;
      const indent=lines[i].match(/^\s*/)[0].length;
      while(i<lines.length&&bullet(lines[i])&&lines[i].match(/^\s*/)[0].length===indent&&/^\s*\d/.test(lines[i])===ordered){
        const marker=lines[i].match(/^\s*(?:[-*•]|\d+[.)])\s+/)[0].length;
        const body=[lines[i++].slice(marker)];
        while(i<lines.length){
          if(!lines[i].trim()){
            let next=i+1;while(next<lines.length&&!lines[next].trim())next++;
            if(next<lines.length&&lines[next].match(/^\s*/)[0].length>indent){body.push('');i++;continue;}
            break;
          }
          const spaces=lines[i].match(/^\s*/)[0].length;
          if(spaces<=indent)break;
          body.push(lines[i++].slice(Math.min(marker,spaces)));
        }
        let content=renderText(body.join('\n'),depth+1);
        if(/^<p>(?:(?!<p>|<\/p>)[\s\S])*<\/p>$/.test(content))content=content.slice(3,-4);
        items.push(content);
      }
      out+=`<${tag}${ordered?` start="${start}"`:''}>${items.map(s=>`<li>${s}</li>`).join('')}</${tag}>`;continue;
    }
    if(line.startsWith('>')){out+=`<blockquote>${inlineText(line.replace(/^>\s?/,''))}</blockquote>`;i++;continue;}
    const paragraph=[line];i++;
    while(i<lines.length&&lines[i].trim()&&!special(lines[i])&&!(lines[i].includes('|')&&i+1<lines.length&&/---/.test(lines[i+1])))paragraph.push(lines[i++].trim());
    // Recover only plain, sequential step lists; headings, code, mathematics and
    // references such as "the result of Step 3." keep their original structure.
    out+=legacySteps(paragraph.join(' '))??`<p>${paragraph.map(s=>inlineText(s)).join(' ')}</p>`;
  }
  return out;
}
