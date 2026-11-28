import {test,expect} from 'bun:test';
import {Window} from 'happy-dom';
import {Draft, type Config} from './draft';

function makeV9Config():Config {
 const a={agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'};
 return {
  version:9,
  dispatch:{parallel:4,max_turns:100},
  model_families:{},
  work:{
   planning:{...a,fallbacks:[],label:'规划',hint:'拆需求、定方案',purpose:'planning'},
   design:{...a,fallbacks:[],label:'设计',hint:'界面与交互',purpose:'code'},
   frontend:{...a,fallbacks:[],label:'前端开发',hint:'写页面代码',purpose:'code'},
   backend:{...a,fallbacks:[],label:'后端开发',hint:'写服务端代码',purpose:'code'},
   testing:{...a,fallbacks:[],label:'测试',hint:'写测试并验证',purpose:'checks'},
  },
  review:{
   implementation:{standards:{...a,candidates:[]},spec:{...a,candidates:[]}},
   'whole-change':{standards:{...a,candidates:[]},spec:{...a,candidates:[]}},
  },
  modes:{fast:{kind:'direct',agents:{pi:{starting:{model:a.model,effort:'low'},execution:{model:a.model,effort:'low'},direct:{model:a.model,effort:'low'}}}}},
 };
}

test('DD-686 设置页 UI：S2 新增、S3 删除与禁用提示、S4 校验拒绝、S5 离线/不可用放行与拦阻、其他设置只展示 modes', async()=>{
 const win=new Window(),doc=win.document;
 const initial=makeV9Config();
 let savedCandidate:Config|undefined;
 const call=async(name:string,...args:unknown[])=>{
  if(name==='Host.AppInfo')return {config_path:'/tmp/dd686-ui.json',config_kind:'test'};
  if(name==='Host.ReadConfig')return {file_state:'ready',config:structuredClone(initial),base_hash:'h1',cells:{}};
  if(name==='Host.ProbeCapabilities')return {
   request_id:args[0],
   observed_at:'now',
   gateway:{status:'ok'},
   sources:{pi:{status:'ok',next_step:''}},
   capabilities:{pi:{binary:true,models:{'magpie/auto/gpt-6.1-sol':['low','high']}}},
  };
  if(name==='Host.Apply'){
   savedCandidate=structuredClone(args[0] as Config);
   return {status:'applied',config:savedCandidate,base_hash:'h2',changed:true};
  }
  throw Error(name);
 };
 Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call}});
 doc.body.innerHTML='<div id="app"></div>';
 try {
  await import('./main?dd686-ui');
  await new Promise(r=>setTimeout(r,30));
  const click=(sel:string)=>{const el=doc.querySelector<HTMLButtonElement>(sel);expect(el).not.toBeNull();el!.click();};
  const setVal=(sel:string,val:string,ev:'input'|'change'='input')=>{
   const el=doc.querySelector<HTMLInputElement|HTMLSelectElement>(sel)!;
   el.value=val;
   el.dispatchEvent(new win.Event(ev,{bubbles:true}));
  };

  // 其他设置只展示 modes 摘要
  expect(doc.querySelector('.readonly-grid')).toBeNull();
  expect(doc.querySelector('.read-only')!.textContent).toContain('fast');

  // S4：新增弹层拒绝非法 id、保留词、重复 id、空 label
  click('#add-task-type');
  expect([...doc.querySelectorAll<HTMLOptionElement>('[data-task-field="purpose"] option')].map(o=>o.textContent)).toEqual(['规划','写代码并提交','产出文档','测试验证','只读咨询']);
  setVal('[data-task-field="id"]','Bad Id');setVal('[data-task-field="label"]','测试');click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog-error')!.textContent).toContain('小写字母');
  setVal('[data-task-field="id"]','review');click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog-error')!.textContent).toContain('保留词');
  setVal('[data-task-field="id"]','planning');click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog-error')!.textContent).toContain('已存在');
  setVal('[data-task-field="id"]','advisory-doc');setVal('[data-task-field="label"]','   ');click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog-error')!.textContent).toContain('显示名称');
  expect(doc.querySelectorAll('[data-task-row]').length).toBe(5);

  // S2：合法新增 advisory-doc，行带用途徽标，差异面板列出新增项，保存为 v9 且 modes 不变
  setVal('[data-task-field="id"]','advisory-doc');
  setVal('[data-task-field="label"]','咨询建议');
  setVal('[data-task-field="hint"]','提供架构与方案建议');
  setVal('[data-task-field="purpose"]','artifact','change');
  setVal('[data-task-field="agent"]','pi','change');
  setVal('[data-task-field="model"]','magpie/auto/gpt-6.1-sol','change');
  setVal('[data-task-field="effort"]','high','change');
  click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog')).toBeNull();
  const row=doc.querySelector('[data-task-row="advisory-doc"]')!;
  expect(row).not.toBeNull();
  expect(row.querySelector('.purpose-badge')!.textContent).toBe('产出文档');
  click('#diff');
  expect(doc.querySelector('.diff-panel')!.textContent).toContain('咨询建议');
  expect(doc.querySelector('.diff-panel')!.textContent).toContain('已新增');
  expect(doc.querySelector<HTMLButtonElement>('#save')!.disabled).toBe(false);
  click('#save');
  await new Promise(r=>setTimeout(r,30));
  expect(savedCandidate!.version).toBe(9);
  expect(savedCandidate!.work['advisory-doc']).toEqual({
   agent:'pi',
   model:'magpie/auto/gpt-6.1-sol',
   effort:'high',
   fallbacks:[],
   label:'咨询建议',
   hint:'提供架构与方案建议',
   purpose:'artifact',
  });
  expect(savedCandidate!.modes).toEqual(initial.modes);

  // S3：删除 frontend 和 design 成功，此后 backend/planning/testing 删除按钮禁用并提示
  click('[data-remove-task="frontend"]');
  click('[data-remove-task="design"]');
  expect(doc.querySelector('[data-task-row="frontend"]')).toBeNull();
  expect(doc.querySelector('[data-task-row="design"]')).toBeNull();
  const backendRm=doc.querySelector<HTMLButtonElement>('[data-remove-task="backend"]')!;
  const planningRm=doc.querySelector<HTMLButtonElement>('[data-remove-task="planning"]')!;
  const testingRm=doc.querySelector<HTMLButtonElement>('[data-remove-task="testing"]')!;
  expect(backendRm.disabled).toBe(true);
  expect(backendRm.title).toBe('至少需保留一个「写代码并提交」类型');
  expect(planningRm.disabled).toBe(true);
  expect(planningRm.title).toBe('至少需保留一个「规划」类型');
  expect(testingRm.disabled).toBe(true);
  expect(testingRm.title).toBe('至少需保留一个「测试验证」类型');
  // 编辑最后一个 code 类型的用途为其他值被拒并显示原因
  click('[data-edit-task="backend"]');
  setVal('[data-task-field="purpose"]','artifact','change');
  click('#submit-task-dialog');
  expect(doc.querySelector('.task-dialog-error')!.textContent).toBe('至少需保留一个「写代码并提交」类型');
  click('#cancel-task-dialog');
  click('#diff');
  expect(doc.querySelector('.diff-panel')!.textContent).toContain('已删除');
  expect(doc.querySelector<HTMLButtonElement>('#save')!.disabled).toBe(false);
 } finally {
  await win.happyDOM.close();
 }
});

test('ST-4/S8: v8 可选任务在桌面升级候选里保留与后端迁移一致的 purpose 和 hint',()=>{
 const v8:Config={
  version:8,
  model_families:{},
  dispatch:{parallel:4,max_turns:100},
  work:{
   ...Object.fromEntries(['planning','design','frontend','backend','testing'].map(n=>[n,{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high',fallbacks:[]}])),
   research:{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'},
   coordinator:{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high'},
  },
  review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(a=>[a,{agent:'pi',model:'magpie/auto/gpt-6.1-sol',effort:'high',candidates:[]}]))])),
  modes:{},
 };
 const d=new Draft(v8);
 d.setBudget('parallel',2);
 expect(d.changes()).toEqual(['dispatch.parallel']);
 const cand=d.candidate();
 expect(cand.work.research?.purpose).toBe('artifact');
 expect(cand.work.research?.hint).toBe('独立调查与搜索');
 expect(cand.work.coordinator?.purpose).toBe('advisory');
 expect(cand.work.coordinator?.hint).toBe('当前协调会话的推荐观测值');
});
