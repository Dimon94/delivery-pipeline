import {test,expect} from 'bun:test';
import {Draft,paths,type Config,type Evidence} from './draft';
import {Editor} from './editor';
// DD-577：Check 判别联合（T1–T8）与项状态（R4、R6–R9）。只穿过 Draft 的公开方法。
const ok={agent:'codex',model:'good@native',effort:'high'};
const base=():Config=>{
 const c={version:7,model_families:{},work:{},review:{implementation:{},'whole-change':{}},modes:{}} as unknown as Config;
 for(const p of paths){const k=p.split('.');if(k[0]==='work')c.work[k[1]!]={...ok,fallbacks:[]};else c.review[k[1]!]![k[2]!]={...ok,candidates:[]};}
 return c;
};
const evidence=(request:string,gateway:'ok'|'unreachable'='ok',over:Partial<Evidence>={}):Evidence=>({
 request_id:request,observed_at:'now',gateway:{status:gateway},
 capabilities:{codex:{binary:true,models:{'good@native':['low','high']}},pi:{binary:true,models:{'pi/m':['low']}},claude:{binary:false,models:{}}},
 sources:{codex:{status:'ok',next_step:''},pi:{status:'ok',next_step:''},claude:{status:'unknown',next_step:'请核对',reason:'未取得完整证据链'}},...over});
const checked=(d:Draft,id='r')=>{d.beginProbe(id);expect(d.acceptProbe(evidence(id))).toBe(true);return d;};

