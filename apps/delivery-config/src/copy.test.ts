import {reviewPreviewText} from './copy';
import {agentLabel,effortChangedText,modelSummary} from './copy';
import {expect,test} from 'bun:test';
import {modelLabel} from './copy';
import {readFileSync} from 'node:fs';
import {copy,FORBIDDEN,toolOffText,bannerText,diffVerdict,effortLabel,type BannerInput} from './copy';
import {guide} from './guide';
import {instanceLabel} from './appinfo';
import {pickerCount} from './copy';
import {pickerView} from './picker';
import {applyTargetText} from './copy';
import {applyRefusalText,applyTriggerLabel,ticketStatusText} from './copy';
// DD-595 的确定示例，预期独立于实现。
test('模型名称按家族与后缀规范显示，陌生名称保留',()=>{
 expect(modelLabel('gpt-6.1-sol')).toBe('GPT 6.1 Sol');
 expect(modelLabel('magpie/group/kimi-k3.1-pro')).toBe('Kimi K3.1 Pro · 模型分组');
 expect(modelLabel('foo-bar-1')).toBe('foo-bar-1');
});
const clean=(text:string)=>{for(const word of FORBIDDEN)expect(text).not.toContain(word);};
test('全部固定文字、状态提示和引导均不含内部词',()=>{
 const inputs:BannerInput[]=[{kind:'checking'},{kind:'unreachable',cause:'gateway'},{kind:'unreachable',cause:'call'},{kind:'saved'},{kind:'loaded'},{kind:'recovered'}];
 for(const value of [...Object.values(copy),...inputs.map(bannerText),diffVerdict(true),diffVerdict(false)])clean(value);
 for(const fileState of ['missing','unsupported_version','app_config','invalid_json','invalid_schema','unreadable','host_unavailable','unknown']){
  const config=fileState==='app_config'?{version:5,default_mode:'normal',work:{frontend:{agent:'codex-app'}}}:{};
  const g=guide({fileState,config,hostUnavailable:fileState==='host_unavailable'});
  for(const [key,value] of Object.entries(g))if(key!=='kind')clean(value);
 }
});
test('不可用工具只显示人话，悬停完整保留来源原因',()=>{
 for(const agent of ['codex','claude']){
  const reason='未取得精确模型与有效档位的完整证据链';
  const result=toolOffText(agent,reason,{evidence:{sources:{[agent]:{status:"unknown",next_step:""}},capabilities:{[agent]:{binary:true,models:{}}}}});clean(result.text);
  expect(result.text).toBe('暂不支持：还不能确认它有哪些模型可用');expect(result.title).toBe(reason);
 }
 expect(toolOffText('pi').title).toBeUndefined();
});
test('思考程度未知值保留，成功提示与差异结论说明结果',()=>{
 expect(effortLabel('high')).toBe('高');expect(effortLabel('future')).toBe('future');
 expect(bannerText({kind:'saved'})).toBe('已保存，新任务会使用新设置');
 expect(bannerText({kind:'recovered'})).toContain('已重新读取');
 expect(diffVerdict(true)).toBe('这些修改都可以使用');expect(diffVerdict(false)).toBe('有修改还不能用，请返回重新选择');
});
// 只扫描用户文字节点，不把注释、数据键、标识符当作文案。
test('页面文字节点不得重新带入内部词',()=>{
 const source=readFileSync(new URL('./main.ts',import.meta.url),'utf8').replace(/\/\/[^\n]*/g,'').replace(/copy\.[\p{L}\p{N}]+/gu,'copy.text');
 // 页面不再自带中文文字；英文内部词只检查字面值，跳过标识符。
 expect(source).not.toMatch(/[\u4e00-\u9fff]/);
 expect(source).not.toMatch(/['"`]Unknown|['"`]slug|['"`]probe['"`]/);
});
test('R1 工具原因按结构区分，当前不可用优先',()=>{
 const evidence={sources:{codex:{status:'unknown',next_step:''},claude:{status:'unknown',next_step:''}},capabilities:{codex:{binary:true,models:{}},claude:{binary:false,models:{}}}};
 expect(toolOffText('codex','原始原因',{evidence}).text).toBe('暂不支持：还不能确认它有哪些模型可用');
 expect(toolOffText('claude','原始原因',{evidence}).text).toBe('暂时用不了，可点重新核对');
 expect(toolOffText('pi','核对失败',{evidence}).text).toBe('暂时用不了，可点重新核对');
 expect(toolOffText('codex','原始原因',{evidence,selected:true}).text).toBe('当前用不了，可点重新核对');
 expect(toolOffText('codex','原始原因',{evidence}).title).toBe('原始原因');
});
test('R1 模型版本、缩写及新增家族显示',()=>{
 for(const [raw,label] of [
 ['claude-opus-5-5','Claude Opus 5.5'],['claude-sonnet-5-5','Claude Sonnet 5.5'],['claude-fable-5-1','Claude Fable 5.1'],
 ['deepseek-v4.1-flash-sg','DeepSeek V4.1 Flash SG'],['glm-5.3','GLM 5.3'],['minimax-m3.1-flash','MiniMax M3.1 Flash'],['foo-bar-1','foo-bar-1']])expect(modelLabel(raw!)).toBe(label!);
});
test('R1 实例标签文字集中并拦截内部词',()=>{
 const source=readFileSync(new URL('./appinfo.ts',import.meta.url),'utf8').replace(/\/\/[^\n]*/g,'').replace(/copy\.[\p{L}\p{N}]+/gu,'copy.text');
 expect(source).not.toMatch(/[\u4e00-\u9fff]/);
 for(const info of [undefined,{build:'',config_kind:'test'},{build:'',config_kind:'cli'}])clean(instanceLabel(info));
});
test('选择器名称、缺失原因、无结果和不可用提示不含内部词',()=>{
 for(const n of [0,1,58])clean(pickerCount(n));
 for(const input of [
 {models:{'magpie/auto/gpt-6.1-sol':['high']},current:'magpie/auto/gone',query:''},
 {models:{},current:'',query:'zz'},
 {models:{},current:'',query:'',unavailable:bannerText({kind:'unreachable',cause:'gateway'})}
 ]){
  const v=pickerView(input);clean(v.empty||'');for(const g of v.groups){clean(g.label);for(const i of g.items){clean(i.label);clean(i.disabled||'');}}
 }
});
test('DD-605 目标文字显示变化或已相同，且没有内部词',()=>{
 const t={name:'设计',now:'Claude Code · Beta · 低',next:'Pi · Alpha · 高',same:false};
 expect(applyTargetText(t)).toBe('设计：Claude Code · Beta · 低 → Pi · Alpha · 高');
 expect(applyTargetText({...t,same:true})).toBe('设计：已相同');
 clean(applyTargetText(t));clean(applyTargetText({...t,same:true}));
});
test('DD-606 每种拒绝说明原因和下一步，入口有工作名，全部通过禁词扫描',()=>{
 const reasons:import('./draft').ApplyRefusal[]=[{kind:'not_checked'},{kind:'no_target'},...(['checking','unverified','incomplete','model_gone','effort_gone'] as const).map(kind=>({kind:'source' as const,status:{kind}})),{kind:'source',status:{kind:'tool_off',reason:'probe Unknown'}}];
 const expected=['核对尚未完成','至少选择','正在核对','还未核实','选完整','模型已不在','不支持当前思考程度','运行工具当前用不了'];
 reasons.forEach((r,i)=>{const text=applyRefusalText(r);clean(text);expect(text).toContain(expected[i]!);expect(text).toMatch(/请/);});
 for(const check of [{kind:'checking',request:'x'},{kind:'unreachable',cause:'call_failed'}] as const)clean(applyRefusalText({kind:'not_checked'},check));
 expect(applyTriggerLabel('设计')).toBe('把设计的设置复制到其他工作');clean(applyTriggerLabel('设计'));
});
test('复制摘要对未知工具、空模型及空思考程度给出可读兜底',()=>{
 expect(modelSummary({agent:'unknown',model:'',effort:''})).toBe('已配置工具 · 请选择模型 · 请选择思考程度');
 expect(modelSummary({agent:'pi',model:'gpt-6.1-sol',effort:'high'})).toBe('Pi · GPT 6.1 Sol · 高');
});
test('空目标拒绝与其他拒绝一样提示再复制',()=>{
 expect(applyRefusalText({kind:'no_target'})).toBe('请至少选择一项工作再复制');
});

