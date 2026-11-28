import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {FORBIDDEN} from './copy';
const pi={agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'};
const direct={agent:'codex',model:'gpt-6.1-sol',effort:'high'};
const config={version:7,work:Object.fromEntries(['planning','design','frontend','backend','testing','research'].map(n=>[n,{...(n==='research'?direct:pi),fallbacks:[]}])),review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(a=>[a,{...pi,candidates:[]}]))])),modes:{}};
config.work.coordinator={agent:'claude',model:'claude-opus-5-5',effort:'high',fallbacks:[]};
let claudeRoute:'official'|null='official';
const claudeReason='请先打开 Claude Code 完成登录后重新核对';
let agRoute:'cli'|'cache'|null='cli';
const agReason='请先完成 Antigravity 登录后重新核对';
let route:'direct'|'gateway'|null='direct',gateway='ok';
const reason='Codex 当前指向的地址既不是本机网关也不是 OpenAI 官方，无法确认可用模型';
const win=new Window(),doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string,id:string)=>{
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd613-cfg/model-roles.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 if(name==='Host.ProbeCapabilities')return {request_id:id,observed_at:'now',gateway:{status:gateway},sources:{antigravity:{status:agRoute?'ok':'unknown',route:agRoute,reason:agRoute?undefined:agReason},claude:{status:claudeRoute?'ok':'unknown',route:claudeRoute,reason:claudeRoute?undefined:claudeReason},pi:{status:'ok'},codex:{status:route?'ok':'unknown',route,reason:route?undefined:reason}},capabilities:{antigravity:{binary:true,models:agRoute?{'gemini-4-neon':['low','medium','high','xhigh'],'gemini-4-carbon':['low','medium','high']}:{}},claude:{binary:true,models:claudeRoute?{'claude-opus-5-5':['low','medium','high','xhigh','max'],'claude-sonnet-4-6':['low','medium','high','max']}:{}},pi:{binary:true,models:{[pi.model]:['high']}},codex:{binary:true,models:route?{'gpt-6.1-sol':['low','medium','high']}: {}}}};
 throw Error(name);
}}});
doc.body.innerHTML='<div id="app"></div>';
await import('./main?dd613');
const settle=()=>new Promise(r=>setTimeout(r,20));await settle();
const click=(s:string)=>doc.querySelector<HTMLButtonElement>(s)!.click();
const option=()=>doc.querySelector<HTMLOptionElement>('select[data-path="work.design"][data-field="agent"] option[value="codex"]')!;
test('DD-613 直连名称贯穿下拉与工作行，选择后列出内置模型',()=>{
 expect(option().disabled).toBe(false);expect(option().textContent).toBe('Codex CLI · 直连 OpenAI');
 expect(doc.querySelector('[data-task-row="research"]')!.textContent).toContain('Codex CLI · 直连 OpenAI');
 for(const word of FORBIDDEN)expect(option().textContent).not.toContain(word);
 const select=option().parentElement as HTMLSelectElement;select.value='codex';select.dispatchEvent(new win.Event('change',{bubbles:true}));
 click('[data-path="work.design"][data-field="model"]');
 expect(doc.querySelector('[data-model="gpt-6.1-sol"]')!.textContent).toContain('GPT 6.1 Sol');
 click('[data-model="gpt-6.1-sol"]');click('#undo');
});
test('DD-613 其他代理禁用并悬停说明原因，网关标签保持原名',async()=>{
 route=null;click('#refresh');await settle();
 expect(option().disabled).toBe(true);expect(option().textContent).toContain('暂不支持');expect(option().title).toBe(reason);
 route='gateway';click('#refresh');await settle();expect(option().disabled).toBe(false);expect(option().textContent).toBe('Codex CLI');
});
test('DD-613 网关未响应仍阻止整页换模型',async()=>{
 route='direct';gateway='unreachable';click('#refresh');await settle();
 expect(doc.body.textContent).toContain('本机模型网关没有响应');
 click('[data-path="work.design"][data-field="model"]');expect(doc.querySelector('.model-popup')!.textContent).toContain('现在不能换模型');
});

