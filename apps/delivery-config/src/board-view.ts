import type {BoardSnapshot,InboxItem,Mmf,Ticket} from './board';
import {copy} from './copy';
import {shouldRereadBoard} from './guide';
import {GRAPH_GEOMETRY,applyHoverChain,graphSummary,isSummarizedMmf,renderGraph,scrollTargetForNode,ticketLayers,type GraphGroup} from './board-graph';
import {INBOX_GROUP_ID,buildBoardGroups,isEpicExpanded,renderLeftColumn,type BoardGroups} from './board-side';
import {renderRightColumn} from './board-detail';

export {ticketLayers};

// 看板视图：读取中 → 已渲染 | 读取失败（DD-668 T1–T6）；左右栏各自收起（R15）。
export type BoardState={kind:'loading'}|{kind:'rendered';board:BoardSnapshot}|{kind:'failed';reason:string};
export interface BoardHost {read():Promise<unknown>; openSettings():void}
// 左栏一级入口：仓库下的 Epic，或独立的 Inbox。
type Group=GraphGroup;
type Pick={group?:string;map?:string;ticket?:string};

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export class BoardView {
 state:BoardState={kind:'loading'};
 visible=true;
 left=true;
 right=true;
 private pick:Pick={};
 private generation=0;
 private currentGroup:Group|undefined;
 private lastGroupId:string|undefined;
 private lastGroups:BoardGroups|undefined;
 private hovered:{map:string;ticket:string}|undefined;
 private scrollRequest:'reset'|'selected'|'summary'|'preserve'='reset';
 private expandedEpics=new Map<string,boolean>();
 private expandedSummaries=new Set<string>();
 private endedOpen=false;
 private inboxOpen=false;
 constructor(private root:HTMLElement,private host:BoardHost) {
  root.addEventListener('click',event=>this.click(event));
  root.addEventListener('mouseover',event=>this.hover(event));
  root.addEventListener('mouseout',event=>this.unhover(event));
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
  this.scrollRequest='preserve';
  this.state=next;this.render();
 }
 rereadOnFocus() {
  if(shouldRereadBoard({visible:this.visible,state:this.state.kind}))void this.load();
 }
 show(visible:boolean) {this.visible=visible;this.root.hidden=!visible;}
 // 所选 Epic 或票消失时退回该 Epic 的第一张票；没有 Epic 时退回第一个入口。
 private settle(all:Group[]):{group?:Group;mmf?:Mmf;ticket?:Ticket} {
  const group=all.find(g=>g.id===this.pick.group)??all[0];
  if(!group){this.pick={};return {};}
  const visible=this.expandedSummaries.has(group.id)?group.mmfs:group.mmfs.filter(m=>!isSummarizedMmf(group,m));
  const mmf=visible.find(m=>m.map===this.pick.map);
  const ticket=mmf?.tickets.find(t=>t.id===this.pick.ticket);
  if(mmf&&(ticket||this.pick.ticket===undefined)){this.pick={group:group.id,map:mmf.map,ticket:ticket?.id};return {group,mmf,ticket};}
  const first=visible.find(m=>m.tickets.length)??visible[0];
  this.pick={group:group.id,map:first?.map,ticket:first?.tickets[0]?.id};
  return {group,mmf:first,ticket:first?.tickets[0]};
 }
 private hover(event:Event) {
  const el=(event.target as Element|null)?.closest<HTMLElement>('.graph-ticket');
  if(!el||!el.dataset.map||!el.dataset.ticket)return;
  if(this.hovered?.map===el.dataset.map&&this.hovered?.ticket===el.dataset.ticket)return;
  this.hovered={map:el.dataset.map,ticket:el.dataset.ticket};
  applyHoverChain(this.root,this.currentGroup,this.hovered);
 }
 private unhover(event:Event) {
  const from=(event.target as Element|null)?.closest<HTMLElement>('.graph-ticket');
  if(!from)return;
  const related=((event as MouseEvent).relatedTarget as Element|null)?.closest<HTMLElement>('.graph-ticket');
  if(related===from)return;
  if(related&&related.dataset.map&&related.dataset.ticket){
   this.hovered={map:related.dataset.map,ticket:related.dataset.ticket};
   applyHoverChain(this.root,this.currentGroup,this.hovered);
   return;
  }
  if(!this.hovered)return;
  this.hovered=undefined;
  applyHoverChain(this.root,this.currentGroup,undefined);
 }
 private click(event:Event) {
  const target=(event.target as Element).closest<HTMLElement>('[data-board]');
  if(!target)return;
  const {board:action,group,map,ticket}=target.dataset;
  if(action==='settings'){this.host.openSettings();return;}
  if(action==='retry'){void this.load();return;}
  if(action==='left'){this.left=!this.left;this.scrollRequest='preserve';this.render();return;}
  if(action==='right'){this.right=!this.right;this.scrollRequest='preserve';this.render();return;}
  if(action==='toggle-inbox'){
   this.inboxOpen=!this.inboxOpen;
   this.scrollRequest='preserve';
   this.render();
   return;
  }
  if(action==='toggle-summary'&&group){
   const focused=target===this.root.ownerDocument.activeElement;
   const inHeader=target.matches('.board-summary-toggle');
   const opening=!this.expandedSummaries.has(group);
   if(!opening)this.expandedSummaries.delete(group);
   else this.expandedSummaries.add(group);
   this.hovered=undefined;
   this.scrollRequest=opening&&inHeader?'summary':'preserve';
   this.render();
   const selector=inHeader?'.board-summary-toggle':'.graph-summary';
   if(focused)this.root.querySelector<HTMLElement>(selector)?.focus({preventScroll:true});
   return;
  }
  if(action==='toggle-epic'&&group){
   const entry=this.lastGroups?[...this.lastGroups.repos.flatMap(r=>r.epics),...this.lastGroups.ended].find(e=>e.group.id===group):undefined;
   const current=entry?isEpicExpanded(entry,this.expandedEpics):Boolean(this.expandedEpics.get(group));
   this.expandedEpics.set(group,!current);
   this.scrollRequest='preserve';
   this.render();
   return;
  }
  if(action==='group'){this.pick={group};this.hovered=undefined;this.scrollRequest='reset';this.render();return;}
  if(action==='side-mmf'){
   const selectedGroup=this.lastGroups?.all.find(g=>g.id===group);
   const entry=selectedGroup?.mmfs.find(m=>m.map===map);
   if(selectedGroup&&entry&&isSummarizedMmf(selectedGroup,entry))this.expandedSummaries.add(selectedGroup.id);
   const sameGroup=group===this.pick.group;
   this.pick={group,map,ticket:undefined};
   this.hovered=undefined;
   this.right=true;
   this.scrollRequest=sameGroup?'selected':'reset';
   this.render();
   return;
  }
  // 图上点票或 MMF：右栏收起时自动展开（R15），并将所选节点滚入中栏视口（R12）。
  if(action==='mmf'||action==='ticket'){this.pick={group:this.pick.group,map,ticket};this.right=true;this.scrollRequest='selected';this.render();}
 }
 render() {
  const prevCenter=this.root.querySelector<HTMLElement>('.board-center');
  const prevViewport={left:prevCenter?.scrollLeft??0,top:prevCenter?.scrollTop??0,width:prevCenter?.clientWidth??0,height:prevCenter?.clientHeight??0};
  const s=this.state;
  const toggle=(side:'left'|'right',open:boolean)=>`<button class="plain" data-board="${side}" aria-pressed="${!open}" aria-controls="board-${side}">${open?(side==='left'?copy.收起左栏:copy.收起右栏):(side==='left'?copy.展开左栏:copy.展开右栏)}</button>`;
  const bar=`<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">${copy.看板}</div><div class="right">${s.kind==='rendered'?toggle('left',this.left)+toggle('right',this.right):''}<button class="plain" data-board="settings">${copy.设置}</button></div></header>`;
  if(s.kind==='loading'){this.currentGroup=undefined;this.hovered=undefined;this.root.innerHTML=`${bar}<main class="board-frame"><p class="board-state" role="status">${copy.读取中}</p></main>`;return;}
  if(s.kind==='failed'){this.currentGroup=undefined;this.hovered=undefined;this.root.innerHTML=`${bar}<main class="board-frame"><div class="board-state board-failed" role="alert"><h2>${copy.读取失败}</h2><p class="board-reason">${esc(s.reason)}</p><button class="primary" data-board="retry">${copy.重试}</button></div></main>`;return;}
  const groups=buildBoardGroups(s.board);
  this.lastGroups=groups;
  const {group,mmf,ticket}=this.settle(groups.all);
  const groupChanged=group?.id!==this.lastGroupId;
  this.currentGroup=group;
  this.lastGroupId=group?.id;
  const isInbox=group?.id===INBOX_GROUP_ID;
  const inboxItem=isInbox&&mmf?mmf as InboxItem:undefined;
  const leftCol=renderLeftColumn({
   groups,
   selectedGroupId:group?.id,
   selectedMap:mmf?.map,
   open:this.left,
   endedOpen:this.endedOpen,
   inboxOpen:this.inboxOpen,
   expandedEpics:this.expandedEpics,
   expandedFinished:this.expandedSummaries,
   generatedAt:s.board.generated_at,
  });
  const legend=`<div class="board-subbar"><span class="board-legend"><span><i class="g-done"></i>已完成</span><span><i class="g-active"></i>进行中</span><span><i class="g-review"></i>待收口</span><span><i class="g-problem"></i>需处理</span><span><i class="g-pending"></i>未派发</span><span class="lg-exec"><b class="lg-ring"></b>执行中（running 且现场 working）</span></span></div>`;
  const summaryOpen=Boolean(group&&this.expandedSummaries.has(group.id));
  const summary=group&&graphSummary(group,summaryOpen);
  const summaryToggle=group&&summary?.items.length
   ?`<button class="plain board-summary-toggle" data-board="toggle-summary" data-group="${esc(group.id)}" aria-expanded="${summaryOpen}" title="${summary.hint}"><span aria-hidden="true">${summaryOpen?'▾':'▸'}</span> ${summary.label} <small>${summary.count}</small></button>`:'';
  const center=`<section class="board-center-pane" aria-label="${copy.依赖}"><div class="board-col-head"><h2 title="${esc(group?.label??copy.看板)}">${esc(group?.label??copy.看板)}</h2>${summaryToggle}</div>${legend}<div class="board-col board-center">${group?renderGraph(group,mmf,ticket,summaryOpen):`<p class="board-state">${copy.没有进行中的工作}</p>`}</div></section>`;
  const rightCol=renderRightColumn({epicKey:isInbox?undefined:group?.label,mmf,ticket,inbox:isInbox,inboxRepo:inboxItem?.repo,inboxSpec:inboxItem?.kind==='spec',open:this.right});
  this.root.innerHTML=`${bar}<main class="board-grid" data-left="${this.left?'open':'closed'}" data-right="${this.right?'open':'closed'}">${leftCol}${center}${rightCol}</main>`;
  const endedDetails=this.root.querySelector<HTMLDetailsElement>('details[data-board-ended]');
  endedDetails?.addEventListener('toggle',()=>{this.endedOpen=endedDetails.open;});
  const centerEl=this.root.querySelector<HTMLElement>('.board-center');
  if(centerEl){
   const mode=groupChanged?'reset':this.scrollRequest;
   this.scrollRequest='preserve';
   if(mode==='reset'){
    centerEl.scrollLeft=0;
    centerEl.scrollTop=0;
   }else{
    centerEl.scrollLeft=prevViewport.left;
    centerEl.scrollTop=prevViewport.top;
    if(mode==='selected'||mode==='summary'){
     const selectedEl=centerEl.querySelector<HTMLElement>(mode==='summary'?'.graph-summary':'.graph-ticket.selected,.graph-mmf.selected');
     if(selectedEl){
      const graphEl=centerEl.querySelector<HTMLElement>('.graph');
      const graphW=graphEl?parseFloat(graphEl.style.width)||0:0;
      const graphH=graphEl?parseFloat(graphEl.style.height)||0:0;
      const x=Number(selectedEl.dataset.x??0),y=Number(selectedEl.dataset.y??0);
      const isMmf=selectedEl.classList.contains('graph-mmf');
      const w=isMmf?GRAPH_GEOMETRY.mmfW:GRAPH_GEOMETRY.ticketW;
      const h=isMmf?GRAPH_GEOMETRY.mmfH:GRAPH_GEOMETRY.ticketH;
      const target=scrollTargetForNode({
       scrollLeft:centerEl.scrollLeft,
       scrollTop:centerEl.scrollTop,
       clientWidth:centerEl.clientWidth||prevViewport.width,
       clientHeight:centerEl.clientHeight||prevViewport.height,
       scrollWidth:centerEl.scrollWidth||graphW,
       scrollHeight:centerEl.scrollHeight||graphH,
      },{x,y,width:w,height:h});
      centerEl.scrollLeft=target.scrollLeft;
      centerEl.scrollTop=target.scrollTop;
     }
    }
   }
  }
  if(this.hovered&&!groupChanged)applyHoverChain(this.root,this.currentGroup,this.hovered);
  else this.hovered=undefined;
 }
}
