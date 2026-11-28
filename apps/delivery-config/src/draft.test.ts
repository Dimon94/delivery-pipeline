import {test,expect} from 'bun:test';
import {Draft,cell,paths,type Config,type Evidence} from './draft';
const original = {version:5,work:{},review:{implementation:{},'whole-change':{}},modes:{keep:{kind:'direct'}}} as Config;
for(const p of paths){const keys=p.split('.');if(keys[0]==='work')original.work[keys[1]!] = {agent:'codex',model:'exact@native',effort:'high'};else original.review[keys[1]!]![keys[2]!] = {agent:'codex',model:'exact@native',effort:'high'};}
original.work.research={agent:'pi',model:'untouched',effort:'low'};
test('旧请求不能覆盖新选择；失效档位重选；只读值与撤销保留',async()=>{
 const d=new Draft(original);d.beginProbe('old');d.select('work.frontend','model','new');d.beginProbe('new');
 const e={request_id:'new',observed_at:'now',gateway:{status:'ok'},capabilities:{codex:{binary:true,models:{new:['low']}}},sources:{codex:{status:'ok',next_step:''}}} as Evidence;
 const delayed = new Promise<boolean>(resolve=>setTimeout(()=>resolve(d.acceptProbe({...e,request_id:'old'})),20));
 expect(d.acceptProbe(e)).toBe(true);expect(await delayed).toBe(false);
 expect(cell(d.config,'work.frontend').effort).toBe('');expect(d.valid()).toBe(false);
 d.select('work.frontend','effort','low');expect(d.valid()).toBe(true);
 expect(d.config.work.research).toEqual(original.work.research);expect(d.config.modes).toEqual(original.modes);
 d.undo();expect(d.changes()).toEqual([]);expect(original.work.frontend!.model).toBe('exact@native');
});
test('完整有序备用含重复位置，经编辑、差异和撤销保留',()=>{
 const initial=structuredClone(original);for(const n of ['planning','design','frontend','backend','testing'])initial.work[n]!.fallbacks=[];
 const d=new Draft(initial),a={agent:'pi',model:'native',effort:'high'},b={...a,effort:'low'};
 d.beginProbe('list');d.acceptProbe({request_id:'list',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{native:['high','low']}}}});
 for(const item of [b,a,b,a])d.editFallbacks('planning',{kind:'add',item});
 expect(d.config.work.planning!.fallbacks).toEqual([b,a,b,a]);expect(d.valid()).toBe(true);
 d.editFallbacks('planning',{kind:'move',index:3,to:0});d.editFallbacks('planning',{kind:'remove',index:3});
 expect(d.config.work.planning!.fallbacks).toEqual([a,b,a]);expect(d.changes()).toContain('work.planning');
 d.undo();expect(d.config.work.planning!.fallbacks).toEqual([]);
});
test('备用与主模型可随时互换或提为主用，离线置换已有项仍可保存，失效项升为主用被拦',()=>{
 const p={agent:'pi',model:'m1',effort:'high'},f1={agent:'pi',model:'m2',effort:'medium'},f2={agent:'pi',model:'m3',effort:'low'};
 const initial=structuredClone(original);
 initial.work.design={...p,fallbacks:[f1]};
 initial.work.frontend={...p,fallbacks:[f1,f2]};
 initial.review.implementation!.standards={...p,candidates:[f1,f2]};
 // 未核对/离线时，在已有主备间切换仍有效（R7）
 const offline=new Draft(initial);
 offline.editFallbacks('design',{kind:'promote',index:0});
 expect(offline.config.work.design).toEqual({...f1,fallbacks:[p]});
 expect(offline.valid()).toBe(true);
 // 多备用：把备用 2 设为主用，原主模型顺延到备用 1
 offline.editFallbacks('frontend',{kind:'promote',index:1});
 expect(offline.config.work.frontend).toEqual({...f2,fallbacks:[p,f1]});
 // 备用 1 上移（to: -1）等价于升为主用
 offline.editFallbacks('frontend',{kind:'move',index:0,to:-1});
 expect(offline.config.work.frontend).toEqual({...p,fallbacks:[f2,f1]});
 // 结果检查候选同样支持设为主用
 offline.editCandidates('review.implementation.standards',{kind:'promote',index:0});
 expect(offline.config.review.implementation!.standards).toEqual({...f1,candidates:[p,f2]});
 expect(offline.valid()).toBe(true);
 offline.undo();expect(offline.config).toEqual(initial);
 // 核对后，把不可用备用设为主用不能通过校验
 const online=new Draft(initial);
 online.beginProbe('p');
 online.acceptProbe({request_id:'p',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{m1:['high'],m2:['medium']}}}});
 online.editFallbacks('frontend',{kind:'promote',index:1}); // m3 不在可用清单
 expect(online.valid()).toBe(false);
 online.editFallbacks('design',{kind:'promote',index:0}); // m2 可用
 expect(online.config.work.design!.model).toBe('m2');
});

