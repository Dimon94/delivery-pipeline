import type {BoardSnapshot,Epic,Mmf,Ticket} from './board';
import {copy,stageLabel,laneGroupNames} from './copy';
import {shouldRereadBoard} from './guide';

// 看板视图：读取中 → 已渲染 | 读取失败（DD-668 T1–T6）；左右栏各自收起（R15）。
export type BoardState={kind:'loading'}|{kind:'rendered';board:BoardSnapshot}|{kind:'failed';reason:string};
export interface BoardHost {read():Promise<unknown>; openSettings():void}
// 左栏一级入口：仓库下的 Epic，或独立的 Inbox。
type Group={id:string;label:string;url:string|null;mmfs:Mmf[]};
type Pick={group?:string;map?:string;ticket?:string};

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const INBOX='inbox';
const epicId=(repo:string,epic:Epic)=>`${repo}|${epic.key}`;
// 图的几何：坐标只由层号与行号决定，栏宽变化后连线仍与卡片对齐。
const G={root:120,card:176,h:56,gx:44,gy:14,head:40,band:20};

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

export class BoardView {
 state:BoardState={kind:'loading'};
 visible=true;
 left=true;
 right=true;
 private pick:Pick={};
 private generation=0;
 constructor(private root:HTMLElement,private host:BoardHost) {
  root.addEventListener('click',event=>this.click(event));
 }
 // T1 启动或从设置返回；T4 重试；T5 回到前台。选择跨读取保留。
 async load() {
  const generation=++this.generation;
  this.state={kind:'loading'};this.render();
  let next:BoardState;
  try {
   const board=await this.host.read() as BoardSnapshot|null;
   next=board&&typeof board==='object'&&board.schema===1&&Array.isArray(board.repos)&&Array.isArray(board.inbox)?{kind:'rendered',board}:{kind:'failed',reason:copy.看板快照格式不对};
  }catch(error){next={kind:'failed',reason:error instanceof Error?error.message:String(error)};}
  if(generation!==this.generation)return;
  this.state=next;this.render();
 }
 rereadOnFocus() {
  if(shouldRereadBoard({visible:this.visible,state:this.state.kind}))void this.load();
 }
 show(visible:boolean) {this.visible=visible;this.root.hidden=!visible;}
 private groups(board:BoardSnapshot) {
  const repos=board.repos.map(r=>({name:r.name,epics:r.epics.map(e=>({ended:e.ended,group:{id:epicId(r.name,e),label:e.title&&e.title!==e.key&&e.title!=='Unknown'?`${e.key} · ${e.title}`:e.key,url:e.url,mmfs:e.mmfs} as Group}))}));
  const inbox:Group={id:INBOX,label:copy.Inbox,url:null,mmfs:board.inbox};
  return {repos,inbox,all:[...repos.flatMap(r=>r.epics.filter(e=>!e.ended).map(e=>e.group)),...repos.flatMap(r=>r.epics.filter(e=>e.ended).map(e=>e.group)),...(board.inbox.length?[inbox]:[])]};
 }
 // 所选 Epic 或票消失时退回该 Epic 的第一张票；没有 Epic 时退回第一个入口。
 private settle(all:Group[]):{group?:Group;mmf?:Mmf;ticket?:Ticket} {
  const group=all.find(g=>g.id===this.pick.group)??all[0];
  if(!group){this.pick={};return {};}
  const mmf=group.mmfs.find(m=>m.map===this.pick.map);
  const ticket=mmf?.tickets.find(t=>t.id===this.pick.ticket);
  if(mmf&&(ticket||this.pick.ticket===undefined)){this.pick={group:group.id,map:mmf.map,ticket:ticket?.id};return {group,mmf,ticket};}
  const first=group.mmfs.find(m=>m.tickets.length)??group.mmfs[0];
  this.pick={group:group.id,map:first?.map,ticket:first?.tickets[0]?.id};
  return {group,mmf:first,ticket:first?.tickets[0]};
 }
 private click(event:Event) {
  const target=(event.target as Element).closest<HTMLElement>('[data-board]');
  if(!target)return;
  const {board:action,group,map,ticket}=target.dataset;
  if(action==='settings'){this.host.openSettings();return;}
  if(action==='retry'){void this.load();return;}
  if(action==='left'){this.left=!this.left;this.render();return;}
  if(action==='right'){this.right=!this.right;this.render();return;}
  if(action==='group'){this.pick={group};this.render();return;}
  // 图上点票或 MMF：右栏收起时自动展开（R15）。
  if(action==='mmf'||action==='ticket'){this.pick={group:this.pick.group,map,ticket};this.right=true;this.render();}
 }
 render() {
  const s=this.state;
  const toggle=(side:'left'|'right',open:boolean)=>`<button class="plain" data-board="${side}" aria-pressed="${!open}" aria-controls="board-${side}">${open?(side==='left'?copy.收起左栏:copy.收起右栏):(side==='left'?copy.展开左栏:copy.展开右栏)}</button>`;
  const bar=`<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">${copy.看板}</div><div class="right">${s.kind==='rendered'?toggle('left',this.left)+toggle('right',this.right):''}<button class="plain" data-board="settings">${copy.设置}</button></div></header>`;
  if(s.kind==='loading'){this.root.innerHTML=`${bar}<main class="board-frame"><p class="board-state" role="status">${copy.读取中}</p></main>`;return;}
  if(s.kind==='failed'){this.root.innerHTML=`${bar}<main class="board-frame"><div class="board-state board-failed" role="alert"><h2>${copy.读取失败}</h2><p class="board-reason">${esc(s.reason)}</p><button class="primary" data-board="retry">${copy.重试}</button></div></main>`;return;}
  const {repos,inbox,all}=this.groups(s.board);
  const {group,mmf,ticket}=this.settle(all);
  const entry=(g:Group)=>`<button class="board-entry${g.id===group?.id?' selected':''}" data-board="group" data-group="${esc(g.id)}" aria-current="${g.id===group?.id}">${esc(g.label)}<small>${g.mmfs.length} MMF</small></button>`;
  const ended=repos.flatMap(r=>r.epics.filter(e=>e.ended).map(e=>e.group));
  const leftCol=`<nav class="board-col board-left" id="board-left" aria-label="Epic" ${this.left?'':'hidden'}><div class="board-col-head"><h2>Epic</h2><button class="quiet" data-board="left">${copy.收起左栏}</button></div>${repos.filter(r=>r.epics.some(e=>!e.ended)).map(r=>`<section class="board-repo"><h3>${esc(r.name)}</h3>${r.epics.filter(e=>!e.ended).map(e=>entry(e.group)).join('')}</section>`).join('')}${ended.length?`<details class="board-repo"${ended.some(g=>g.id===group?.id)?' open':''}><summary>${copy.已结束} ${ended.length}</summary>${ended.map(entry).join('')}</details>`:''}${board_inbox(inbox,entry)}</nav>`;
  const center=`<section class="board-col board-center" aria-label="${copy.依赖}">${group?graph(group,mmf,ticket):`<p class="board-state">${copy.没有进行中的工作}</p>`}</section>`;
  const rightCol=`<aside class="board-col board-right" id="board-right" aria-label="${copy.选择一张票查看详情}" ${this.right?'':'hidden'}><div class="board-col-head"><h2>${ticket?esc(ticket.id):mmf?'MMF':''}</h2><button class="quiet" data-board="right">${copy.收起右栏}</button></div>${detail(mmf,ticket,group?.id===INBOX)}</aside>`;
  this.root.innerHTML=`${bar}<main class="board-grid" data-left="${this.left?'open':'closed'}" data-right="${this.right?'open':'closed'}">${leftCol}${center}${rightCol}</main>`;
 }
}

