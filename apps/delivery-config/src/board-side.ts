import type {BoardError,BoardSnapshot,Epic,InboxItem} from './board';
import type {GraphGroup} from './board-graph';
import {copy,issueLinkLabel,mmfStatusText,stageLabel} from './copy';

export const INBOX_GROUP_ID='inbox';

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export const epicGroupId=(repo:string,epic:Epic)=>`${repo}|${epic.key}`;

export function epicHasRunningTicket(epic:Epic):boolean {
 return epic.mmfs.some(m=>
  Boolean(m.executing)||
  m.direct_lanes.some(l=>l.state==='running')||
  m.tickets.some(t=>Boolean(t.executing)||t.lane?.state==='running')
 );
}

export function inboxItemExecuting(item:InboxItem):boolean {
 return Boolean(item.executing)||item.tickets.some(t=>Boolean(t.executing));
}

export type SideEpicEntry={
 repo:string;
 epic:Epic;
 ended:boolean;
 hasRunning:boolean;
 group:GraphGroup;
};

export type SideRepoSection={
 name:string;
 epics:SideEpicEntry[];
};

export type BoardGroups={
 repos:SideRepoSection[];
 ended:SideEpicEntry[];
 inbox:{group:GraphGroup;items:InboxItem[]};
 errors:BoardError[];
 all:GraphGroup[];
};

export function buildBoardGroups(board:BoardSnapshot):BoardGroups {
 const repos:SideRepoSection[]=[];
 const ended:SideEpicEntry[]=[];
 for(const r of board.repos){
  const activeEpics:SideEpicEntry[]=[];
  for(const e of r.epics){
   const label=e.title&&e.title!==e.key&&e.title!=='Unknown'?`${e.key} · ${e.title}`:e.key;
   const entry:SideEpicEntry={
    repo:r.name,
    epic:e,
    ended:e.ended,
    hasRunning:epicHasRunningTicket(e),
    group:{id:epicGroupId(r.name,e),label,url:e.url,mmfs:e.mmfs},
   };
   if(e.ended)ended.push(entry);
   else activeEpics.push(entry);
  }
  if(activeEpics.length)repos.push({name:r.name,epics:activeEpics});
 }
 const inboxGroup:GraphGroup={id:INBOX_GROUP_ID,label:copy.Inbox,url:null,mmfs:board.inbox};
 const errors=Array.isArray(board.errors)?board.errors:[];
 const all:GraphGroup[]=[
  ...repos.flatMap(r=>r.epics.map(e=>e.group)),
  ...ended.map(e=>e.group),
  ...(board.inbox.length?[inboxGroup]:[]),
 ];
 return {repos,ended,inbox:{group:inboxGroup,items:board.inbox},errors,all};
}

export function isEpicExpanded(entry:SideEpicEntry,overrides:ReadonlyMap<string,boolean>):boolean {
 if(overrides.has(entry.group.id))return overrides.get(entry.group.id)!;
 return !entry.ended&&entry.hasRunning;
}

function renderEpicItem(entry:SideEpicEntry,selectedGroupId:string|undefined,selectedMap:string|undefined,overrides:ReadonlyMap<string,boolean>):string {
 const g=entry.group;
 const expanded=isEpicExpanded(entry,overrides);
 const selected=g.id===selectedGroupId;
 const allTickets=g.mmfs.flatMap(m=>m.tickets);
 const doneCount=allTickets.filter(t=>t.lane?.group==='done').length;
 const problemCount=allTickets.filter(t=>t.lane?.group==='problem').length;
 const activeCount=allTickets.filter(t=>t.lane?.group==='active'||t.lane?.group==='review').length;
 const pct=allTickets.length?Math.round((doneCount/allTickets.length)*100):0;
 const flagsHtml=(problemCount?`<em class="epic-flag problem">${problemCount} 需处理</em>`:'')+(activeCount?`<em class="epic-flag">${activeCount} 进行中</em>`:'');
 const mmfsHtml=g.mmfs.map(m=>{
  const mmfSelected=selected&&m.map===selectedMap;
  return `<button class="board-mmf-entry${mmfSelected?' selected':''}" data-board="side-mmf" data-group="${esc(g.id)}" data-map="${esc(m.map)}" aria-current="${mmfSelected}" title="${esc(m.title)} · ${esc(stageLabel(m.stage))}"><span class="board-mmf-title">${esc(m.title)}</span><small>${esc(stageLabel(m.stage))}</small></button>`;
 }).join('');
 return `<div class="board-epic${expanded?' is-expanded':''}" data-epic="${esc(g.id)}" data-expanded="${expanded}"><div class="board-epic-row"><button class="epic-toggle" data-board="toggle-epic" data-group="${esc(g.id)}" aria-expanded="${expanded}" aria-label="${esc(expanded?copy.收起Epic:copy.展开Epic)} ${esc(g.label)}">${expanded?'▾':'▸'}</button><button class="board-entry${selected?' selected':''}" data-board="group" data-group="${esc(g.id)}" aria-current="${selected}" title="${esc(g.label)}"><span class="epic-top"><span class="board-entry-label">${esc(g.label)}</span><small>${g.mmfs.length} MMF${allTickets.length?` · ${allTickets.length} 票`:''}</small></span><span class="epic-bar"><i style="width:${pct}%"></i></span>${flagsHtml?`<span class="epic-flags">${flagsHtml}</span>`:''}</button></div><div class="epic-mmfs"${expanded?'':' hidden'}>${mmfsHtml}</div></div>`;
}

