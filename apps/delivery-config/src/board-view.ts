import {validateBoardSnapshot,type BoardLinear,type BoardSnapshot,type InboxItem,type Mmf,type MmfCandidate,type Ticket} from './board';
import {copy} from './copy';
import {shouldRereadBoard} from './guide';
import {GRAPH_GEOMETRY,applyHoverChain,candidateKey,graphSummary,isSummarizedMmf,missingMmfEdges,renderGraph,scrollTargetForNode,ticketLayers,type GraphGroup} from './board-graph';
import {INBOX_GROUP_ID,buildBoardGroups,isEpicExpanded,renderLeftColumn,type BoardGroups} from './board-side';
import {renderRightColumn} from './board-detail';

export {ticketLayers};

const LINEAR_COOLDOWN_MS=5*60*1000;

export function isLinearFresh(linear:BoardLinear|undefined,nowMs=Date.now()):boolean {
 if(!linear||linear.status!=='ok')return false;
 const attempted=Date.parse(linear.attempted_at);
 if(Number.isNaN(attempted))return false;
 const age=nowMs-attempted;
 return age>=0&&age<LINEAR_COOLDOWN_MS;
}

function formatLinearTime(iso:string):string {
 return iso.replace('T',' ').replace(/\.\d+/,'').replace(/([+-]\d\d:\d\d|Z)$/,'');
}

