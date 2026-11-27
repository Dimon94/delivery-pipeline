import {pickerUnavailable} from './copy';
export type ModelTriple = {agent: string; model: string; effort: string};
export type Cell = ModelTriple & {fallbacks?:ModelTriple[]; candidates?:ModelTriple[]};
export const TASK_PURPOSES = ['planning','code','artifact','checks','advisory'] as const;
export type TaskPurpose = typeof TASK_PURPOSES[number];
export const REQUIRED_PURPOSES: readonly TaskPurpose[] = ['planning','code','checks'];
export const RESERVED_TASK_IDS = new Set(['review','map','all']);
export type TaskTypeMeta = {label:string; hint:string; purpose:TaskPurpose};
export type WorkCell = Cell & Partial<TaskTypeMeta>;
export type TaskTypeValidationError = 'invalid_id'|'reserved_id'|'duplicate_id'|'empty_label'|'invalid_purpose'|'last_required_purpose';
export type AddTaskTypeInput = {id:string; label:string; hint?:string; purpose:TaskPurpose; agent?:string; model?:string; effort?:string; fallbacks?:ModelTriple[]};
export const DEFAULT_TASK_META: Record<string, TaskTypeMeta> = {
 planning: {label:'规划', hint:'拆需求、定方案', purpose:'planning'},
 design: {label:'设计', hint:'界面与交互', purpose:'code'},
 frontend: {label:'前端开发', hint:'写页面代码', purpose:'code'},
 backend: {label:'后端开发', hint:'写服务端代码', purpose:'code'},
 testing: {label:'测试', hint:'写测试并验证', purpose:'checks'},
 coordinator: {label:'协调', hint:'', purpose:'planning'},
 research: {label:'调研', hint:'', purpose:'advisory'},
 prototype: {label:'原型', hint:'', purpose:'artifact'},
 integration: {label:'集成', hint:'', purpose:'code'},
 assistance: {label:'协助', hint:'', purpose:'advisory'},
 'second-opinion': {label:'第二意见', hint:'', purpose:'advisory'},
};
export type FallbackEdit = {kind:"add";item:ModelTriple}|{kind:"set";index:number;item:ModelTriple}|{kind:"move";index:number;to:number}|{kind:"promote";index:number}|{kind:"remove";index:number};
export const budgetKeys = ["parallel", "max_turns"] as const;
export type BudgetKey = typeof budgetKeys[number];
export const defaultBudget = {parallel:4, max_turns:100};
export type Config = {dispatch?: Record<BudgetKey, number>;model_families?:Record<string,Record<string,{family:string;source:"user_declared"}>>;work: Record<string, WorkCell>; review: Record<string, Record<string, Cell>>; modes: Record<string, unknown>; [key: string]: unknown};
export type SourceEvidence = {status:string;next_step:string;reason?:string;route?:'gateway'|'direct'|'official'|'cli'|'cache'|null};
export type Evidence = {request_id:string; observed_at:string; gateway:{status:string}; capabilities:Record<string,{binary:boolean;models:Record<string,string[]>}>; sources:Record<string,SourceEvidence>};
// 唯一的核对状态；网关是否可达只看证据里的 gateway.status，不从 sources 反推。
export type Check =
 | {kind:'idle'}
 | {kind:'checking'; request:string}
 | {kind:'checked'; evidence:Evidence}
 | {kind:'unreachable'; cause:'gateway'|'call_failed'};
// 唯一的项状态口径（R4）；页面只做映射。
export type ItemStatus =
 | {kind:'checking'} | {kind:'unverified'}
 | {kind:'ok'} | {kind:'incomplete'}
 | {kind:'tool_off'; reason:string}
 | {kind:'model_gone'} | {kind:'effort_gone'};
