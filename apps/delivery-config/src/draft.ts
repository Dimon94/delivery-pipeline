import {pickerUnavailable} from './copy';
export type ModelTriple = {agent: string; model: string; effort: string};
export type Cell = ModelTriple & {fallbacks?:ModelTriple[]; candidates?:ModelTriple[]};
export type FallbackEdit = {kind:"add";item:ModelTriple}|{kind:"set";index:number;item:ModelTriple}|{kind:"move";index:number;to:number}|{kind:"remove";index:number};
export const budgetKeys = ["parallel", "max_turns"] as const;
export type BudgetKey = typeof budgetKeys[number];
export const defaultBudget = {parallel:4, max_turns:100};
export type Config = {dispatch?: Record<BudgetKey, number>;model_families?:Record<string,Record<string,{family:string;source:"user_declared"}>>;work: Record<string, Cell>; review: Record<string, Record<string, Cell>>; modes: Record<string, unknown>; [key: string]: unknown};
export type SourceEvidence = {status:string;next_step:string;reason?:string;route?:'gateway'|'direct'|'official'|'t3code'|null};
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
export const paths = [...work.map(n=>`work.${n}`), ...['implementation','whole-change'].flatMap(s=>['standards','spec'].map(a=>`review.${s}.${a}`))];
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
 applyTargets(from:string):ApplyTarget[] {
 const source=cell(this.config,from);
 return paths.filter(p=>p.startsWith('work.')&&p!==from).map(path=>{
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
 changes() {
 const cells=paths.filter(p=>JSON.stringify(cell(this.snapshot,p))!==JSON.stringify(cell(this.config,p)));
 const budgets=budgetKeys.filter(key=>(this.snapshot.dispatch??defaultBudget)[key] !== (this.config.dispatch??defaultBudget)[key]);
 return [...cells,...budgets.map(key=>'dispatch.'+key)];
 }
 candidate():Config {
 const result=structuredClone(this.config);
 if(result.version===6||result.version===7){result.version=8;result.model_families??={};result.dispatch??={...defaultBudget};}
 return result;
 }
 editCandidates(path:string,edit:FallbackEdit) {
 const items=cell(this.config,path).candidates!;
 if(edit.kind==='add')items.push(structuredClone(edit.item));
 else if(edit.kind==='set')items[edit.index]=structuredClone(edit.item);
 else if(edit.kind==='remove')items.splice(edit.index,1);
 else items.splice(edit.to,0,items.splice(edit.index,1)[0]!);
 }
 editFallbacks(name:string,edit:FallbackEdit) {
 const items=this.config.work[name]!.fallbacks!;
 if(edit.kind==='add')items.push(structuredClone(edit.item));
 else if(edit.kind==='set')items[edit.index]=structuredClone(edit.item);
 else if(edit.kind==='remove')items.splice(edit.index,1);
 else items.splice(edit.to,0,items.splice(edit.index,1)[0]!);
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
 attention() {return this.check.kind!=='checked'?0:paths.filter(p=>{const s=this.status(p);return [s.primary,...s.queue].some(i=>i.kind!=='ok');}).length;}
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
 const key=(c:ModelTriple)=>JSON.stringify([c.agent,c.model,c.effort]);
 return this.changes().every(p=>{
 if(p.startsWith("dispatch.")){const value=this.config.dispatch![p.slice(9) as BudgetKey];return Number.isSafeInteger(value)&&value>0;}
 const c=cell(this.config,p),old=cell(this.snapshot,p);
 if(key(c)!==key(old)&&!this.options(c).includes(c.effort))return false;
 const remaining=new Map<string,number>();
 const list=p.startsWith("review.")?"candidates":"fallbacks";
 for(const item of old[list]||[])remaining.set(key(item),(remaining.get(key(item))||0)+1);
 return (c[list]||[]).every(item=>{const k=key(item),n=remaining.get(k)||0;if(n){remaining.set(k,n-1);return true;}return this.options(item).includes(item.effort);});
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
