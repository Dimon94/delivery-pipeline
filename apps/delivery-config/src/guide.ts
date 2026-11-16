import type {AppInfo} from './appinfo';
export type GuideKind = 'missing'|'unsupported_version'|'app_config'|'invalid_json'|'invalid_schema'|'unreadable'|'host_unavailable'|'unknown';
export interface GuideInput {fileState?:string; path?:string; config?:unknown; errors?:string[]; hostUnavailable?:boolean}
export interface Guide {kind:GuideKind; title:string; detail:string; impact:string; next:string; instruction?:string}
const content:Record<GuideKind,[string,string,string]> = {
 missing:['尚未完成初始设置','没有这份配置，模型设置和交付流程暂不能使用。','初始化交付配置'],
 unsupported_version:['配置版本需要处理','这份配置需要迁移后，模型设置和交付流程才能使用。','迁移到当前版本'],
 invalid_json:['配置内容无法读取','配置不是有效的 JSON，模型设置和交付流程暂不能使用。','保留原文件并修复 JSON 内容'],
 invalid_schema:['配置项目不完整或不符合要求','配置校验未通过，暂不能在这里编辑或用于交付。','修正配置项目并通过校验'],
 unreadable:['无法访问配置','无法读取这份配置，暂不能查看和编辑模型设置。','检查文件位置与读取权限'],
 host_unavailable:['读取环境无法使用','尚不能确认配置内容，暂不能查看和编辑模型设置。','检查读取环境、应用绑定的 Python（至少 3.10）与随附配置工具'],
 app_config:['这是 Codex App 的配置','这份 Codex App 配置本身有效；本页面只编辑 CLI 设置。','请在 Codex App 中使用这份配置；需要 CLI 设置时让 AI 助手另行配置。'],
 unknown:['配置状态暂未识别','尚不能确认这份配置是否可用，暂不能在这里编辑。','检查配置与应用的读取结果'],
};
export function guide(input:GuideInput, app?:AppInfo):Guide {
 const config=input.config as {version?:unknown;default_mode?:unknown;work?:Record<string,{agent?:string}>}|undefined;
 // 与 canonical migrate_document 相同：default_mode 存在且任意 work 格为 codex-app。
 const isApp=config?.version===5 && 'default_mode' in config && Object.values(config.work||{}).some(c=>c?.agent==='codex-app');
 const state=input.hostUnavailable?'host_unavailable':isApp?'app_config':input.fileState;
 const kind:GuideKind=state && Object.hasOwn(content,state)?state as GuideKind:'unknown';
 const [title,impact,goal]=content[kind];
 const path=input.path || app?.config_path || 'Unknown（未取得配置完整路径，请先确认）';
 const target=(app?.config_kind==='test'?'测试配置':'配置')+'：'+path;
 let detail=target;
 if(kind==='unsupported_version')detail+='；实际版本：'+String(config?.version??'Unknown');
 if(kind==='invalid_schema'&&input.errors?.length)detail+='\n'+input.errors.slice(0,3).join('\n');
 const next=kind==='app_config'?goal:'请复制下方指令给 AI 助手，'+goal+'，处理后点击“重新读取”。';
 return {kind,title,detail,impact,next,...(kind==='app_config'?{}:{instruction:`请使用 delivery-pipeline-setup 处理${target}。当前状态：${title}。详情：${detail}。期望结果：${goal}，使配置可以正常使用。处理后请读回核对配置路径、版本和校验结果，并告诉我结果，然后我会回到模型设置点击“重新读取”。`})};
}