export type ApplyTarget = {path:string; same:boolean};
export type ApplyRefusal = {kind:'not_checked'} | {kind:'source';status:Exclude<ItemStatus,{kind:'ok'}>} | {kind:'no_target'};
export type ApplyResult = {kind:'applied';changed:string[]} | {kind:'refused';reason:ApplyRefusal};
export type CellStatus = {
 path:string;
 primary:ItemStatus;
 queue:ItemStatus[];
 queueLabel:'备用'|'候选';
 // 主选可用、或尚未核对（无法判断）时为 null。
 takeover:{kind:'fallback';index:number}|{kind:'none'}|{kind:'candidates';usable:number}|null;
};
export const agentIds = ['pi','codex','claude','antigravity'];
export const work = ['planning','design','frontend','backend','testing'];
export const reviewPaths = ['implementation','whole-change'].flatMap(s=>['standards','spec'].map(a=>`review.${s}.${a}`));
export const paths = [...work.map(n=>`work.${n}`), ...reviewPaths];
const TASK_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
function isValidPurpose(value:unknown):value is TaskPurpose {
 return typeof value==='string' && (TASK_PURPOSES as readonly string[]).includes(value);
}
function isValidLabel(value:unknown):boolean {
 if(typeof value!=='string')return false;
 const trimmed=value.trim();
 return trimmed.length>0 && trimmed.toLowerCase()!=='unknown';
}
export function cell(config: Config, path:string):Cell {
 const p=path.split('.');const parent=p[0]==='work'?config.work[p[1]!]!:config.review[p[1]!]![p[2]!]!;
 const list=p[0]==='work'?'fallbacks':'candidates';const offset=p[0]==='work'?2:3;
 return p[offset]===list?parent[list]![Number(p[offset+1])]!:parent;
}
export type EffortChange = {path:string;from:string;to:string};
export const EFFORT_ORDER = ['none','minimal','low','medium','high','xhigh','max','ultra'] as const;
export function nearestEffort(current:string,supported:string[]):string {
 if(supported.includes(current))return current;
 const order:readonly string[]=EFFORT_ORDER,index=order.indexOf(current);
 if(index<0)return '';
 let nearest='',distance=Infinity;
 for(const [i,effort] of order.entries())if(supported.includes(effort)&&Math.abs(i-index)<distance){
 nearest=effort;distance=Math.abs(i-index);
 }
 return nearest;
}
export class Draft {
 config:Config;
 check:Check={kind:'idle'};
 constructor(readonly snapshot:Config) {this.config=structuredClone(snapshot);}
 get evidence():Evidence|undefined {return this.check.kind==='checked'?this.check.evidence:undefined;}
 workIds():string[] {return Object.keys(this.config.work);}
 allPaths():string[] {return [...this.workIds().map(id=>`work.${id}`),...reviewPaths];}
 taskMeta(id:string, source:Config=this.config):TaskTypeMeta {
  const entry=source.work[id];
  const fallback=DEFAULT_TASK_META[id];
  const label=typeof entry?.label==='string'&&entry.label.trim()?entry.label:fallback?.label??id;
  const hint=typeof entry?.hint==='string'?entry.hint:fallback?.hint??'';
  const purpose=isValidPurpose(entry?.purpose)?entry.purpose:fallback?.purpose??'advisory';
  return {label,hint,purpose};
 }
 private purposeCount(purpose:TaskPurpose):number {
  return this.workIds().filter(id=>this.taskMeta(id).purpose===purpose).length;
 }
 canRemoveTaskType(id:string):{ok:true}|{ok:false;reason:'last_required_purpose';purpose:TaskPurpose}|{ok:false;reason:'not_found'} {
  if(!Object.hasOwn(this.config.work,id))return {ok:false,reason:'not_found'};
  const purpose=this.taskMeta(id).purpose;
  if(REQUIRED_PURPOSES.includes(purpose)&&this.purposeCount(purpose)<=1)return {ok:false,reason:'last_required_purpose',purpose};
  return {ok:true};
 }
 addTaskType(input:AddTaskTypeInput):{ok:true}|{ok:false;error:TaskTypeValidationError} {
  if(typeof input.id!=='string'||!TASK_ID_RE.test(input.id))return {ok:false,error:'invalid_id'};
  if(RESERVED_TASK_IDS.has(input.id))return {ok:false,error:'reserved_id'};
  if(Object.hasOwn(this.config.work,input.id))return {ok:false,error:'duplicate_id'};
  if(!isValidLabel(input.label))return {ok:false,error:'empty_label'};
  if(!isValidPurpose(input.purpose))return {ok:false,error:'invalid_purpose'};
  this.config.work[input.id]={
   agent:input.agent??'',
   model:input.model??'',
   effort:input.effort??'',
   fallbacks:structuredClone(input.fallbacks??[]),
   label:input.label.trim(),
   hint:(input.hint??'').trim(),
   purpose:input.purpose,
  };
  return {ok:true};
 }
 updateTaskTypeMeta(id:string, patch:Partial<TaskTypeMeta>):{ok:true}|{ok:false;error:TaskTypeValidationError} {
  if(!Object.hasOwn(this.config.work,id))return {ok:false,error:'invalid_id'};
  const current=this.taskMeta(id);
  const label=patch.label!==undefined?patch.label:current.label;
  const hint=patch.hint!==undefined?patch.hint:current.hint;
  const purpose=patch.purpose!==undefined?patch.purpose:current.purpose;
  if(!isValidLabel(label))return {ok:false,error:'empty_label'};
  if(!isValidPurpose(purpose))return {ok:false,error:'invalid_purpose'};
  if(purpose!==current.purpose&&REQUIRED_PURPOSES.includes(current.purpose)&&this.purposeCount(current.purpose)<=1){
   return {ok:false,error:'last_required_purpose'};
  }
  const entry=this.config.work[id]!;
  entry.label=label.trim();
  entry.hint=hint.trim();
  entry.purpose=purpose;
  return {ok:true};
 }
 removeTaskType(id:string):{ok:true}|{ok:false;error:TaskTypeValidationError} {
  const res=this.canRemoveTaskType(id);
  if(!res.ok)return {ok:false,error:res.reason==='last_required_purpose'?'last_required_purpose':'invalid_id'};
  delete this.config.work[id];
  return {ok:true};
 }
 applyTargets(from:string):ApplyTarget[] {
 const source=cell(this.config,from);
 return this.workIds().map(id=>`work.${id}`).filter(p=>p!==from).map(path=>{
 const target=cell(this.config,path);
 return {path,same:source.agent===target.agent&&source.model===target.model&&source.effort===target.effort};
 });
 }
 applyBlocked(from:string):ApplyRefusal|undefined {
 if(!this.canEdit().select||this.check.kind!=='checked')return {kind:'not_checked'};
 const status=this.itemStatus(cell(this.config,from));
 if(status.kind!=='ok')return {kind:'source',status};
 }
 applyPrimary(from:string,to:string[]):ApplyResult {
 const reason=this.applyBlocked(from);
 if(reason)return {kind:'refused',reason};
 const source=cell(this.config,from);
 const targets=this.applyTargets(from).filter(t=>to.includes(t.path));
 if(!targets.length)return {kind:'refused',reason:{kind:'no_target'}};
 const changed=targets.filter(t=>!t.same).map(t=>t.path);
 for(const p of changed)for(const field of ['agent','model','effort'] as const)this.select(p,field,source[field]);
 return {kind:'applied',changed};
 }
 setBudget(key:BudgetKey, value:number) {
 this.config.dispatch={...(this.config.dispatch??defaultBudget),[key]:value};
 }
 private normalizedWork(id:string, source:Config) {
  const entry=source.work[id];
  if(!entry)return undefined;
  const meta=this.taskMeta(id,source);
  return {
   agent:entry.agent,
   model:entry.model,
   effort:entry.effort,
   fallbacks:entry.fallbacks??[],
   label:meta.label,
   hint:meta.hint,
   purpose:meta.purpose,
  };
 }
 changes() {
 const workIdSet=new Set([...Object.keys(this.snapshot.work),...Object.keys(this.config.work)]);
 const workChanges=[...workIdSet]
  .filter(id=>JSON.stringify(this.normalizedWork(id,this.snapshot))!==JSON.stringify(this.normalizedWork(id,this.config)))
  .map(id=>`work.${id}`);
 const reviewChanges=reviewPaths.filter(p=>JSON.stringify(cell(this.snapshot,p))!==JSON.stringify(cell(this.config,p)));
 const budgets=budgetKeys.filter(key=>(this.snapshot.dispatch??defaultBudget)[key] !== (this.config.dispatch??defaultBudget)[key]);
 return [...workChanges,...reviewChanges,...budgets.map(key=>'dispatch.'+key)];
 }
 candidate():Config {
 const result=structuredClone(this.config);
 if(typeof result.version==='number'&&result.version>=6&&result.version<=9){
  result.version=9;
  result.model_families??={};
  result.dispatch??={...defaultBudget};
  for(const id of Object.keys(result.work)){
   const meta=this.taskMeta(id,result);
   const entry=result.work[id]!;
   entry.label=meta.label;
   entry.hint=meta.hint;
   entry.purpose=meta.purpose;
   entry.fallbacks??=[];
  }
 }
 return result;
 }
 editQueue(path:string,edit:FallbackEdit) {
  const parent=cell(this.config,path);
  const key=path.startsWith('review.')?'candidates':'fallbacks';
  const items=(parent[key]??=[]);
  if(edit.kind==='add')items.push(structuredClone(edit.item));
  else if(edit.kind==='set')items[edit.index]=structuredClone(edit.item);
  else if(edit.kind==='remove')items.splice(edit.index,1);
  else if(edit.kind==='promote'||(edit.kind==='move'&&edit.to<0)) {
   if(edit.index<0||edit.index>=items.length)return;
   const prev:ModelTriple={agent:parent.agent,model:parent.model,effort:parent.effort};
   const [picked]=items.splice(edit.index,1);
   if(!picked)return;
   parent.agent=picked.agent;parent.model=picked.model;parent.effort=picked.effort;
   items.unshift(prev);
  } else {
   items.splice(edit.to,0,items.splice(edit.index,1)[0]!);
  }
 }
 editCandidates(path:string,edit:FallbackEdit) {
  this.editQueue(path,edit);
 }
 editFallbacks(name:string,edit:FallbackEdit) {
  this.editQueue(`work.${name}`,edit);
 }
 // 核对只改 check，不碰 config（R1、R3）。只有最新请求的结果生效（R2）。
 beginProbe(id:string) {this.check={kind:'checking',request:id};}
 acceptProbe(value:Evidence) {
 if(this.check.kind!=='checking'||this.check.request!==value.request_id)return false;
 this.check=value.gateway?.status==='ok'?{kind:'checked',evidence:value}:{kind:'unreachable',cause:'gateway'};
 return true;
 }
 failProbe(id:string) {if(this.check.kind==='checking'&&this.check.request===id)this.check={kind:'unreachable',cause:'call_failed'};}
 private itemStatus(c:ModelTriple):ItemStatus {
 const check=this.check;
 if(check.kind==='checking')return {kind:'checking'};
 if(check.kind!=='checked')return {kind:'unverified'};
 if(!c.agent||!c.model||!c.effort)return {kind:'incomplete'};
 const source=check.evidence.sources[c.agent];
 if(source?.status!=='ok')return {kind:'tool_off',reason:source?.reason||source?.next_step||'没有该工具的核对结果'};
 const levels=check.evidence.capabilities[c.agent]?.models[c.model];
 if(!levels)return {kind:'model_gone'};
 return levels.includes(c.effort)?{kind:'ok'}:{kind:'effort_gone'};
 }
 status(path:string):CellStatus {
 const c=cell(this.config,path),isWork=path.startsWith('work.');
 const primary=this.itemStatus(c),queue=(isWork?c.fallbacks:c.candidates)?.map(i=>this.itemStatus(i))||[];
 let takeover:CellStatus['takeover']=null;
 if(this.check.kind==='checked'&&primary.kind!=='ok') {
 const first=queue.findIndex(q=>q.kind==='ok');
 takeover=isWork?(first>=0?{kind:'fallback',index:first}:{kind:'none'}):{kind:'candidates',usable:queue.filter(q=>q.kind==='ok').length};
 }
 return {path,primary,queue,queueLabel:isWork?'备用':'候选',takeover};
 }
 attention() {return this.check.kind!=='checked'?0:this.allPaths().filter(p=>{const s=this.status(p);return [s.primary,...s.queue].some(i=>i.kind!=='ok');}).length;}
 agentChoices() {
 const check=this.check;
 return agentIds.map(agent=>{
 if(check.kind!=='checked')return {agent,enabled:false};
 const source=check.evidence.sources[agent];
 return source?.status==='ok'?{agent,enabled:true}:{agent,enabled:false,reason:source?.reason||source?.next_step||'没有该工具的核对结果'};
 });
 }
 // 删除与调序始终允许（R7）；选择与新增只在已核对时开放。
 canEdit() {const on=pickerUnavailable(this.check)===undefined;return {select:on,addToQueue:this.check.kind==='checked'};}
 options(c:Cell) {return this.evidence?.sources[c.agent]?.status==='ok'?this.evidence.capabilities[c.agent]?.models[c.model] || []:[];}
 select(path:string, field:keyof ModelTriple,value:string):EffortChange|undefined {
 const c=cell(this.config,path); if(c[field]===value)return;
 c[field]=value;
 if(field==='agent') {c.model='';c.effort='';}
 if(field==='model' && !this.options(c).includes(c.effort)){
 const from=c.effort;c.effort=nearestEffort(from,this.options(c));
 if(c.effort&&c.effort!==from)return {path,from,to:c.effort};
 }
 }
 valid() {
 if(!REQUIRED_PURPOSES.every(purpose=>this.purposeCount(purpose)>=1))return false;
 const key=(c:ModelTriple)=>JSON.stringify([c.agent,c.model,c.effort]);
 return this.changes().every(p=>{
 if(p.startsWith("dispatch.")){const value=this.config.dispatch![p.slice(9) as BudgetKey];return Number.isSafeInteger(value)&&value>0;}
 if(p.startsWith("work.")){
  const id=p.slice(5);
  const current=this.config.work[id];
  const old=this.snapshot.work[id];
  // 删除任务类型不需要新能力证据
  if(!current)return true;
  const meta=this.taskMeta(id);
  if(!isValidLabel(meta.label)||!isValidPurpose(meta.purpose))return false;
  // 新增任务类型：主三元组及所有备用都必须在本次能力证据内
  if(!old){
   if(this.check.kind!=='checked')return false;
   if(!this.options(current).includes(current.effort))return false;
   return (current.fallbacks||[]).every(item=>this.options(item).includes(item.effort));
  }
  const remaining=new Map<string,number>();
  for(const item of [old,...(old.fallbacks||[])])remaining.set(key(item),(remaining.get(key(item))||0)+1);
  const consume=(item:ModelTriple)=>{const k=key(item),n=remaining.get(k)||0;if(n){remaining.set(k,n-1);return true;}return false;};
  if(key(current)!==key(old)){
   const reused=consume(current);
   if(this.check.kind==='checked'){if(!this.options(current).includes(current.effort))return false;}
   else if(!reused)return false;
  } else {
   consume(current);
  }
  return (current.fallbacks||[]).every(item=>consume(item)||this.options(item).includes(item.effort));
 }
 const c=cell(this.config,p),old=cell(this.snapshot,p);
 const list="candidates";
 const remaining=new Map<string,number>();
 for(const item of [old,...(old[list]||[])])remaining.set(key(item),(remaining.get(key(item))||0)+1);
 const consume=(item:ModelTriple)=>{const k=key(item),n=remaining.get(k)||0;if(n){remaining.set(k,n-1);return true;}return false;};
 if(key(c)!==key(old)){
 const reused=consume(c);
 if(this.check.kind==='checked'){if(!this.options(c).includes(c.effort))return false;}
 else if(!reused)return false;
 } else {
 consume(c);
 }
 return (c[list]||[]).every(item=>consume(item)||this.options(item).includes(item.effort));
 });
 }
 undo() {this.config=structuredClone(this.snapshot);}
}
// 页面收到 Host 证据后的唯一收口：证据被拒绝（request 不匹配）而 draft 仍停在本次请求的 checking 时，
// 按核对失败处理，避免重新核对/重新读取永久禁用。旧请求的 id 不会命中 failProbe，仍被忽略（R2）。
export function settleProbe(draft:Draft,id:string,value:Evidence):boolean {
 if(draft.acceptProbe(value))return true;
 draft.failProbe(id);
 return false;
}
