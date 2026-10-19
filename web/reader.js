// Only our Markdown vocabulary and KaTeX's untrusted-input renderer produce HTML.
export const escapeText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function math(text, display=false){
  if(!globalThis.katex || text.length>20000)return `<code class="math-fallback">${escapeText(text)}</code>`;
  try{return globalThis.katex.renderToString(text,{displayMode:display,throwOnError:true,trust:false,strict:'ignore',maxExpand:500,maxSize:10,output:'htmlAndMathml'});}
  catch{return `<code class="math-fallback" title="View the original source for exact notation">${escapeText(text)}</code>`;}
}

export function inlineText(text){
  // Scan formatting tokens BEFORE escaping, and escape every ordinary text fragment.
  const tokens=/\\\(([\s\S]*?)\\\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*/g;
  let out='',pos=0;
  for(const match of String(text??'').matchAll(tokens)){
    out+=escapeText(String(text).slice(pos,match.index));
    if(match[1]!==undefined)out+=math(match[1]);
    else if(match[2]!==undefined)out+=`<code>${escapeText(match[2])}</code>`;
    else if(match[3]!==undefined)out+=`<strong>${escapeText(match[3])}</strong>`;
    else out+=`<em>${escapeText(match[4])}</em>`;
    pos=match.index+match[0].length;
  }
  return out+escapeText(String(text??'').slice(pos));
}

export function renderText(text){
  // Older saved lessons sometimes place an entire numbered derivation on one line.
  text=String(text||'').replace(/\r\n?/g,'\n').replace(/([^\n])\s+(Step \d+[:.])/g,'$1\n\n**$2**');
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
      while(i<lines.length&&bullet(lines[i])&&/^\s*\d/.test(lines[i])===ordered){
        items.push(lines[i++].replace(/^\s*(?:[-*•]|\d+[.)])\s+/,''));
        while(i<lines.length&&/^\s{2,}\S/.test(lines[i])&&!bullet(lines[i]))items[items.length-1]+=' '+lines[i++].trim();
      }
      out+=`<${tag}${ordered?` start="${start}"`:''}>${items.map(s=>`<li>${inlineText(s)}</li>`).join('')}</${tag}>`;continue;
    }
    if(line.startsWith('>')){out+=`<blockquote>${inlineText(line.replace(/^>\s?/,''))}</blockquote>`;i++;continue;}
    const paragraph=[line];i++;
    while(i<lines.length&&lines[i].trim()&&!special(lines[i])&&!(lines[i].includes('|')&&i+1<lines.length&&/---/.test(lines[i+1])))paragraph.push(lines[i++].trim());
    out+=`<p>${paragraph.map(inlineText).join(' ')}</p>`;
  }
  return out;
}
