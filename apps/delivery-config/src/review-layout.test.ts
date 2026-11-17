import {test,expect,describe,beforeEach} from 'bun:test';
import {Window} from 'happy-dom';
import type {Config} from './draft';

// 预期来自 DD-597 / 方案 B；只通过页面操作，Host 是唯一替身边界。
const a={agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'};
const b={...a,model:'magpie/auto/claude-opus-5-5'};
const target='magpie/junbo/gpt-6.1-sol';
const config:Config={version:7,model_families:{},work:Object.fromEntries(['planning','design','frontend','backend','testing'].map(n=>[n,{...a,fallbacks:[]}])),modes:{},review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(x=>[x,{...a,candidates:[{...a},{...b}]}]))]))};
config.work.planning!.fallbacks=[{...a},{...b}];
let models:Record<string,string[]>={[a.model]:['high'],[b.model]:['high'],[target]:['high']};
let pendingProbe:((v:unknown)=>void)|undefined;
let holdProbe=false;
let pendingId='';
const win=new Window();const doc=win.document;
Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call:async(name:string,id:string)=>{
 if(name==='Host.AppInfo')return {config_path:'/tmp/dd597/test.json'};
 if(name==='Host.ReadConfig')return {file_state:'ready',config,base_hash:'hash',cells:{}};
 if(name==='Host.Apply')return {status:'rejected',error:{code:'base_conflict'}};
 if(name==='Host.ProbeCapabilities'&&holdProbe)return new Promise(resolve=>{pendingProbe=resolve;pendingId=id;});
 if(name==='Host.ProbeCapabilities')return {request_id:id,observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok'}},capabilities:{pi:{binary:true,models}}};
 throw Error(name);
}}});
doc.body.innerHTML='<div id="app"></div>';
await import('./main');
await new Promise(r=>setTimeout(r,20));
const click=(selector:string)=>{const e=doc.querySelector<HTMLButtonElement>(selector);expect(e).not.toBeNull();e!.click();};
const p='review.implementation.standards';
test('备用、结果检查、候选共用模型按钮，选择只修改对应草稿',()=>{
 for(const [path,title,queue] of [
  ['work.planning.fallbacks.0','规划','work.planning'],
  [p,'实施结果 · 代码规范',undefined],
  [p+'.candidates.1','实施结果 · 代码规范',p],
 ] as const){
  if(queue)click(`button[data-queue="${queue}"]`);
  click('button[data-path="work.frontend"][data-field="model"]');
  click(`button[data-path="${path}"][data-field="model"]`);
  expect(doc.querySelectorAll('button[data-path][data-field="model"][aria-expanded="true"]').length).toBe(1);
  expect(doc.querySelectorAll('.model-popup').length).toBe(1);
  click('[data-source="junbo"]');click(`[data-model="${target}"]`);
  expect(doc.querySelector('.model-popup')).toBeNull();
  expect(doc.querySelector(`button[data-path="${path}"][data-field="model"]`)!.textContent).toContain('骏伯');
  expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');
  click('#diff');
  expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual([title]);
  expect(doc.querySelector('.diff-panel')!.textContent).toContain('GPT 6.1 Sol · 骏伯');
  click('#back');click('#undo');
  if(queue)click(`button[data-queue="${queue}"]`);
 }
});
test('重读、核对到达保留唯一弹层和搜索，高亮消失回首个可选项',async()=>{
 const input=()=>doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 const active=()=>doc.getElementById(input().getAttribute('aria-activedescendant')!)?.getAttribute('data-model');
 click('button[data-path="work.frontend"][data-field="model"]');
 input().value='magpie';input().dispatchEvent(new win.Event('input',{bubbles:true}));
 input().dispatchEvent(new win.KeyboardEvent('keydown',{key:'End',bubbles:true}));
 expect(active()).toBe(target);
 holdProbe=true;click('#refresh');
 pendingProbe!({request_id:pendingId,observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok'}},capabilities:{pi:{binary:true,models}}});
 await new Promise(r=>setTimeout(r,20));
 holdProbe=false;
 expect(doc.querySelectorAll('.model-popup').length).toBe(1);
 expect(input().value).toBe('magpie');expect(active()).toBe(target);
 click('#reload');
 await new Promise(r=>setTimeout(r,20));
 expect(input().value).toBe('magpie');expect(active()).toBe(target);
 models={[b.model]:['high'],[a.model]:['high']};
 click('#refresh');
 await new Promise(r=>setTimeout(r,20));
 expect(input().value).toBe('magpie');expect(active()).toBe(b.model);
 doc.body.click();models={[a.model]:['high'],[b.model]:['high'],[target]:['high']};
 click('#refresh');await new Promise(r=>setTimeout(r,20));
});
test('工作模型三次点击选中，差异中只有该项，点外部不修改',()=>{
 click('button[data-path="work.frontend"][data-field="model"]');
 expect(doc.querySelector('.model-popup')).not.toBeNull();
 click('[data-source="junbo"]');click(`[data-model="${target}"]`);
 expect(doc.querySelector('.model-popup')).toBeNull();
 expect(doc.querySelector('button[data-path="work.frontend"][data-field="model"]')!.textContent).toContain('GPT 6.1 Sol · 骏伯');
 expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');
 click('#diff');expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['前端开发']);
 expect(doc.querySelector('.diff-panel')!.textContent).toContain('GPT 6.1 Sol · 骏伯');click('#back');
 click('button[data-path="work.frontend"][data-field="model"]');
 doc.body.dispatchEvent(new win.MouseEvent('click',{bubbles:true}));
 expect(doc.querySelector('.model-popup')).toBeNull();expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');click('#undo');
});
test('键盘搜索选中、取消与读屏状态跟随可见结果',()=>{
 const selector='button[data-path="work.frontend"][data-field="model"]';
 const key=(e:Element,k:string)=>e.dispatchEvent(new win.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
 const trigger=()=>doc.querySelector<HTMLButtonElement>(selector)!;
 trigger().focus();key(trigger(),'Enter');
 const input=()=>doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 expect(doc.activeElement===input()).toBe(true);
 expect(input().getAttribute('aria-expanded')).toBe('true');
 expect(doc.getElementById(input().getAttribute('aria-controls')!)?.getAttribute('role')).toBe('listbox');
 input().value='sol 骏伯';input().dispatchEvent(new win.Event('input',{bubbles:true}));
 expect(doc.activeElement===input()).toBe(true);
 expect(doc.querySelector('[aria-live="polite"]')!.textContent).toBe('1 个可选模型');
 key(input(),'ArrowDown');
 const active=doc.getElementById(input().getAttribute('aria-activedescendant')!)!;
 expect(active.getAttribute('role')).toBe('option');expect(active.getAttribute('data-model')).toBe(target);
 expect(active.getAttribute('aria-selected')).toBe('false');expect(active.getAttribute('aria-disabled')).toBe('false');
 key(input(),'Enter');
 expect(doc.querySelector('.model-popup')).toBeNull();expect(doc.activeElement===trigger()).toBe(true);
 expect(trigger().textContent).toContain('骏伯');expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');
 key(trigger(),' ');
 expect(doc.activeElement===input()).toBe(true);
 expect(doc.querySelector('[role="option"][aria-selected="true"]')?.getAttribute('data-model')).toBe(target);
 key(input(),'Escape');expect(doc.querySelector('.model-popup')).toBeNull();expect(doc.activeElement===trigger()).toBe(true);
 expect(trigger().textContent).toContain('骏伯');
 key(trigger(),'Enter');key(input(),'Tab');
 expect(doc.querySelector('.model-popup')).toBeNull();expect(doc.activeElement===trigger()).toBe(true);
 expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');click('#undo');
});
test('中文组合输入期间保留搜索框，完成组词后再过滤',()=>{
 click('button[data-path="work.frontend"][data-field="model"]');
 const input=doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 input.dispatchEvent(new win.CompositionEvent('compositionstart',{bubbles:true}));
 input.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:true}));
 expect(doc.querySelector('.model-popup')!==null).toBe(true);
 input.value='骏';
 input.dispatchEvent(new win.InputEvent('input',{bubbles:true,isComposing:true}));
 expect(doc.activeElement===input).toBe(true);
 expect(doc.querySelector('[role="combobox"]')===input).toBe(true);
 input.value='骏伯';
 input.dispatchEvent(new win.CompositionEvent('compositionend',{bubbles:true,data:'骏伯'}));
 expect(doc.querySelector<HTMLInputElement>('[role="combobox"]')!.value).toBe('骏伯');
 expect(doc.querySelector('[aria-live]')!.textContent).toBe('1 个可选模型');
 doc.querySelector('[role="combobox"]')!.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
});
test('刷新核对与重读不替换正在组词的输入框',async()=>{
 click('button[data-path="work.frontend"][data-field="model"]');
 const input=doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 input.dispatchEvent(new win.CompositionEvent('compositionstart',{bubbles:true}));input.value='jun';
 input.dispatchEvent(new win.InputEvent('input',{bubbles:true,isComposing:true}));
 click('#refresh');await new Promise(r=>setTimeout(r,20));
 expect(doc.querySelector('[role="combobox"]')===input).toBe(true);expect(input.value).toBe('jun');
 click('#reload');await new Promise(r=>setTimeout(r,20));
 expect(doc.querySelector('[role="combobox"]')===input).toBe(true);expect(input.value).toBe('jun');
 input.value='骏伯';input.dispatchEvent(new win.CompositionEvent('compositionend',{bubbles:true,data:'骏伯'}));
 expect(doc.querySelector('[aria-live]')!.textContent).toBe('1 个可选模型');doc.body.click();
});
test('WebKit 组词确认后 keyCode 229 不选择模型',()=>{
 click('button[data-path="work.frontend"][data-field="model"]');
 const input=doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 input.value='骏伯';input.dispatchEvent(new win.CompositionEvent('compositionend',{bubbles:true,data:'骏伯'}));
 const event=new win.KeyboardEvent('keydown',{key:'Enter',bubbles:true,isComposing:false});Object.defineProperty(event,'keyCode',{value:229});input.dispatchEvent(event);
 expect(doc.querySelector('.model-popup')!==null).toBe(true);expect(doc.querySelector('.footer-status')!.textContent).toBe('0 项修改待确认');doc.body.click();
});
test('Alt 方向键切换来源，Tab 仍关闭且不改值',()=>{
 click('button[data-path="work.frontend"][data-field="model"]');
 const input=doc.querySelector<HTMLInputElement>('[role="combobox"]')!;
 input.dispatchEvent(new win.KeyboardEvent('keydown',{key:'ArrowRight',altKey:true,bubbles:true}));
 expect(doc.querySelector('.provider-tabs .active')?.getAttribute('data-source')).toBe('junbo');
 expect(doc.querySelectorAll('[role="option"]').length).toBe(1);expect(doc.querySelector('[role="option"]')?.getAttribute('data-model')).toBe(target);
 input.dispatchEvent(new win.KeyboardEvent('keydown',{key:'ArrowLeft',altKey:true,bubbles:true}));
 expect(doc.querySelector('.provider-tabs .active')?.getAttribute('data-source')).toBe('auto');
 input.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Tab',bubbles:true}));expect(doc.querySelector('.model-popup')).toBeNull();
 expect(doc.querySelector('.footer-status')!.textContent).toBe('0 项修改待确认');
});
test('触发按钮关联列表，结果项被有名称的分组包含',()=>{
 const trigger=doc.querySelector<HTMLButtonElement>('button[data-path="work.frontend"][data-field="model"]')!;trigger.click();
 expect(trigger.getAttribute('aria-haspopup')).toBe('listbox');expect(doc.getElementById(trigger.getAttribute('aria-controls')!)?.getAttribute('role')).toBe('listbox');
 const groups=doc.querySelectorAll('[role="listbox"] > [role="group"]');expect(groups.length).toBe(1);expect(groups[0]!.getAttribute('aria-label')).toBe('自动路由');expect(groups[0]!.querySelectorAll('[role="option"]').length).toBe(2);doc.body.click();
});
test('差异预览锁定时关闭已打开的选择器',()=>{
 click('button[data-path="work.frontend"][data-field="model"]');click('[data-source="junbo"]');click(`[data-model="${target}"]`);
 click('button[data-path="work.frontend"][data-field="model"]');
 doc.querySelector('#diff')!.dispatchEvent(new win.MouseEvent('click',{bubbles:false}));
 expect(doc.querySelector('.diff-panel')).not.toBeNull();expect(doc.querySelector('.model-popup')).toBeNull();click('#back');click('#undo');
});
test('Host 网关失败时弹层只有恢复原因，没有可选项',async()=>{
 holdProbe=true;click('#refresh');pendingProbe!({request_id:pendingId,gateway:{status:'failed'},sources:{},capabilities:{}});await new Promise(r=>setTimeout(r,20));holdProbe=false;
 click('button[data-path="work.frontend"][data-field="model"]');
 expect(doc.querySelector('.model-popup')!.textContent).toContain('本机模型网关没有响应');expect(doc.querySelector('.model-popup')!.textContent).toContain('重新核对');expect(doc.querySelectorAll('[role="option"]').length).toBe(0);doc.body.click();
 click('#refresh');await new Promise(r=>setTimeout(r,20));
});
test('方案 B 两阶段四行：候选在名字旁，同一行包含三个设置控件',()=>{
 const groups=[...doc.querySelectorAll('.review-section .review-stage')];
 expect(groups.map(g=>g.querySelector('h3')?.textContent)).toEqual(['实施结果 · 每张票写完后','整体交付 · 合并前看整体']);
 for(const group of groups){
  const rows=group.querySelectorAll(':scope > .task-row');expect(rows.length).toBe(2);
  expect([...rows].map(r=>r.querySelector('.task-label')?.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('代码规范'),expect.stringContaining('需求符合度')]));
  for(const row of rows){expect(row.querySelector('.task-label .qchip')).not.toBeNull();expect(row.querySelectorAll('.fields select,.fields button[data-field="model"]').length).toBe(3);}
 }
});
test('候选子行操作保序，编辑归属正确差异路径，候选异常计入原行',()=>{
 click(`[data-queue="${p}"]`);
 const select=(i:number)=>doc.querySelector<HTMLButtonElement>(`button[data-path="${p}.candidates.${i}"][data-field="model"]`)!;
 expect(select(0).getAttribute('aria-label')).toContain('候选 1');
 click(`[data-review="${p}"][data-action="down"][data-index="0"]`);expect(select(0).textContent).toBe('Claude Opus 5.5 · 自动路由');
 click(`[data-review="${p}"][data-action="up"][data-index="1"]`);expect(select(0).textContent).toBe('GPT 6.1 Sol · 自动路由');
 click(`[data-review="${p}"][data-action="remove"][data-index="0"]`);expect(select(0).textContent).toBe('Claude Opus 5.5 · 自动路由');expect(select(1)).toBeNull();
 click(`[data-review="${p}"][data-action="add"]`);expect(select(1).textContent).toBe('请选择模型');
 expect(doc.querySelector(`[data-queue="${p}"]`)!.textContent).toContain('1 项需处理');
 expect(doc.querySelector('.attention')!.textContent).toContain('1 项设置需要处理');
 expect(select(1).closest('.task-row')!.textContent).toContain('还没选完整');
 click('#diff');
 expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['实施结果 · 代码规范']);
 expect(doc.querySelector('.diff-panel')!.textContent).toContain('1. Pi · Claude Opus 5.5');
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
 const before=doc.querySelector('button[data-path="work.frontend"][data-field="model"]')!.outerHTML;
 click('#diagnostic');expect(doc.querySelector('h1')!.textContent).toBe('独立诊断');
 expect(JSON.parse(doc.querySelector('pre')!.textContent!)).toEqual({file_state:'ready',config,base_hash:'hash',cells:{}});
 click('#close-diagnostic');
 expect(doc.querySelector('button[data-path="work.frontend"][data-field="model"]')!.outerHTML).toBe(before);
});
import {readFileSync} from 'node:fs';
test('外观只跟随系统：无手动入口，深浅两套色板由系统媒体条件选择',()=>{
 expect(doc.querySelector('#theme')).toBeNull();
 expect(doc.documentElement.hasAttribute('data-theme')).toBe(false);
 const source=readFileSync(new URL('./main.ts',import.meta.url),'utf8');
 const css=readFileSync(new URL('./style.css',import.meta.url),'utf8');
 expect(source).not.toMatch(/dataset\.theme|data-theme/);
 expect(css).not.toContain('data-theme');
 expect(readFileSync(new URL('../index.html',import.meta.url),'utf8')).not.toContain('data-theme');
 const sheet=new win.CSSStyleSheet();sheet.replaceSync(css);
 for(const mode of ['light','dark']){
  const rule=[...sheet.cssRules].find(r=>r.cssText.includes(`prefers-color-scheme: ${mode}`)||r.cssText.includes(`prefers-color-scheme:${mode}`));
  expect(rule).toBeDefined();
  expect(rule!.cssText).toContain(`color-scheme: ${mode}`);
  for(const token of ['--bg:','--card:','--ink:','--accent:'])expect(rule!.cssText).toContain(token);
 }
});
test('R1 检查行顺序为名字、说明、候选',()=>{
 const label=doc.querySelector('.review-stage .task-label')!;
 expect(label.textContent).toMatch(/^代码规范写法是否合规[▾▸] 候选/);
});
test('R1 窄窗口两区堆叠，宽窗口对齐',()=>{
 const sheet=new win.CSSStyleSheet();sheet.replaceSync(readFileSync(new URL('./style.css',import.meta.url),'utf8'));
 function value(element:Element,property:string,width:number){
  let result='',specificity=-1;
  function visit(rules:CSSRuleList){for(const rule of rules){
   const r=rule as CSSStyleRule & CSSMediaRule;
   if(r.conditionText){const max=r.conditionText.match(/max-width:\s*(\d+)px/);if(max&&width<=Number(max[1]))visit(r.cssRules);}
   else if(r.selectorText)for(const selector of r.selectorText.split(','))if(element.matches(selector.trim())&&r.style.getPropertyValue(property)){
    const score=(selector.match(/\./g)||[]).length;
    if(score>=specificity){specificity=score;result=r.style.getPropertyValue(property);}
   }
  }}visit(sheet.cssRules as unknown as CSSRuleList);return result;
 }
 for(const section of ['work-section','review-section']){
  const row=doc.querySelector(`.${section} .task-row`)!;
  const fields=row.querySelector('.fields')!;
  for(const width of [700,520]){
   expect(value(row,'min-width',width)).toBe('0');
   expect(value(row,'grid-template-columns',width)).toBe('minmax(0,1fr)');
   expect(value(fields,'width',width)).toBe('100%');
  }
  expect(value(fields,'width',1100)).toBe('600px');
 }
});