function v9Base():Config {
 const ok={agent:'pi',model:'m1',effort:'high'};
 return {
  version:9,
  dispatch:{parallel:4,max_turns:100},
  model_families:{},
  work:{
   planning:{...ok,fallbacks:[],label:'规划',hint:'拆需求、定方案',purpose:'planning'},
   design:{...ok,fallbacks:[],label:'设计',hint:'界面与交互',purpose:'code'},
   frontend:{...ok,fallbacks:[],label:'前端开发',hint:'写页面代码',purpose:'code'},
   backend:{...ok,fallbacks:[],label:'后端开发',hint:'写服务端代码',purpose:'code'},
   testing:{...ok,fallbacks:[],label:'测试',hint:'写测试并验证',purpose:'checks'},
  },
  review:{
   implementation:{standards:{...ok,candidates:[]},spec:{...ok,candidates:[]}},
   'whole-change':{standards:{...ok,candidates:[]},spec:{...ok,candidates:[]}},
  },
  modes:{fast:{kind:'direct',agents:{pi:{starting:{model:'m1',effort:'low'},execution:{model:'m1',effort:'low'},direct:{model:'m1',effort:'low'}}}}},
 };
}

function v8Base():Config {
 const ok={agent:'pi',model:'m1',effort:'high'};
 return {
  version:8,
  dispatch:{parallel:4,max_turns:100},
  model_families:{},
  work:{
   planning:{...ok,fallbacks:[]},
   design:{...ok,fallbacks:[]},
   frontend:{...ok,fallbacks:[]},
   backend:{...ok,fallbacks:[]},
   testing:{...ok,fallbacks:[]},
  },
  review:{
   implementation:{standards:{...ok,candidates:[]},spec:{...ok,candidates:[]}},
   'whole-change':{standards:{...ok,candidates:[]},spec:{...ok,candidates:[]}},
  },
  modes:{keep:{kind:'direct'}},
 };
}

const okEvidence:Evidence={
 request_id:'req-1',
 observed_at:'now',
 gateway:{status:'ok'},
 sources:{pi:{status:'ok',next_step:''}},
 capabilities:{pi:{binary:true,models:{m1:['low','high'],m2:['medium','high']}}},
};

test('DD-686 S2：新增 advisory-doc 后 candidate 为 version 9 含全部字段且 modes 不变',()=>{
 const base=v9Base();
 const d=new Draft(base);
 d.beginProbe('req-1');
 d.acceptProbe(okEvidence);
 expect(d.addTaskType({
  id:'advisory-doc',
  label:'咨询建议',
  hint:'提供架构与方案建议',
  purpose:'artifact',
  agent:'pi',
  model:'m2',
  effort:'medium',
 })).toEqual({ok:true});
 expect(d.workIds()).toContain('advisory-doc');
 expect(d.taskMeta('advisory-doc')).toEqual({label:'咨询建议',hint:'提供架构与方案建议',purpose:'artifact'});
 expect(d.changes()).toEqual(['work.advisory-doc']);
 expect(d.valid()).toBe(true);
 const cand=d.candidate();
 expect(cand.version).toBe(9);
 expect(cand.work['advisory-doc']).toEqual({
  agent:'pi',
  model:'m2',
  effort:'medium',
  fallbacks:[],
  label:'咨询建议',
  hint:'提供架构与方案建议',
  purpose:'artifact',
 });
 expect(cand.modes).toEqual(base.modes);
});

test('DD-686 S3：删 frontend/design 成功，删最后一个 code/planning/checks 或改其用途返回 last_required_purpose',()=>{
 const d=new Draft(v9Base());
 expect(d.removeTaskType('frontend')).toEqual({ok:true});
 expect(d.removeTaskType('design')).toEqual({ok:true});
 expect(d.changes()).toEqual(['work.design','work.frontend']);
 const remaining=d.workIds();
 expect(remaining).toEqual(['planning','backend','testing']);
 for(const [id,purpose] of [['backend','code'],['planning','planning'],['testing','checks']] as const){
  expect(d.canRemoveTaskType(id)).toEqual({ok:false,reason:'last_required_purpose',purpose});
  expect(d.removeTaskType(id)).toEqual({ok:false,error:'last_required_purpose'});
  expect(d.workIds()).toEqual(remaining);
 }
 // 把最后一个 code 类型的用途改为其他值同样被拒
 expect(d.updateTaskTypeMeta('backend',{purpose:'artifact'})).toEqual({ok:false,error:'last_required_purpose'});
 expect(d.taskMeta('backend').purpose).toBe('code');
 // 只改最后一个必需用途的 label/hint 允许
 expect(d.updateTaskTypeMeta('backend',{label:'服务端',hint:'API 实现'})).toEqual({ok:true});
 expect(d.taskMeta('backend')).toEqual({label:'服务端',hint:'API 实现',purpose:'code'});
});

