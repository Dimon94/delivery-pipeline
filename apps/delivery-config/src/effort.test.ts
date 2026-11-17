import {test,expect} from 'bun:test';
import {Draft,cell,paths,nearestEffort, type Config,type Evidence} from './draft';
// 独立预期来自 DD-607 的固定顺序与手算距离，不依赖核对结果的排列。
test('DD-610 就近、平局取低、乱序、支持原值及未知档位',()=>{
 for(const [current,supported,want] of [
 ['xhigh',['low','medium','high'],'high'],['xhigh',['high','max'],'high'],
 ['medium',['high','low'],'low'],['medium',['low','high'],'low'],
 ['high',['high'],'high'],['',['high'],''],['turbo',['high'],''],
 ['high',['turbo'],''],['turbo',['turbo'],'turbo'],['high',[],''],
 ['xhigh',['turbo','low','high'],'high'],['ultra',['none','max'],'max'],
 ] as [string,string[],string][])expect(nearestEffort(current,supported)).toBe(want);
});
const a={agent:'pi',model:'old',effort:'xhigh'};
const original:Config={work:{planning:{...a,fallbacks:[{...a}]}},review:{implementation:{spec:{...a,candidates:[{...a}]}}},modes:{}};
for(const path of paths){const p=path.split('.');if(p[0]==='work')original.work[p[1]!]??={...a,fallbacks:[]};else (original.review[p[1]!]??={})[p[2]!]??={...a,candidates:[]};}
const evidence:Evidence={request_id:'x',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{old:['xhigh'],next:['low','medium','high'],keep:['xhigh']}}}};
test('DD-610 主模型、备用、候选换模型后可用、返回提示、差异可见且可撤销',()=>{
 for(const path of ['work.planning','work.planning.fallbacks.0','review.implementation.spec','review.implementation.spec.candidates.0']){
 const d=new Draft(original);d.beginProbe('x');d.acceptProbe(evidence);
 expect(d.select(path,'model','next')).toEqual({path,from:'xhigh',to:'high'});
 expect(cell(d.config,path)).toMatchObject({...a,model:'next',effort:'high'});
 expect(d.valid()).toBe(true);expect(d.changes()).toContain(path.split('.').slice(0,path.startsWith('work')?2:3).join('.'));
 expect(original.work.planning!.effort).toBe('xhigh');d.undo();expect(d.config).toEqual(original);
 }
});
test('DD-610 保留原档、未变、手选、无核对和换工具不产生自动提示',()=>{
 const d=new Draft(original);d.beginProbe('x');d.acceptProbe(evidence);
 expect(d.select('work.planning','model','keep')).toBeUndefined();expect(d.config.work.planning!.effort).toBe('xhigh');
 expect(d.select('work.planning','model','keep')).toBeUndefined();
 expect(d.select('work.planning','effort','high')).toBeUndefined();
 expect(d.select('work.planning','agent','codex')).toBeUndefined();expect(d.config.work.planning).toMatchObject({agent:'codex',model:'',effort:''});
 const unchecked=new Draft(original);expect(unchecked.select('work.planning','model','next')).toBeUndefined();expect(unchecked.config.work.planning!.effort).toBe('');
});
