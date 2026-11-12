import './style.css';

import {Draft,cell,paths,work,type Cell,type Config,type Evidence} from './draft';
import {Editor,type Snapshot,type Outcome} from './editor';
let editor:Editor|undefined;
declare const mygo: {call<T>(name: string,...args:unknown[]): Promise<T>};
let draft:Draft|undefined;

let probing=false;
let probeCounter=0;
const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | undefined;
let message = '正在读取本机设置…';
let help = false;
let diagnostic:unknown;
let diagnosing=false;
let reading = false;
const workNames: Record<string,string> = {planning:'规划',design:'设计',frontend:'前端开发',backend:'后端开发',testing:'测试',coordinator:'协调',research:'调研',prototype:'原型',integration:'集成',assistance:'协助', 'second-opinion':'第二意见'};

const escape = (s: string) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
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
 function select(field:keyof Cell,values:string[],label:(v:string)=>string) {
  const current=c[field]; const entries=[...new Set([...(current?[current]:[]),...values])];
  return `<select class="pill" aria-label="${escape(pathLabel(path!))} · ${{agent:'运行工具',model:'模型',effort:'思考程度'}[field]}" data-path="${path}" data-field="${field}"><option value="" disabled ${!current?'selected':''}>请选择</option>${entries.map(v=>`<option value="${escape(v)}" ${v===current?'selected':''} ${!values.includes(v)?'disabled':''}>${escape(label(v))}</option>`).join('')}</select>`;
 }
 return `<div><div class="fields">${select('agent',Object.keys(agents),v=>agents[v]!)}${select('model',models,modelLabel)}${select('effort',levels,v=>efforts[v] || '已核验档位')}</div>${!levels.includes(c.effort)?`<p class="row-foot">${draft?.changes().includes(path)?'请选择有能力证据的模型和思考程度':'原值保留 · 能力 Unknown，请让 AI 助手核对接入后刷新'}</p>`:''}</div>`;
}
function pathLabel(path:string) {const p=path.split('.');return p[0]==='work'?workNames[p[1]!]!: `${p[1]==='implementation'?'实施结果':'整体交付'} · ${p[2]==='standards'?'代码规范':'需求符合度'}`;}
function summary(c:Cell) {return `${agents[c.agent] || '已配置工具'} · ${modelLabel(c.model)} · ${efforts[c.effort] || '请选择思考程度'}`;}
async function probe() {
 if(!draft)return;
 const owner=draft;const id=`desktop-${Date.now()}-${++probeCounter}`;
 owner.beginProbe(id);probing=true;message='正在核对本机模型能力，草稿已保留…';render();
 try {const result=await mygo.call<Evidence>('Host.ProbeCapabilities',id);if(draft===owner && owner.acceptProbe(result))message='能力已刷新。仅核验元数据；认证、额度与实际运行仍为 Unknown。';}
 catch {if(draft===owner)message='能力 Unknown。请让 AI 助手检查本机工具与接入，再刷新；草稿已保留。';}
 if(draft===owner){probing=false;render();}
}
const guidance: Record<string,string> = {
 missing:'尚未完成初始设置。请让 AI 助手运行 delivery-pipeline-setup 初始化本机交付配置，然后点击重新读取。',
 invalid_json:'配置内容无法读取。请让 AI 助手检查并修复交付配置，保留原文件，然后点击重新读取。',
 unsupported_version:'配置版本需要处理。请让 AI 助手通过 delivery-pipeline-setup 检查并迁移配置，然后点击重新读取。',
 invalid_schema:'配置项目不完整或不符合要求。请让 AI 助手通过 delivery-pipeline-setup 修正配置，然后点击重新读取。',
 unreadable:'无法访问配置。请让 AI 助手检查文件位置和读取权限，然后点击重新读取。'
};
function render() {
 const kind=editor?.state.kind;
 const locked=kind==='saving'||kind==='conflict'||kind==='uncertain'||kind==='preview';
 const reviewing=kind==='preview';
 const config = draft?.config || null;
 if(diagnosing){app.innerHTML=`<main class="frame"><h1>独立诊断</h1><p>此页包含配置工具的机器结果。不会修改配置。</p><pre>${escape(JSON.stringify(diagnostic??snapshot,null,2))}</pre><button id="close-diagnostic">返回设置</button></main>`;document.querySelector('#close-diagnostic')!.addEventListener('click',()=>{diagnosing=false;render();});return;}

 app.innerHTML = `<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">设置 › 模型设置</div><div class="right"><button class="plain" id="theme">切换外观</button><button class="plain" id="help">使用说明</button><button class="plain" id="diagnostic">打开诊断</button></div></header><main class="frame"><div class="page-title"><div><h1>模型设置</h1><p>调整每种工作使用的 AI，核对差异后保存。</p></div><span class="instance">本机设置 · 草稿</span></div>${help?'<aside class="help-panel"><h2>查看当前设置</h2><p>运行工具负责启动 AI；模型完成工作；思考程度是模型提供的档位。需要初始化或修复时，请让 AI 助手运行 delivery-pipeline-setup，处理后点击重新读取。</p><p>读取设置不会联网；刷新能力只读取元数据，不验证模型额度。确认保存后会重新核验能力。主设置用于新任务；显式指定的预设仍按原规则覆盖，正在进行的任务保持原设置。</p></aside>':''}<div class="notice" role="status">${escape(message)}</div>${editor&&'retained' in editor.state&&editor.state.retained?`<aside class="notice"><h2>请人工核对后重新选择</h2><p>当前页面以最新设置为起点，旧草稿仅供参考。请逐项重新选择，再查看差异。</p>${editor.state.retained.changes().map(p=>`<p>${escape(pathLabel(p))}：旧草稿 ${escape(summary(cell((editor!.state as Extract<import('./editor').State,{kind:'draft'|'preview'}>).retained!.config,p)))}；最新 ${escape(summary(cell(draft!.snapshot,p)))}</p>`).join('')}</aside>`:''}${kind==='conflict'||kind==='uncertain'?`<aside class="notice"><h2>${kind==='conflict'?'设置已在别处更新':'保存结果待确认'}</h2><p>草稿已保留。请检查当前设置并人工核对，不会自动重试或回滚。</p><button id="recover" ${reading?'disabled':''}>${kind==='conflict'?'读取最新设置并核对':'检查当前保存结果'}</button></aside>`:''}${config?`<section class="work-section"><div class="section-label"><h2>工作模型</h2><p>每种工作的当前设置</p></div><div class="card"><div class="table-head"><span>工作</span><div class="fields"><span>运行工具</span><span>模型</span><span>思考程度</span></div></div>${work.map(name=>`<div class="task-row"><span class="task-label">${workNames[name]}</span>${fields(config.work[name]!,`work.${name}`)}</div>`).join('')}</div></section><section class="review-section"><div class="section-label"><h2>结果检查</h2><p>分别检查代码写法和需求完成情况</p></div><div class="card review-grid"><div class="review-heading"></div><div class="review-heading">代码规范</div><div class="review-heading">需求符合度</div>${['implementation','whole-change'].map((scope,i)=>`<div class="review-heading scope">${i?'整体交付':'实施结果'}</div>${['standards','spec'].map(axis=>`<div class="review-cell">${fields(config.review[scope]![axis]!,`review.${scope}.${axis}`)}</div>`).join('')}`).join('')}</div></section><details class="card read-only"><summary>其他设置 · 仅查看</summary><div class="readonly-body"><p class="compact-note">由初始化助手维护。${Object.keys(config.modes).length} 组预设，仅在任务明确指定时使用。</p><div class="readonly-grid">${Object.entries(config.work).filter(([key])=>!work.includes(key)).map(([key,cell])=>`<div class="readonly-item">${workNames[key] || '其他工作'}<span>${escape(modelLabel(cell.model))}</span><small>${agents[cell.agent] || '已配置工具'} · ${efforts[cell.effort] || '已配置档位'}</small></div>`).join('') || '<p class="compact-note">没有其他工作设置</p>'}</div></div></details>`:''}<footer class="footer"><span class="footer-status">${config?`${draft!.changes().length} 项修改待确认`:'此页面不会自动创建、修复或迁移配置。'}</span>${config?`<button class="plain" id="refresh" ${probing?'disabled':''}>刷新能力</button><button class="plain" id="undo" ${!draft!.changes().length?'disabled':''}>撤销修改</button><button class="primary" id="diff" ${!draft!.changes().length?'disabled':''}>查看差异</button>`:''}<button class="plain" id="reload" ${reading?'disabled':''}>重新读取</button></footer>${reviewing&&draft?`<section class="diff-panel" role="dialog" aria-label="查看差异"><h2>核对修改</h2>${draft.changes().map(p=>`<article><h3>${escape(pathLabel(p))}</h3><p>原来：${escape(summary(cell(draft!.snapshot,p)))}</p><p>现在：${escape(summary(cell(draft!.config,p)))}</p></article>`).join('')}<p>${draft.valid()?'修改已命中当前能力证据。':'部分修改缺少能力证据，请返回重新选择。'}确认后保存，保存期间不能继续修改。</p><button class="primary" id="back">返回继续修改</button><button class="primary" id="save" ${draft.valid()?'':'disabled'}>确认保存设置</button></section>`:''}</main>`;
 document.querySelector('#theme')!.addEventListener('click',()=>{document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark'?'light':'dark';});
 document.querySelector('#diagnostic')!.addEventListener('click',()=>{diagnosing=true;render();});
 document.querySelector('#help')!.addEventListener('click',()=>{help=!help;render();});
 document.querySelector('#reload')!.addEventListener('click',()=>{if(draft?.changes().length){message='草稿已保留。若要重新读取设置，请先撤销修改。';render();}else read();});
 document.querySelector('#refresh')?.addEventListener('click',probe);
 document.querySelector('#undo')?.addEventListener('click',()=>{draft!.undo();editor?.back();message='修改已撤销，已恢复读取时的设置。';render();});
 document.querySelector('#diff')?.addEventListener('click',()=>{editor?.preview();render();});
 document.querySelector('#back')?.addEventListener('click',()=>{editor?.back();render();});
 document.querySelector('#save')?.addEventListener('click',save);
 document.querySelector('#recover')?.addEventListener('click',recover);
 if(locked||probing||reading){document.querySelectorAll<HTMLSelectElement>('select').forEach(el=>el.disabled=true);for(const id of ['refresh','undo','diff','reload']){const el=document.querySelector<HTMLButtonElement>('#'+id);if(el)el.disabled=true;}}
 document.querySelectorAll<HTMLSelectElement>('select[data-path]').forEach(select=>select.addEventListener('change',()=>{draft!.select(select.dataset.path!,select.dataset.field as keyof Cell,select.value);render();}));
}
async function read() {
 reading=true; message='正在读取本机设置…';render();
 try {snapshot=await mygo.call<Snapshot>('Host.ReadConfig');editor=undefined;draft=snapshot.file_state==='ready'&&snapshot.config?(editor=new Editor(snapshot)).state.draft:undefined;message=snapshot.file_state==='ready'?'当前设置已载入；本次读取未联网，也未更改配置。':(guidance[snapshot.file_state] || '请让 AI 助手检查应用与配置，再重新读取。');}
 catch {snapshot=undefined;editor=undefined;draft=undefined;message='读取环境无法使用。请让 AI 助手检查已绑定的 Python（至少 3.10）及应用随附的配置工具，再点击重新读取。';}
 reading=false;render();
}
read();

async function save(){
 if(!editor||probing||reading)return;
 const pending=editor.save((candidate,hash)=>mygo.call<Outcome>('Host.Apply',candidate,hash));
 message='正在保存，请等待结果…';render();
 const result=await pending;diagnostic=result;draft=editor.state.draft;snapshot=editor.state.base;
 message=result?.status==='applied'?'当前设置已保存并读回。主设置用于新任务；显式指定的预设仍按原规则覆盖，正在进行的任务保持原设置。':editor.state.kind==='uncertain'?'保存结果待确认。请显式检查当前设置。':editor.state.kind==='conflict'?'设置已在别处更新。请读取最新设置并人工核对。':'保存前检查未通过，草稿已保留。请刷新能力或让 AI 助手检查环境，再重新核对并确认保存。';render();
}
async function recover(){
 if(!editor||reading)return;
 reading=true;render();
 try{const latest=await mygo.call<Snapshot>('Host.ReadConfig');if(editor.recover(latest)){draft=editor.state.draft;snapshot=editor.state.base;message='当前设置已读取。'+('retained' in editor.state?'旧草稿已保留供人工核对，请重新选择并预览。':'当前设置与候选一致；这是当前观察结果。');}else message='当前设置仍无法读取，草稿已保留。请让 AI 助手处理后再次检查。';}
 catch{message='检查失败，草稿已保留，请处理环境后再次检查。';}
 reading=false;render();
}
