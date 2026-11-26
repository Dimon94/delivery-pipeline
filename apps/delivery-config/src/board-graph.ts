import type {Mmf,Ticket} from './board';
import {copy,stageLabel,ticketStatusText} from './copy';

export type GraphGroup={id:string;label:string;url:string|null;mmfs:Mmf[]};
export type NodeRect={x:number;y:number;width:number;height:number};
export type ViewportMetrics={scrollLeft:number;scrollTop:number;clientWidth:number;clientHeight:number;scrollWidth?:number;scrollHeight?:number};
export type DependencyChain={nodes:Set<string>;edges:Set<string>};

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

// 图的几何：坐标只由层号与行号决定，栏宽变化后连线仍与卡片对齐。
export const GRAPH_GEOMETRY={root:136,card:176,h:56,gx:32,gy:10,head:92,band:14,pad:10,rootGap:36,mmfGap:32} as const;

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
 const rw=width+8,rh=height+8;
 return `<svg class="exec-ring" viewBox="0 0 ${rw} ${rh}" aria-hidden="true"><rect class="exec-ring-path" x="1.5" y="1.5" width="${rw-3}" height="${rh-3}" rx="11" ry="11" pathLength="100"/></svg>`;
}

function ticketStateClass(ticket:Ticket):string {
 if(ticket.executing)return 'st-running';
 if(!ticket.lane)return 'st-pending';
 if(ticket.lane.state==='running'&&ticket.lane.live!=='working')return 'st-unconfirmed';
 return `st-${esc(ticket.lane.state)}`;
}