const claudeOption=()=>doc.querySelector<HTMLOptionElement>('select[data-path="work.design"][data-field="agent"] option[value="claude"]')!;
test('DD-618 官方清单贯穿工具下拉与已有行，模型档位与就近提示来自清单',async()=>{
 gateway='ok';click('#refresh');await settle();
 expect(claudeOption().disabled).toBe(false);
 expect(claudeOption().textContent).toBe('Claude Code · 官方清单');
 expect(doc.querySelector('[data-task-row="coordinator"]')!.textContent).toContain('Claude Code · 官方清单');
 for(const word of FORBIDDEN)expect(claudeOption().textContent).not.toContain(word);
 const select=claudeOption().parentElement as HTMLSelectElement;select.value='claude';select.dispatchEvent(new win.Event('change',{bubbles:true}));
 click('[data-path="work.design"][data-field="model"]');
 expect(doc.querySelector('[data-model="claude-opus-5-5"]')!.textContent).toContain('Claude Opus 5.5');
 click('[data-model="claude-opus-5-5"]');
 const effort=doc.querySelector<HTMLSelectElement>('[data-path="work.design"][data-field="effort"]')!;
 effort.value='xhigh';effort.dispatchEvent(new win.Event('change',{bubbles:true}));
 click('[data-path="work.design"][data-field="model"]');click('[data-model="claude-sonnet-4-6"]');
 const next=doc.querySelector<HTMLSelectElement>('[data-path="work.design"][data-field="effort"]')!;
 expect([...next.options].filter(o=>!o.disabled).map(o=>o.value)).toEqual(['high','low','medium','max']);
 expect(next.value).toBe('high');expect(doc.body.textContent).toContain('思考程度已从“很高”改为“高”');click('#undo');
});
test('DD-618 无清单时禁用并悬停登录原因；网关异常沿用整页限制',async()=>{
 claudeRoute=null;click('#refresh');await settle();
 expect(claudeOption().disabled).toBe(true);expect(claudeOption().textContent).toContain('暂不支持');expect(claudeOption().title).toBe(claudeReason);
 claudeRoute='official';gateway='unreachable';click('#refresh');await settle();
 expect(doc.body.textContent).toContain('本机模型网关没有响应');
 click('[data-path="work.design"][data-field="model"]');expect(doc.querySelector('.model-popup')!.textContent).toContain('现在不能换模型');
});

const agOption=()=>doc.querySelector<HTMLOptionElement>('select[data-path="work.design"][data-field="agent"] option[value="antigravity"]')!;
test('Antigravity 清单可选、切模型就近降档，停用时禁用并悬停原因',async()=>{
 gateway='ok';agRoute='cli';click('#refresh');await settle();
 expect(agOption().disabled).toBe(false);
 expect(agOption().textContent).toBe('Antigravity');
 for(const word of FORBIDDEN)expect(agOption().textContent).not.toContain(word);
 const select=agOption().parentElement as HTMLSelectElement;select.value='antigravity';select.dispatchEvent(new win.Event('change',{bubbles:true}));
 click('[data-path="work.design"][data-field="model"]');
 expect(doc.querySelector('[data-model="gemini-4-neon"]')!.textContent).toContain('Gemini 4 Neon');
 click('[data-model="gemini-4-neon"]');
 const effort=doc.querySelector<HTMLSelectElement>('[data-path="work.design"][data-field="effort"]')!;
 effort.value='xhigh';effort.dispatchEvent(new win.Event('change',{bubbles:true}));
 click('[data-path="work.design"][data-field="model"]');click('[data-model="gemini-4-carbon"]');
 const next=doc.querySelector<HTMLSelectElement>('[data-path="work.design"][data-field="effort"]')!;
 expect([...next.options].filter(o=>!o.disabled).map(o=>o.value)).toEqual(['high','low','medium']);
 expect(next.value).toBe('high');expect(doc.body.textContent).toContain('思考程度已从“很高”改为“高”');click('#undo');
 agRoute=null;click('#refresh');await settle();
 expect(agOption().disabled).toBe(true);expect(agOption().textContent).toContain('暂不支持');expect(agOption().title).toBe(agReason);
});
