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

let probeCounter=0;
const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | undefined;
let message = '正在读取本机设置…';
let help = false;
let diagnostic:unknown;
let diagnosing=false;
let reading = false;
let guideInput:GuideInput|undefined;
// 队列展开状态是纯 UI 状态，不进 Draft；重新渲染后保持。
const openQueues=new Set<string>();
const loadedMessage='当前设置已载入；本次读取未联网，也未更改配置。';
// 保存成功确认独立于 message：核对期间与核对完成后都保留，直到下一次编辑或读取。
let saved='';
const workNames: Record<string,string> = {planning:'规划',design:'设计',frontend:'前端开发',backend:'后端开发',testing:'测试',coordinator:'协调',research:'调研',prototype:'原型',integration:'集成',assistance:'协助', 'second-opinion':'第二意见'};

const escape = (s: string) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const workHints: Record<string,string> = {planning:'拆需求、定方案',design:'界面与交互',frontend:'写页面代码',backend:'写服务端代码',testing:'写测试并验证'};
const agents: Record<string,string> = {pi:'Pi',codex:'Codex CLI',claude:'Claude Code'};
const efforts: Record<string,string> = {minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高',ultra:'极高',none:'不额外思考'};
// 仅转换已知显示名称；未知身份不直接泄露到普通页面。
function modelLabel(raw: string) {
 if(!raw)return '请选择模型';
 const parts=raw.split('/');const leaf=parts.pop()!;const base=leaf.split('@')[0]!;
 let label='模型名称待识别';
 if (/^gpt-\d+(?:\.\d+)?(?:-[a-z0-9.]+)*$/.test(base)) label=base.replace('gpt-', 'GPT ').replaceAll('-', ' ');
 else if (/^claude-(sonnet|opus|haiku|fable)-[\d.-]+$/.test(base)) label=base.replace('claude-', 'Claude ').replaceAll('-', ' ');
 else if (/^(kimi|gemini|deepseek|grok|k3|hy3)[a-z0-9.\-]*$/.test(base)) label=base.replaceAll('-', ' ').replace(/^(kimi|gemini|deepseek|grok|k3|hy3)/,v=>({kimi:'Kimi',gemini:'Gemini',deepseek:'DeepSeek',grok:'Grok',k3:'Kimi K3',hy3:'腾讯混元'}[v]!));
 const source=parts.filter(p=>p!=='magpie').pop();
 const sources:Record<string,string>={auto:'自动路由',group:'模型分组',junbo:'骏伯',codex:'OpenAI',claude:'Anthropic',cursor:'Cursor',grok:'xAI','kimi-code-cn':'Kimi Code','workbuddy-ai':'WorkBuddy'};
 const context=leaf.match(/@(\d+)k$/)?.[1];
 return label+(source&&sources[source]?` · ${sources[source]}`:'')+(context?` · ${Number(context)/10}万上下文`:'');
}
function fields(c: Cell, path?:string) {
 if(!path)return `<div class="fields"><span class="pill">${agents[c.agent] || '已配置工具'}</span><span class="pill">${escape(modelLabel(c.model))}</span><span class="pill">${efforts[c.effort] || '已配置档位'}</span></div>`;
 const evidence=draft?.evidence;
 const models=evidence?.sources[c.agent]?.status==='ok'?Object.keys(evidence.capabilities[c.agent]?.models || {}):[];
 const levels=draft?.options(c) || [];
 function select(field:keyof ModelTriple,values:string[],label:(v:string)=>string,all:string[]=[]) {
  const current=c[field]; const entries=[...new Set([...(current?[current]:[]),...all,...values])];
  return `<select class="pill" aria-label="${escape(pathLabel(path!))} · ${{agent:'运行工具',model:'模型',effort:'思考程度'}[field]}" data-path="${path}" data-field="${field}"><option value="" disabled ${!current?'selected':''}>请选择</option>${entries.map(v=>`<option value="${escape(v)}" ${v===current?'selected':''} ${!values.includes(v)?'disabled':''}>${escape(label(v))}</option>`).join('')}</select>`;
 }
 const choices=draft?.agentChoices()||[];
 // 已选中却不可用的工具保持选中并标“工具不可用”；其余不可用工具写来源给的原因。
 const agentLabel=(v:string)=>{const ch=choices.find(a=>a.agent===v);if(!ch?.reason)return agents[v]!;return agents[v]!+' · '+(v===c.agent?'工具不可用':ch.reason);};
 return `<div class="fields">${select('agent',choices.filter(a=>a.enabled).map(a=>a.agent),agentLabel,agentIds)}${select('model',models,modelLabel)}${select('effort',levels,v=>efforts[v] || '已核验档位')}</div>`;
}
// 行内状态只由 Draft 的项状态决定（R4/R5）：可用、核对中、未核实都不写字；其余每项一句原因加一个处理动作。
function note(path:string,c:Cell):{why:string;action:string;field:keyof ModelTriple}|undefined {
 const st=itemStatus(path);
 if(st?.kind==='incomplete')return {why:'还没选完整',action:'去选择',field:!c.agent?'agent':!c.model?'model':'effort'};
 if(st?.kind==='tool_off')return {why:`${agents[c.agent]||'这个运行工具'}暂不可用：${st.reason}`,action:'换用其他工具',field:'agent'};
 if(st?.kind==='model_gone')return {why:'这个模型已不在可用清单里',action:'换一个模型',field:'model'};
 if(st?.kind==='effort_gone')return {why:'这个模型不支持当前思考程度',action:'换思考程度',field:'effort'};
}
const needsAction=(st?:ItemStatus)=>!!st&&st.kind!=='ok'&&st.kind!=='checking'&&st.kind!=='unverified';
const rowClass=(path:string)=>{const st=itemStatus(path);return st?.kind==='checking'?'checking':needsAction(st)?'flag':'';};
// R9：主选不可用时写明接替；只出现在主选行的提示里。
function takeoverText(path:string) {
 const t=draft?.status(path).takeover;
 if(!t)return '';
 if(t.kind==='fallback')return `主模型启动失败后会按顺序改用备用；目前第一个可用的是备用 ${t.index+1}。`;
 if(t.kind==='none')return '没有可用备用，新任务会启动失败。';
 return `候选中 ${t.usable} 个可用。`;
}
// R10：队列折叠标签；k 为非可用项个数。
function queueChip(path:string) {
 const st=draft?.status(path);if(!st)return '';
 const k=st.queue.filter(needsAction).length,open=openQueues.has(path);
 return `<button class="qchip${k?' amber':''}" data-queue="${path}" aria-expanded="${open}">${open?'▾':'▸'} ${st.queueLabel} ${st.queue.length}${k?` · ${k} 项需处理`:''}</button>`;
}
function foot(path:string,c:Cell,extra='') {
 const n=note(path,c);
 return n?`<p class="row-foot">${escape(n.why.replace(/[。.]+$/,''))}。${escape(extra)}<button class="inline-action" data-focus="${path}" data-field="${n.field}">${n.action}</button></p>`:'';
}
function itemStatus(path:string):ItemStatus|undefined {
 if(!draft)return;
 const p=path.split('.'),isWork=p[0]==='work',offset=isWork?2:3;
 if(p[offset]===(isWork?'fallbacks':'candidates'))return draft.status(p.slice(0,offset).join('.')).queue[Number(p[offset+1])];
 return draft.status(path).primary;
}
function banner() {
 const check=draft?.check;
 if(check?.kind==='checking')return '正在核对本机模型能力，草稿已保留…';
 if(check?.kind==='unreachable')return (check.cause==='gateway'?'暂时无法核对：本机模型网关没有响应。':'暂时无法核对：核对调用失败。')+'设置保持原值，运行工具、模型、思考程度暂不能修改；备用和候选仍可删除、调序。网关恢复后点击“重新核对”，草稿已保留。';
 // 全部可用时顶部安静：读取后的载入提示在已核对时不再显示（方案 A，用户故事 2）。
 if(check?.kind==='checked'&&message===loadedMessage)return '';
 return message;
}
function pathLabel(path:string) {if(path==='model_families')return '共享家族声明';const p=path.split('.');return p[0]==='work'?workNames[p[1]!]!+(p[2]==='fallbacks'?` · 备用 ${Number(p[3])+1}`:''): `${p[1]==='implementation'?'实施结果':'整体交付'} · ${p[2]==='standards'?'代码规范':'需求符合度'}`;}
function summary(c:Cell) {return `${agents[c.agent] || '已配置工具'} · ${modelLabel(c.model)} · ${efforts[c.effort] || '请选择思考程度'}`;}
function ordered(c:Cell) {if(c.candidates)return summary(c)+`；候选：${c.candidates.length?c.candidates.map((v,i)=>`${i+1}. ${summary(v)}`).join(' → '):'空'}`;return summary(c)+(c.fallbacks?`；备用：${c.fallbacks.length?c.fallbacks.map((v,i)=>`${i+1}. ${summary(v)}`).join(' → '):'空'}`:'');}
function changeSummary(config:Config,path:string) {
 if(path!=='model_families')return ordered(cell(config,path));
 return Object.entries(config.model_families||{}).flatMap(([agent,models])=>Object.entries(models).map(([model,d])=>`${agents[agent]} · ${modelLabel(model)}：${d.family}（用户声明）`)).join('；')||'无声明 · Unknown';
}
function candidateFields(config:Config,path:string) {
 const items=cell(config,path).candidates||[];
 const open=openQueues.has(path);
 const addOff=!draft?.canEdit().addToQueue;
 return `<div class="queue-bar">${queueChip(path)}</div>${!open?'':`<div class="queue">${items.map((c,i)=>`<div class="queue-item ${rowClass(`${path}.candidates.${i}`)}"><p>候选 ${i+1}</p>${fields(c,`${path}.candidates.${i}`)}${foot(`${path}.candidates.${i}`,c)}<button data-review="${path}" data-action="up" data-index="${i}" ${i===0?'disabled':''}>上移</button><button data-review="${path}" data-action="down" data-index="${i}" ${i===items.length-1?'disabled':''}>下移</button><button data-review="${path}" data-action="remove" data-index="${i}">删除</button></div>`).join('')}<button class="add-queue" data-review="${path}" data-action="add" ${addOff?'title="核对完成后才能新增"':''}>＋ 添加候选</button></div>`}`;
}
function familyFields() {
 if(!draft?.config.model_families)return '<p>共享家族声明需要 AI 助手显式升级配置后使用。</p>';
 return `<section class="card"><h2>共享家族声明</h2><p>按运行工具和精确原生模型共享，思考程度不改变家族。仅为用户声明，未经外部认证；留空为 Unknown。</p>${draft.familyIdentities().map((c,i)=>`<label class="task-row">${escape(agents[c.agent]||c.agent)} · ${escape(modelLabel(c.model))}<small>${escape(c.model)}</small><input aria-label="共享家族 ${i+1}" data-family="${i}" value="${escape(draft!.config.model_families?.[c.agent]?.[c.model]?.family||'')}" placeholder="Unknown · 未声明"></label>`).join('')}</section>`;
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
 return `<section class="card guide-card" aria-label="配置处理引导"><h2>${escape(g.title)}</h2><p class="guide-detail">${escape(g.detail)}</p><h3>影响</h3><p>${escape(g.impact)}</p><h3>下一步</h3><p>${escape(g.next)}</p>${g.instruction?`<label for="guide-instruction">给 AI 助手的指令</label><textarea id="guide-instruction" readonly>${escape(g.instruction)}</textarea>`:''}<div class="guide-actions">${g.instruction?'<button class="primary" id="copy-guide">复制指令</button>':''}<button class="plain" id="guide-reload" ${reading?'disabled':''}>重新读取</button>${g.instruction?'<span id="copy-status" role="status"></span>':''}</div></section>`;
}
function render() {
 const kind=editor?.state.kind;
 const locked=kind==='saving'||kind==='conflict'||kind==='uncertain'||kind==='preview';
 const reviewing=kind==='preview';
 const config = draft?.config || null;
 if(diagnosing){app.innerHTML=`<main class="frame"><h1>独立诊断</h1><p>此页包含配置工具的机器结果。不会修改配置。</p><pre>${escape(JSON.stringify(diagnostic??snapshot,null,2))}</pre><button id="close-diagnostic">返回设置</button></main>`;document.querySelector('#close-diagnostic')!.addEventListener('click',()=>{diagnosing=false;render();});return;}

 app.innerHTML = `<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">设置 › 模型设置</div><div class="right"><button class="plain" id="theme">切换外观</button><button class="plain" id="help">使用说明</button><button class="plain" id="diagnostic">打开诊断</button></div></header><main class="frame"><div class="page-title"><div><h1>模型设置</h1><p>调整每种工作使用的 AI，核对差异后保存。</p></div>${appInfoLoaded?`<span class="instance${isTestConfig(appInfo)?' test-config':''}" title="${escape(instanceTitle(appInfo))}">${escape(instanceLabel(appInfo))}</span>`:''}</div>${help?'<aside class="help-panel"><h2>查看当前设置</h2><p>运行工具负责启动 AI；模型完成工作；思考程度是模型提供的档位。需要初始化或修复时，请按页面引导卡的说明处理，并复制其中的指令给 AI 助手。</p><p>读取设置不会联网；打开设置、保存和恢复后会自动核对能力；核对只读取元数据，认证、额度与实际运行仍为 Unknown，需要时可点击“重新核对”。主设置用于新任务；显式指定的预设仍按原规则覆盖，正在进行的任务保持原设置。</p></aside>':''}${guideCard()}${(!guideInput||reading)&&banner()?`<div class="notice${draft?.check.kind==='checked'?' calm':''}" role="status">${escape(banner())}</div>`:''}${saved?`<div class="notice calm" role="status">${escape(saved)}</div>`:''}${draft&&draft.attention()?`<div class="notice attention" role="status">${draft.attention()} 项设置需要处理，其余 ${paths.length-draft.attention()} 项可以正常使用。</div>`:''}${editor&&'retained' in editor.state&&editor.state.retained?`<aside class="notice"><h2>请人工核对后重新选择</h2><p>当前页面以最新设置为起点，旧草稿仅供参考。请逐项重新选择，再查看差异。</p>${[...paths,'model_families'].map(p=>`<p>${escape(pathLabel(p))}：旧草稿 ${escape(changeSummary((editor!.state as Extract<import('./editor').State,{kind:'draft'|'preview'}>).retained!.config,p))}；最新 ${escape(changeSummary(draft!.snapshot,p))}</p>`).join('')}</aside>`:''}${kind==='conflict'||kind==='uncertain'?`<aside class="notice"><h2>${kind==='conflict'?'设置已在别处更新':'保存结果待确认'}</h2><p>草稿已保留。请检查当前设置并人工核对，不会自动重试或回滚。</p><button id="recover" ${reading?'disabled':''}>${kind==='conflict'?'读取最新设置并核对':'检查当前保存结果'}</button></aside>`:''}${config?`<section class="work-section"><div class="section-label"><h2>工作模型</h2><p>每种工作的当前设置</p></div><div class="card"><div class="table-head"><span>工作</span><div class="fields"><span>运行工具</span><span>模型</span><span>思考程度</span></div></div>${work.map(name=>`<div class="task-row ${rowClass(`work.${name}`)}"><span class="task-label"><span>${workNames[name]}<small class="task-hint">${workHints[name]}</small>${queueChip(`work.${name}`)}</span></span>${fields(config.work[name]!,`work.${name}`)}${foot(`work.${name}`,config.work[name]!,takeoverText(`work.${name}`))}</div>${!openQueues.has(`work.${name}`)?'':`<div class="fallbacks">${(config.work[name]!.fallbacks||[]).map((c,i)=>`<div class="task-row ${rowClass(`work.${name}.fallbacks.${i}`)}"><span>备用 ${i+1}</span>${fields(c,`work.${name}.fallbacks.${i}`)}<div class="fallback-actions"><button data-work="${name}" data-action="up" data-index="${i}" ${i===0?"disabled":""}>上移</button><button data-work="${name}" data-action="down" data-index="${i}" ${i===(config.work[name]!.fallbacks!.length-1)?"disabled":""}>下移</button><button data-work="${name}" data-action="remove" data-index="${i}">删除</button></div>${foot(`work.${name}.fallbacks.${i}`,c)}</div>`).join("")}<button class="add-queue" data-work="${name}" data-action="add" aria-label="添加备用 · ${workNames[name]}" ${draft?.canEdit().addToQueue?'':'title="核对完成后才能新增"'}>＋ 添加备用</button></div>`}`).join('')}</div></section><section class="review-section"><div class="section-label"><h2>结果检查</h2><p>分别检查代码写法和需求完成情况</p></div><div class="card review-grid"><div class="review-heading"></div><div class="review-heading">代码规范</div><div class="review-heading">需求符合度</div>${['implementation','whole-change'].map((scope,i)=>`<div class="review-heading scope">${i?'整体交付':'实施结果'}</div>${['standards','spec'].map(axis=>`<div class="review-cell ${rowClass(`review.${scope}.${axis}`)}">${fields(config.review[scope]![axis]!,`review.${scope}.${axis}`)}${foot(`review.${scope}.${axis}`,config.review[scope]![axis]!,takeoverText(`review.${scope}.${axis}`))}${candidateFields(config,`review.${scope}.${axis}`)}</div>`).join('')}`).join('')}</div></section>${familyFields()}<details class="card read-only"><summary>其他设置 · 仅查看</summary><div class="readonly-body"><p class="compact-note">由初始化助手维护。${Object.keys(config.modes).length} 组预设，仅在任务明确指定时使用。</p><div class="readonly-grid">${Object.entries(config.work).filter(([key])=>!work.includes(key)).map(([key,cell])=>`<div class="readonly-item">${workNames[key] || '其他工作'}<span>${escape(modelLabel(cell.model))}</span><small>${agents[cell.agent] || '已配置工具'} · ${efforts[cell.effort] || '已配置档位'}</small></div>`).join('') || '<p class="compact-note">没有其他工作设置</p>'}</div></div></details>`:''}<footer class="footer"><span class="footer-status">${config?`${draft!.changes().length} 项修改待确认`:'此页面不会自动创建、修复或迁移配置。'}</span>${config?`<button class="plain" id="refresh" ${draft!.check.kind==='checking'?'disabled':''}>重新核对</button><button class="plain" id="undo" ${!draft!.changes().length?'disabled':''}>撤销修改</button><button class="primary" id="diff" ${!draft!.changes().length?'disabled':''}>查看差异</button>`:''}<button class="plain" id="reload" ${reading?'disabled':''}>重新读取</button></footer>${reviewing&&draft?`<section class="diff-panel" role="dialog" aria-label="查看差异"><h2>核对修改</h2>${draft.changes().map(p=>`<article><h3>${escape(pathLabel(p))}</h3><p>原来：${escape(changeSummary(draft!.snapshot,p))}</p><p>现在：${escape(changeSummary(draft!.config,p))}</p></article>`).join('')}<p>${draft.valid()?'修改已命中当前能力证据。':'部分修改缺少能力证据，请返回重新选择。'}确认后保存，保存期间不能继续修改。</p><button class="primary" id="back">返回继续修改</button><button class="primary" id="save" ${draft.valid()?'':'disabled'}>确认保存设置</button></section>`:''}</main>`;
 document.querySelector('#theme')!.addEventListener('click',()=>{document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark'?'light':'dark';});
 document.querySelector('#diagnostic')!.addEventListener('click',()=>{diagnosing=true;render();});
 document.querySelector('#help')!.addEventListener('click',()=>{help=!help;render();});
 document.querySelector('#copy-guide')?.addEventListener('click',async()=>{
 const text=document.querySelector<HTMLTextAreaElement>('#guide-instruction')!;
 const status=document.querySelector<HTMLElement>('#copy-status')!;
 try {await navigator.clipboard.writeText(text.value);status.textContent='已复制，粘贴给 AI 助手即可';}
 catch {text.focus();text.select();status.textContent='已选中，请按 ⌘C 复制';}
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
 const target=document.querySelector<HTMLSelectElement>(`select[data-path="${button.dataset.focus}"][data-field="${button.dataset.field}"]`);
 if(target&&!target.disabled){target.focus();try{target.showPicker();}catch{}}
 }));
 document.querySelector('#undo')?.addEventListener('click',()=>{saved='';draft!.undo();editor?.back();message='修改已撤销，已恢复读取时的设置。';render();});
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
 const checking=draft?.check.kind==='checking';
 if(locked||reading||!draft?.canEdit().select)document.querySelectorAll<HTMLSelectElement>('select').forEach(el=>el.disabled=true);
 if(locked||checking||reading){for(const id of ['refresh','undo','diff','reload']){const el=document.querySelector<HTMLButtonElement>('#'+id);if(el)el.disabled=true;}}
 document.querySelectorAll<HTMLSelectElement>('select[data-path]').forEach(select=>select.addEventListener('change',()=>{saved='';draft!.select(select.dataset.path!,select.dataset.field as keyof ModelTriple,select.value);render();}));
}
function reload() {
 if(reading)return;
 if(draft?.changes().length){message='草稿已保留。若要重新读取设置，请先撤销修改。';render();}else void read();
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
 else {message='正在读取本机设置…';render();}
 try {snapshot=await mygo.call<Snapshot & {path?:string;validation?:{errors:string[]}}>('Host.ReadConfig');
 const result=snapshot as Snapshot & {path?:string;validation?:{errors:string[]}};
 guideInput=snapshot.file_state==='ready'?undefined:{fileState:result.file_state,path:result.path,config:result.config,errors:result.validation?.errors};editor=undefined;draft=snapshot.file_state==='ready'&&snapshot.config?(editor=new Editor(snapshot)).state.draft:undefined;message=snapshot.file_state==='ready'?loadedMessage:'';}
 catch {guideInput={hostUnavailable:true};snapshot=undefined;editor=undefined;draft=undefined;message='读取环境无法使用。请让 AI 助手检查已绑定的 Python（至少 3.10）及应用随附的配置工具，再点击重新读取。';}
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
 saved='';message='正在保存，请等待结果…';render();
 const result=await pending;diagnostic=result;draft=editor.state.draft;snapshot=editor.state.base;
 saved=result?.status==='applied'?'当前设置已保存并读回。主设置用于新任务；显式指定的预设仍按原规则覆盖，正在进行的任务保持原设置。':'';message=result?.status==='applied'?'':editor.state.kind==='uncertain'?'保存结果待确认。请显式检查当前设置。':editor.state.kind==='conflict'?'设置已在别处更新。请读取最新设置并人工核对。':'保存前检查未通过，草稿已保留。请点击“重新核对”或让 AI 助手检查环境，再确认保存。';render();
 if(result?.status==='applied')void probe();
}
async function recover(){
 if(!editor||reading)return;
 reading=true;saved='';render();let recovered=false;
 try{const latest=await mygo.call<Snapshot>('Host.ReadConfig');if(editor.recover(latest)){draft=editor.state.draft;snapshot=editor.state.base;recovered=true;message='当前设置已读取。'+('retained' in editor.state?'旧草稿已保留供人工核对，请重新选择并预览。':'当前设置与候选一致；这是当前观察结果。');}else message='当前设置仍无法读取，草稿已保留。请让 AI 助手处理后再次检查。';}
 catch{message='检查失败，草稿已保留，请处理环境后再次检查。';}
 reading=false;render(); if(recovered)void probe();
}