function board_inbox(inbox:Group,entry:(g:Group)=>string) {
 return inbox.mmfs.length?`<section class="board-repo board-inbox">${entry(inbox)}</section>`:'';
}

const groupOf=(t:Ticket)=>t.lane?laneGroupNames[t.lane.group]??t.lane.group:copy.未派发;
function graph(group:Group,mmf:Mmf|undefined,ticket:Ticket|undefined) {
 const nodes:string[]=[],links:string[]=[];
 const x0=G.root+G.gx;let y=0,width=x0+G.card;
 for(const m of group.mmfs){
  const layer=ticketLayers(m.tickets),rows=new Map<number,number>();
  const pos=new Map<string,{x:number;y:number}>();
  for(const t of m.tickets){const l=layer.get(t.id)!,r=rows.get(l)??0;rows.set(l,r+1);pos.set(t.id,{x:x0+l*(G.card+G.gx),y:y+G.head+r*(G.h+G.gy)});}
  const height=G.head+Math.max(1,...rows.values())*(G.h+G.gy);
  links.push(`<path data-link="${esc(group.id)}>${esc(m.map)}" d="M${G.root} ${G.h/2} C${G.root+G.gx/2} ${G.h/2},${x0-G.gx/2} ${y+G.head/2-4},${x0} ${y+G.head/2-4}"/>`);
  nodes.push(`<button class="graph-mmf${m===mmf&&!ticket?' selected':''}" data-board="mmf" data-map="${esc(m.map)}" style="left:${x0}px;top:${y}px">${esc(m.title)}<small>${esc(stageLabel(m.stage))}</small></button>`);
  for(const t of m.tickets){
   const p=pos.get(t.id)!;width=Math.max(width,p.x+G.card);
   for(const d of t.deps){const q=pos.get(d);if(q)links.push(`<path data-map="${esc(m.map)}" data-dep="${esc(d)}>${esc(t.id)}" d="M${q.x+G.card} ${q.y+G.h/2} C${q.x+G.card+G.gx/2} ${q.y+G.h/2},${p.x-G.gx/2} ${p.y+G.h/2},${p.x} ${p.y+G.h/2}"/>`);}
   nodes.push(`<button class="graph-ticket g-${t.lane?esc(t.lane.group):'none'}${m===mmf&&t===ticket?' selected':''}" data-board="ticket" data-map="${esc(m.map)}" data-ticket="${esc(t.id)}" data-x="${p.x}" data-y="${p.y}" style="left:${p.x}px;top:${p.y}px"><b>${esc(t.id)}</b> ${esc(t.title)}<small>${esc(groupOf(t))}${t.lane?` · ${esc(t.lane.state)}`:''}</small></button>`);
  }
  y+=height+G.band;
 }
 const h=Math.max(y,G.h);
 return `<div class="graph" style="width:${width}px;height:${h}px"><svg class="graph-links" width="${width}" height="${h}" viewBox="0 0 ${width} ${h}" aria-hidden="true">${links.join('')}</svg><div class="graph-root" style="left:0;top:0">${esc(group.label)}</div>${nodes.join('')}</div>`;
}

