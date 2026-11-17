import {test,expect} from 'bun:test';
import {Draft,type Config} from './draft';
import {Editor} from './editor';
const a={agent:'pi',model:'route/native-model',effort:'high'},b={...a,effort:'low'};
const config:Config={version:7,model_families:{pi:{[a.model]:{family:"custom",source:"user_declared"}}},work:{planning:{...a,fallbacks:[]},design:a,frontend:a,backend:a,testing:a},modes:{},review:Object.fromEntries(['implementation','whole-change'].map(s=>[s,Object.fromEntries(['standards','spec'].map(x=>[x,{...a,candidates:[b,a,b]}]))]))};
test('四格保序，手动声明保持不变且不列入差异；取消恢复',()=>{
 const d=new Draft(config);
 for(const scope of ['implementation','whole-change'])for(const axis of ['standards','spec']){
 const p=`review.${scope}.${axis}`;d.editCandidates(p,{kind:'move',index:0,to:1});expect(d.config.review[scope]![axis]!.candidates).toEqual([a,b,b]);
 }
 expect(d.config.model_families).toEqual({pi:{'route/native-model':{family:'custom',source:'user_declared'}}});
 expect(d.changes()).not.toContain('model_families');expect(d.valid()).toBe(true);
 d.editCandidates('review.whole-change.spec',{kind:'remove',index:0});expect(d.config.model_families).toEqual({pi:{'route/native-model':{family:'custom',source:'user_declared'}}});
 d.undo();expect(d.config).toEqual(config);expect(d.changes()).toEqual([]);
});
test('增加重复必须有能力，精确模型与effort不可借用',()=>{
 const d=new Draft(config);d.editCandidates('review.whole-change.spec',{kind:'add',item:b});expect(d.valid()).toBe(false);
 d.beginProbe('now');d.acceptProbe({request_id:'now',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{'route/native-model':['low']}}}});expect(d.valid()).toBe(true);
 d.select('review.whole-change.spec.candidates.3','model','native-model');expect(d.valid()).toBe(false);
});
for(const uncertain of [true,false])test(`冲突/待确认保留顺序与声明，不重提 ${uncertain}`,async()=>{
 const e=new Editor({config,base_hash:'old',file_state:'ready',cells:{}});e.state.draft.editCandidates('review.whole-change.spec',{kind:'move',index:0,to:1});e.preview();
 const wanted=structuredClone(e.state.draft.config);let calls=0;
 await e.save(async(c,h)=>{calls++;expect(c).toEqual(wanted);expect(h).toBe('old');return uncertain?{status:'commit_unverified'}:{status:'rejected',error:{code:'base_conflict'}};});
 await e.save(async()=>{throw Error('不应重提');});expect(calls).toBe(1);expect(e.state.draft.config).toEqual(wanted);
 e.recover({config,base_hash:'new',file_state:'ready',cells:{}});expect('retained' in e.state&&e.state.retained?.config).toEqual(wanted);expect(e.state.kind).toBe('draft');
});