test('R1 冲突恢复仅一条成功提示',async()=>{
 click('#undo');
 click('button[data-path="work.frontend"][data-field="model"]');
 click(`[data-model="${b.model}"]`);
 click('#diff');click('#save');await new Promise(r=>setTimeout(r,20));
 click('#recover');await new Promise(r=>setTimeout(r,20));
 const notices=[...doc.querySelectorAll('[role="status"]')].filter(e=>e.textContent?.includes('已重新读取当前设置。'));
 expect(notices.length).toBe(1);expect(notices[0]!.classList.contains('success')).toBe(true);
});
describe('M5b 独立页面场景',()=>{
 beforeEach(async()=>{
  holdProbe=false;models={[a.model]:['high'],[b.model]:['high'],[target]:['high']};
  doc.body.click();
  doc.querySelector<HTMLButtonElement>('#back')?.click();
  doc.querySelector<HTMLButtonElement>('#undo')?.click();
  click('#reload');await new Promise(r=>setTimeout(r,20));
 });
test('DD-605 T1/T3/T6 鼠标复制、取消勾选、差异与撤销',()=>{
 const trigger='button[data-apply-from="work.planning"]';
 click(trigger);
 expect(doc.querySelectorAll('.apply-popup input[type="checkbox"]').length).toBe(4);
 expect([...doc.querySelectorAll<HTMLInputElement>('.apply-popup input')].every(i=>!i.checked)).toBe(true);
 expect(doc.querySelector('.apply-popup')!.textContent).toContain('已相同');
 click('#cancel-apply');expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.querySelector('.footer-status')!.textContent).toBe('0 项修改待确认');
 click('button[data-path="work.planning"][data-field="model"]');
 click('[data-source="junbo"]');click(`[data-model="${target}"]`);
 click(trigger);
 expect(doc.querySelectorAll('.model-popup').length).toBe(0);
 expect([...doc.querySelectorAll<HTMLInputElement>('.apply-popup input')].every(i=>i.checked)).toBe(true);
 expect(doc.querySelector('.apply-popup')!.textContent).toContain('→');
 click('input[data-apply-target="work.testing"]');click('#apply-primary');
 expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.querySelector('.footer-status')!.textContent).toBe('4 项修改待确认');
 expect(doc.querySelector('button[data-path="work.testing"][data-field="model"]')!.textContent).not.toContain('骏伯');
 click('#diff');
 expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['规划','设计','前端开发','后端开发']);
 expect(doc.querySelector<HTMLButtonElement>('#save')!.disabled).toBe(false);
 click('#back');click(trigger);
 expect([...doc.querySelectorAll<HTMLInputElement>('.apply-popup input')].filter(i=>i.checked).map(i=>i.dataset.applyTarget)).toEqual(['work.testing']);
 click('button[data-path="work.frontend"][data-field="model"]');
 expect(doc.querySelector('.apply-popup')).toBeNull();doc.body.click();
 click('#undo');expect(doc.querySelector('.footer-status')!.textContent).toBe('0 项修改待确认');
 click(trigger);doc.body.click();expect(doc.querySelector('.apply-popup')).toBeNull();
});

