import {pickerView,moveActive} from './picker';
import {modelLabel,toolOffText,bannerText,diffVerdict,effortLabel,copy,pickerCount,pickerUnavailable,pickerEfforts,applyTargetText,applyRefusalText,applyTriggerLabel} from './copy';
import './style.css';
import {guide,shouldRereadOnFocus,type GuideInput} from './guide';

import {Draft,settleProbe,cell,paths,work,agentIds,type Cell,type ModelTriple,type Config,type Evidence,type ItemStatus} from './draft';
import {Editor,type Snapshot,type Outcome} from './editor';
import {instanceLabel,instanceTitle,isTestConfig,loadAppInfo,type AppInfo} from './appinfo';
let appInfo:AppInfo|undefined;
let appInfoLoaded=false; // 加载完成前标签留空，避免闪现“构建号未知”
let editor:Editor|undefined;
declare const mygo: {call<T>(name: string,...args:unknown[]): Promise<T>};
let draft:Draft|undefined;
let picker:{path:string;query:string;source?:string;active?:string}|undefined;

let applying:{from:string;selected:Set<string>}|undefined;
let probeCounter=0;
const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | undefined;
let message = copy.正在读取本机设置;
let help = false;
let diagnostic:unknown;
let diagnosing=false;
let reading = false;
let guideInput:GuideInput|undefined;
// 队列展开状态是纯 UI 状态，不进 Draft；重新渲染后保持。
const openQueues=new Set<string>();
const loadedMessage=bannerText({kind:'loaded'});
// 保存成功确认独立于 message：核对期间与核对完成后都保留，直到下一次编辑或读取。
let saved='';
const workNames: Record<string,string> = {planning:copy.规划,design:copy.设计,frontend:copy.前端开发,backend:copy.后端开发,testing:copy.测试,coordinator:copy.协调,research:copy.调研,prototype:copy.原型,integration:copy.集成,assistance:copy.协助, 'second-opinion':copy.第二意见};

