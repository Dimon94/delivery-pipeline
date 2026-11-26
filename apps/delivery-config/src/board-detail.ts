import type {Mmf,Stage,Ticket} from './board';
import {STAGE_ORDER,copy,liveStatusLabel,mmfStatusText,stageLabel,ticketStatusText} from './copy';

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function renderStageBar(stage:Stage|'Unknown'):string {
 const idx=STAGE_ORDER.indexOf(stage as Stage);
 const steps=STAGE_ORDER.map((s,i)=>{
  const cls=idx<0?'unknown':i<idx?'done':i===idx?'current':'pending';
  return `<li class="stage-step ${cls}" data-stage="${s}"${i===idx?' aria-current="step"':''}><span>${esc(stageLabel(s))}</span></li>`;
 }).join('');
 const unknownNote=idx<0?`<p class="stage-unknown">${esc(stage)}</p>`:'';
 return `<div class="stage-bar-wrap"><ol class="stage-bar" aria-label="${copy.交付阶段}">${steps}</ol>${unknownNote}</div>`;
}

export interface RightColumnParams {
 mmf?:Mmf;
 ticket?:Ticket;
 inbox:boolean;
 inboxRepo?:string;
 open:boolean;
}

function row(k:string,v:string):string {
 return `<div class="detail-row"><dt>${k}</dt><dd>${v}</dd></div>`;
}

function link(url:string|null,label:string):string {
 return url?`<a href="${esc(url)}" target="_blank" rel="noreferrer">${label}</a>`:'';
}

function renderDetailBody(mmf:Mmf|undefined,ticket:Ticket|undefined,inbox:boolean,inboxRepo?:string):string {
 if(!mmf)return `<p class="board-state">${copy.选择一张票查看详情}</p>`;
 const inboxSuffix=inbox?`${inboxRepo?` · ${esc(inboxRepo)}`:''} · ${copy.待归属}`:'';
 if(ticket){
  const lane=ticket.lane;
  const status=ticketStatusText(ticket);
  const statusHtml=ticket.executing?`<span class="exec-label">${esc(status)}</span>`:esc(status);
  const linksHtml=link(ticket.linear,copy.打开Linear);
  const extraRows=lane
   ?[
    row(copy.编号,esc(lane.lane_id)),
    row(copy.角色,esc(lane.role)),
    row('Agent',esc(lane.agent)),
    row(copy.模型,esc(lane.model)),
    row(copy.分支,esc(lane.branch??copy.无)),
    row(copy.工作目录,esc(lane.worktree??copy.无)),
    row(copy.实时状态,esc(liveStatusLabel(lane.live))),
    row(copy.更新时间,esc(lane.updated_at??copy.无)),
   ].join('')
   :row(copy.执行状态,copy.未派发);
  return `<h3 class="detail-title">${esc(ticket.title)}</h3><p class="detail-sub">${esc(mmf.title)}${inboxSuffix}</p>${renderStageBar(ticket.stage)}<dl class="detail-core">${row(copy.交付阶段,esc(stageLabel(ticket.stage)))}${row(copy.执行状态,statusHtml)}${lane?.blocked_reason?row(copy.阻塞原因,esc(lane.blocked_reason)):''}${row(copy.依赖,ticket.deps.length?ticket.deps.map(esc).join('、'):copy.无)}</dl>${linksHtml?`<div class="detail-links">${linksHtml}</div>`:''}<details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraRows}</dl></details>`;
 }
 const status=mmfStatusText(mmf);
 const statusHtml=mmf.executing?`<span class="exec-label">${esc(status)}</span>`:esc(status);
 const linksHtml=[
  link(mmf.links.plan_review,copy.打开计划审查页),
  link(mmf.links.merge_review,copy.打开合并审查页),
  link(mmf.links.linear,copy.打开Linear),
 ].filter(Boolean).join('');
 const directLanesText=mmf.direct_lanes.length
  ?mmf.direct_lanes.map(l=>`${esc(l.lane_id)}（${esc(l.role)} · ${esc(l.state)} · ${esc(liveStatusLabel(l.live))}）`).join('<br>')
  :copy.无;
 const extraRows=[
  ...(inbox&&inboxRepo?[row(copy.来源仓库,esc(inboxRepo))]:[]),
  row(copy.更新时间,esc(mmf.updated_at??copy.无)),
  row(copy.直属执行,directLanesText),
 ].join('');
 return `<h3 class="detail-title">${esc(mmf.title)}</h3><p class="detail-sub">${esc(mmf.map)}${inboxSuffix}</p>${renderStageBar(mmf.stage)}<dl class="detail-core">${row(copy.交付阶段,esc(stageLabel(mmf.stage)))}${row(copy.执行状态,statusHtml)}${mmf.halt?row('Halt',`${esc(mmf.halt.label)}：${esc(mmf.halt.reason)}`):''}</dl>${linksHtml?`<div class="detail-links">${linksHtml}</div>`:''}<details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraRows}</dl></details>`;
}

export function renderRightColumn(params:RightColumnParams):string {
 const {mmf,ticket,inbox,inboxRepo,open}=params;
 return `<aside class="board-col board-right" id="board-right" aria-label="${copy.选择一张票查看详情}" ${open?'':'hidden'}><div class="board-col-head"><h2>${ticket?esc(ticket.id):mmf?'MMF':''}</h2><button class="quiet" data-board="right">${copy.收起右栏}</button></div>${renderDetailBody(mmf,ticket,inbox,inboxRepo)}</aside>`;
}