export function renderGraph(group:GraphGroup,mmf:Mmf|undefined,ticket:Ticket|undefined):string {
 const G=GRAPH_GEOMETRY;
 const bands:string[]=[],nodes:string[]=[],links:string[]=[];
 const mmfX=G.root+G.rootGap;
 const ticketX0=mmfX+G.card+G.mmfGap;
 let y=G.pad,width=mmfX+G.card+G.pad;

 const totalTickets=group.mmfs.reduce((sum,m)=>sum+m.tickets.length,0);
 const doneTickets=group.mmfs.reduce((sum,m)=>sum+m.tickets.filter(t=>t.lane?.group==='done').length,0);

 // 预计算每个 MMF 横带的高度与垂直中心，使 EP 根节点可垂直居中对齐。
 type BandLayout={mmf:Mmf;bandY:number;bandH:number;mmfY:number;pos:Map<string,{x:number;y:number}>;bandW:number};
 const layouts:BandLayout[]=[];
 for(const m of group.mmfs){
  const layer=ticketLayers(m.tickets),rows=new Map<number,number>();
  for(const t of m.tickets){
   const l=layer.get(t.id)!;
   rows.set(l,(rows.get(l)??0)+1);
  }
  const maxRows=Math.max(1,...rows.values());
  const ticketsH=m.tickets.length?maxRows*G.h+(maxRows-1)*G.gy:G.head;
  const contentH=Math.max(G.head,ticketsH);
  const bandH=contentH+G.pad*2;
  const mmfY=Math.round(y+(bandH-G.head)/2);

  // 每列在横带内垂直居中，同原型 .layers align-items:center
  const colCursor=new Map<number,number>();
  const pos=new Map<string,{x:number;y:number}>();
  let bandRight=mmfX+G.card+G.pad;
  for(const t of m.tickets){
   const l=layer.get(t.id)!,r=colCursor.get(l)??0;
   colCursor.set(l,r+1);
   const colCount=rows.get(l)??1;
   const colH=colCount*G.h+(colCount-1)*G.gy;
   const colTop=Math.round(y+(bandH-colH)/2);
   const tx=ticketX0+l*(G.card+G.gx);
   const ty=colTop+r*(G.h+G.gy);
   pos.set(t.id,{x:tx,y:ty});
   bandRight=Math.max(bandRight,tx+G.card+G.pad);
  }
  if(!m.tickets.length)bandRight=Math.max(bandRight,ticketX0+160+G.pad);
  const bandW=bandRight-(mmfX-G.pad);
  width=Math.max(width,bandRight+G.pad);
  layouts.push({mmf:m,bandY:y,bandH,mmfY,pos,bandW});
  y+=bandH+G.band;
 }

 const h=Math.max(y,G.head+G.pad*2);
 const rootH=74;
 const rootY=Math.max(G.pad,Math.round((h-rootH)/2));
 const rootMidY=rootY+rootH/2;

 for(const item of layouts){
  const {mmf:m,bandY,bandH,mmfY,pos,bandW}=item;
  const mmfMidY=mmfY+G.head/2;
  bands.push(`<div class="graph-band" data-band="${esc(m.map)}" style="left:${mmfX-G.pad}px;top:${bandY}px;width:${bandW}px;height:${bandH}px"></div>`);
  const dxRoot=Math.max(16,(mmfX-G.root)/2);
  links.push(`<path class="e-mmf" data-link="${esc(group.id)}>${esc(m.map)}" d="M${G.root} ${rootMidY} C${G.root+dxRoot} ${rootMidY},${mmfX-dxRoot} ${mmfMidY},${mmfX} ${mmfMidY}"/>`);

  const mmfSelected=m===mmf&&!ticket;
  const mmfExec=Boolean(m.executing);
  const doneCount=m.tickets.filter(t=>t.lane?.group==='done').length;
  const segHtml=m.tickets.map(t=>`<i class="g-${t.lane?esc(t.lane.group):'pending'}"></i>`).join('');
  const countText=m.tickets.length?`${doneCount}/${m.tickets.length} 已集成`:'尚无票';
  const mmfTitleAttr=`${m.title} · ${stageLabel(m.stage)} · ${countText}`;
  nodes.push(`<button class="graph-mmf${mmfExec?' is-executing':''}${mmfSelected?' selected':''}" data-board="mmf" data-map="${esc(m.map)}" data-x="${mmfX}" data-y="${mmfY}" aria-pressed="${mmfSelected}" title="${esc(mmfTitleAttr)}" style="left:${mmfX}px;top:${mmfY}px">${mmfExec?execRing(G.card,G.head):''}<span class="mmf-top"><b class="mmf-key">${esc(m.map)}</b><span class="mmf-stage">${esc(stageLabel(m.stage))}</span></span><span class="mmf-t">${esc(m.title)}</span><span class="mmf-seg">${segHtml}</span><span class="mmf-meta">${esc(countText)}${mmfExec?` · <span class="exec-label">${esc(copy.执行中)}</span>`:''}</span></button>`);

  if(!m.tickets.length){
   nodes.push(`<div class="graph-band-empty" style="left:${ticketX0}px;top:${Math.round(bandY+bandH/2-10)}px">尚无票</div>`);
  }

  for(const t of m.tickets){
   const p=pos.get(t.id)!;
   if(!t.deps.length){
    const dxFirst=Math.max(16,(p.x-(mmfX+G.card))/2);
    links.push(`<path class="e-root" data-map="${esc(m.map)}" data-root-to="${esc(t.id)}" d="M${mmfX+G.card} ${mmfMidY} C${mmfX+G.card+dxFirst} ${mmfMidY},${p.x-dxFirst} ${p.y+G.h/2},${p.x} ${p.y+G.h/2}"/>`);
   }
   for(const d of t.deps){
    const q=pos.get(d);
    if(q)links.push(`<path class="e-dep" data-map="${esc(m.map)}" data-dep="${esc(d)}>${esc(t.id)}" d="M${q.x+G.card} ${q.y+G.h/2} C${q.x+G.card+G.gx/2} ${q.y+G.h/2},${p.x-G.gx/2} ${p.y+G.h/2},${p.x} ${p.y+G.h/2}"/>`);
   }
   const selected=m===mmf&&t===ticket;
   const executing=Boolean(t.executing);
   const status=ticketStatusText(t);
   const groupCls=t.lane?esc(t.lane.group):'pending';
   const titleAttr=`${t.id} ${t.title} · ${status}`;
   nodes.push(`<button class="graph-ticket g-${groupCls}${executing?' is-executing':''}${selected?' selected':''}" data-board="ticket" data-map="${esc(m.map)}" data-ticket="${esc(t.id)}" data-x="${p.x}" data-y="${p.y}" aria-pressed="${selected}" title="${esc(titleAttr)}" style="left:${p.x}px;top:${p.y}px">${executing?execRing(G.card,G.h):''}<span class="tk-row"><b class="tk-id">${esc(t.id)}</b><span class="tk-t">${esc(t.title)}</span></span><small class="tk-st ${ticketStateClass(t)}${executing?' exec-label':''}">${executing?'<i class="pulse-dot" aria-hidden="true"></i>':''}${esc(status)}</small></button>`);
  }
 }

 const rootMeta=`${group.mmfs.length} MMF · ${doneTickets}/${totalTickets} 票`;
 return `<div class="graph" style="width:${width}px;height:${h}px">${bands.join('')}<svg class="graph-links" width="${width}" height="${h}" viewBox="0 0 ${width} ${h}" style="width:${width}px;height:${h}px" aria-hidden="true">${links.join('')}</svg><div class="graph-root" data-x="0" data-y="${rootY}" data-meta="${esc(rootMeta)}" title="${esc(group.label)} · ${esc(rootMeta)}" style="left:0;top:${rootY}px">${esc(group.label)}</div>${nodes.join('')}</div>`;
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
  const rootTo=p.getAttribute('data-root-to');
  let active=false;
  if(dep!==null){
   active=p.getAttribute('data-map')===hovered.map&&chain.edges.has(dep);
  }else if(rootTo!==null){
   active=p.getAttribute('data-map')===hovered.map&&chain.nodes.has(rootTo);
  }else{
   const link=p.getAttribute('data-link')??'';
   active=link.endsWith(`>${hovered.map}`);
  }
  p.classList.toggle('chain',active);
  p.classList.toggle('dimmed',!active);
 }
}