const escape = (s: string) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const workHints: Record<string,string> = {planning:copy.拆需求定方案,design:copy.界面与交互,frontend:copy.写页面代码,backend:copy.写服务端代码,testing:copy.写测试并验证};
const agents: Record<string,string> = {pi:'Pi',codex:'Codex CLI',claude:'Claude Code'};
function fields(c: Cell, path?:string) {
 if(!path)return `<div class="fields"><span class="pill">${agents[c.agent] || copy.已配置工具}</span><span class="pill">${escape(modelLabel(c.model))}</span><span class="pill">${effortLabel(c.effort)}</span></div>`;
 const evidence=draft?.evidence;
 const levels=draft?.options(c) || [];
 function select(field:keyof ModelTriple,values:string[],label:(v:string)=>string,all:string[]=[]) {
  const current=c[field]; const entries=[...new Set([...(current?[current]:[]),...all,...values])];
  return `<select class="pill" aria-label="${escape(pathLabel(path!))} · ${{agent:copy.运行工具,model:copy.模型,effort:copy.思考程度}[field]}" data-path="${path}" data-field="${field}"><option value="" disabled ${!current?'selected':''}>${copy.请选择}</option>${entries.map(v=>`<option title="${escape(field==='agent'?(toolOffText(v,choices.find(a=>a.agent===v)?.reason).title||''):'')}" value="${escape(v)}" ${v===current?'selected':''} ${!values.includes(v)?'disabled':''}>${escape(label(v))}</option>`).join('')}</select>`;
 }
 const choices=draft?.agentChoices()||[];
 // 已选中却不可用的工具保持选中并标“工具不可用”；其余不可用工具写来源给的原因。
 const agentLabel=(v:string)=>{const ch=choices.find(a=>a.agent===v);if(!ch?.reason)return agents[v]!;return agents[v]!+' · '+toolOffText(v,ch.reason,{evidence,selected:v===c.agent}).text;};
 const controls={agent:select('agent',choices.filter(a=>a.enabled).map(a=>a.agent),agentLabel,agentIds),model:`<button class="pill" data-path="${path}" data-field="model" aria-label="${escape(pathLabel(path))} · ${copy.模型}" aria-expanded="false" aria-haspopup="listbox" aria-controls="picker-results">${escape(modelLabel(c.model))}</button>`,effort:select('effort',levels,effortLabel)};
 return `<div class="fields">${(['agent','model','effort'] as const).map(field=>controls[field]).join('')}</div>`;
}
// 行内状态只由 Draft 的项状态决定（R4/R5）：可用、核对中、未核实都不写字；其余每项一句原因加一个处理动作。
function note(path:string,c:Cell):{why:string;action:string;field:keyof ModelTriple}|undefined {
 const st=itemStatus(path);
 if(st?.kind==='incomplete')return {why:copy.还没选完整,action:copy.去选择,field:!c.agent?'agent':!c.model?'model':'effort'};
 if(st?.kind==='tool_off')return {why:`${agents[c.agent]||copy.这个运行工具} · ${toolOffText(c.agent,st.reason,{evidence:draft?.evidence,selected:true}).text}`,action:copy.换用其他工具,field:'agent'};
 if(st?.kind==='model_gone')return {why:copy.这个模型已不在可用清单里,action:copy.换一个模型,field:'model'};
 if(st?.kind==='effort_gone')return {why:copy.这个模型不支持当前思考程度,action:copy.换思考程度,field:'effort'};
}
const needsAction=(st?:ItemStatus)=>!!st&&st.kind!=='ok'&&st.kind!=='checking'&&st.kind!=='unverified';
const rowClass=(path:string)=>{const st=itemStatus(path);return st?.kind==='checking'?'checking':needsAction(st)?'flag':'';};
// R9：主选不可用时写明接替；只出现在主选行的提示里。
function takeoverText(path:string) {
 const t=draft?.status(path).takeover;
 if(!t)return '';
 if(t.kind==='fallback')return `${copy.主模型启动失败后会按顺序改用备用目前第一个可用的是备用} ${t.index+1}。`;
 if(t.kind==='none')return copy.没有可用备用新任务会启动失败;
 return `${copy.候选中} ${t.usable} ${copy.个可用}`;
}
// R10：队列折叠标签；k 为非可用项个数。
function queueChip(path:string) {
 const st=draft?.status(path);if(!st)return '';
 const k=st.queue.filter(needsAction).length,open=openQueues.has(path);
 return `<button class="qchip${k?' amber':''}" data-queue="${path}" aria-expanded="${open}">${open?'▾':'▸'} ${st.queueLabel} ${st.queue.length}${k?` · ${k} ${copy.项需处理}`:''}</button>`;
}
function foot(path:string,c:Cell,extra='') {
 const n=note(path,c);
 return n?`<p class="row-foot" title="${escape(itemStatus(path)?.kind==='tool_off'?(itemStatus(path) as Extract<ItemStatus,{kind:'tool_off'}>).reason:'')}">${escape(n.why.replace(/[。.]+$/,''))}。${escape(extra)}<button class="inline-action" data-focus="${path}" data-field="${n.field}">${n.action}</button></p>`:'';
}
function itemStatus(path:string):ItemStatus|undefined {
 if(!draft)return;
 const p=path.split('.'),isWork=p[0]==='work',offset=isWork?2:3;
 if(p[offset]===(isWork?'fallbacks':'candidates'))return draft.status(p.slice(0,offset).join('.')).queue[Number(p[offset+1])];
 return draft.status(path).primary;
}
function banner() {
 const check=draft?.check;
 if(check?.kind==='checking')return bannerText({kind:'checking'});
 if(check?.kind==='unreachable')return bannerText({kind:'unreachable',cause:check.cause==='gateway'?'gateway':'call'});
 // 全部可用时顶部安静：读取后的载入提示在已核对时不再显示（方案 A，用户故事 2）。
 if(check?.kind==='checked'&&message===loadedMessage)return '';
 return message;
}
function pathLabel(path:string) {if(path==='model_families')return copy.共享家族声明;const p=path.split('.');return p[0]==='work'?workNames[p[1]!]!+(p[2]==='fallbacks'?` · ${copy.备用} ${Number(p[3])+1}`:''): `${p[1]==='implementation'?copy.实施结果:copy.整体交付} · ${p[2]==='standards'?copy.代码规范:copy.需求符合度}${p[3]==='candidates'?` · ${copy.候选2} ${Number(p[4])+1}`:''}`;}
function summary(c:Cell) {return `${agents[c.agent] || copy.已配置工具} · ${modelLabel(c.model)} · ${effortLabel(c.effort) || copy.请选择思考程度}`;}
function ordered(c:Cell) {if(c.candidates)return summary(c)+`；${copy.候选}${c.candidates.length?c.candidates.map((v,i)=>`${i+1}. ${summary(v)}`).join(' → '):copy.空}`;return summary(c)+(c.fallbacks?`；${copy.备用2}${c.fallbacks.length?c.fallbacks.map((v,i)=>`${i+1}. ${summary(v)}`).join(' → '):copy.空}`:'');}
function changeSummary(config:Config,path:string) {
 if(path!=='model_families')return ordered(cell(config,path));
 return Object.entries(config.model_families||{}).flatMap(([agent,models])=>Object.entries(models).map(([model,d])=>`${agents[agent]} · ${modelLabel(model)}：${d.family}（${copy.用户声明}`)).join('；')||copy.未声明;
}
function candidateFields(config:Config,path:string) {
 if(!openQueues.has(path))return '';
 const items=cell(config,path).candidates||[];
 return `<div class="fallbacks">${items.map((c,i)=>`<div class="task-row ${rowClass(`${path}.candidates.${i}`)}"><span>${copy.候选2} ${i+1}</span>${fields(c,`${path}.candidates.${i}`)}<div class="fallback-actions"><button data-review="${path}" data-action="up" data-index="${i}" ${i===0?'disabled':''}>${copy.上移}</button><button data-review="${path}" data-action="down" data-index="${i}" ${i===items.length-1?'disabled':''}>${copy.下移}</button><button data-review="${path}" data-action="remove" data-index="${i}">${copy.删除}</button></div>${foot(`${path}.candidates.${i}`,c)}</div>`).join('')}<button class="add-queue" data-review="${path}" data-action="add" aria-label="${copy.添加候选} · ${pathLabel(path)}" ${draft?.canEdit().addToQueue?'':copy.title核对完成后才能新增}>＋ ${copy.添加候选}</button></div>`;
}
function familyFields() {
 if(!draft?.config.model_families)return '';
 return `<section class="card"><h2>${copy.共享家族声明}</h2><p>${copy.为不同工具中的同类模型填写相同家族名思考程度不影响分组此处由你填}</p>${draft.familyIdentities().map((c,i)=>`<label class="task-row">${escape(agents[c.agent]||c.agent)} · ${escape(modelLabel(c.model))}<small>${escape(c.model)}</small><input aria-label="${copy.共享家族} ${i+1}" data-family="${i}" value="${escape(draft!.config.model_families?.[c.agent]?.[c.model]?.family||'')}" placeholder="${copy.未声明}"></label>`).join('')}</section>`;
}
async function probe() {
 if(!draft)return;
 const owner=draft;const id=`desktop-${Date.now()}-${++probeCounter}`;
 owner.beginProbe(id);render();
 try {const result=await mygo.call<Evidence>('Host.ProbeCapabilities',id);if(draft===owner)settleProbe(owner,id,result);}
 catch {if(draft===owner)owner.failProbe(id);}
 if(draft===owner)render();
}
function guideCard() {
 if(!guideInput||!appInfoLoaded)return '';
 const g=guide(guideInput,appInfo);
 return `<section class="card guide-card" aria-label="${copy.配置处理引导}"><h2>${escape(g.title)}</h2><p class="guide-detail">${escape(g.detail)}</p><h3>${copy.影响}</h3><p>${escape(g.impact)}</p><h3>${copy.下一步}</h3><p>${escape(g.next)}</p>${g.instruction?`<label for="guide-instruction">${copy.给AI助手的指令}</label><textarea id="guide-instruction" readonly>${escape(g.instruction)}</textarea>`:''}<div class="guide-actions">${g.instruction?`<button class="primary" id="copy-guide">${copy.复制指令}</button>`:''}<button class="plain" id="guide-reload" ${reading?'disabled':''}>${copy.重新读取}</button>${g.instruction?'<span id="copy-status" role="status"></span>':''}</div></section>`;
}
function render() {
 const kind=editor?.state.kind;
 const locked=kind==='saving'||kind==='conflict'||kind==='uncertain'||kind==='preview';
 const reviewing=kind==='preview';
 const config = draft?.config || null;
 if(diagnosing){app.innerHTML=`<main class="frame"><h1>${copy.独立诊断}</h1><p>${copy.此页包含配置工具的机器结果不会修改配置}</p><pre>${escape(JSON.stringify(diagnostic??snapshot,null,2))}</pre><button id="close-diagnostic">${copy.返回设置}</button></main>`;document.querySelector('#close-diagnostic')!.addEventListener('click',()=>{diagnosing=false;render();});return;}

 app.innerHTML = `<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">${copy.设置模型设置}</div><div class="right"><button class="plain" id="help">${copy.使用说明}</button></div></header><main class="frame"><div class="page-title"><div><h1>${copy.模型设置}</h1><p>${copy.调整每种工作使用的AI核对差异后保存}</p></div>${appInfoLoaded?`<span class="instance${isTestConfig(appInfo)?' test-config':''}" title="${escape(instanceTitle(appInfo))}">${escape(instanceLabel(appInfo))}</span>`:''}</div>${help?`<aside class="help-panel"><h2>${copy.使用说明}</h2><p>${copy.每行是一种工作依次显示运行工具模型和思考程度}</p><p>${copy.点模型格搜索或按来源选择备用会在主模型启动失败时依次接替}</p><p>${copy.改好后点击查看差异确认后保存新任务会使用新设置指定预设的任务和正}</p><p>${copy.遇到问题先按页面提示处理也可点击重新核对或打开诊断把结果交给AI}</p></aside>`:''}${guideCard()}${(!guideInput||reading)&&banner()?`<div class="notice${draft?.check.kind==='checked'||draft?.check.kind==='checking'||reading||kind==='saving'?' calm':''}" role="status">${escape(banner())}</div>`:''}${saved?`<div class="notice success" role="status">${escape(saved)}</div>`:''}${draft&&draft.attention()?`<div class="notice attention" role="status">${draft.attention()} ${copy.项设置需要处理其余} ${paths.length-draft.attention()} ${copy.项可以正常使用}</div>`:''}${editor&&'retained' in editor.state&&editor.state.retained?`<aside class="notice"><h2>${copy.请人工核对后重新选择}</h2><p>${copy.当前页面以最新设置为起点上次修改仅供参考请逐项重新选择再查看差异}</p>${[...paths,'model_families'].map(p=>`<p>${escape(pathLabel(p))}：${copy.上次修改} ${escape(changeSummary((editor!.state as Extract<import('./editor').State,{kind:'draft'|'preview'}>).retained!.config,p))}；${copy.最新} ${escape(changeSummary(draft!.snapshot,p))}</p>`).join('')}</aside>`:''}${kind==='conflict'||kind==='uncertain'?`<aside class="notice"><h2>${kind==='conflict'?copy.设置已在别处更新:copy.保存结果待确认}</h2><p>${copy.修改还在请检查当前设置并人工核对不会自动重试或回滚}</p><button id="recover" ${reading?'disabled':''}>${kind==='conflict'?copy.读取最新设置并核对:copy.检查当前保存结果}</button></aside>`:''}${config?`<section class="work-section"><div class="section-label"><h2>${copy.工作模型}</h2><p>${copy.每种工作的当前设置}</p></div><div class="card"><div class="table-head"><span>${copy.工作}</span><div class="fields"><span>${copy.运行工具}</span><span>${copy.模型}</span><span>${copy.思考程度}</span></div></div>${work.map(name=>`<div class="task-row ${rowClass(`work.${name}`)}"><span class="task-label"><span>${workNames[name]}<small class="task-hint">${workHints[name]}</small>${queueChip(`work.${name}`)}${config.work[name]!.agent&&config.work[name]!.model&&config.work[name]!.effort?`<button class="plain apply-trigger" aria-label="${escape(applyTriggerLabel(workNames[name]!))}" aria-haspopup="dialog" aria-expanded="false" aria-controls="apply-targets" data-apply-from="work.${name}">${copy.复制到其他工作}</button>`:''}</span></span>${fields(config.work[name]!,`work.${name}`)}${foot(`work.${name}`,config.work[name]!,takeoverText(`work.${name}`))}</div>${!openQueues.has(`work.${name}`)?'':`<div class="fallbacks">${(config.work[name]!.fallbacks||[]).map((c,i)=>`<div class="task-row ${rowClass(`work.${name}.fallbacks.${i}`)}"><span>${copy.备用} ${i+1}</span>${fields(c,`work.${name}.fallbacks.${i}`)}<div class="fallback-actions"><button data-work="${name}" data-action="up" data-index="${i}" ${i===0?"disabled":""}>${copy.上移}</button><button data-work="${name}" data-action="down" data-index="${i}" ${i===(config.work[name]!.fallbacks!.length-1)?"disabled":""}>${copy.下移}</button><button data-work="${name}" data-action="remove" data-index="${i}">${copy.删除}</button></div>${foot(`work.${name}.fallbacks.${i}`,c)}</div>`).join("")}<button class="add-queue" data-work="${name}" data-action="add" aria-label="${copy.添加备用} · ${workNames[name]}" ${draft?.canEdit().addToQueue?'':copy.title核对完成后才能新增}>＋ ${copy.添加备用}</button></div>`}`).join('')}</div></section><section class="review-section"><div class="section-label"><h2>${copy.结果检查}</h2><p>${copy.分别检查代码写法和需求完成情况}</p></div><div class="card"><div class="table-head"><span>${copy.检查}</span><div class="fields"><span>${copy.运行工具}</span><span>${copy.模型}</span><span>${copy.思考程度}</span></div></div>${['implementation','whole-change'].map((scope,i)=>`<section class="review-stage"><h3>${i?copy.整体交付:copy.实施结果} · ${i?copy.合并前看整体:copy.每张票写完后}</h3>${['standards','spec'].map(axis=>{const path=`review.${scope}.${axis}`;return `<div class="task-row ${rowClass(path)}"><span class="task-label"><span>${axis==='standards'?copy.代码规范:copy.需求符合度}<small class="task-hint">${axis==='standards'?copy.写法是否合规:copy.是否做到Spec的要求}</small>${queueChip(path)}</span></span>${fields(config.review[scope]![axis]!,path)}${foot(path,config.review[scope]![axis]!,takeoverText(path))}</div>${candidateFields(config,path)}`;}).join('')}</section>`).join('')}</div></section>${familyFields()}<details class="card read-only"><summary>${copy.其他设置仅查看}</summary><div class="readonly-body"><p class="compact-note">${copy.由初始化助手维护}${Object.keys(config.modes).length} ${copy.组预设仅在任务明确指定时使用}</p><div class="readonly-grid">${Object.entries(config.work).filter(([key])=>!work.includes(key)).map(([key,cell])=>`<div class="readonly-item">${workNames[key] || copy.其他工作}<span>${escape(modelLabel(cell.model))}</span><small>${agents[cell.agent] || copy.已配置工具} · ${effortLabel(cell.effort)}</small></div>`).join('') || `<p class="compact-note">${copy.没有其他工作设置}</p>`}</div></div></details>`:''}<footer class="footer"><span class="footer-status">${config?`${draft!.changes().length} ${copy.项修改待确认}`:copy.请按页面提示完成设置}</span>${config?`<button class="plain" id="refresh" ${draft!.check.kind==='checking'?'disabled':''}>${copy.重新核对}</button><button class="plain" id="undo" ${!draft!.changes().length?'disabled':''}>${copy.撤销修改}</button><button class="primary" id="diff" ${!draft!.changes().length?'disabled':''}>${copy.查看差异}</button>`:''}<button class="plain" id="reload" ${reading?'disabled':''}>${copy.重新读取}</button><button class="text-button" id="diagnostic">${copy.打开诊断}</button></footer>${reviewing&&draft?`<section class="diff-panel" role="dialog" aria-label="${copy.查看差异}"><h2>${copy.核对修改}</h2>${draft.changes().map(p=>`<article><h3>${escape(pathLabel(p))}</h3><p>${copy.原来}${escape(changeSummary(draft!.snapshot,p))}</p><p>${copy.现在}${escape(changeSummary(draft!.config,p))}</p></article>`).join('')}<p>${diffVerdict(draft.valid())}。${copy.确认后保存保存期间不能继续修改}</p><button class="plain" id="back">${copy.返回继续修改}</button><button class="primary" id="save" ${draft.valid()?'':'disabled'}>${copy.确认保存设置}</button></section>`:''}</main>`;
 document.querySelector('#diagnostic')!.addEventListener('click',()=>{diagnosing=true;render();});
 document.querySelector('#help')!.addEventListener('click',()=>{help=!help;render();});
 document.querySelector('#copy-guide')?.addEventListener('click',async()=>{
 const text=document.querySelector<HTMLTextAreaElement>('#guide-instruction')!;
 const status=document.querySelector<HTMLElement>('#copy-status')!;
 try {await navigator.clipboard.writeText(text.value);status.textContent=copy.已复制粘贴给AI助手即可;}
 catch {text.focus();text.select();status.textContent=copy.已选中请按C复制;}
 });
 for(const id of ['reload','guide-reload'])document.querySelector('#'+id)?.addEventListener('click',reload);
 document.querySelector('#refresh')?.addEventListener('click',probe);
 document.querySelectorAll<HTMLButtonElement>('button[data-queue]').forEach(button=>button.addEventListener('click',()=>{
 const path=button.dataset.queue!;
 if(!openQueues.delete(path))openQueues.add(path);
 render();
 document.querySelector<HTMLButtonElement>(`button[data-queue="${path}"]`)?.focus();
 }));
 document.querySelectorAll<HTMLButtonElement>('button[data-focus]').forEach(button=>button.addEventListener('click',()=>{
 const target=document.querySelector<HTMLButtonElement|HTMLSelectElement>(`[data-path="${button.dataset.focus}"][data-field="${button.dataset.field}"]`);
 if(target&&!target.disabled){target.focus();if(target.tagName==='BUTTON')target.click();else try{(target as HTMLSelectElement).showPicker();}catch{}}
 }));
 document.querySelector('#undo')?.addEventListener('click',()=>{saved='';draft!.undo();editor?.back();message=copy.修改已撤销已恢复读取时的设置;render();});
 document.querySelector('#diff')?.addEventListener('click',()=>{editor?.preview();render();});
 document.querySelector('#back')?.addEventListener('click',()=>{editor?.back();render();});
 document.querySelector('#save')?.addEventListener('click',save);
 document.querySelector('#recover')?.addEventListener('click',recover);
 document.querySelectorAll<HTMLInputElement>('input[data-family]').forEach(input=>{
 input.disabled=!!locked||reading;
 input.addEventListener('change',()=>{saved='';const c=draft!.familyIdentities()[Number(input.dataset.family)]!;draft!.setFamilyDeclaration(c.agent,c.model,input.value);render();});
 });
 document.querySelectorAll<HTMLButtonElement>('button[data-review]').forEach(button=>{
 if(locked||reading||(button.dataset.action==='add'&&!draft?.canEdit().addToQueue)){button.disabled=true;return;}
 button.addEventListener('click',()=>{saved='';const path=button.dataset.review!,index=Number(button.dataset.index),action=button.dataset.action;
 draft!.editCandidates(path,action==='add'?{kind:'add',item:{agent:'',model:'',effort:''}}:action==='remove'?{kind:'remove',index}:{kind:'move',index,to:index+(action==='up'?-1:1)});render();});
 });
 document.querySelectorAll<HTMLButtonElement>('button[data-work]').forEach(button=>{
 if(locked||reading||(button.dataset.action==='add'&&!draft?.canEdit().addToQueue)){button.disabled=true;return;}
 button.addEventListener('click',()=>{saved='';const name=button.dataset.work!,index=Number(button.dataset.index),action=button.dataset.action;
 draft!.editFallbacks(name,action==='add'?{kind:'add',item:{agent:'',model:'',effort:''}}:action==='remove'?{kind:'remove',index}:{kind:'move',index,to:index+(action==='up'?-1:1)});render();});
 });
 document.querySelectorAll<HTMLButtonElement>('button[data-path][data-field="model"]').forEach(button=>{
 button.disabled=!!locked||reading;
 const open=()=>{closeApply();closePicker();picker={path:button.dataset.path!,query:''};renderPicker();};
  button.addEventListener('click',open);
  button.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}});
 });
 document.querySelectorAll<HTMLButtonElement>('button[data-apply-from]').forEach(button=>{
 button.disabled=!!locked||reading;
 button.addEventListener('click',()=>{
 closePicker();closeApply();
 const from=button.dataset.applyFrom!;
 const reason=draft!.check.kind!=='checked'?{kind:'not_checked' as const}:draft!.status(from).primary.kind!=='ok'?{kind:'source' as const,status:draft!.status(from).primary as Exclude<ItemStatus,{kind:'ok'}>}:undefined;
 if(reason){showApplyRefusal(from,reason);return;}
 applying={from,selected:new Set(draft!.applyTargets(from).filter(t=>!t.same).map(t=>t.path))};
 renderApply(true);
 });
 button.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();button.click();}});
 });
 renderApply();
 renderPicker();
 const checking=draft?.check.kind==='checking';
 if(locked||reading||!draft?.canEdit().select)document.querySelectorAll<HTMLSelectElement>('select').forEach(el=>el.disabled=true);
 if(locked||checking||reading){for(const id of ['refresh','undo','diff','reload']){const el=document.querySelector<HTMLButtonElement>('#'+id);if(el)el.disabled=true;}}
 document.querySelectorAll<HTMLSelectElement>('select[data-path]').forEach(select=>select.addEventListener('change',()=>{saved='';draft!.select(select.dataset.path!,select.dataset.field as keyof ModelTriple,select.value);render();}));
}
function showApplyRefusal(from:string,reason:import('./draft').ApplyRefusal) {
 document.querySelectorAll('[data-apply-status]').forEach(e=>e.remove());
 const status=document.createElement('p');status.dataset.applyStatus=from;status.className='row-foot';status.setAttribute('role','status');status.textContent=applyRefusalText(reason,draft?.check);
 document.querySelector(`button[data-apply-from="${from}"]`)!.closest('.task-row')!.append(status);
}
function closeApply() {
 const from=applying?.from;
 applying=undefined;document.querySelector('.apply-popup')?.remove();
 const button=document.querySelector<HTMLButtonElement>(`button[data-apply-from="${from}"]`);button?.setAttribute('aria-expanded','false');button?.focus();
}
function renderApply(focus=false) {
 const active=document.activeElement as HTMLElement|null;
 const focused=active?.closest('.apply-popup')?(active.dataset.applyTarget||active.id):undefined;
 document.querySelector('.apply-popup')?.remove();
 if(!applying||!draft)return;
 if(editor?.state.kind!=='draft'){closeApply();return;}
 const {from,selected}=applying,source=cell(draft.config,from);
 const summary=(c:ModelTriple)=>`${agents[c.agent]} · ${modelLabel(c.model)} · ${effortLabel(c.effort)}`;
 const popup=document.createElement('div');popup.className='popup apply-popup';popup.id='apply-targets';popup.setAttribute('role','dialog');popup.setAttribute('aria-label',copy.复制到其他工作);
 popup.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeApply();}});
 popup.innerHTML=`<div class="apply-targets">${draft.applyTargets(from).map(t=>`<label><input type="checkbox" data-apply-target="${t.path}" ${selected.has(t.path)?'checked':''}><span>${escape(applyTargetText({name:pathLabel(t.path),now:summary(cell(draft!.config,t.path)),next:summary(source),same:t.same}))}</span></label>`).join('')}</div><div class="apply-actions"><button id="cancel-apply">${copy.取消}</button><button class="primary" id="apply-primary" ${selected.size?'':'disabled'}>${copy.应用}</button></div>`;
 popup.addEventListener('click',e=>e.stopPropagation());
 popup.querySelectorAll<HTMLInputElement>('input').forEach(input=>input.addEventListener('change',()=>{
 if(input.checked)selected.add(input.dataset.applyTarget!);else selected.delete(input.dataset.applyTarget!);
 popup.querySelector<HTMLButtonElement>('#apply-primary')!.disabled=!selected.size;
 }));
 popup.querySelector('#cancel-apply')!.addEventListener('click',closeApply);
 popup.querySelector('#apply-primary')!.addEventListener('click',()=>{
 const result=draft!.applyPrimary(from,[...selected]);
 closeApply();
 if(result.kind==='applied'){saved='';render();document.querySelector<HTMLButtonElement>(`button[data-apply-from="${from}"]`)?.focus();}
 else showApplyRefusal(from,result.reason);
 });
 document.body.append(popup);
 const button=document.querySelector<HTMLElement>(`button[data-apply-from="${from}"]`)!;
 button.setAttribute('aria-expanded','true');
 positionPopup(popup,button);
 if(focus)popup.querySelector<HTMLInputElement>('input')?.focus();
 else if(focused)popup.querySelector<HTMLElement>(`[data-apply-target="${focused}"],#${focused.replaceAll('.','\\.')}`)?.focus();
}
function closePicker(update=false) {
 const path=picker?.path;picker=undefined;
 document.querySelector('.model-popup')?.remove();
 if(update)render();
 const button=document.querySelector<HTMLButtonElement>(`button[data-path="${path}"][data-field="model"]`);
 button?.setAttribute('aria-expanded','false');button?.focus();
}
function renderPicker() {
 if(editor&&editor.state.kind!=='draft'){closePicker();return;}
 if(!picker||!draft){document.querySelector('.model-popup')?.remove();return;}
 const {path,query,source}=picker,c=cell(draft.config,path);
 const button=document.querySelector<HTMLButtonElement>(`button[data-path="${path}"][data-field="model"]`);
 if(!button){closePicker();return;}
 const check=draft.check,evidence=draft.evidence;
 const unavailable=pickerUnavailable(check,c.agent,reading);
 const view=pickerView({models:evidence?.capabilities[c.agent]?.models||{},current:c.model,query,source,unavailable});
 const items=view.groups.flatMap(g=>g.items);
 if(!reading&&check.kind==='checked')picker.active=items.find(i=>i.id===picker!.active&&!i.disabled)?.id||(picker.active?undefined:items.find(i=>i.selected&&!i.disabled)?.id)||items.find(i=>!i.disabled)?.id;
 const search=(input:HTMLInputElement)=>{picker!.query=input.value;picker!.active=undefined;renderPicker();};
 let popup=document.querySelector<HTMLDivElement>('.model-popup');
 if(!popup){
  popup=document.createElement('div');popup.className='popup model-popup';
  popup.innerHTML=`<div class="picker-content"><label class="picker-search"><span>${copy.搜索模型}</span><input role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls="picker-results" aria-describedby="picker-shortcuts" aria-label="${copy.搜索模型}" placeholder="${copy.搜索模型示例}" value="${escape(query)}"></label><div class="picker-body"></div></div><div class="popup-note"><div id="picker-shortcuts">${copy.来源切换快捷键}</div><div role="status" aria-live="polite" aria-atomic="true"></div></div>`;
  popup.addEventListener('click',event=>event.stopPropagation());
  popup.querySelector('input')!.addEventListener('compositionend',event=>search(event.target as HTMLInputElement));
  document.body.append(popup);
 }
 popup.querySelector('.picker-body')!.innerHTML=`<div class="provider-tabs">${view.sources.map(s=>`<button data-source="${escape(s.id)}" class="${!query.trim()&&view.groups.some(g=>g.source===s.id)?'active':''}"><span>${escape(s.label)}</span><span>${s.count}</span></button>`).join('')}</div><div class="option-list" id="picker-results" role="listbox" aria-label="${copy.可选模型}">${view.groups.map(g=>`<div role="group" aria-label="${escape(g.label)}"><div class="option-group">${escape(g.label)}</div>${g.items.map(i=>`<button id="picker-option-${items.indexOf(i)}" role="option" tabindex="-1" aria-selected="${i.selected}" aria-disabled="${!!i.disabled}" class="option${i.selected?' selected':''}" data-model="${escape(i.id)}" ${i.disabled?'disabled':''}><span class="option-info"><span>${escape(i.label)}</span><span class="sub">${escape(i.disabled||pickerEfforts(i.efforts))}</span></span>${i.selected?`<span class="check">${copy.选中标记}</span>`:''}</button>`).join('')}</div>`).join('')}${view.empty?`<p class="empty">${escape(view.empty)}</p>`:''}</div>`;
 popup.querySelector('[aria-live]')!.textContent=pickerCount(items.filter(i=>!i.disabled).length);
 button.setAttribute('aria-expanded','true');
 positionPicker();
 const input=popup.querySelector<HTMLInputElement>('input')!;
 const highlight=()=>{
  popup!.querySelectorAll<HTMLElement>('[data-model]').forEach(option=>option.classList.toggle('active',option.dataset.model===picker?.active));
  const active=Array.from(popup!.querySelectorAll<HTMLElement>('[data-model]')).find(option=>option.dataset.model===picker?.active);
  if(active){input.setAttribute('aria-activedescendant',active.id);active.scrollIntoView?.({block:'nearest'});}
  else input.removeAttribute('aria-activedescendant');
 };
 input.onkeydown=event=>{
  if(event.isComposing||event.keyCode===229)return;
  if(event.altKey&&(event.key==='ArrowLeft'||event.key==='ArrowRight')){
   event.preventDefault();
   const index=view.sources.findIndex(s=>s.id===view.groups.find(g=>g.source!=='current')?.source);
   const next=view.sources[Math.max(0,Math.min(view.sources.length-1,index+(event.key==='ArrowRight'?1:-1)))];
   if(next){picker!.source=next.id;picker!.query='';picker!.active=undefined;input.value='';renderPicker();}
   return;
  }
  if(event.key==='Escape'||event.key==='Tab'){event.preventDefault();closePicker();}
  else if(event.key==='ArrowUp'||event.key==='ArrowDown'||event.key==='Home'||event.key==='End'){
   event.preventDefault();picker!.active=moveActive(view,picker!.active,event.key);highlight();
  }else if(event.key==='Enter'){
   event.preventDefault();
   Array.from(popup!.querySelectorAll<HTMLButtonElement>('[data-model]')).find(b=>b.dataset.model===picker?.active&&!b.disabled)?.click();
  }
 };
 input.oninput=event=>{if(!event.isComposing)search(input);};
 popup.querySelectorAll<HTMLButtonElement>('[data-source]').forEach(b=>b.addEventListener('click',()=>{picker!.source=b.dataset.source;picker!.active=undefined;renderPicker();}));
 popup.querySelectorAll<HTMLButtonElement>('[data-model]').forEach(b=>b.addEventListener('click',()=>{saved='';draft!.select(path,'model',b.dataset.model!);closePicker(true);}));
 if(document.activeElement!==input)input.focus();
 highlight();
}
function positionPicker() {
 const popup=document.querySelector<HTMLDivElement>('.model-popup');
 const button=document.querySelector<HTMLButtonElement>(`button[data-path="${picker?.path}"][data-field="model"]`);
 if(!popup||!button)return;
 positionPopup(popup,button);
}
function positionPopup(popup:HTMLElement,button:HTMLElement) {
 const rect=button.getBoundingClientRect();
 popup.style.maxHeight=Math.max(0,window.innerHeight-20)+'px';
 const above=rect.bottom+4+popup.offsetHeight>window.innerHeight-10;
 const space=above?rect.top-14:window.innerHeight-rect.bottom-14;
 popup.style.maxHeight=Math.max(0,space)+'px';
 popup.style.left=Math.max(10,Math.min(rect.left,window.innerWidth-popup.offsetWidth-10))+'px';
 popup.style.top=Math.max(10,above?rect.top-popup.offsetHeight-4:rect.bottom+4)+'px';
}
function positionPopups() {
 positionPicker();
 const popup=document.querySelector<HTMLElement>('.apply-popup');
 const button=document.querySelector<HTMLElement>(`button[data-apply-from="${applying?.from}"]`);
 if(popup&&button)positionPopup(popup,button);
}
window.addEventListener('resize',positionPopups);
window.addEventListener('scroll',event=>{
 if(!(event.target as Element)?.closest?.('.popup'))positionPopups();
},true);
document.addEventListener('click',event=>{
 const target=event.target as Element;
 if(applying&&!target.closest('.apply-popup,button[data-apply-from],#refresh,#reload'))closeApply();
 if(picker&&!target.closest('.model-popup,button[data-path][data-field="model"],button[data-focus],#refresh,#reload'))closePicker();
});
function reload() {
 if(reading)return;
 if(draft?.changes().length){message=copy.修改还在若要重新读取设置请先撤销修改;render();}else void read();
}
function disableReload(disabled:boolean) {
 for(const id of ['reload','guide-reload']){
  const button=document.querySelector<HTMLButtonElement>('#'+id);if(button)button.disabled=disabled;
 }
}
async function read(automatic=false) {
 const previous=guideInput&&appInfoLoaded?guide(guideInput,appInfo):undefined;
 reading=true; saved='';
 // 自动读取保留卡片 DOM，复制提示、焦点和文字选区不受影响。
 if(automatic)disableReload(true);
 else {message=copy.正在读取本机设置;render();}
 try {snapshot=await mygo.call<Snapshot & {path?:string;validation?:{errors:string[]}}>('Host.ReadConfig');
 const result=snapshot as Snapshot & {path?:string;validation?:{errors:string[]}};
 guideInput=snapshot.file_state==='ready'?undefined:{fileState:result.file_state,path:result.path,config:result.config,errors:result.validation?.errors};editor=undefined;draft=snapshot.file_state==='ready'&&snapshot.config?(editor=new Editor(snapshot)).state.draft:undefined;message=snapshot.file_state==='ready'?loadedMessage:'';}
 catch {guideInput={hostUnavailable:true};snapshot=undefined;editor=undefined;draft=undefined;message=copy.读取环境无法使用请让AI助手检查已绑定的Python至少310及;}
 await appInfoReady;
 reading=false;
 const current=guideInput?guide(guideInput,appInfo):undefined;
 if(automatic&&previous&&current&&previous.kind===current.kind&&previous.detail===current.detail)disableReload(false);
 else render();
 if(draft)void probe();
}
function rereadOnFocus() {
 if(shouldRereadOnFocus({ready:!!draft,reading}))void read(true);
}
window.addEventListener('focus',rereadOnFocus);
document.addEventListener('visibilitychange',()=>{
 if(document.visibilityState==='visible')rereadOnFocus();
});
// 与读取并行；无论成功或失败，来源落定后才展示引导卡与指令。
const appInfoReady=loadAppInfo(()=>mygo.call<AppInfo>('Host.AppInfo')).then(info=>{appInfo=info;appInfoLoaded=true;});
void read();