// DD-606 T2/T5：拒绝不能改变页面草稿；预期来自 DD-604。
test('DD-606 拒绝原因可见，核对期间和失败不打开列表，重新核对后应用一项不改',async()=>{
 const trigger='button[data-apply-from="work.planning"]';
 click('#undo');
 click('button[data-path="work.planning"][data-field="model"]');click('[data-source="junbo"]');click(`[data-model="${target}"]`);
 const before=doc.querySelector('.footer-status')!.textContent;
 click(trigger);click('input[data-apply-target="work.testing"]');
 holdProbe=true;click('#refresh');click('#apply-primary');
 expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('核对');
 expect(doc.querySelector('.footer-status')!.textContent).toBe(before);
 click(trigger);expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('正在核对');
 expect(doc.querySelector('[data-apply-status]')?.getAttribute('role')).toBe('status');
 pendingProbe!({request_id:pendingId,gateway:{status:'failed'},sources:{},capabilities:{}});await new Promise(r=>setTimeout(r,20));holdProbe=false;
 click(trigger);expect(doc.querySelector('.apply-popup')).toBeNull();expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('核对失败');
 models={[a.model]:['high'],[b.model]:['high']};click('#refresh');await new Promise(r=>setTimeout(r,20));
 click(trigger);expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('模型已不在');
 expect(doc.querySelector('.footer-status')!.textContent).toBe(before);
 click('#diff');expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['规划']);click('#back');click('#undo');
 models={[a.model]:['high'],[b.model]:['high'],[target]:['high']};click('#refresh');await new Promise(r=>setTimeout(r,20));
});
test('DD-606 键盘入口、复选框名称、关闭与应用恢复焦点',()=>{
 const trigger=()=>doc.querySelector<HTMLButtonElement>('button[data-apply-from="work.planning"]')!;
 const key=(e:Element,k:string)=>e.dispatchEvent(new win.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
 expect(trigger().getAttribute('aria-label')).toBe('把规划的设置复制到其他工作');
 for(const close of ['Escape','cancel']){
  trigger().focus();key(trigger(),'Enter');
  const input=doc.querySelector<HTMLInputElement>('.apply-popup input')!;
  expect(doc.activeElement===input).toBe(true);
  expect(input.closest('label')!.textContent).toContain('设计：');
  expect(trigger().getAttribute('aria-expanded')).toBe('true');
  expect(doc.getElementById(trigger().getAttribute('aria-controls')!)?.getAttribute('role')).toBe('dialog');
  if(close==='Escape')key(input,'Escape');else if(close==='cancel')click('#cancel-apply');else doc.body.click();
  expect(doc.querySelector('.apply-popup')).toBeNull();expect(doc.activeElement===trigger()).toBe(true);
  expect(trigger().getAttribute('aria-expanded')).toBe('false');expect(doc.querySelector('.footer-status')!.textContent).toBe('0 项修改待确认');
 }
 key(trigger(),' ');click('input[data-apply-target="work.design"]');click('#apply-primary');
 expect(doc.activeElement===trigger()).toBe(true);expect(doc.querySelector('.apply-popup')).toBeNull();
});
test('DD-606 窄窗口列表靠右不出界、底部向上翻，resize/scroll 重定位',()=>{
 const trigger=doc.querySelector<HTMLButtonElement>('button[data-apply-from="work.planning"]')!;
 const original=trigger.getBoundingClientRect;
 const width=win.innerWidth,height=win.innerHeight;
 try {
 trigger.getBoundingClientRect=()=>({left:400,top:420,bottom:444,right:520,width:120,height:24,x:400,y:420,toJSON(){}});
 Object.defineProperty(win,'innerWidth',{value:530,configurable:true});Object.defineProperty(win,'innerHeight',{value:500,configurable:true});
 click('button[data-apply-from="work.planning"]');
 const popup=doc.querySelector<HTMLElement>('.apply-popup')!;
 Object.defineProperty(popup,'offsetWidth',{get:()=>510});Object.defineProperty(popup,'offsetHeight',{get:()=>300});
 win.dispatchEvent(new win.Event('resize'));
 expect(popup.style.left).toBe('10px');expect(popup.style.top).toBe('116px');expect(popup.style.maxHeight).toBe('406px');
 popup.style.left='999px';doc.dispatchEvent(new win.Event('scroll',{bubbles:true}));expect(popup.style.left).toBe('10px');
 const sheet=new win.CSSStyleSheet();sheet.replaceSync(readFileSync(new URL('./style.css',import.meta.url),'utf8'));
 expect([...sheet.cssRules].filter(r=>['.popup','.apply-popup'].includes((r as CSSStyleRule).selectorText)).map(r=>(r as CSSStyleRule).style.maxWidth)).toContain('calc(100vw - 24px)');
 } finally {doc.body.click();trigger.getBoundingClientRect=original;
 Object.defineProperty(win,'innerWidth',{value:width,configurable:true});Object.defineProperty(win,'innerHeight',{value:height,configurable:true});
 }
});
test('点外部控件关闭复制列表，焦点留在该控件',()=>{
 click('button[data-apply-from="work.planning"]');
 const control=doc.querySelector<HTMLSelectElement>('select[data-path="work.design"][data-field="agent"]')!;control.focus();control.click();
 expect(doc.querySelector('.apply-popup')).toBeNull();
 expect(doc.activeElement===control).toBe(true);
});
test('复制列表 Tab 与 picker 一样关闭，入口 Esc 也关闭，controls 仅在展开存在',()=>{
 const trigger=()=>doc.querySelector<HTMLButtonElement>('button[data-apply-from="work.planning"]')!;
 expect(trigger().hasAttribute('aria-controls')).toBe(false);
 trigger().click();
 doc.querySelector('.apply-popup input')!.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
 expect(doc.querySelector('.apply-popup')).toBeNull();expect(doc.activeElement===trigger()).toBe(true);
 expect(trigger().hasAttribute('aria-controls')).toBe(false);
 trigger().click();trigger().focus();trigger().dispatchEvent(new win.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
 expect(doc.querySelector('.apply-popup')).toBeNull();
});
test('拒绝提示随重绘保留，点另一入口或成功复制后清除',async()=>{
 models={[b.model]:['high']};click('#refresh');await new Promise(r=>setTimeout(r,20));
 click('button[data-apply-from="work.planning"]');
 expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('模型已不在');
 click('#help');expect(doc.querySelector('[data-apply-status]')?.textContent).toContain('模型已不在');
 models={[a.model]:['high'],[b.model]:['high']};click('#refresh');await new Promise(r=>setTimeout(r,20));
 click('button[data-apply-from="work.design"]');expect(doc.querySelector('[data-apply-status]')).toBeNull();
 click('input[data-apply-target="work.frontend"]');click('#apply-primary');
 expect(doc.querySelector('[data-apply-status]')).toBeNull();
});
test('已有修改时取消复制，原有修改与差异保持',()=>{
 click('button[data-path="work.planning"][data-field="model"]');click(`[data-model="${b.model}"]`);
 click('button[data-apply-from="work.planning"]');click('#cancel-apply');
 expect(doc.querySelector('.footer-status')!.textContent).toBe('1 项修改待确认');
 click('#diff');expect([...doc.querySelectorAll('.diff-panel article h3')].map(e=>e.textContent)).toEqual(['规划']);
 expect(doc.querySelector('.diff-panel')!.textContent).toContain('Claude Opus 5.5');
});
});