// 看板视图：读取中 → 已渲染 | 读取失败（DD-668 T1–T6）；左右栏各自收起（R15）。
export type BoardState={kind:'loading'}|{kind:'rendered';board:BoardSnapshot}|{kind:'failed';reason:string};
export interface BoardHost {
 read():Promise<unknown>;
 refreshLinear?(manual:boolean):Promise<unknown>;
 openSettings():void;
 openLink?(target:string):Promise<void>|void;
}
// 左栏一级入口：仓库下的 Epic，或独立的 Inbox。
type Group=GraphGroup;
type Pick={group?:string;map?:string;ticket?:string;candidate?:string};

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export class BoardView {
 state:BoardState={kind:'loading'};
 visible=true;
 left=true;
 right=true;
 private pick:Pick={};
 private generation=0;
 private linearRefreshing=false;
 private linearRefreshPromise:Promise<void>|undefined;
 private linearError:string|undefined;
 private currentGroup:Group|undefined;
 private lastGroupId:string|undefined;
 private lastGroups:BoardGroups|undefined;
 private hovered:{map?:string;ticket?:string;candidate?:string}|undefined;
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
   const raw=await this.host.read();
   const invalid=validateBoardSnapshot(raw);
   next=invalid?{kind:'failed',reason:`${copy.看板快照格式不对}（${invalid}）`}:{kind:'rendered',board:raw as BoardSnapshot};
  }catch(error){next={kind:'failed',reason:error instanceof Error?error.message:String(error)};}
  if(generation!==this.generation)return;
  this.scrollRequest='preserve';
  this.state=next;
  try {
   this.render();
  }catch(error){
   this.state={kind:'failed',reason:error instanceof Error?error.message:String(error)};
   this.render();
   return;
  }
  if(next.kind==='rendered'&&this.host.refreshLinear&&!isLinearFresh(next.board.linear)){
   void this.refreshLinear(false);
  }
 }
 // T3/T4/T5/T6/T7/T8：触发 Linear 更新；并发共享同一次在途请求，期间按钮置灰，完成后保留选择重绘。
 refreshLinear(manual:boolean):Promise<void> {
  if(!this.host.refreshLinear)return Promise.resolve();
  if(this.linearRefreshPromise)return this.linearRefreshPromise;
  if(!manual&&this.state.kind==='rendered'&&isLinearFresh(this.state.board.linear))return Promise.resolve();
  this.linearRefreshing=true;
  this.linearError=undefined;
  if(this.state.kind==='rendered'){
   this.scrollRequest='preserve';
   this.render();
  }
  const run=(async()=>{
   try {
    const raw=await this.host.refreshLinear!(manual);
    const invalid=validateBoardSnapshot(raw);
    if(invalid){
     this.linearError=`${copy.看板快照格式不对}（${invalid}）`;
    }else{
     this.linearError=undefined;
     this.scrollRequest='preserve';
     this.state={kind:'rendered',board:raw as BoardSnapshot};
    }
   }catch(error){
    this.linearError=error instanceof Error?error.message:String(error);
   }finally{
    this.linearRefreshing=false;
    this.linearRefreshPromise=undefined;
    if(this.state.kind==='rendered'){
     this.scrollRequest='preserve';
     this.render();
    }
   }
  })();
  this.linearRefreshPromise=run;
  return run;
 }
 private renderLinearStatus(board:BoardSnapshot):string {
  const linear=board.linear;
  const fetched=linear?.fetched_at?formatLinearTime(linear.fetched_at):'';
  const reason=this.linearError??linear?.reason??null;
  let cls='is-offline';
  let text='未接上 Linear，显示本机数据';
  if(this.linearRefreshing){
   cls='is-updating';
   text=fetched?`Linear 数据 ${fetched} · 正在从 Linear 更新…`:'未接上 Linear · 正在从 Linear 更新…';
  }else if(this.linearError||linear?.status==='failed'){
   if(fetched){
    cls='is-warn';
    text=`Linear 更新失败（${reason||'请重试'}）· 上次获取 ${fetched}`;
   }else{
    cls='is-offline';
    text=reason?`未接上 Linear，显示本机数据（${reason}）`:'未接上 Linear，显示本机数据';
   }
  }else if(linear?.status==='partial'&&fetched){
   cls='is-warn';
   text=`Linear 数据 ${fetched} · ${reason||'部分 Linear 条目读取失败'}`;
  }else if(linear?.status==='ok'&&fetched){
   cls='is-ok';
   text=`Linear 数据 ${fetched}`;
  }
  const btn=this.host.refreshLinear
   ?`<button class="plain board-linear-btn" data-board="refresh-linear"${this.linearRefreshing?' disabled':''}>从 Linear 更新</button>`
   :'';
  return `<div class="board-linear-bar"><span class="board-linear-status ${cls}" role="status" title="${esc(text)}">${esc(text)}</span>${btn}</div>`;
 }
 rereadOnFocus() {
  if(shouldRereadBoard({visible:this.visible,state:this.state.kind}))void this.load();
 }
 show(visible:boolean) {this.visible=visible;this.root.hidden=!visible;}
 // 所选 Epic 或票仍在快照中时保留选中（含已合入归入汇总的 MMF）；对象消失才退回第一张票或入口。
 private settle(all:Group[]):{group?:Group;mmf?:Mmf;ticket?:Ticket;candidate?:MmfCandidate} {
  const group=all.find(g=>g.id===this.pick.group)??all[0];
  if(!group){this.pick={};return {};}
  if(this.pick.candidate!==undefined){
   const cand=(group.candidates??[]).find((c,i)=>candidateKey(c,i)===this.pick.candidate);
   if(cand){
    this.pick={group:group.id,candidate:this.pick.candidate};
    return {group,candidate:cand};
   }
  }
  const pickedMmf=this.pick.map!==undefined?group.mmfs.find(m=>m.map===this.pick.map):undefined;
  const pickedTicket=pickedMmf?.tickets.find(t=>t.id===this.pick.ticket);
  if(pickedMmf&&(pickedTicket||this.pick.ticket===undefined)){
   this.pick={group:group.id,map:pickedMmf.map,ticket:pickedTicket?.id};
   return {group,mmf:pickedMmf,ticket:pickedTicket};
  }
  const visible=this.expandedSummaries.has(group.id)?group.mmfs:group.mmfs.filter(m=>!isSummarizedMmf(group,m));
  const first=visible.find(m=>m.tickets.length)??visible[0];
  this.pick={group:group.id,map:first?.map,ticket:first?.tickets[0]?.id};
  return {group,mmf:first,ticket:first?.tickets[0]};
 }
 private hoverTarget(el:Element|null):{map?:string;ticket?:string;candidate?:string}|undefined {
  const node=el?.closest<HTMLElement>('.graph-ticket,.graph-mmf[data-map],.graph-candidate[data-candidate]');
  if(!node)return undefined;
  if(node.classList.contains('graph-candidate')&&node.dataset.candidate){
   return {candidate:node.dataset.candidate};
  }
  if(!node.dataset.map)return undefined;
  return node.classList.contains('graph-ticket')&&node.dataset.ticket
   ?{map:node.dataset.map,ticket:node.dataset.ticket}
   :{map:node.dataset.map};
 }
 private hover(event:Event) {
  const next=this.hoverTarget(event.target as Element|null);
  if(!next)return;
  if(this.hovered?.map===next.map&&this.hovered?.ticket===next.ticket&&this.hovered?.candidate===next.candidate)return;
  this.hovered=next;
  applyHoverChain(this.root,this.currentGroup,this.hovered);
 }
 private unhover(event:Event) {
  const from=(event.target as Element|null)?.closest<HTMLElement>('.graph-ticket,.graph-mmf[data-map],.graph-candidate[data-candidate]');
  if(!from)return;
  const relatedEl=((event as MouseEvent).relatedTarget as Element|null)?.closest<HTMLElement>('.graph-ticket,.graph-mmf[data-map],.graph-candidate[data-candidate]');
  if(relatedEl===from)return;
  const next=this.hoverTarget(relatedEl??null);
  if(next){
   this.hovered=next;
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
  const {board:action,group,map,ticket,candidate,href}=target.dataset;
  if(action==='open-link'&&href){event.preventDefault();void this.host.openLink?.(href);return;}
  if(action==='settings'){this.host.openSettings();return;}
  if(action==='retry'){void this.load();return;}
  if(action==='refresh-linear'){void this.refreshLinear(true);return;}
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
   if(!opening){
    this.expandedSummaries.delete(group);
    const current=this.lastGroups?.all.find(g=>g.id===group);
    const picked=current?.mmfs.find(m=>m.map===this.pick.map);
    if(current&&picked&&isSummarizedMmf(current,picked))this.pick={group};
   }else this.expandedSummaries.add(group);
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
  // 图上点票、MMF 或未开工候选卡：右栏收起时自动展开（R15），并将所选节点滚入中栏视口（R12）。
  if(action==='candidate'&&candidate){this.pick={group:this.pick.group,candidate};this.right=true;this.scrollRequest='selected';this.render();return;}
  if(action==='mmf'||action==='ticket'){this.pick={group:this.pick.group,map,ticket};this.right=true;this.scrollRequest='selected';this.render();}
 }
 render() {
  const prevCenter=this.root.querySelector<HTMLElement>('.board-center');
  const prevViewport={left:prevCenter?.scrollLeft??0,top:prevCenter?.scrollTop??0,width:prevCenter?.clientWidth??0,height:prevCenter?.clientHeight??0};
  const s=this.state;
  const toggle=(side:'left'|'right',open:boolean)=>`<button class="plain" data-board="${side}" aria-pressed="${!open}" aria-controls="board-${side}">${open?(side==='left'?copy.收起左栏:copy.收起右栏):(side==='left'?copy.展开左栏:copy.展开右栏)}</button>`;
  const linearBar=s.kind==='rendered'?this.renderLinearStatus(s.board):'';
  const bar=`<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">${copy.看板}</div>${linearBar}<div class="right">${s.kind==='rendered'?toggle('left',this.left)+toggle('right',this.right):''}<button class="plain" data-board="settings">${copy.设置}</button></div></header>`;
  if(s.kind==='loading'){this.currentGroup=undefined;this.hovered=undefined;this.root.innerHTML=`${bar}<main class="board-frame"><p class="board-state" role="status">${copy.读取中}</p></main>`;return;}
  if(s.kind==='failed'){this.currentGroup=undefined;this.hovered=undefined;this.root.innerHTML=`${bar}<main class="board-frame"><div class="board-state board-failed" role="alert"><h2>${copy.读取失败}</h2><p class="board-reason">${esc(s.reason)}</p><button class="primary" data-board="retry">${copy.重试}</button></div></main>`;return;}
  const groups=buildBoardGroups(s.board);
  this.lastGroups=groups;
  const {group,mmf,ticket,candidate}=this.settle(groups.all);
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
  const hasLinear=Boolean(s.board.linear?.fetched_at);
  const linearLegend=hasLinear
   ?'<span><b class="lg-candidate"></b>未开工</span><span><b class="lg-edge-start"></b>开工依赖</span><span><b class="lg-edge-launch"></b>上线依赖</span>'
   :'';
  const legend=`<div class="board-subbar"><span class="board-legend"><span><i class="g-done"></i>已完成</span><span><i class="g-active"></i>进行中</span><span><i class="g-review"></i>待收口</span><span><i class="g-problem"></i>需处理</span><span><i class="g-pending"></i>未派发</span><span class="lg-exec"><b class="lg-ring"></b>执行中（running 且现场 working）</span>${linearLegend}</span></div>`;
  const summaryOpen=Boolean(group&&this.expandedSummaries.has(group.id));
  const summary=group&&graphSummary(group,summaryOpen);
  const summaryToggle=group&&summary?.items.length
   ?`<button class="plain board-summary-toggle" data-board="toggle-summary" data-group="${esc(group.id)}" aria-expanded="${summaryOpen}" title="${summary.hint}"><span aria-hidden="true">${summaryOpen?'▾':'▸'}</span> ${summary.label} <small>${summary.count}</small></button>`:'';
  const center=`<section class="board-center-pane" aria-label="${copy.依赖}"><div class="board-col-head"><h2 title="${esc(group?.label??copy.看板)}">${esc(group?.label??copy.看板)}</h2>${summaryToggle}</div>${legend}<div class="board-col board-center">${group?renderGraph(group,mmf,ticket,summaryOpen,candidate):`<p class="board-state">${copy.没有进行中的工作}</p>`}</div></section>`;
  const rightCol=renderRightColumn({epicKey:isInbox?undefined:group?.label,mmf,ticket,candidate,missingEdges:group&&!isInbox?missingMmfEdges(group,summaryOpen):undefined,inbox:isInbox,inboxRepo:inboxItem?.repo,inboxSpec:inboxItem?.kind==='spec',hasLinear,open:this.right});
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