test('DD-610 自动变化文字使用中文档位并通过禁词扫描',()=>{
 const text=effortChangedText('xhigh','high');
 expect(text).toBe('思考程度已从“很高”改为“高”，新模型不支持“很高”');clean(text);
});

test('DD-613 工具路由文案与禁用原因通过禁词扫描',()=>{
 for(const agent of ['pi','codex','claude'])for(const route of ['direct','gateway',null,undefined] as const)clean(agentLabel(agent,route));
 const reason='Codex 当前指向的地址既不是本机网关也不是 OpenAI 官方，无法确认可用模型';
 const evidence={sources:{codex:{status:'unknown',next_step:'',route:null,reason}},capabilities:{codex:{binary:true,models:{}}}};
 const text=toolOffText('codex',undefined,{evidence});
 expect(text.title).toBe(reason);expect(text.text).toContain('暂不支持');clean(text.text);clean(text.title!);
});

test('DD-618 Claude 官方来源、可读模型名与禁用原因',()=>{
 const label=agentLabel('claude','official');expect(label).toBe('Claude Code · 官方清单');clean(label);
 expect(agentLabel('claude','gateway')).toBe('Claude Code');
 expect(modelLabel('claude-opus-5-5')).toBe('Claude Opus 5.5');
 const reason='请先打开 Claude Code 完成登录后重新核对';
 const off=toolOffText('claude',undefined,{evidence:{sources:{claude:{route:null,status:'unknown',next_step:'',reason}},capabilities:{claude:{binary:true,models:{}}}}});
 expect(off.title).toBe(reason);expect(off.text).toContain('暂不支持');clean(off.text);
});