describe('DD-610 自动思考程度提示',()=>{
 beforeEach(async()=>{
  doc.body.click();doc.querySelector<HTMLButtonElement>('#back')?.click();click('#undo');
  models={[a.model]:['high'],[b.model]:['low','medium'],[target]:['high']};
  click('#reload');await new Promise(r=>setTimeout(r,20));
 });
 const change=()=>{click('button[data-path="work.planning"][data-field="model"]');click(`[data-model="${b.model}"]`);};
 const status=()=>doc.querySelector('.task-row [data-effort-note]');
 test('选择后该格显示就近档位和可读屏提示，差异显示原来和现在，再修改清除',()=>{
  change();expect(status()?.getAttribute('role')).toBe('status');
  expect(status()?.closest('.task-row')?.querySelector('[data-path="work.planning"]')).not.toBeNull();
  expect(status()?.textContent).toBe('思考程度已从“高”改为“中”，新模型不支持“高”');
  expect(doc.querySelector<HTMLSelectElement>('select[data-path="work.planning"][data-field="effort"]')!.value).toBe('medium');
  click('#diff');const text=doc.querySelector('.diff-panel')!.textContent!;
  expect(text).toContain('高');expect(text).toContain('中');click('#back');
  const effort=doc.querySelector<HTMLSelectElement>('select[data-path="work.design"][data-field="effort"]')!;
  effort.dispatchEvent(new win.Event('change',{bubbles:true}));expect(status()).toBeNull();
 });
 test('撤销和重新核对清除提示；有修改时重新读取被拒绝，提示保留',async()=>{
  change();expect(status()).not.toBeNull();click('#undo');expect(status()).toBeNull();
  change();click('#refresh');expect(status()).toBeNull();await new Promise(r=>setTimeout(r,20));
  click('#undo');change();click('#reload');expect(status()).not.toBeNull();
 });
});
