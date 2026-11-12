export type Cell = {agent: string; model: string; effort: string};
export type Config = {work: Record<string, Cell>; review: Record<string, Record<string, Cell>>; modes: Record<string, unknown>; [key: string]: unknown};
export type Evidence = {request_id:string; observed_at:string; capabilities:Record<string,{binary:boolean;models:Record<string,string[]>}>; sources:Record<string,{status:string;next_step:string}>};
export const work = ['planning','design','frontend','backend','testing'];
export const paths = [...work.map(n=>`work.${n}`), ...['implementation','whole-change'].flatMap(s=>['standards','spec'].map(a=>`review.${s}.${a}`))];
export function cell(config: Config, path:string):Cell {const p=path.split('.'); return p[0]==='work'?config.work[p[1]!]!:config.review[p[1]!]![p[2]!]!;}
export class Draft {
 readonly config:Config;
 evidence?:Evidence;
 private request='';
 constructor(readonly snapshot:Config) {this.config=structuredClone(snapshot);}
 changes() {return paths.filter(p=>{const a=cell(this.snapshot,p),b=cell(this.config,p);return a.agent!==b.agent||a.model!==b.model||a.effort!==b.effort;});}
 beginProbe(id:string) {this.request=id;}
 acceptProbe(value:Evidence) {if(value.request_id!==this.request)return false;this.evidence=value;return true;}
 options(c:Cell) {return this.evidence?.sources[c.agent]?.status==='ok'?this.evidence.capabilities[c.agent]?.models[c.model] || []:[];}
 select(path:string, field:keyof Cell,value:string) {
 const c=cell(this.config,path); if(c[field]===value)return;
 c[field]=value;
 if(field==='agent') {c.model='';c.effort='';}
 if(field==='model' && !this.options(c).includes(c.effort))c.effort='';
 }
 valid() {return this.changes().every(p=>{const c=cell(this.config,p);return this.options(c).includes(c.effort);});}
 undo() {for(const p of paths)Object.assign(cell(this.config,p),cell(this.snapshot,p));}
}