test('T1/T8：新建、保存成功、恢复后的 Draft 都从 idle 开始',async()=>{
 expect(new Draft(base()).check).toEqual({kind:'idle'});
 const config=base(),e=new Editor({config,base_hash:'h',file_state:'ready',cells:{}});
 checked(e.state.draft);e.state.draft.select('work.planning','effort','low');e.preview();
 await e.save(async c=>({status:'applied',config:c,base_hash:'new',changed:true}));
 expect(e.state.draft.check).toEqual({kind:'idle'});
 const u=new Editor({config,base_hash:'h',file_state:'ready',cells:{}});checked(u.state.draft);u.state.draft.select('work.planning','effort','low');u.preview();
 await u.save(async()=>({status:'commit_unverified'}));expect(u.state.kind).toBe('uncertain');
 expect(u.recover({config,base_hash:'h2',file_state:'ready',cells:{}})).toBe(true);
 expect(u.state.draft.check).toEqual({kind:'idle'});
});
test('T2/T3：按证据里的 gateway.status 进入 checked 或 unreachable/gateway',()=>{
 const a=new Draft(base());a.beginProbe('a');expect(a.acceptProbe(evidence('a','ok'))).toBe(true);
 expect(a.check.kind).toBe('checked');
 // 网关挂了时 sources 仍可能写 ok（证据层字段才是依据），必须仍然判为无法核对。
 const b=new Draft(base());b.beginProbe('b');expect(b.acceptProbe(evidence('b','unreachable'))).toBe(true);
 expect(b.check).toEqual({kind:'unreachable',cause:'gateway'});
 expect(b.valid()).toBe(true);b.select('work.planning','effort','low');expect(b.valid()).toBe(false);
});
test('T4：当前请求失败进入 unreachable/call_failed，旧请求失败被忽略',()=>{
 const d=new Draft(base());d.beginProbe('old');d.beginProbe('new');
 d.failProbe('old');expect(d.check).toEqual({kind:'checking',request:'new'});
 d.failProbe('new');expect(d.check).toEqual({kind:'unreachable',cause:'call_failed'});
 d.failProbe('new');expect(d.check).toEqual({kind:'unreachable',cause:'call_failed'});
});
test('T5/T6：unreachable 与 checked 下重新核对都回到 checking',()=>{
 const d=new Draft(base());d.beginProbe('1');d.failProbe('1');d.beginProbe('2');expect(d.check).toEqual({kind:'checking',request:'2'});
 d.acceptProbe(evidence('2'));expect(d.check.kind).toBe('checked');
 d.beginProbe('3');expect(d.check).toEqual({kind:'checking',request:'3'});
});
test('T7/R2：旧请求晚到的结果与失败都不改变状态（两种到达顺序）',async()=>{
 const d=new Draft(base());d.beginProbe('old');d.beginProbe('new');
 const lateOld=new Promise<boolean>(r=>setTimeout(()=>r(d.acceptProbe(evidence('old','unreachable'))),10));
 const lateFail=new Promise<void>(r=>setTimeout(()=>{d.failProbe('old');r();},15));
 expect(d.acceptProbe(evidence('new'))).toBe(true);
 expect(await lateOld).toBe(false);await lateFail;
 expect(d.check.kind).toBe('checked');expect(d.check.kind==='checked'&&d.check.evidence.request_id).toBe('new');
 // 旧结果先于新结果到达：仍在 checking。
 const e=new Draft(base());e.beginProbe('old');e.beginProbe('new');
 expect(e.acceptProbe(evidence('old'))).toBe(false);expect(e.check).toEqual({kind:'checking',request:'new'});
});
test('R1/R3：核对开始、成功、失败前后，草稿与差异完全不变',()=>{
 const d=new Draft(base());d.select('work.design','model','x@native');d.editFallbacks('planning',{kind:'add',item:{agent:'pi',model:'pi/m',effort:'low'}});
 const config=structuredClone(d.config),changes=[...d.changes()];
 expect(changes.length).toBeGreaterThan(0);
 const same=()=>{expect(d.config).toEqual(config);expect(d.changes()).toEqual(changes);};
 d.beginProbe('a');same();d.acceptProbe(evidence('a'));same();
 d.beginProbe('b');same();d.failProbe('b');same();
 d.beginProbe('c');d.acceptProbe(evidence('c','unreachable'));same();
});
test('R4：五种项状态各一，且按 未选完 > 工具不可用 > 需换模型 > 需换档位 判定',()=>{
 const c=base();
 c.work.planning={...ok,effort:'',fallbacks:[]};
 c.work.design={agent:'claude',model:'any',effort:'high',fallbacks:[]};
 c.work.frontend={...ok,model:'gone@native',fallbacks:[]};
 c.work.backend={...ok,effort:'max',fallbacks:[]};
 const d=checked(new Draft(c));
 const kind=(p:string)=>d.status(p).primary.kind;
 expect(['planning','design','frontend','backend','testing'].map(n=>kind(`work.${n}`))).toEqual(['incomplete','tool_off','model_gone','effort_gone','ok']);
 // 同时满足多条时命中靠前者：工具不可用 + 模型不在 + 档位不在 → 工具不可用；未选完 + 工具不可用 → 未选完。
 const e=base();
 e.work.planning={agent:'claude',model:'gone',effort:'max',fallbacks:[]};
 e.work.design={agent:'claude',model:'',effort:'high',fallbacks:[]};
 e.work.frontend={...ok,model:'gone@native',effort:'max',fallbacks:[]};
 const f=checked(new Draft(e));
 expect(['planning','design','frontend'].map(n=>f.status(`work.${n}`).primary.kind)).toEqual(['tool_off','incomplete','model_gone']);
 const tool=f.status('work.planning').primary;expect(tool.kind==='tool_off'&&tool.reason).toBe('未取得完整证据链');
});
test('R4（DD-578）：清单里有该模型、档位也不在，但来源不是 ok → 仍是工具不可用，不是需换档位',()=>{
 const c=base();c.work.planning={...ok,effort:'max',fallbacks:[]};
 const d=new Draft(c);d.beginProbe('r');
 d.acceptProbe(evidence('r','ok',{sources:{codex:{status:'unknown',next_step:'请核对',reason:'来源不可靠'},pi:{status:'ok',next_step:''},claude:{status:'ok',next_step:''}}}));
 expect(d.status('work.planning').primary.kind).toBe('tool_off');
 // 来源恢复 ok 后，同一配置才落到需换档位。
 const g=checked(new Draft(c));expect(g.status('work.planning').primary.kind).toBe('effort_gone');
});
test('状态随核对阶段：checking 全部是核对中；idle/unreachable 全部是未核实',()=>{
 const c=base();c.work.planning.fallbacks=[{...ok},{agent:'pi',model:'pi/m',effort:'low'}];
 const d=new Draft(c);
 const all=()=>paths.flatMap(p=>{const s=d.status(p);return [s.primary.kind,...s.queue.map(q=>q.kind)];});
 expect(new Set(all())).toEqual(new Set(['unverified']));
 d.beginProbe('a');expect(new Set(all())).toEqual(new Set(['checking']));
 d.acceptProbe(evidence('a','unreachable'));expect(new Set(all())).toEqual(new Set(['unverified']));
 expect(d.status('work.planning').takeover).toBeNull();
});
test('R6：计数等于主选或队列有非可用项的格数；非 checked 为 0',()=>{
 const c=base();
 c.work.frontend={...ok,model:'gone@native',fallbacks:[]};                       // 主选坏
 c.work.backend={...ok,fallbacks:[{...ok,effort:'max'}]};                       // 只有备用坏
 c.work.testing={...ok,fallbacks:[{...ok},{agent:'pi',model:'pi/m',effort:'low'}]}; // 全好
 const d=new Draft(c);expect(d.attention()).toBe(0);
 d.beginProbe('a');expect(d.attention()).toBe(0);
 d.acceptProbe(evidence('a'));expect(d.attention()).toBe(2);
 d.beginProbe('b');expect(d.attention()).toBe(0);
 d.acceptProbe(evidence('b','unreachable'));expect(d.attention()).toBe(0);
 // 检查格的候选坏也算一格。
 c.review.implementation!.spec!.candidates=[{...ok,model:'gone@native'}];
 expect(checked(new Draft(c)).attention()).toBe(3);
});
test('R7：无法核对时选择与新增锁定，删除与调序仍生效；只有 checked 可编辑',()=>{
 const c=base();c.work.planning.fallbacks=[{...ok},{...ok,effort:'low'},{...ok,effort:'high'}];
 c.review.implementation!.spec!.candidates=[{...ok},{...ok,effort:'low'}];
 const d=new Draft(c);
 expect(d.canEdit()).toEqual({select:false,addToQueue:false});
 d.beginProbe('a');expect(d.canEdit()).toEqual({select:false,addToQueue:false});
 d.acceptProbe(evidence('a'));expect(d.canEdit()).toEqual({select:true,addToQueue:true});
 d.beginProbe('b');d.acceptProbe(evidence('b','unreachable'));
 expect(d.canEdit()).toEqual({select:false,addToQueue:false});
 d.editFallbacks('planning',{kind:'move',index:0,to:1});d.editFallbacks('planning',{kind:'remove',index:2});
 d.editCandidates('review.implementation.spec',{kind:'move',index:0,to:1});d.editCandidates('review.implementation.spec',{kind:'remove',index:1});
 expect(d.config.work.planning!.fallbacks).toEqual([{...ok,effort:'low'},{...ok}]);
 expect(d.config.review.implementation!.spec!.candidates).toEqual([{...ok,effort:'low'}]);
 d.beginProbe('c');d.failProbe('c');expect(d.canEdit()).toEqual({select:false,addToQueue:false});
});
test('R8：来源不是 ok 的工具置灰并带原因；已选中的仍显示并标工具不可用',()=>{
 const c=base();c.work.design={agent:'claude',model:'m',effort:'high',fallbacks:[]};
 const d=new Draft(c);
 expect(d.agentChoices().every(a=>!a.enabled)).toBe(true);
 d.beginProbe('a');d.acceptProbe(evidence('a'));
 const by=Object.fromEntries(d.agentChoices().map(a=>[a.agent,a]));
 expect(by.pi).toMatchObject({enabled:true});expect(by.codex).toMatchObject({enabled:true});
 expect(by.claude).toEqual({agent:'claude',enabled:false,reason:'未取得完整证据链'});
 expect(d.config.work.design!.agent).toBe('claude');expect(d.status('work.design').primary.kind).toBe('tool_off');
 d.beginProbe('b');d.acceptProbe(evidence('b','unreachable'));expect(d.agentChoices().every(a=>!a.enabled)).toBe(true);
});
test('R9：主选不可用时给出接替：第一个可用备用 / 无可用备用 / 候选可用数；主选可用为 null',()=>{
 const c=base(),bad={...ok,model:'gone@native'};
 c.work.planning={...bad,fallbacks:[{...bad},{...ok},{...ok}]};
 c.work.design={...bad,fallbacks:[{...bad},{...bad,effort:''}]};
 c.work.frontend={...ok,fallbacks:[{...bad}]};
 c.work.backend={...bad,fallbacks:[]};
 c.review.implementation!.standards={...bad,candidates:[{...ok},{...bad},{...ok,effort:'low'}]};
 c.review.implementation!.spec={...bad,candidates:[{...bad}]};
 c.review['whole-change']!.standards={...ok,candidates:[{...bad}]};
 const d=checked(new Draft(c)),t=(p:string)=>d.status(p).takeover;
 expect(t('work.planning')).toEqual({kind:'fallback',index:1});
 expect(t('work.design')).toEqual({kind:'none'});
 expect(t('work.frontend')).toBeNull();
 expect(t('work.backend')).toEqual({kind:'none'});
 expect(t('review.implementation.standards')).toEqual({kind:'candidates',usable:2});
 expect(t('review.implementation.spec')).toEqual({kind:'candidates',usable:0});
 expect(t('review.whole-change.standards')).toBeNull();
});
test('R10：队列标签与逐项状态，顺序同配置，k 为非可用项个数',()=>{
 const c=base();
 c.work.planning.fallbacks=[{...ok},{...ok,model:'gone@native'},{...ok,effort:''},{...ok,effort:'max'}];
 c.review.implementation!.spec!.candidates=[{agent:'claude',model:'x',effort:'low'},{...ok}];
 const d=checked(new Draft(c));
 const w=d.status('work.planning'),r=d.status('review.implementation.spec');
 expect(w.queueLabel).toBe('备用');expect(r.queueLabel).toBe('候选');
 expect(w.queue.map(q=>q.kind)).toEqual(['ok','model_gone','incomplete','effort_gone']);
 expect(w.queue.filter(q=>q.kind!=='ok').length).toBe(3);
 expect(r.queue.map(q=>q.kind)).toEqual(['tool_off','ok']);
 expect(d.status('work.design').queue).toEqual([]);
});
