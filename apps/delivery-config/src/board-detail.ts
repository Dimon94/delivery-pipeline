import type {Halt,Lane,Mmf,Stage,Ticket} from './board';
import {ticketMatchesHalt} from './board-graph';
import {STAGE_ORDER,copy,laneGroupNames,liveStatusLabel,mmfStatusText,stageLabel,ticketStatusText} from './copy';

const esc=(s:string)=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function renderStageBar(stage:Stage|'Unknown',options?:{bad?:boolean;waiting?:boolean;note?:string}):string {
 const idx=STAGE_ORDER.indexOf(stage as Stage);
 const steps=STAGE_ORDER.map((s,i)=>{
  const baseCls=idx<0?'unknown':i<idx?'done':i===idx?'current':'pending';
  const extra=i===idx?(options?.bad?' bad':options?.waiting?' wait':''):'';
  const noteHtml=i===idx&&options?.note?`<em class="step-note">${esc(options.note)}</em>`:'';
  return `<li class="stage-step ${baseCls}${extra}" data-stage="${s}"${i===idx?' aria-current="step"':''}><span class="step-dot" aria-hidden="true"></span><span class="step-label">${esc(stageLabel(s))}</span>${noteHtml}</li>`;
 }).join('');
 const unknownNote=idx<0?`<p class="stage-unknown">${esc(stage)}</p>`:'';
 return `<div class="stage-bar-wrap"><ol class="stage-bar" aria-label="${copy.交付阶段}">${steps}</ol>${unknownNote}</div>`;
}

export interface RightColumnParams {
 epicKey?:string;
 mmf?:Mmf;
 ticket?:Ticket;
 inbox:boolean;
 inboxRepo?:string;
 open:boolean;
}

function kvRow(k:string,v:string,mono=false):string {
 return `<dt>${k}</dt><dd${mono?' class="mono"':''}>${v}</dd>`;
}

function renderLinkRow(url:string|null,label:string):string {
 return url
  ?`<a class="detail-lnk" href="${esc(url)}" target="_blank" rel="noreferrer">${esc(label)} ↗</a>`
  :`<span class="detail-lnk off">${esc(label)} · ${copy.尚无}</span>`;
}

function renderHaltCard(halt:Halt):string {
 const optionsHtml=halt.options.length?`<div class="muted small">${copy.可选}${halt.options.map(esc).join(' / ')}</div>`:'';
 return `<div class="detail-halt"><b>Halt · ${esc(halt.label)}</b><p>${esc(halt.reason)}</p>${optionsHtml}<div class="muted small">${copy.回复Halt说明}</div></div>`;
}

function formatUpdatedAt(iso:string|null|undefined):string {
 if(!iso||!iso.trim())return 'Unknown';
 const m=iso.trim().match(/^\d{4}-(\d{2}-\d{2})[T ](\d{2}:\d{2})/);
 return m?`${m[1]} ${m[2]}`:iso.trim();
}

function formatAgentModel(lane:Lane|null):string {
 if(!lane)return 'Unknown';
 const parts=[lane.agent,lane.model].map(v=>v?.trim()).filter((v):v is string=>Boolean(v));
 if(!parts.length||parts.every(v=>v==='Unknown'))return 'Unknown';
 return parts.join(' · ');
}

function mmfPathSegment(mmf:Mmf,epicKey?:string):string {
 if(epicKey){
  const prefix=`${epicKey.toLowerCase()}-`;
  if(mmf.map.toLowerCase().startsWith(prefix)){
   const rest=mmf.map.slice(prefix.length);
   if(/^m\d+$/i.test(rest))return rest.toUpperCase();
   if(rest)return rest;
  }
 }
 return mmf.map;
}

function headerTitle(epicKey:string|undefined,mmf:Mmf|undefined,ticket:Ticket|undefined):string {
 if(!mmf)return '';
 const seg=mmfPathSegment(mmf,epicKey);
 if(ticket)return epicKey?`${epicKey} · ${seg} · ${ticket.id}`:`${seg} · ${ticket.id}`;
 return epicKey?`${epicKey} · ${seg}`:'MMF';
}

function renderRelSection(title:string,mmf:Mmf,tickets:Ticket[]):string {
 const body=tickets.length
  ?tickets.map(t=>{
    const groupCls=t.lane?esc(t.lane.group):'pending';
    return `<button type="button" class="detail-chip g-${groupCls}" data-board="ticket" data-map="${esc(mmf.map)}" data-ticket="${esc(t.id)}">${esc(t.id)} ${esc(t.title)}</button>`;
   }).join('')
  :`<span class="muted small">${copy.无}</span>`;
 return `<div class="detail-rel"><div class="muted small">${esc(title)}</div>${body}</div>`;
}

