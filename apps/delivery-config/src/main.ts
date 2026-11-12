import './style.css';

type Cell = {agent: string; model: string; effort: string};
type Config = {work: Record<string, Cell>; review: Record<string, Record<string, Cell>>; modes: Record<string, unknown>};
type Snapshot = {file_state: string; config: Config | null; cells: Record<string, {status: string}>};
declare const mygo: {call(name: string): Promise<Snapshot>};
const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | undefined;
let message = '正在读取本机设置…';
let help = false;
let reading = false;
const workNames: Record<string,string> = {planning:'规划',design:'设计',frontend:'前端开发',backend:'后端开发',testing:'测试',coordinator:'协调',research:'调研',prototype:'原型',integration:'集成',assistance:'协助', 'second-opinion':'第二意见'};
const work = ['planning','design','frontend','backend','testing'];
const escape = (s: string) => s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const agents: Record<string,string> = {pi:'Pi',codex:'Codex CLI',claude:'Claude Code'};
const efforts: Record<string,string> = {minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高',ultra:'极高',none:'不额外思考'};
// 仅转换已知显示名称；未知身份不直接泄露到普通页面。
function modelLabel(raw: string) {
 const leaf = raw.split('/').pop()!.split('@')[0]!;
 if (/^gpt-\d+(?:\.\d+)?-(sol|astra|terra|luna)$/.test(leaf)) return leaf.replace('gpt-', 'GPT ').replace(/-(sol|astra|terra|luna)$/, ' $1');
 if (/^claude-(sonnet|opus|haiku)-[\d.-]+$/.test(leaf)) return leaf.replace('claude-', 'Claude ').replaceAll('-', ' ');
 return '已配置模型（名称待识别）';
}
function fields(cell: Cell) {return `<div class="fields"><span class="pill">${agents[cell.agent] || '已配置工具'}</span><span class="pill model-label">${escape(modelLabel(cell.model))}</span><span class="pill">${efforts[cell.effort] || '已配置档位'}</span></div>`;}
const guidance: Record<string,string> = {
 missing:'尚未完成初始设置。请让 AI 助手运行 delivery-pipeline-setup 初始化本机交付配置，然后点击重新读取。',
 invalid_json:'配置内容无法读取。请让 AI 助手检查并修复交付配置，保留原文件，然后点击重新读取。',
 unsupported_version:'配置版本需要处理。请让 AI 助手通过 delivery-pipeline-setup 检查并迁移配置，然后点击重新读取。',
 invalid_schema:'配置项目不完整或不符合要求。请让 AI 助手通过 delivery-pipeline-setup 修正配置，然后点击重新读取。',
 unreadable:'无法访问配置。请让 AI 助手检查文件位置和读取权限，然后点击重新读取。'
};
function render() {
 const config = snapshot?.file_state === 'ready' ? snapshot.config : null;
 app.innerHTML = `<header class="app-bar"><div class="app-brand">Delivery Pipeline</div><div class="app-location">设置 › 模型设置</div><div class="right"><button class="plain" id="theme">切换外观</button><button class="plain" id="help">使用说明</button></div></header><main class="frame"><div class="page-title"><div><h1>模型设置</h1><p>查看每种工作使用的 AI。</p></div><span class="instance">本机设置 · 仅查看</span></div>${help?'<aside class="help-panel"><h2>查看当前设置</h2><p>运行工具负责启动 AI；模型完成工作；思考程度是模型提供的档位。需要初始化或修复时，请让 AI 助手运行 delivery-pipeline-setup，处理后点击重新读取。</p><p>此页面离线读取，不会修改设置或验证模型额度。主设置用于新任务；显式指定的预设仍按原规则覆盖，正在进行的任务保持原设置。</p></aside>':''}<div class="notice" role="status">${escape(message)}</div>${config?`<section class="work-section"><div class="section-label"><h2>工作模型</h2><p>每种工作的当前设置</p></div><div class="card"><div class="table-head"><span>工作</span><div class="fields"><span>运行工具</span><span>模型</span><span>思考程度</span></div></div>${work.map(name=>`<div class="task-row"><span class="task-label">${workNames[name]}</span>${fields(config.work[name]!)}</div>`).join('')}</div></section><section class="review-section"><div class="section-label"><h2>结果检查</h2><p>分别检查代码写法和需求完成情况</p></div><div class="card review-grid"><div class="review-heading"></div><div class="review-heading">代码规范</div><div class="review-heading">需求符合度</div>${['implementation','whole-change'].map((scope,i)=>`<div class="review-heading scope">${i?'整体交付':'实施结果'}</div>${['standards','spec'].map(axis=>`<div class="review-cell">${fields(config.review[scope]![axis]!)}</div>`).join('')}`).join('')}</div></section><details class="card read-only"><summary>其他设置 · 仅查看</summary><div class="readonly-body"><p class="compact-note">由初始化助手维护。${Object.keys(config.modes).length} 组预设，仅在任务明确指定时使用。</p><div class="readonly-grid">${Object.entries(config.work).filter(([key])=>!work.includes(key)).map(([key,cell])=>`<div class="readonly-item">${workNames[key] || '其他工作'}<span>${escape(modelLabel(cell.model))}</span><small>${agents[cell.agent] || '已配置工具'} · ${efforts[cell.effort] || '已配置档位'}</small></div>`).join('') || '<p class="compact-note">没有其他工作设置</p>'}</div></div></details>`:''}<footer class="footer"><span class="footer-status">${config?'能力状态 Unknown：本次未联网核验；不代表模型已实际运行。':'此页面不会自动创建、修复或迁移配置。'}</span><button class="primary" id="reload" ${reading?'disabled':''}>重新读取</button></footer></main>`;
 document.querySelector('#theme')!.addEventListener('click',()=>{document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark'?'light':'dark';});
 document.querySelector('#help')!.addEventListener('click',()=>{help=!help;render();});
 document.querySelector('#reload')!.addEventListener('click',read);
}
async function read() {
 reading=true; message='正在读取本机设置…';render();
 try {snapshot=await mygo.call('Host.ReadConfig');message=snapshot.file_state==='ready'?'当前设置已载入；本次读取未联网，也未更改配置。':(guidance[snapshot.file_state] || '请让 AI 助手检查应用与配置，再重新读取。');}
 catch {snapshot=undefined;message='读取环境无法使用。请让 AI 助手检查已绑定的 Python（至少 3.10）及应用随附的配置工具，再点击重新读取。';}
 reading=false;render();
}
read();
