export type ModelTriple = {agent: string; model: string; effort: string};
export type Cell = ModelTriple & {fallbacks?:ModelTriple[]; candidates?:ModelTriple[]};
export type FallbackEdit = {kind:"add";item:ModelTriple}|{kind:"set";index:number;item:ModelTriple}|{kind:"move";index:number;to:number}|{kind:"remove";index:number};
export type Config = {work: Record<string, Cell>; review: Record<string, Record<string, Cell>>; modes: Record<string, unknown>; [key: string]: unknown};
export type Evidence = {request_id:string; observed_at:string; capabilities:Record<string,{binary:boolean;models:Record<string,string[]>}>; sources:Record<string,{status:string;next_step:string}>};
export const work = ['planning','design','frontend','backend','testing'];
export const paths = [...work.map(n=>`work.${n}`), ...['implementation','whole-change'].flatMap(s=>['standards','spec'].map(a=>`review.${s}.${a}`))];
export function cell(config: Config, path:string):Cell {const p=path.split('.'); return p[0]==='work'?(p[2]==='fallbacks'?config.work[p[1]!]!.fallbacks![Number(p[3])]!:config.work[p[1]!]!):config.review[p[1]!]![p[2]!]!;}
export class Draft {
 config:Config;
 evidence?:Evidence;
 private request='';
 constructor(readonly snapshot:Config) {this.config=structuredClone(snapshot);}
 changes() {return paths.filter(p=>JSON.stringify(cell(this.snapshot,p))!==JSON.stringify(cell(this.config,p)));}
 editFallbacks(name:string,edit:FallbackEdit) {
 const items=this.config.work[name]!.fallbacks!;
 if(edit.kind==='add')items.push(structuredClone(edit.item));
 else if(edit.kind==='set')items[edit.index]=structuredClone(edit.item);
 else if(edit.kind==='remove')items.splice(edit.index,1);
 else items.splice(edit.to,0,items.splice(edit.index,1)[0]!);
 }
 beginProbe(id:string) {this.request=id;}
 acceptProbe(value:Evidence) {if(value.request_id!==this.request)return false;this.evidence=value;return true;}
 options(c:Cell) {return this.evidence?.sources[c.agent]?.status==='ok'?this.evidence.capabilities[c.agent]?.models[c.model] || []:[];}
 select(path:string, field:keyof ModelTriple,value:string) {
 const c=cell(this.config,path); if(c[field]===value)return;
 c[field]=value;
 if(field==='agent') {c.model='';c.effort='';}
 if(field==='model' && !this.options(c).includes(c.effort))c.effort='';
 }
 valid() {
 const key=(c:ModelTriple)=>JSON.stringify([c.agent,c.model,c.effort]);
 return this.changes().every(p=>{
 const c=cell(this.config,p),old=cell(this.snapshot,p);
 if(key(c)!==key(old)&&!this.options(c).includes(c.effort))return false;
 const remaining=new Map<string,number>();
 for(const item of old.fallbacks||[])remaining.set(key(item),(remaining.get(key(item))||0)+1);
 return (c.fallbacks||[]).every(item=>{const k=key(item),n=remaining.get(k)||0;if(n){remaining.set(k,n-1);return true;}return this.options(item).includes(item.effort);});
 });
 }
 undo() {this.config=structuredClone(this.snapshot);}
}