function detail(mmf:Mmf|undefined,ticket:Ticket|undefined,inbox:boolean) {
 if(!mmf)return `<p class="board-state">${copy.选择一张票查看详情}</p>`;
 const row=(k:string,v:string)=>`<div class="detail-row"><dt>${k}</dt><dd>${v}</dd></div>`;
 const link=(url:string|null,label:string)=>url?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${label}</a>`:'';
 if(ticket){
  const lane=ticket.lane;
  return `<h3 class="detail-title">${esc(ticket.title)}</h3><p class="detail-sub">${esc(mmf.title)}${inbox?` · ${copy.待归属}`:''}</p><dl>${row(copy.交付阶段,esc(stageLabel(ticket.stage)))}${row(copy.执行状态,lane?`${esc(groupOf(ticket))} · ${esc(lane.state)}`:copy.未派发)}${lane?row('Agent',`${esc(lane.agent)} · ${esc(lane.model)}`)+row(copy.分支,esc(lane.branch??lane.lane_id)):''}${row(copy.依赖,ticket.deps.length?ticket.deps.map(esc).join('、'):copy.无)}</dl><div class="detail-links">${link(ticket.linear,copy.打开Linear)}</div>`;
 }
 return `<h3 class="detail-title">${esc(mmf.title)}</h3><p class="detail-sub">${esc(mmf.map)}${inbox?` · ${copy.待归属}`:''}</p><dl>${row(copy.交付阶段,esc(stageLabel(mmf.stage)))}${mmf.halt?row('Halt',esc(mmf.halt.label)):''}</dl><div class="detail-links">${link(mmf.links.plan_review,copy.打开计划审查页)}${link(mmf.links.merge_review,copy.打开合并审查页)}${link(mmf.links.linear,copy.打开Linear)}</div>`;
}