async function save(){
 if(!editor||draft?.check.kind==='checking'||reading)return;
 const pending=editor.save((candidate,hash)=>mygo.call<Outcome>('Host.Apply',candidate,hash));
 saved='';message=copy.正在保存请等待结果;render();
 const result=await pending;diagnostic=result;draft=editor.state.draft;snapshot=editor.state.base;
 saved=result?.status==='applied'?bannerText({kind:'saved'}):'';message=result?.status==='applied'?'':editor.state.kind==='uncertain'?copy.保存结果待确认请显式检查当前设置:editor.state.kind==='conflict'?copy.设置已在别处更新请读取最新设置并人工核对:copy.保存前检查未通过修改还在请点击重新核对或让AI助手检查环境再确认;render();
 if(result?.status==='applied')void probe();
}
async function recover(){
 if(!editor||reading)return;
 reading=true;saved='';render();let recovered=false;
 try{const latest=await mygo.call<Snapshot>('Host.ReadConfig');if(editor.recover(latest)){draft=editor.state.draft;snapshot=editor.state.base;recovered=true;message=('retained' in editor.state?copy.请参考上次修改重新选择并查看差异:copy.当前设置与待保存的设置一致);saved=bannerText({kind:'recovered'});}else message=copy.当前设置仍无法读取修改还在请让AI助手处理后再次检查;}
 catch{message=copy.检查失败修改还在请处理环境后再次检查;}
 reading=false;render(); if(recovered)void probe();
}
