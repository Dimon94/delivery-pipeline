import {expect,test} from 'bun:test';
import {guide,shouldRereadOnFocus,shouldRereadBoard} from './guide';
const path='/tmp/dd593/配置.json';
test('R1 missing：说明缺失、路径、影响与下一步',()=>{
 const g=guide({fileState:'missing',path});
 expect(g.kind).toBe('missing');
 expect(g.title).toContain('尚未');
 expect(g.detail).toContain(path);
 expect(g.impact.length).toBeGreaterThan(0);
 expect(g.next.length).toBeGreaterThan(0);
});
// 独立预期来自 spec-m3 的 Interface 与测试表；每种状态都检查用户可见内容。
for(const [state,title,goal] of [
 ['missing','尚未','初始化'],['unsupported_version','版本','迁移到当前版本'],
 ['invalid_json','内容','修复'],['invalid_schema','项目','修正'],['unreadable','访问','权限'],
 ['host_unavailable','环境','读取环境'],['unknown','状态','检查'],
] as const){
 test(`R1/R2 ${state}：完整引导与可复制指令`,()=>{
  const g=guide({fileState:state==='unknown'?'future_state':state,path,config:{version:4},hostUnavailable:state==='host_unavailable'});
  expect(g.kind).toBe(state);expect(g.title).toContain(title);
  for(const value of [g.title,g.detail,g.impact,g.next])expect(value.length).toBeGreaterThan(0);
  expect(g.detail).toContain(path);
  for(const value of ['delivery-pipeline-setup',path,g.title,goal,'读回','核对'])expect(g.instruction).toContain(value);
  expect(g.instruction).not.toContain('model_config.py');
 });
}
test('R1：实际版本与前三条校验错误',()=>{
 expect(guide({fileState:'unsupported_version',path,config:{version:42}}).detail).toContain('42');
 const g=guide({fileState:'invalid_schema',path,errors:['错误一','错误二','错误三','错误四']});
 for(const e of ['错误一','错误二','错误三'])expect(g.detail).toContain(e);
 expect(g.detail).not.toContain('错误四');
});
test('R6：测试路径优先、AppInfo 路径兜底，指令标记测试配置',()=>{
 const app={build:'',config_kind:'test',config_path:'/tmp/fallback.json'};
 const g=guide({fileState:'missing',path},app);
 for(const v of [g.detail,g.instruction]){expect(v).toContain('测试配置');expect(v).toContain(path);expect(v).not.toContain(app.config_path);}
 expect(guide({hostUnavailable:true},app).detail).toContain(app.config_path);
 expect(guide({hostUnavailable:true},app).instruction).toContain(app.config_path);
 expect(guide({hostUnavailable:true}).detail).toContain('未取得配置完整路径');
});
test('R7：v5 + default_mode + 任意 work 格 codex-app 才属于 App',()=>{
 const config={version:5,default_mode:'normal',work:{research:{agent:'codex-app'}}};
 const g=guide({fileState:'unsupported_version',path,config},{build:'',config_kind:'test',config_path:path});
 expect(g.kind).toBe('app_config');expect(g.instruction).toBeUndefined();
 expect(g.detail).toContain(path);expect(g.detail).toContain('测试配置');
 expect(g.impact).toContain('识别为 Codex App 配置（本页面只编辑 CLI 设置）');expect(g.impact).not.toContain('有效');expect(g.next).toContain('Codex App');
 expect(g.impact+g.next).not.toContain('迁移');
 for(const c of [{...config,work:{research:{agent:'codex'}}},{version:5,work:config.work},{...config,version:4}]){
  expect(guide({fileState:'unsupported_version',path,config:c}).kind).toBe('unsupported_version');
 }
});
test('R8：未知状态仍有完整引导；读取环境不可用优先',()=>{
 expect(guide({path,fileState:'future'}).kind).toBe('unknown');
 expect(guide({path,fileState:'missing',hostUnavailable:true}).kind).toBe('host_unavailable');
});

// 独立预期：spec-m3 R4/R5；可编辑包括草稿、核对、保存、冲突和待确认。
test('R4/R5：仅需要处理且没有读取任务时自动重读',()=>{
 expect(shouldRereadOnFocus({ready:false,reading:false})).toBe(true);
 expect(shouldRereadOnFocus({ready:false,reading:true})).toBe(false);
 expect(shouldRereadOnFocus({ready:true,reading:false})).toBe(false);
 expect(shouldRereadOnFocus({ready:true,reading:true})).toBe(false);
});

test('R6：AppInfo 失败或尚未返回时，详情和指令均标明配置来源未确认',()=>{
 const g=guide({fileState:'unsupported_version',path,config:{version:5}},undefined);
 for(const text of [g.detail,g.instruction])expect(text).toContain('配置来源未确认');
 expect(g.detail).toContain(path);expect(g.instruction).toContain(path);
});

test('R1：非字符串或数字的版本按 JSON 展示',()=>{
 for(const [version,expected] of [[{major:5},'{"major":5}'],[[5,6],'[5,6]'],[false,'false'],[null,'null']] as const){
  const detail=guide({fileState:'unsupported_version',path,config:{version}}).detail;
  expect(detail).toContain('实际版本：'+expected);expect(detail).not.toContain('[object Object]');
 }
});

// 独立预期：DD-668 T4 失败态回前台重读、T5 已渲染回前台重读；读取中或停在设置页不重读。
test('看板仅在显示且不在读取中时随前台重读',()=>{
 expect(shouldRereadBoard({visible:true,state:'failed'})).toBe(true);
 expect(shouldRereadBoard({visible:true,state:'rendered'})).toBe(true);
 expect(shouldRereadBoard({visible:true,state:'loading'})).toBe(false);
 expect(shouldRereadBoard({visible:false,state:'failed'})).toBe(false);
});