test('DD-686 S4：非法 id、保留词、重复 id、空 label 均被拒绝且草稿不变',()=>{
 const d=new Draft(v9Base());
 const beforeIds=d.workIds();
 expect(d.addTaskType({id:'Advisory-Doc',label:'咨询',purpose:'artifact'})).toEqual({ok:false,error:'invalid_id'});
 expect(d.addTaskType({id:'advisory doc',label:'咨询',purpose:'artifact'})).toEqual({ok:false,error:'invalid_id'});
 expect(d.addTaskType({id:'',label:'咨询',purpose:'artifact'})).toEqual({ok:false,error:'invalid_id'});
 for(const reserved of ['review','map','all']){
  expect(d.addTaskType({id:reserved,label:'保留',purpose:'artifact'})).toEqual({ok:false,error:'reserved_id'});
 }
 expect(d.addTaskType({id:'planning',label:'重复',purpose:'planning'})).toEqual({ok:false,error:'duplicate_id'});
 expect(d.addTaskType({id:'new-doc',label:'   ',purpose:'artifact'})).toEqual({ok:false,error:'empty_label'});
 expect(d.addTaskType({id:'new-doc',label:'Unknown',purpose:'artifact'})).toEqual({ok:false,error:'empty_label'});
 expect(d.workIds()).toEqual(beforeIds);
 expect(d.changes()).toEqual([]);
});

test('DD-686 S5：能力不可用但三元组未改时改元信息或删可选类型 valid 为真；新增或改模型无证据时 valid 为假',()=>{
 const base=v9Base();
 base.work.backend!.model='gone-model';
 const d=new Draft(base);
 d.beginProbe('req-1');
 d.acceptProbe(okEvidence);
 // 原模型不可用、三元组未改，只改 label/hint 和删除可选类型 frontend → valid 为真
 expect(d.updateTaskTypeMeta('backend',{label:'核心后端',hint:'新说明'})).toEqual({ok:true});
 expect(d.removeTaskType('frontend')).toEqual({ok:true});
 expect(d.valid()).toBe(true);
 // 离线/未核对时同样成立
 const offline=new Draft(base);
 expect(offline.updateTaskTypeMeta('backend',{label:'核心后端'})).toEqual({ok:true});
 expect(offline.removeTaskType('design')).toEqual({ok:true});
 expect(offline.valid()).toBe(true);
 // 新增类型而所选三元组不在能力证据中 → valid 为假
 expect(d.addTaskType({id:'advisory-doc',label:'咨询建议',purpose:'artifact',agent:'pi',model:'missing',effort:'high'})).toEqual({ok:true});
 expect(d.valid()).toBe(false);
 // 改现有类型模型到不在能力证据中的值 → valid 为假
 const d2=new Draft(base);
 d2.beginProbe('req-1');
 d2.acceptProbe(okEvidence);
 d2.select('work.planning','model','missing');
 expect(d2.valid()).toBe(false);
});

test('DD-686 S8：v8 加载后 changes 为空；改一格模型后 candidate 为 version 9 且补齐 taskMeta 默认元信息，modes 不变',()=>{
 const base=v8Base();
 const d=new Draft(base);
 expect(d.changes()).toEqual([]);
 d.beginProbe('req-1');
 d.acceptProbe(okEvidence);
 d.select('work.planning','model','m2');
 expect(d.changes()).toEqual(['work.planning']);
 expect(d.valid()).toBe(true);
 const cand=d.candidate();
 expect(cand.version).toBe(9);
 expect(cand.modes).toEqual(base.modes);
 expect(cand.work.planning).toMatchObject({label:'规划',hint:'拆需求、定方案',purpose:'planning',model:'m2'});
 expect(cand.work.design).toMatchObject({label:'设计',hint:'界面与交互',purpose:'code'});
 expect(cand.work.frontend).toMatchObject({label:'前端开发',hint:'写页面代码',purpose:'code'});
 expect(cand.work.backend).toMatchObject({label:'后端开发',hint:'写服务端代码',purpose:'code'});
 expect(cand.work.testing).toMatchObject({label:'测试',hint:'写测试并验证',purpose:'checks'});
});
