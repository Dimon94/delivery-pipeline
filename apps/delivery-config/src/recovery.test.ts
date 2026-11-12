import {test,expect} from 'bun:test';
import {Editor,type Snapshot} from './editor';
import {type Config} from './draft';
import {execFileSync} from 'node:child_process';
const fixture=JSON.parse(execFileSync('python3',['-c',`import importlib.util,json
s=importlib.util.spec_from_file_location('m','skills/delivery-pipeline-setup/scripts/model_config.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.valid_fixture()))`],{cwd:new URL('../../../',import.meta.url).pathname}).toString()) as Config;
const a={agent:'pi',model:'provider/model',effort:'high'},b={...a,effort:'low'};
function start(){const config=structuredClone(fixture);config.work.planning={...a,fallbacks:[b,a,b,a]};return new Editor({config,base_hash:'old',file_state:'ready',cells:{}});}
function edit(e:Editor){e.state.draft.editFallbacks('planning',{kind:'move',index:0,to:1});e.preview();}
// DD407 T4/T11: 返回保持候选，撤销恢复整个读取快照（含可选字段与只读区域）。
test('返回完整草稿；撤销恢复原文档且保留只读文档',()=>{
 const e=start(),original=structuredClone(e.state.base.config);edit(e);const candidate=structuredClone(e.state.draft.config);
 e.back();expect(e.state.draft.config).toEqual(candidate);
 e.state.draft.config.modes={};
 e.state.draft.undo();expect(e.state.draft.config).toEqual(original);expect(e.state.draft.changes()).toEqual([]);
});
// DD407 T8-T10: 两类不确定保存都只能显式读回，不从读回推断历史。
for(const status of ['conflict','uncertain'] as const)test(`${status}保留完整列表；失败读回不丢失；当前等于候选采用当前快照`,async()=>{
 const e=start();edit(e);const candidate=structuredClone(e.state.draft.config);let calls=0;
 await e.save(async()=>{calls++;return status==='conflict'?{status:'rejected',error:{code:'base_conflict'}}:{status:'commit_unverified'};});
 expect(e.state.kind).toBe(status);e.preview();e.back();await e.save(async()=>{calls++;throw Error();});expect(calls).toBe(1);
 expect(e.recover({...e.state.base,file_state:'unreadable',config:null})).toBe(false);
 expect(e.state.kind).toBe(status);expect(e.state.draft.config).toEqual(candidate);
 expect(e.recover({...e.state.base,base_hash:'observed',config:structuredClone(candidate)})).toBe(true);
 expect(e.state.base.base_hash).toBe('observed');expect(e.state.draft.config).toEqual(candidate);expect(e.state.draft.changes()).toEqual([]);
 expect('retained' in e.state&&e.state.retained).toBeFalsy();
});
test('另一完整文档为新基线；旧完整列表只供参考；拒绝后仍保留参考',async()=>{
 const e=start();edit(e);const candidate=structuredClone(e.state.draft.config);
 await e.save(async()=>({status:'commit_unverified'}));
 const latest=structuredClone(fixture);latest.work.planning={...b,fallbacks:[a,b,a]};
 const observed={...e.state.base,base_hash:'new',config:latest} as Snapshot;
 e.recover(observed);expect(e.state.draft.config).toEqual(latest);expect('retained' in e.state&&e.state.retained?.config).toEqual(candidate);
 let calls=0;await e.save(async()=>{calls++;throw Error();});expect(calls).toBe(0);
 e.state.draft.editFallbacks('planning',{kind:'remove',index:0});e.preview();
 await e.save(async(c,h)=>{expect(h).toBe('new');expect(c.work.planning!.fallbacks).toEqual([b,a]);return {status:'rejected',error:{code:'io_error'}};});
 expect('retained' in e.state&&e.state.retained?.config).toEqual(candidate);
});
