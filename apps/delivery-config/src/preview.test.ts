import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
const a={agent:'codex',model:'gpt-6.1-sol',effort:'high'},b={agent:'claude',model:'claude-opus-5-5',effort:'high'};
const config={version:7,model_families:{codex:{'gpt-6.1-sol':{family:'custom',source:'user_declared'}}},work:Object.fromEntries(['planning','design','frontend','backend','testing'].map(n=>[n,{...a,fallbacks:[]}])),review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(x=>[x,{...a,candidates:x==='standards'&&s==='whole-change'?[b]:[]}]))])),modes:{}};
let outcome='different',gateway='ok',calls=0,saved:any;
const win=new Window(),doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string,...args:any[])=>{
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd630.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 if(name==='Host.ProbeCapabilities')return {request_id:args[0],observed_at:'now',gateway:{status:gateway},sources:{codex:{status:'ok'},claude:{status:'ok'}},capabilities:{codex:{binary:true,models:{[a.model]:['high']}},claude:{binary:true,models:{[b.model]:['high']}}}};
 if(name==='Host.PreviewReview'){calls++;return {standards:{selected:b,selected_index:1,outcome,unrecognized:outcome==='unrecognized'?[a]:[]}};}
 if(name==='Host.Apply'){saved=args[0];return {status:'applied',config:saved,base_hash:'new',changed:true};}
 throw Error(name);
}}});
doc.body.innerHTML='<div id="app"></div>';await import('./main?dd630');
const settle=()=>new Promise(r=>setTimeout(r,350));await settle();
const click=(s:string)=>doc.querySelector<HTMLButtonElement>(s)!.click();
test('删除声明卡片，只在有候选轴显示预计结果',()=>{
 expect(doc.querySelector('[data-family]')).toBeNull();expect(doc.body.textContent).not.toContain('共享家族声明');
 expect(doc.querySelectorAll('[data-review-preview]').length).toBe(1);
 const node=doc.querySelector('[data-review-preview]')!;expect(node.classList.contains('review-preview')).toBe(true);expect(node.classList.contains('row-foot')).toBe(false);
 const css=require('fs').readFileSync(new URL('./style.css',import.meta.url),'utf8');expect(css).toMatch(/\.review-preview\{[^}]*padding:[^}]*color:var\(--muted\)/);
 expect(doc.body.textContent).toContain('优先：');expect(doc.body.textContent).toContain('按当前设置推算');
});
test('重新核对更新三种结果与悬停，网关失败显示等待',async()=>{
 for(const [value,text] of [['no_different_family','没有可换的另一家'],['unrecognized','有模型认不出出自哪家']]){
 outcome=value!;click('#refresh');await settle();expect(doc.body.textContent).toContain(text!);
 }
 expect(doc.querySelector('[data-review-preview]')!.getAttribute('title')).toContain(a.model);
 gateway='unreachable';click('#refresh');await settle();expect(doc.body.textContent).toContain('核对完成后显示');
 gateway='ok';click('#refresh');await settle();
});
test('改候选重算，保存声明完全保留，无候选隐藏',async()=>{
 click('[data-queue="review.whole-change.standards"]');const before=calls;
 click('[data-review="review.whole-change.standards"][data-action="add"]');await settle();expect(calls).toBeGreaterThan(before);
 click('[data-review="review.whole-change.standards"][data-action="remove"][data-index="1"]');
 click('[data-review="review.whole-change.standards"][data-action="remove"][data-index="0"]');await settle();
 expect(doc.querySelector('[data-review-preview]')).toBeNull();click('#diff');expect(doc.querySelector('.diff-panel')!.textContent).not.toContain('声明');click('#save');await settle();
 expect(JSON.stringify(saved.model_families)).toBe(JSON.stringify(config.model_families));
});
