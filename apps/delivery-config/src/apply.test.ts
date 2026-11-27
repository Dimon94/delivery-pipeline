import {test,expect} from 'bun:test';
import {Draft,cell,type Config,type Evidence} from './draft';
const a={agent:'pi',model:'alpha',effort:'high'},b={agent:'claude',model:'beta',effort:'low'};
const names=['planning','design','frontend','backend','testing'];
function setup(){
 const config:Config={work:Object.fromEntries(names.map(n=>[n,{...(n==='planning'?a:b),fallbacks:[{...b}],candidates:[{...b}]}])),review:{implementation:{standards:{...b,candidates:[a]}}},modes:{keep:true},model_families:{pi:{alpha:{family:'alpha',source:'user_declared'}}}};
 config.work.research={...b};config.work.planning!.fallbacks=[a];
 const d=new Draft(config);
 const evidence:Evidence={request_id:'1',observed_at:'now',gateway:{status:'ok'},sources:{pi:{status:'ok',next_step:''}},capabilities:{pi:{binary:true,models:{alpha:['high']}}}};
 d.beginProbe('1');d.acceptProbe(evidence);return d;
}
const targets=['work.design','work.frontend','work.backend','work.testing','work.research'];
test('R1 只复制选中主模型三项，整行覆盖会破坏备用',()=>{
 const d=setup(),expected=structuredClone(d.config);
 for(const p of targets)Object.assign(cell(expected,p),a);
 expect(d.applyPrimary('work.planning',[...targets,'work.planning','review.implementation.standards','work.nonexistent','work.design','work.design.fallbacks.0'])).toEqual({kind:'applied',changed:targets});
 expect(d.config).toEqual(expected);
});
test('R2 未核对与来源不可用均拒绝，拒绝前后一字不改',()=>{
 for(const kind of ['idle','checking','unreachable','tool_off','model_gone','effort_gone','incomplete','no_target']){
 const d=setup();
 if(kind==='idle')d.check={kind:'idle'};
 if(kind==='checking')d.beginProbe('2');
 if(kind==='unreachable')d.check={kind:'unreachable',cause:'gateway'};
 if(kind==='tool_off')d.evidence!.sources.pi!.status='off';
 if(kind==='model_gone')d.config.work.planning!.model='gone';
 if(kind==='effort_gone')d.config.work.planning!.effort='ultra';
 if(kind==='incomplete')d.config.work.planning!.effort='';
 const before=JSON.stringify(d.config);
 const result=d.applyPrimary('work.planning',kind==='no_target'?['work.planning','work.nonexistent','review.implementation.standards']:targets);
 const reason=['idle','checking','unreachable'].includes(kind)?{kind:'not_checked'}:kind==='no_target'?{kind:'no_target'}:{kind:'source',status:kind==='tool_off'?{kind,reason:'没有该工具的核对结果'}:{kind}};
 expect(result).toEqual({kind:'refused',reason});expect(JSON.stringify(d.config)).toBe(before);
 }
});
test('R4 按页面顺序列所有其他工作项，已相同不计数',()=>{
 const d=setup();Object.assign(d.config.work.design!,a);
 expect(d.applyTargets('work.planning')).toEqual([{path:'work.design',same:true},{path:'work.frontend',same:false},{path:'work.backend',same:false},{path:'work.testing',same:false},{path:'work.research',same:false}]);
 expect(d.applyPrimary('work.planning',targets)).toEqual({kind:'applied',changed:targets.slice(1)});
 expect(d.applyPrimary('work.planning',targets)).toEqual({kind:'applied',changed:[]});
});
test('复制遵守选择闸门，已核对但选择被禁用也不能写草稿',()=>{
 const d=setup();d.canEdit=()=>({select:false,addToQueue:false});const before=structuredClone(d.config);
 expect(d.canEdit().select).toBe(false);
 expect(d.applyPrimary('work.planning',targets)).toEqual({kind:'refused',reason:{kind:'not_checked'}});
 expect(d.config).toEqual(before);
});
