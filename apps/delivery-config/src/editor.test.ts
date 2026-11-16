import {test,expect} from 'bun:test';
import {Editor,type Snapshot} from './editor';
import type {Config} from './draft';
import {execFileSync} from 'node:child_process';
const config=JSON.parse(execFileSync('python3',['-c',`import importlib.util,json
s=importlib.util.spec_from_file_location('m','skills/delivery-pipeline-setup/scripts/model_config.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.valid_fixture()))`],{cwd:new URL('../../../',import.meta.url).pathname}).toString()) as Config;
const snapshot={config,base_hash:'original',file_state:'ready',cells:{}} as Snapshot;
function edited(){const e=new Editor(snapshot);e.state.draft.config.work.planning!.effort='low';e.state.draft.beginProbe('x');e.state.draft.acceptProbe({request_id:'x',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{'provider/model':['low','high']}}}});e.preview();return e;}
test('保存冻结候选，待确认禁止重复提交；显式检查只说明当前',async()=>{
 const e=edited();let calls=0;
 let finish!:(v:any)=>void;
 const p=e.save(async c=>{calls++;expect(c.work.planning!.effort).toBe('low');return new Promise(r=>finish=r);});
 await e.save(async()=>{throw Error('重复保存');});expect(calls).toBe(1);expect(e.state.kind).toBe('saving');
 finish({status:'commit_unverified'});await p;expect(e.state.kind).toBe('uncertain');
 await e.save(async()=>{throw Error('重复保存');});
 expect(e.recover({...snapshot,file_state:'invalid_json',config:null})).toBe(false);
 expect(e.state.kind).toBe('uncertain');
 expect(e.recover({...snapshot,config:structuredClone(e.state.draft.config),base_hash:'current'})).toBe(true);
 expect(e.state.draft.changes()).toEqual([]);
});
test('冲突重读从最新完整文档开始，旧草稿仅供参考且须再次选择/预览',async()=>{
 const e=edited();await e.save(async()=>({status:'rejected',error:{code:'base_conflict'}}));
 expect(e.state.kind).toBe('conflict');
 const latest=structuredClone(config);latest.modes={someoneElse:{protected:true}};
 expect(e.recover({...snapshot,config:latest,base_hash:'latest'})).toBe(true);
 expect(e.state.draft.config.modes).toEqual({someoneElse:{protected:true}});
 expect(e.state.draft.config.work.planning!.effort).toBe('high');
 expect('retained' in e.state&&e.state.retained?.config.work.planning!.effort).toBe('low');
 let calls=0;await e.save(async()=>{calls++;throw Error();});expect(calls).toBe(0);
});
test('提交前拒绝须重新预览；当前不同保留旧草稿但不套用旧完整文档',async()=>{
 const e=edited();await e.save(async()=>({status:'rejected',error:{code:'capability_unavailable'}}));
 expect(e.state.kind).toBe('draft');expect(e.state.draft.config.work.planning!.effort).toBe('low');
 let calls=0;await e.save(async()=>{calls++;throw Error();});expect(calls).toBe(0);
 e.preview();await e.save(async()=>({status:'commit_unverified'}));
 expect(e.recover(snapshot)).toBe(true);expect('retained' in e.state).toBe(true);
 expect(e.state.draft.changes()).toEqual([]);
});
