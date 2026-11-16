import {expect,test} from 'bun:test';
import {modelLabel} from './copy';
// DD-595 的确定示例，预期独立于实现。
test('模型名称按家族与后缀规范显示，陌生名称保留',()=>{
 expect(modelLabel('gpt-6.1-sol')).toBe('GPT 6.1 Sol');
 expect(modelLabel('magpie/group/kimi-k3.1-pro')).toBe('Kimi K3.1 Pro · 模型分组');
 expect(modelLabel('foo-bar-1')).toBe('foo-bar-1');
});
import {readFileSync} from 'node:fs';
import {copy,FORBIDDEN,toolOffText,bannerText,diffVerdict,effortLabel,type BannerInput} from './copy';
import {guide} from './guide';
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
  const result=toolOffText(agent,reason);clean(result.text);
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
