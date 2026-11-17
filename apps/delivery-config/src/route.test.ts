import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {FORBIDDEN} from './copy';
const pi={agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'};
const direct={agent:'codex',model:'gpt-6.1-sol',effort:'high'};
const config={version:7,work:Object.fromEntries(['planning','design','frontend','backend','testing','research'].map(n=>[n,{...(n==='research'?direct:pi),fallbacks:[]}])),review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(a=>[a,{...pi,candidates:[]}]))])),modes:{}};
let route:'direct'|'gateway'|null='direct',gateway='ok';
const reason='Codex 当前指向的地址既不是本机网关也不是 OpenAI 官方，无法确认可用模型';
const win=new Window(),doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string,id:string)=>{
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd613-cfg/model-roles.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 if(name==='Host.ProbeCapabilities')return {request_id:id,observed_at:'now',gateway:{status:gateway},sources:{pi:{status:'ok'},codex:{status:route?'ok':'unknown',route,reason:route?undefined:reason}},capabilities:{pi:{binary:true,models:{[pi.model]:['high']}},codex:{binary:true,models:route?{'gpt-6.1-sol':['low','medium','high']}: {}}}};
 throw Error(name);
}}});
doc.body.innerHTML='<div id="app"></div>';
await import('./main?dd613');
const settle=()=>new Promise(r=>setTimeout(r,20));await settle();
const click=(s:string)=>doc.querySelector<HTMLButtonElement>(s)!.click();
const option=()=>doc.querySelector<HTMLOptionElement>('select[data-path="work.design"][data-field="agent"] option[value="codex"]')!;
test('DD-613 直连名称贯穿下拉与只读行，选择后列出内置模型',()=>{
 expect(option().disabled).toBe(false);expect(option().textContent).toBe('Codex CLI · 直连 OpenAI');
 expect(doc.querySelector('.readonly-grid')!.textContent).toContain('Codex CLI · 直连 OpenAI');
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
