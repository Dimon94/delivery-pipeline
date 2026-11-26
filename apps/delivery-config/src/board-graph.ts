import type {Mmf,Ticket} from './board';
import {copy,stageLabel,ticketStatusText} from './copy';

export type GraphGroup={id:string;label:string;url:string|null;mmfs:Mmf[]};
export type NodeRect={x:number;y:number;width:number;height:number};
export type ViewportMetrics={scrollLeft:number;scrollTop:number;clientWidth:number;clientHeight:number;scrollWidth?:number;scrollHeight?:number};
export type DependencyChain={nodes:Set<string>;edges:Set<string>};

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

// 图的几何：坐标只由层号与行号决定，栏宽变化后连线仍与卡片对齐。
export const GRAPH_GEOMETRY={root:120,card:176,h:56,gx:44,gy:14,head:40,band:20} as const;

// 同一 map 内按 deps 求拓扑层；map 外或成环的依赖不再加层。
export function ticketLayers(tickets:Ticket[]):Map<string,number> {
 const byId=new Map(tickets.map(t=>[t.id,t])),layer=new Map<string,number>();
 const visit=(t:Ticket,path:Set<string>):number=>{
  const known=layer.get(t.id);if(known!==undefined)return known;
  path.add(t.id);
  let n=0;
  for(const d of t.deps){const dep=byId.get(d);if(dep&&!path.has(d))n=Math.max(n,visit(dep,path)+1);}
  path.delete(t.id);layer.set(t.id,n);return n;
 };
 for(const t of tickets)visit(t,new Set());
 return layer;
}

// 计算某张票在同 MMF 内的全部上游与下游节点及连线（`${from}>${to}`）。
export function dependencyChain(tickets:Ticket[],targetId:string):DependencyChain {
 const byId=new Map(tickets.map(t=>[t.id,t]));
 const edges=new Set<string>();
 if(!byId.has(targetId))return {nodes:new Set(),edges};

 const dependents=new Map<string,string[]>();
 for(const t of tickets){
  for(const d of t.deps){
   if(!byId.has(d))continue;
   const list=dependents.get(d);
   if(list)list.push(t.id);else dependents.set(d,[t.id]);
  }
 }

 const upstream=new Set<string>([targetId]);
 const upQueue=[targetId];
 while(upQueue.length){
  const cur=upQueue.shift()!;
  for(const d of byId.get(cur)!.deps){
   if(!byId.has(d))continue;
   edges.add(`${d}>${cur}`);
   if(!upstream.has(d)){upstream.add(d);upQueue.push(d);}
  }
 }

 const downstream=new Set<string>([targetId]);
 const downQueue=[targetId];
 while(downQueue.length){
  const cur=downQueue.shift()!;
  for(const nxt of dependents.get(cur)??[]){
   edges.add(`${cur}>${nxt}`);
   if(!downstream.has(nxt)){downstream.add(nxt);downQueue.push(nxt);}
  }
 }

 return {nodes:new Set([...upstream,...downstream]),edges};
}

// 计算将目标节点滚入视口所需的 scrollLeft/scrollTop（R12）。
export function scrollTargetForNode(viewport:ViewportMetrics,node:NodeRect,padding=24):{scrollLeft:number;scrollTop:number} {
 let {scrollLeft,scrollTop}=viewport;
 if(viewport.clientWidth>0){
  if(node.x+node.width+padding>scrollLeft+viewport.clientWidth){
   scrollLeft=node.x+node.width+padding-viewport.clientWidth;
  }else if(node.x-padding<scrollLeft){
   scrollLeft=Math.max(0,node.x-padding);
  }
  if(viewport.scrollWidth!==undefined&&viewport.scrollWidth>viewport.clientWidth){
   scrollLeft=Math.min(scrollLeft,viewport.scrollWidth-viewport.clientWidth);
  }
  scrollLeft=Math.max(0,scrollLeft);
 }
 if(viewport.clientHeight>0){
  if(node.y+node.height+padding>scrollTop+viewport.clientHeight){
   scrollTop=node.y+node.height+padding-viewport.clientHeight;
  }else if(node.y-padding<scrollTop){
   scrollTop=Math.max(0,node.y-padding);
  }
  if(viewport.scrollHeight!==undefined&&viewport.scrollHeight>viewport.clientHeight){
   scrollTop=Math.min(scrollTop,viewport.scrollHeight-viewport.clientHeight);
  }
  scrollTop=Math.max(0,scrollTop);
 }
 return {scrollLeft,scrollTop};
}

// 只有 executing 为真的节点才渲染动态虚线环（R11）。
function execRing(width:number,height:number):string {
 const rw=Math.max(2,width-2),rh=Math.max(2,height-2);
 return `<svg class="exec-ring" viewBox="0 0 ${width} ${height}" aria-hidden="true"><rect class="exec-ring-path" x="1" y="1" width="${rw}" height="${rh}" rx="9" ry="9"/></svg>`;
}

