import type {Evidence,Check} from './draft';
// 用户文字的唯一入口；运行数据与原始诊断原因不改写。
export const FORBIDDEN = ['Unknown','证据','元数据','未联网','草稿','原值','slug','probe'] as const;
export const copy = {
 "可选模型":"可选模型",
 "搜索模型": "搜索模型",
 "搜索模型示例": "模型名或来源，如 sol 骏伯",
 "没有匹配的模型": "没有匹配的模型",
 "当前模型": "当前模型",
 "支持的思考程度": "支持的思考程度",
 "测试配置": "测试配置 · ",
 "本机设置": "本机设置 · ",
 "构建号未知": "构建号未知",
  "来源切换快捷键": "Alt + ← / → 切换来源；Tab 关闭",
  "选中标记": "✓",
  "检查": "检查",
  "每张票写完后": "每张票写完后",
  "合并前看整体": "合并前看整体",
  "写法是否合规": "写法是否合规",
  "是否做到Spec的要求": "是否做到 Spec 的要求",
  "正在读取本机设置": "正在读取本机设置…",
  "规划": "规划",
  "设计": "设计",
  "前端开发": "前端开发",
  "后端开发": "后端开发",
  "测试": "测试",
  "协调": "协调",
  "调研": "调研",
  "原型": "原型",
  "集成": "集成",
  "协助": "协助",
  "第二意见": "第二意见",
  "拆需求定方案": "拆需求、定方案",
  "界面与交互": "界面与交互",
  "写页面代码": "写页面代码",
  "写服务端代码": "写服务端代码",
  "写测试并验证": "写测试并验证",
  "已配置工具": "已配置工具",
  "运行工具": "运行工具",
  "模型": "模型",
  "思考程度": "思考程度",
  "请选择": "请选择",
  "还没选完整": "还没选完整",
  "去选择": "去选择",
  "这个运行工具": "这个运行工具",
  "换用其他工具": "换用其他工具",
  "这个模型已不在可用清单里": "这个模型已不在可用清单里",
  "换一个模型": "换一个模型",
  "这个模型不支持当前思考程度": "这个模型不支持当前思考程度",
  "换思考程度": "换思考程度",
  "主模型启动失败后会按顺序改用备用目前第一个可用的是备用": "主模型启动失败后会按顺序改用备用；目前第一个可用的是备用",
  "没有可用备用新任务会启动失败": "没有可用备用，新任务会启动失败。",
  "候选中": "候选中",
  "个可用": "个可用。",
  "项需处理": "项需处理",
  "共享家族声明": "共享家族声明",
  "备用": "备用",
  "实施结果": "实施结果",
  "整体交付": "整体交付",
  "代码规范": "代码规范",
  "需求符合度": "需求符合度",
  "请选择思考程度": "请选择思考程度",
  "候选": "候选：",
  "空": "空",
  "备用2": "备用：",
  "用户声明": "用户声明）",
  "未声明": "未声明",
  "候选2": "候选",
  "上移": "上移",
  "下移": "下移",
  "删除": "删除",
  "title核对完成后才能新增": "title=\"核对完成后才能新增\"",
  "添加候选": "添加候选",
  "为不同工具中的同类模型填写相同家族名思考程度不影响分组此处由你填": "为不同工具中的同类模型填写相同家族名，思考程度不影响分组。此处由你填写，留空表示未声明。",
  "共享家族": "共享家族",
  "配置处理引导": "配置处理引导",
  "影响": "影响",
  "下一步": "下一步",
  "给AI助手的指令": "给 AI 助手的指令",
  "复制指令": "复制指令",
  "重新读取": "重新读取",
  "独立诊断": "独立诊断",
  "此页包含配置工具的机器结果不会修改配置": "此页包含配置工具的机器结果。不会修改配置。",
  "返回设置": "返回设置",
  "设置模型设置": "设置 › 模型设置",
  "使用说明": "使用说明",
  "打开诊断": "打开诊断",
  "模型设置": "模型设置",
  "调整每种工作使用的AI核对差异后保存": "调整每种工作使用的 AI，核对差异后保存。",
  "每行是一种工作依次显示运行工具模型和思考程度": "每行是一种工作，依次显示运行工具、模型和思考程度。",
  "点模型格搜索或按来源选择备用会在主模型启动失败时依次接替": "点模型格搜索或按来源选择；备用会在主模型启动失败时依次接替。",
  "改好后点击查看差异确认后保存新任务会使用新设置指定预设的任务和正": "改好后点击“查看差异”，确认后保存；新任务会使用新设置，指定预设的任务和正在进行的任务保持原设置。",
  "遇到问题先按页面提示处理也可点击重新核对或打开诊断把结果交给AI": "遇到问题先按页面提示处理，也可点击“重新核对”或“打开诊断”，把结果交给 AI 助手。",
  "项设置需要处理其余": "项设置需要处理，其余",
  "项可以正常使用": "项可以正常使用。",
  "请人工核对后重新选择": "请人工核对后重新选择",
  "当前页面以最新设置为起点上次修改仅供参考请逐项重新选择再查看差异": "当前页面以最新设置为起点，上次修改仅供参考。请逐项重新选择，再查看差异。",
  "上次修改": "上次修改",
  "最新": "最新",
  "设置已在别处更新": "设置已在别处更新",
  "保存结果待确认": "保存结果待确认",
  "修改还在请检查当前设置并人工核对不会自动重试或回滚": "修改还在。请检查当前设置并人工核对，不会自动重试或回滚。",
  "读取最新设置并核对": "读取最新设置并核对",
  "检查当前保存结果": "检查当前保存结果",
  "工作模型": "工作模型",
  "每种工作的当前设置": "每种工作的当前设置",
  "工作": "工作",
  "添加备用": "添加备用",
  "结果检查": "结果检查",
  "分别检查代码写法和需求完成情况": "分别检查代码写法和需求完成情况",
  "其他设置仅查看": "其他设置 · 仅查看",
  "由初始化助手维护": "由初始化助手维护。",
  "组预设仅在任务明确指定时使用": "组预设，仅在任务明确指定时使用。",
  "其他工作": "其他工作",
  "没有其他工作设置": "没有其他工作设置",
  "项修改待确认": "项修改待确认",
  "请按页面提示完成设置": "请按页面提示完成设置。",
  "重新核对": "重新核对",
  "撤销修改": "撤销修改",
  "查看差异": "查看差异",
  "核对修改": "核对修改",
  "原来": "原来：",
  "现在": "现在：",
  "确认后保存保存期间不能继续修改": "确认后保存，保存期间不能继续修改。",
  "返回继续修改": "返回继续修改",
  "确认保存设置": "确认保存设置",
  "已复制粘贴给AI助手即可": "已复制，粘贴给 AI 助手即可",
  "已选中请按C复制": "已选中，请按 ⌘C 复制",
  "修改已撤销已恢复读取时的设置": "修改已撤销，已恢复读取时的设置。",
  "修改还在若要重新读取设置请先撤销修改": "修改还在。若要重新读取设置，请先撤销修改。",
  "读取环境无法使用请让AI助手检查已绑定的Python至少310及": "读取环境无法使用。请让 AI 助手检查已绑定的 Python（至少 3.10）及应用随附的配置工具，再点击重新读取。",
  "正在保存请等待结果": "正在保存，请等待结果…",
  "保存结果待确认请显式检查当前设置": "保存结果待确认。请显式检查当前设置。",
  "设置已在别处更新请读取最新设置并人工核对": "设置已在别处更新。请读取最新设置并人工核对。",
  "保存前检查未通过修改还在请点击重新核对或让AI助手检查环境再确认": "保存前检查未通过，修改还在。请点击“重新核对”或让 AI 助手检查环境，再确认保存。",
  "请参考上次修改重新选择并查看差异": "请参考上次修改，重新选择并查看差异。",
  "当前设置与待保存的设置一致": "当前设置与待保存的设置一致。",
  "当前设置仍无法读取修改还在请让AI助手处理后再次检查": "当前设置仍无法读取，修改还在。请让 AI 助手处理后再次检查。",
  "检查失败修改还在请处理环境后再次检查": "检查失败，修改还在，请处理环境后再次检查。"
};
const families:Record<string,string>={glm:'GLM',minimax:'MiniMax',gpt:'GPT',claude:'Claude',kimi:'Kimi',gemini:'Gemini',deepseek:'DeepSeek',grok:'Grok',k3:'Kimi K3',hy3:'腾讯混元'};
export const sources:Record<string,string>={auto:'自动路由',group:'模型分组',junbo:'骏伯',codex:'OpenAI',claude:'Anthropic',cursor:'Cursor',grok:'xAI','kimi-code-cn':'Kimi Code','workbuddy-ai':'WorkBuddy'};
export function modelLabel(raw:string):string {
 if(!raw)return '请选择模型';
 const parts=raw.split('/'),leaf=parts.pop()!,base=leaf.split('@')[0]!;
 const family=Object.keys(families).find(f=>base===f||base.startsWith(f+'-')||((f==='k3'||f==='hy3')&&base.startsWith(f)));
 const label=family?families[family]+base.slice(family.length).replace(/^-/, ' ').replace(/(?<=\b\d)(?:-\d)+\b/g,v=>v.replaceAll('-','.')).replaceAll('-',' ').replace(/\b[a-z]+/g,v=>v.length<=2?v.toUpperCase():v[0]!.toUpperCase()+v.slice(1)):base;
 const source=parts.filter(p=>p!=='magpie').pop(),context=leaf.match(/@(\d+)k$/)?.[1];
 return label+(source&&sources[source]?` · ${sources[source]}`:'')+(context?` · ${Number(context)/10}万上下文`:'');
}
// unknown + 已安装 + 空模型清单表示尚无完整能力；不匹配来源原因文字。
export function toolOffText(agent:string,reason?:string,context:{evidence?:Pick<Evidence,'sources'|'capabilities'>;selected?:boolean}={}):{text:string;title?:string} {
 const source=context.evidence?.sources[agent],cap=context.evidence?.capabilities[agent];
 const unsupported=['codex','claude'].includes(agent)&&source?.status==='unknown'&&cap?.binary===true&&Object.keys(cap.models).length===0;
 return {text:context.selected?'当前用不了，可点重新核对':unsupported?'暂不支持：还不能确认它有哪些模型可用':'暂时用不了，可点重新核对',...(reason?{title:reason}:{})};
}
export function effortLabel(effort:string):string {return ({minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高',ultra:'极高',none:'不额外思考'} as Record<string,string>)[effort]||effort;}
export type BannerInput={kind:'checking'}|{kind:'unreachable';cause:'gateway'|'call'}|{kind:'saved'}|{kind:'loaded'}|{kind:'recovered'};
export function bannerText(input:BannerInput):string {
 if(input.kind==='unreachable')return (input.cause==='gateway'?'本机模型网关没有响应。':'暂时无法检查可用模型。')+'现在不能换模型；恢复后请点击“重新核对”。备用和候选仍可删除、调序。';
 return {checking:'正在检查哪些模型可以用…',saved:'已保存，新任务会使用新设置',loaded:'已读取当前设置。',recovered:'已重新读取当前设置。'}[input.kind];
}
export function diffVerdict(valid:boolean):string {return valid?'这些修改都可以使用':'有修改还不能用，请返回重新选择';}

export function pickerCount(count:number):string {return `${count} 个可选模型`;}

export function pickerEfforts(efforts:string):string {return `支持的思考程度：${efforts}`;}
export function pickerUnavailable(check:Check,agent?:string,reading=false):string|undefined {
 if(reading)return copy.正在读取本机设置;
 if(check.kind==='unreachable')return bannerText({kind:'unreachable',cause:check.cause==='gateway'?'gateway':'call'});
 if(check.kind!=='checked')return bannerText({kind:'checking'});
 if(agent!==undefined&&check.evidence.sources[agent]?.status!=='ok')return toolOffText(agent,undefined,{evidence:check.evidence,selected:true}).text;
}
