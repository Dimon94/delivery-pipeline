import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import type {Config} from './draft';

// 预期来自 DD-597 / 方案 B；只通过页面操作，Host 是唯一替身边界。
const a={agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'};
const b={...a,model:'magpie/auto/claude-opus-5-5'};
const config:Config={version:7,work:Object.fromEntries(['planning','design','frontend','backend','testing'].map(n=>[n,{...a,fallbacks:[]}])),modes:{},review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(x=>[x,{...a,candidates:[a,b]}]))]))};
const win=new Window();const doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string,id:string)=>{
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd597/test.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 if(name==='Host.ProbeCapabilities')return {request_id:id,observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok'}},capabilities:{pi:{binary:true,models:{[a.model]:['high'],[b.model]:['high']}}}};
 throw Error(name);
}}});
doc.body.innerHTML='<div id="app"></div>';
await import('./main');
await new Promise(r=>setTimeout(r,20));
const click=(selector:string)=>{const e=doc.querySelector<HTMLButtonElement>(selector);expect(e).not.toBeNull();e!.click();};
const p='review.implementation.standards';
test('方案 B 两阶段四行：候选在名字旁，同一行包含三个设置控件',()=>{
 const groups=[...doc.querySelectorAll('.review-section .review-stage')];
 expect(groups.map(g=>g.querySelector('h3')?.textContent)).toEqual(['实施结果 · 每张票写完后','整体交付 · 合并前看整体']);
 for(const group of groups){
  const rows=group.querySelectorAll(':scope > .task-row');expect(rows.length).toBe(2);
  expect([...rows].map(r=>r.querySelector('.task-label')?.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('代码规范'),expect.stringContaining('需求符合度')]));
  for(const row of rows){expect(row.querySelector('.task-label .qchip')).not.toBeNull();expect(row.querySelectorAll('.fields select').length).toBe(3);}
 }
});
test('候选子行操作保序，编辑归属正确差异路径，候选异常计入原行',()=>{
 click(`[data-queue="${p}"]`);
 const select=(i:number)=>doc.querySelector<HTMLSelectElement>(`select[data-path="${p}.candidates.${i}"][data-field="model"]`)!;
 expect(select(0).getAttribute('aria-label')).toContain('候选 1');
 click(`[data-review="${p}"][data-action="down"][data-index="0"]`);expect(select(0).value).toBe(b.model);
 click(`[data-review="${p}"][data-action="up"][data-index="1"]`);expect(select(0).value).toBe(a.model);
 click(`[data-review="${p}"][data-action="remove"][data-index="0"]`);expect(select(0).value).toBe(b.model);expect(select(1)).toBeNull();
 click(`[data-review="${p}"][data-action="add"]`);expect(select(1).value).toBe('');
 expect(doc.querySelector(`[data-queue="${p}"]`)!.textContent).toContain('1 项需处理');
 expect(doc.querySelector('.attention')!.textContent).toContain('1 项设置需要处理');
 expect(select(1).closest('.task-row')!.textContent).toContain('还没选完整');
 click('#diff');
 expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['实施结果 · 代码规范']);
 expect(doc.querySelector('.diff-panel')!.textContent).toContain('1. Pi · Claude Opus 5 5');
 click('#back');
});
// DD-598：预期来自票据的保存主次、诊断位置与系统外观合同。
test('差异对话框只有确认保存设置为主按钮',()=>{
 click('#diff');
 expect([...doc.querySelectorAll('.diff-panel .primary')].map(e=>e.textContent)).toEqual(['确认保存设置']);
 expect(doc.querySelector('#back')!.classList.contains('plain')).toBe(true);
 click('#back');
});
test('诊断在页脚作为文字按钮，使用说明留顶栏，诊断可返回原设置',()=>{
 expect(doc.querySelector('header #diagnostic')).toBeNull();
 expect(doc.querySelector('header #help')!.textContent).toBe('使用说明');
 const diagnostic=doc.querySelector('footer #diagnostic')!;
 expect(diagnostic).not.toBeNull();expect(diagnostic.classList.contains('text-button')).toBe(true);
 const before=doc.querySelector('select[data-path="work.frontend"][data-field="model"]')!.outerHTML;
 click('#diagnostic');expect(doc.querySelector('h1')!.textContent).toBe('独立诊断');
 expect(JSON.parse(doc.querySelector('pre')!.textContent!)).toEqual({file_state:'ready',config,base_hash:'hash',cells:{}});
 click('#close-diagnostic');
 expect(doc.querySelector('select[data-path="work.frontend"][data-field="model"]')!.outerHTML).toBe(before);
});
import {readFileSync} from 'node:fs';
test('外观只跟随系统：无手动入口，深浅两套色板由系统媒体条件选择',()=>{
 expect(doc.querySelector('#theme')).toBeNull();
 expect(doc.documentElement.hasAttribute('data-theme')).toBe(false);
 const source=readFileSync(new URL('./main.ts',import.meta.url),'utf8');
 const css=readFileSync(new URL('./style.css',import.meta.url),'utf8');
 expect(source).not.toMatch(/dataset\.theme|data-theme/);
 expect(css).not.toContain('data-theme');
 const sheet=new win.CSSStyleSheet();sheet.replaceSync(css);
 for(const mode of ['light','dark']){
  const rule=[...sheet.cssRules].find(r=>r.cssText.includes(`prefers-color-scheme: ${mode}`)||r.cssText.includes(`prefers-color-scheme:${mode}`));
  expect(rule).toBeDefined();
  expect(rule!.cssText).toContain(`color-scheme: ${mode}`);
  for(const token of ['--bg:','--card:','--ink:','--accent:'])expect(rule!.cssText).toContain(token);
 }
});
