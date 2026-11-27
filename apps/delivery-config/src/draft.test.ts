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
