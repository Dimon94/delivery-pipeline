import {test,expect} from 'bun:test';
import {pickerView} from './picker';
const models={'magpie/auto/x':['medium','high','xhigh'],'magpie/remote-magpie/auto/y':['high'],'magpie/junbo/gpt-6.1-sol':['high'],'magpie/codex/gpt-6.1-sol':['medium']};
test('来源取最后非叶子段，合并同名来源并默认当前来源',()=>{
 const v=pickerView({models,current:'magpie/junbo/gpt-6.1-sol',query:''});
 expect(v.sources.map(s=>[s.label,s.count])).toEqual([['自动路由',2],['骏伯',1],['OpenAI',1]]);
 expect(v.groups.map(g=>g.label)).toEqual(['骏伯']);expect(v.groups[0]!.items[0]!.selected).toBe(true);
 expect(pickerView({models,current:'',query:''}).groups[0]!.items.map(i=>i.id)).toEqual(['magpie/auto/x','magpie/remote-magpie/auto/y']);
});
test('多词跨来源搜索，不区分大小写且匹配原始 id',()=>{
 expect(pickerView({models,current:'',query:'sol 骏伯',source:'auto'}).groups.flatMap(g=>g.items.map(i=>i.id))).toEqual(['magpie/junbo/gpt-6.1-sol']);
 expect(pickerView({models,current:'',query:'GPT-6.1-SOL'}).groups.map(g=>g.label)).toEqual(['骏伯','OpenAI']);
});
test('当前模型缺失时置顶、置灰并说明原因',()=>{
 const item=pickerView({models,current:'magpie/auto/gpt-5.4-old',query:''}).groups[0]!.items[0]!;
 expect(item.id).toBe('magpie/auto/gpt-5.4-old');expect(item.selected).toBe(true);expect(item.disabled).toBe('这个模型已不在可用清单里');
});
test('不可用时只有原因，无匹配时提示并保留可切换来源',()=>{
 expect(pickerView({models,current:'gone',query:'',unavailable:'现在不能换模型；请重新核对'})).toEqual({sources:[],groups:[],empty:'现在不能换模型；请重新核对'});
 const v=pickerView({models,current:'',query:'zzzz'});expect(v.groups).toEqual([]);expect(v.empty).toBe('没有匹配的模型');expect(v.sources.length).toBe(3);
});
test('模型支持的思考程度显示中文档位',()=>{
 expect(pickerView({models,current:'',query:''}).groups[0]!.items[0]!.efforts).toBe('中 · 高 · 很高');
});