export function renderGraph(group:GraphGroup,mmf:Mmf|undefined,ticket:Ticket|undefined):string {
 const G=GRAPH_GEOMETRY;
 const nodes:string[]=[],links:string[]=[];
 const x0=G.root+G.gx;let y=0,width=x0+G.card;
 for(const m of group.mmfs){
  const layer=ticketLayers(m.tickets),rows=new Map<number,number>();
  const pos=new Map<string,{x:number;y:number}>();
  for(const t of m.tickets){
   const l=layer.get(t.id)!,r=rows.get(l)??0;
   rows.set(l,r+1);
   pos.set(t.id,{x:x0+l*(G.card+G.gx),y:y+G.head+r*(G.h+G.gy)});
  }
  const height=G.head+Math.max(1,...rows.values())*(G.h+G.gy);
  links.push(`<path data-link="${esc(group.id)}>${esc(m.map)}" d="M${G.root} ${G.h/2} C${G.root+G.gx/2} ${G.h/2},${x0-G.gx/2} ${y+G.head/2-4},${x0} ${y+G.head/2-4}"/>`);
  const mmfSelected=m===mmf&&!ticket;
  const mmfExec=Boolean(m.executing);
  nodes.push(`<button class="graph-mmf${mmfExec?' is-executing':''}${mmfSelected?' selected':''}" data-board="mmf" data-map="${esc(m.map)}" data-x="${x0}" data-y="${y}" aria-pressed="${mmfSelected}" style="left:${x0}px;top:${y}px">${mmfExec?execRing(G.card,30):''}${esc(m.title)}<small>${esc(stageLabel(m.stage))}${mmfExec?` · <span class="exec-label">${esc(copy.执行中)}</span>`:''}</small></button>`);
  for(const t of m.tickets){
   const p=pos.get(t.id)!;width=Math.max(width,p.x+G.card);
   for(const d of t.deps){
    const q=pos.get(d);
    if(q)links.push(`<path data-map="${esc(m.map)}" data-dep="${esc(d)}>${esc(t.id)}" d="M${q.x+G.card} ${q.y+G.h/2} C${q.x+G.card+G.gx/2} ${q.y+G.h/2},${p.x-G.gx/2} ${p.y+G.h/2},${p.x} ${p.y+G.h/2}"/>`);
   }
   const selected=m===mmf&&t===ticket;
   const executing=Boolean(t.executing);
   const status=ticketStatusText(t);
   nodes.push(`<button class="graph-ticket g-${t.lane?esc(t.lane.group):'none'}${executing?' is-executing':''}${selected?' selected':''}" data-board="ticket" data-map="${esc(m.map)}" data-ticket="${esc(t.id)}" data-x="${p.x}" data-y="${p.y}" aria-pressed="${selected}" style="left:${p.x}px;top:${p.y}px">${executing?execRing(G.card,G.h):''}<span><b>${esc(t.id)}</b> ${esc(t.title)}</span><small class="${executing?'exec-label':''}">${esc(status)}</small></button>`);
  }
  y+=height+G.band;
 }
 const h=Math.max(y,G.h);
 return `<div class="graph" style="width:${width}px;height:${h}px"><svg class="graph-links" width="${width}" height="${h}" viewBox="0 0 ${width} ${h}" aria-hidden="true">${links.join('')}</svg><div class="graph-root" data-x="0" data-y="0" style="left:0;top:0">${esc(group.label)}</div>${nodes.join('')}</div>`;
}

// 悬停某张票时只保留其上下游链高亮，其余淡出；离开时恢复。
export function applyHoverChain(container:Element,group:GraphGroup|undefined,hovered?:{map:string;ticket:string}):void {
 const graphEl=container.querySelector('.graph');
 if(!graphEl)return;
 const tickets=[...graphEl.querySelectorAll<HTMLElement>('.graph-ticket')];
 const mmfs=[...graphEl.querySelectorAll<HTMLElement>('.graph-mmf')];
 const paths=[...graphEl.querySelectorAll<SVGPathElement>('.graph-links path')];
 if(!hovered||!group){
  graphEl.classList.remove('has-hover');
  for(const el of [...tickets,...mmfs,...paths]){el.classList.remove('chain','dimmed');}
  return;
 }
 const mmf=group.mmfs.find(m=>m.map===hovered.map);
 if(!mmf){
  graphEl.classList.remove('has-hover');
  for(const el of [...tickets,...mmfs,...paths]){el.classList.remove('chain','dimmed');}
  return;
 }
 const chain=dependencyChain(mmf.tickets,hovered.ticket);
 graphEl.classList.add('has-hover');
 for(const el of tickets){
  const active=el.dataset.map===hovered.map&&chain.nodes.has(el.dataset.ticket??'');
  el.classList.toggle('chain',active);
  el.classList.toggle('dimmed',!active);
 }
 for(const el of mmfs){
  const active=el.dataset.map===hovered.map;
  el.classList.toggle('chain',active);
  el.classList.toggle('dimmed',!active);
 }
 for(const p of paths){
  const dep=p.getAttribute('data-dep');
  let active=false;
  if(dep!==null){
   active=p.getAttribute('data-map')===hovered.map&&chain.edges.has(dep);
  }else{
   const link=p.getAttribute('data-link')??'';
   active=link.endsWith(`>${hovered.map}`);
  }
  p.classList.toggle('chain',active);
  p.classList.toggle('dimmed',!active);
 }
}
