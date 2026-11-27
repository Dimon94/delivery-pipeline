import type {Halt,Lane,Mmf,MmfCandidate,MmfEdge,Stage,Ticket} from './board';
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
 candidate?:MmfCandidate;
 mmfEdges?:MmfEdge[];
 missingEdges?:MmfEdge[];
 inbox:boolean;
 inboxRepo?:string;
 inboxSpec?:boolean;
 hasLinear?:boolean;
 open:boolean;
}

function kvRow(k:string,v:string,mono=false):string {
 return `<dt>${k}</dt><dd${mono?' class="mono"':''}>${v}</dd>`;
}

function renderLinkRow(url:string|null,label:string):string {
 if(!url)return `<span class="detail-lnk off">${esc(label)} · ${copy.尚无}</span>`;
 if(/^https?:\/\//i.test(url)){
  return `<a class="detail-lnk" href="${esc(url)}" target="_blank" rel="noreferrer">${esc(label)} ↗</a>`;
 }
 return `<button type="button" class="detail-lnk" data-board="open-link" data-href="${esc(url)}">${esc(label)} ↗</button>`;
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

function headerTitle(epicKey:string|undefined,mmf:Mmf|undefined,ticket:Ticket|undefined,showSteps:boolean,candidate?:MmfCandidate):string {
 if(candidate)return epicKey?`${epicKey} · ${candidate.mmf_id}`:candidate.mmf_id;
 if(!mmf)return '';
 const seg=mmfPathSegment(mmf,epicKey);
 if(ticket)return epicKey?`${epicKey} · ${seg} · ${ticket.id}`:`${seg} · ${ticket.id}`;
 return epicKey?`${epicKey} · ${seg}`:(showSteps?'MMF':copy.条目);
}

function renderCandidateBody(candidate:MmfCandidate,mmfEdges?:MmfEdge[]):string {
 const sourceText=candidate.source==='epic_table'?'Epic 正文':'Linear 子项';
 const coreHtml=[
  kvRow('标识',`<span class="detail-candidate-id mono">${esc(candidate.mmf_id)}</span>`),
  kvRow(copy.状态,'未开工'),
  kvRow('来源',`<span class="detail-candidate-source">${esc(sourceText)}</span>`),
  ...(candidate.spec?[kvRow('Spec',`<span class="detail-candidate-spec">${esc(candidate.spec.key)} · ${esc(candidate.spec.status)}</span>`)]:[]),
 ].join('');
 const relatedEdges=candidate.mmf_id!=='Unknown'
  ?(mmfEdges??[]).filter(e=>e.to===candidate.mmf_id||e.from===candidate.mmf_id)
  :[];
 const depsBody=relatedEdges.length
  ?`<ul class="cand-dep-list">${relatedEdges.map(e=>`<li class="cand-dep-item"><span class="mono">${esc(e.from)} ──${esc(e.kind)}──▶ ${esc(e.to)}</span><span class="cand-dep-text"> · ${esc(e.text)}</span></li>`).join('')}</ul>`
  :`<span class="muted small">${copy.无}</span>`;
 const depsHtml=`<section class="detail-cand-deps" aria-label="${copy.依赖}"><div class="muted small">${copy.依赖}</div>${depsBody}</section>`;
 const specLink=candidate.spec&&candidate.spec.url
  ?`<div class="detail-links">${renderLinkRow(candidate.spec.url,`${candidate.spec.key} · ${copy.LinearIssue}`)}</div>`
  :`<div class="detail-links">${renderLinkRow(null,'Spec')}</div>`;
 const noactionHtml=`<p class="detail-cand-noaction muted small">${copy.候选只读说明}</p>`;
 return `<h3 class="detail-title">${esc(candidate.title)}</h3><dl class="detail-core">${coreHtml}</dl>${depsHtml}${specLink}${noactionHtml}`;
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

function renderDetailBody(mmf:Mmf|undefined,ticket:Ticket|undefined,inbox:boolean,inboxRepo:string|undefined,showSteps:boolean,hasLinear?:boolean):string {
 if(!mmf)return `<p class="board-state detail-empty">${copy.选择一张票查看详情}</p>`;
 if(ticket){
  const lane=ticket.lane;
  const status=ticketStatusText(ticket);
  const statusHtml=ticket.executing?`<b class="exec-label">${esc(status)}</b>`:esc(status);
  const showLinear=Boolean(hasLinear)||Boolean(ticket.linear_issue)||mmf.tickets.some(t=>Boolean(t.linear_issue));
  const displayTitle=ticket.linear_issue?.title||ticket.title;
  const linearStatus=ticket.linear_issue?.status??'Unknown';
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
   ...(showLinear?[kvRow('Linear',`<span class="detail-linear-status">${esc(linearStatus)}</span>`)]:[]),
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
  return `<h3 class="detail-title">${esc(displayTitle)}</h3>${stepsHtml}${alertCard}<dl class="detail-core">${coreHtml}</dl><details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraHtml}</dl></details>${renderRelSection(copy.上游,mmf,ups)}${renderRelSection(copy.下游,mmf,downs)}<div class="detail-links">${linksHtml}</div>`;
 }
 const inboxSub=inbox?`<p class="detail-sub">${inboxRepo?`${esc(inboxRepo)} · `:''}${copy.待归属}</p>`:'';
 const attributionSub=!inbox&&mmf.attribution_source==='linear'?'<p class="detail-sub detail-attribution">归属来自 Linear</p>':'';
 const directLane=mmf.direct_lanes.find(l=>l.state==='running'&&l.live==='working')
  ??mmf.direct_lanes.find(l=>l.group==='problem')
  ??mmf.direct_lanes.find(l=>l.group==='review')
  ??mmf.direct_lanes.find(l=>l.group==='active')
  ??mmf.direct_lanes[0]
  ??null;
 const status=mmfStatusText(mmf);
 const statusHtml=mmf.executing?`<b class="exec-label">${esc(status)}</b>`:esc(status);
 const stepsHtml=showSteps?renderStageBar(mmf.stage,{bad:Boolean(mmf.halt)||directLane?.group==='problem'}):'';
 const blockedDirect=directLane?.blocked_reason?directLane:mmf.direct_lanes.find(l=>Boolean(l.blocked_reason))??null;
 const alertCard=mmf.halt
  ?renderHaltCard(mmf.halt)
  :blockedDirect?.blocked_reason
   ?`<div class="detail-halt soft"><b>${blockedDirect.state==='running'&&blockedDirect.live!=='working'?copy.现场:copy.阻塞原因}</b><p>${esc(blockedDirect.blocked_reason)}</p></div>`
   :'';
 const directLanesText=mmf.direct_lanes.length
  ?mmf.direct_lanes.map(l=>`${esc(l.role)} · ${esc(liveStatusLabel(l.live))}`).join('<br>')
  :copy.无;
 const mmfUpdated=directLane?.updated_at??mmf.updated_at;
 const coreHtml=[
  kvRow(copy.状态,`${statusHtml} <span class="muted small"${mmfUpdated?` title="${esc(mmfUpdated)}"`:''}>· ${esc(formatUpdatedAt(mmfUpdated))}</span>`),
  kvRow('Agent',esc(formatAgentModel(directLane))),
  kvRow(copy.分支,esc(directLane?.branch?.trim()?directLane.branch:'Unknown'),true),
  kvRow(copy.直属执行,directLanesText),
 ].join('');
 const extraHtml=[
  kvRow('lane',esc(directLane?.lane_id?.trim()?directLane.lane_id:'Unknown'),true),
  kvRow('registry',esc(directLane?directLane.state:copy.无lane),true),
  kvRow(copy.工作树,esc(directLane?.worktree?.trim()?directLane.worktree:'Unknown'),true),
  ...(inbox&&inboxRepo?[kvRow(copy.来源仓库,esc(inboxRepo))]:[]),
  kvRow('map',esc(mmf.map),true),
  kvRow(copy.更新时间,esc(mmfUpdated??'Unknown')),
 ].join('');
 const linksHtml=[
  renderLinkRow(mmf.links.plan_review,copy.PlanReview页),
  renderLinkRow(mmf.links.merge_review,copy.MergeReview页),
  renderLinkRow(mmf.links.linear,copy.LinearIssue),
 ].join('');
 return `<h3 class="detail-title">${esc(mmf.title)}</h3>${inboxSub}${attributionSub}${stepsHtml}${alertCard}<dl class="detail-core">${coreHtml}</dl><details class="detail-more"><summary>${copy.更多现场信息}</summary><dl class="detail-extra">${extraHtml}</dl></details><div class="detail-links">${linksHtml}</div>`;
}

function renderMissingEdges(edges?:MmfEdge[]):string {
 if(!edges?.length)return '';
 const items=edges.map(e=>
  `<li class="missing-edge-item" data-missing-edge="${esc(e.from)}>${esc(e.to)}"><div class="missing-edge-head"><span class="missing-edge-pair mono">${esc(e.from)} → ${esc(e.to)}</span><span class="missing-edge-kind">${esc(e.kind)}</span></div><p class="missing-edge-text">${esc(e.text)}</p></li>`
 ).join('');
 return `<section class="detail-missing-edges" aria-label="未画出的跨 MMF 依赖"><div class="muted small">未画出的跨 MMF 依赖</div><ul class="missing-edge-list">${items}</ul></section>`;
}

export function renderRightColumn(params:RightColumnParams):string {
 const {epicKey,mmf,ticket,candidate,mmfEdges,missingEdges,inbox,inboxRepo,inboxSpec,hasLinear,open}=params;
 const showSteps=!inbox||inboxSpec===true;
 const groupCls=ticket?(ticket.lane?ticket.lane.group:'pending'):undefined;
 const pillHtml=candidate
  ?'<span class="muted small">未开工</span>'
  :ticket&&groupCls
   ?`<span class="board-pill g-${esc(groupCls)}">${esc(laneGroupNames[groupCls]??copy.未派发)}</span>`
   :mmf&&epicKey?'<span class="muted small">MMF</span>':'';
 const missingHtml=!ticket&&!inbox?renderMissingEdges(missingEdges):'';
 const bodyHtml=(candidate
  ?renderCandidateBody(candidate,mmfEdges)
  :renderDetailBody(mmf,ticket,inbox,inboxRepo,showSteps,hasLinear))+missingHtml;
 return `<aside class="board-col board-right" id="board-right" aria-label="${copy.选择一张票查看详情}" ${open?'':'hidden'}><div class="board-col-head"><h2>${esc(headerTitle(epicKey,mmf,ticket,showSteps,candidate))}</h2><span class="board-head-acts">${pillHtml}<button class="quiet col-close" data-board="right" title="${copy.收起右栏}" aria-label="${copy.收起右栏}">${copy.收起Epic}</button></span></div><div class="board-scroll detail-body">${bodyHtml}</div></aside>`;
}