function renderInboxSection(inbox:{group:GraphGroup;items:InboxItem[]},selectedGroupId:string|undefined,selectedMap:string|undefined,inboxOpen:boolean):string {
 if(!inbox.items.length)return '';
 const inboxSelected=selectedGroupId===INBOX_GROUP_ID;
 const expanded=inboxOpen||inboxSelected;
 const itemsHtml=inbox.items.map(item=>{
  const executing=inboxItemExecuting(item);
  const status=mmfStatusText(item);
  const selected=inboxSelected&&selectedMap===item.map;
  const link=item.links.linear?`<a class="inbox-link" href="${esc(item.links.linear)}" target="_blank" rel="noreferrer">${esc(issueLinkLabel(item.links.linear))} ↗</a>`:'';
  return `<li class="inbox-item${executing?' is-executing':''}${selected?' selected':''}" data-inbox-map="${esc(item.map)}"><button class="inbox-select" data-board="side-mmf" data-group="${INBOX_GROUP_ID}" data-map="${esc(item.map)}" aria-current="${selected}" title="${esc(item.title)} · ${esc(item.repo)}"><span class="inbox-title">${esc(item.title)}</span><span class="inbox-repo">${esc(item.repo)}</span><span class="inbox-meta"><span class="inbox-attribution">${copy.待归属}</span><span class="inbox-stage">${esc(stageLabel(item.stage))}</span><span class="inbox-status${executing?' exec-label':''}">${executing?'<span class="exec-dot" aria-hidden="true"></span>':''}${esc(status)}</span></span></button>${link}</li>`;
 }).join('');
 return `<section class="board-repo board-inbox" data-board-inbox="true" data-expanded="${expanded}" aria-label="${copy.Inbox}"><div class="board-inbox-head"><button class="inbox-toggle${inboxSelected?' selected':''}" data-board="toggle-inbox" aria-expanded="${expanded}"><span class="chev" aria-hidden="true">${expanded?'▾':'▸'}</span><span class="inbox-head-label">${copy.Inbox} · ${copy.待归属}</span><small class="muted">${inbox.items.length}</small></button></div><ul class="inbox-list"${expanded?'':' hidden'}>${itemsHtml}</ul></section>`;
}

function renderErrorsSection(errors:BoardError[]):string {
 if(!errors.length)return '';
 const itemsHtml=errors.map(err=>
  `<li class="board-error-item" data-error-map="${esc(err.map)}"><span class="board-error-map mono">${esc(err.map)}</span><span class="board-error-reason">${esc(err.reason)}</span></li>`
 ).join('');
 return `<section class="board-repo board-errors" data-board-errors="true" aria-label="${copy.读取失败}"><div class="board-errors-head"><h3>${copy.读取失败}</h3><small>${errors.length}</small></div><ul class="board-error-list">${itemsHtml}</ul></section>`;
}

export interface LeftColumnParams {
 groups:BoardGroups;
 selectedGroupId?:string;
 selectedMap?:string;
 open:boolean;
 endedOpen:boolean;
 inboxOpen?:boolean;
 expandedEpics:ReadonlyMap<string,boolean>;
 generatedAt?:string;
}

function formatSnapshotTime(iso?:string):string {
 if(!iso)return '';
 return iso.replace('T',' ').replace(/\.\d+/, '').replace(/([+-]\d\d:\d\d|Z)$/,'');
}

export function renderLeftColumn(params:LeftColumnParams):string {
 const {groups,selectedGroupId,selectedMap,open,endedOpen,inboxOpen=false,expandedEpics,generatedAt}=params;
 const activeCount=groups.repos.reduce((sum,r)=>sum+r.epics.length,0);
 const activeHtml=groups.repos.map(r=>
  `<section class="board-repo" data-repo="${esc(r.name)}"><div class="board-repo-head"><h3>${esc(r.name)}</h3><small>${r.epics.length}</small></div>${r.epics.map(e=>renderEpicItem(e,selectedGroupId,selectedMap,expandedEpics)).join('')}</section>`
 ).join('');
 const endedExpanded=endedOpen||groups.ended.some(e=>e.group.id===selectedGroupId);
 const endedHtml=groups.ended.length
  ?`<details class="board-repo board-ended" data-board-ended="true"${endedExpanded?' open':''}><summary>${copy.已结束} ${groups.ended.length}</summary>${groups.ended.map(e=>renderEpicItem(e,selectedGroupId,selectedMap,expandedEpics)).join('')}</details>`
  :'';
 const inboxHtml=renderInboxSection(groups.inbox,selectedGroupId,selectedMap,inboxOpen);
 const errorsHtml=renderErrorsSection(groups.errors);
 const snapTime=formatSnapshotTime(generatedAt);
 const footHtml=`<footer class="board-col-foot muted small">${snapTime?`快照 ${esc(snapTime)} · `:''}回到前台自动重读</footer>`;
 return `<nav class="board-col board-left" id="board-left" aria-label="Epic" ${open?'':'hidden'}><div class="board-col-head"><h2>Epic <span class="muted small">进行中 ${activeCount}</span></h2><button class="quiet col-close" data-board="left">${copy.收起左栏}</button></div><div class="board-scroll board-left-body">${inboxHtml}${activeHtml}${endedHtml}${errorsHtml}</div>${footHtml}</nav>`;
}
