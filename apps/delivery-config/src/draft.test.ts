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