function renderDetailBody(mmf:Mmf|undefined,ticket:Ticket|undefined,inbox:boolean,inboxRepo:string|undefined,showSteps:boolean):string {
 if(!mmf)return `<p class="board-state detail-empty">${copy.选择一张票查看详情}</p>`;
 if(ticket){
  const lane=ticket.lane;
  const status=ticketStatusText(ticket);
  const statusHtml=ticket.executing?`<b class="exec-label">${esc(status)}</b>`:esc(status);
  const bad=lane?.group==='problem';
  const waiting=!lane;
  const note=lane?lane.state:copy.未派发;
  const stepsHtml=showSteps?renderStageBar(ticket.stage,{bad,waiting,note}):'';
  const alertCard=mmf.halt&&ticketMatchesHalt(mmf,ticket)
   ?renderHaltCard(mmf.halt)
   :lane?.blocked_reason
    ?`<div class="detail-halt soft"><b>${lane.state==='running'&&lane.live!=='working'?copy.现场:copy.阻塞原因}</b><p>${esc(lane.blocked_reason)}</p></div>`
    :'';
  const updatedText=formatUpdatedAt(lane?.updated_at);
  const updatedTitle=lane?.updated_at?` title="${esc(lane.updated_at)}"`:'';
  const agentText=formatAgentModel(lane);
  const branchText=lane?.branch?.trim()?lane.branch:'Unknown';
  const coreHtml=[
   kvRow(copy.状态,`${statusHtml} <span class="muted small"${updatedTitle}>· ${esc(updatedText)}</span>`),
   kvRow('Agent',esc(agentText)),
   kvRow(copy.分支,esc(branchText),true),
  ].join('');
  const extraHtml=[
   kvRow('lane',esc(lane?.lane_id?.trim()?lane.lane_id:'Unknown'),true),
   kvRow('registry',esc(lane?lane.state:copy.无lane),true),
   kvRow(copy.工作树,esc(lane?.worktree?.trim()?lane.worktree:'Unknown'),true),
  ].join('');
  const ups=ticket.deps.map(d=>mmf.tickets.find(t=>t.id===d)).filter((t):t is Ticket=>Boolean(t));
  const downs=mmf.tickets.filter(t=>t.deps.includes(ticket.id));
  const linksHtml=[
   renderLinkRow(mmf.links.plan_review,copy.PlanReview页),
   renderLinkRow(mmf.links.merge_review,copy.MergeReview页),
   renderLinkRow(ticket.linear,copy.LinearIssue),
  ].join('');
  return `<h3 class="detail-title">${esc(ticket.title)}</h3>${stepsHtml}${alertCard}<dl class="detail-core">${coreHtml}</dl><details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraHtml}</dl></details>${renderRelSection(copy.上游,mmf,ups)}${renderRelSection(copy.下游,mmf,downs)}<div class="detail-links">${linksHtml}</div>`;
 }
 const inboxSub=inbox?`<p class="detail-sub">${inboxRepo?`${esc(inboxRepo)} · `:''}${copy.待归属}</p>`:'';
 const status=mmfStatusText(mmf);
 const statusHtml=mmf.executing?`<b class="exec-label">${esc(status)}</b>`:esc(status);
 const stepsHtml=showSteps?renderStageBar(mmf.stage,{bad:Boolean(mmf.halt)}):'';
 const haltCard=mmf.halt?renderHaltCard(mmf.halt):'';
 const directLanesText=mmf.direct_lanes.length
  ?mmf.direct_lanes.map(l=>`${esc(l.lane_id)}（${esc(l.role)} · ${esc(l.state)} · ${esc(liveStatusLabel(l.live))}）`).join('<br>')
  :copy.无;
 const coreHtml=[
  kvRow(copy.状态,`${statusHtml} <span class="muted small">· ${esc(formatUpdatedAt(mmf.updated_at))}</span>`),
  kvRow('map',esc(mmf.map),true),
  kvRow(copy.直属执行,directLanesText),
 ].join('');
 const extraHtml=[
  ...(inbox&&inboxRepo?[kvRow(copy.来源仓库,esc(inboxRepo))]:[]),
  kvRow('map',esc(mmf.map),true),
  kvRow(copy.更新时间,esc(mmf.updated_at??'Unknown')),
 ].join('');
 const linksHtml=[
  renderLinkRow(mmf.links.plan_review,copy.PlanReview页),
  renderLinkRow(mmf.links.merge_review,copy.MergeReview页),
  renderLinkRow(mmf.links.linear,copy.LinearIssue),
 ].join('');
 return `<h3 class="detail-title">${esc(mmf.title)}</h3>${inboxSub}${stepsHtml}${haltCard}<dl class="detail-core">${coreHtml}</dl><details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraHtml}</dl></details><div class="detail-links">${linksHtml}</div>`;
}

export function renderRightColumn(params:RightColumnParams):string {
 const {epicKey,mmf,ticket,inbox,inboxRepo,open}=params;
 const showSteps=true;
 const groupCls=ticket?(ticket.lane?ticket.lane.group:'pending'):undefined;
 const pillHtml=ticket&&groupCls
  ?`<span class="board-pill g-${esc(groupCls)}">${esc(laneGroupNames[groupCls]??copy.未派发)}</span>`
  :mmf&&epicKey?'<span class="muted small">MMF</span>':'';
 return `<aside class="board-col board-right" id="board-right" aria-label="${copy.选择一张票查看详情}" ${open?'':'hidden'}><div class="board-col-head"><h2>${esc(headerTitle(epicKey,mmf,ticket))}</h2><span class="board-head-acts">${pillHtml}<button class="quiet col-close" data-board="right">${copy.收起右栏}</button></span></div><div class="board-scroll detail-body">${renderDetailBody(mmf,ticket,inbox,inboxRepo,showSteps)}</div></aside>`;
}