test('Antigravity 来源显示纯名称、可读模型名与禁用原因通过禁词扫描',()=>{
 for(const route of ['cli','cache',null,undefined] as const){
  const label=agentLabel('antigravity',route);
  expect(label).toBe('Antigravity');expect(label).not.toContain('T3');clean(label);
 }
 expect(modelLabel('gemini-4-neon')).toBe('Gemini 4 Neon');
 expect(modelLabel('gemini-pro-orchestrator-neon')).toBe('Gemini Pro Orchestrator Neon');
 const reason='请先完成 Antigravity 登录后重新核对';
 const off=toolOffText('antigravity',undefined,{evidence:{sources:{antigravity:{route:null,status:'unknown',next_step:'',reason}},capabilities:{antigravity:{binary:true,models:{}}}}});
 expect(off.title).toBe(reason);expect(off.text).toContain('暂不支持');clean(off.text);clean(off.title!);
});

test('检查预计结果的所有说法进入禁用词扫描',()=>{
 for(const outcome of ['different','no_different_family','unrecognized','none_runnable'] as const)clean(reviewPreviewText({selected:{agent:'claude',model:'claude-opus-5-5',effort:'high'},selected_index:1,outcome,unrecognized:[]}).text);
});

test('DD-674 票状态文字区分执行中、running 现场 Unknown、待收口与未派发',()=>{
 const baseLane={lane_id:'l1',role:'frontend',agent:'pi',model:'gpt-6.1-sol',worktree:null,branch:null,blocked_reason:null,updated_at:null};
 expect(ticketStatusText({executing:true,lane:{...baseLane,state:'running',group:'active',live:'working'}})).toBe('执行中');
 expect(ticketStatusText({executing:false,lane:{...baseLane,state:'running',group:'active',live:'unknown'}})).toBe('running · 现场 Unknown');
 expect(ticketStatusText({executing:false,lane:{...baseLane,state:'terminal',group:'review',live:'unknown'}})).toBe('待收口 · terminal');
 expect(ticketStatusText({executing:false,lane:{...baseLane,state:'blocked',group:'problem',live:'unknown'}})).toBe('需处理 · blocked');
 expect(ticketStatusText({executing:false,lane:null})).toBe('未派发');
});
