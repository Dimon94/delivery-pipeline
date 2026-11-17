import {copy,sources,modelLabel,effortLabel} from './copy';
export type PickerInput={models:Record<string,string[]>;current:string;query:string;source?:string;unavailable?:string};
export type PickerItem={id:string;label:string;efforts:string;selected:boolean;disabled?:string};
export type PickerView={sources:{id:string;label:string;count:number}[];groups:{source:string;label:string;items:PickerItem[]}[];empty?:string};
export function pickerView(input:PickerInput):PickerView {
 if(input.unavailable)return {sources:[],groups:[],empty:input.unavailable};
 const grouped=new Map<string,PickerView['groups'][number]>();
 for(const [id,levels] of Object.entries(input.models)){
  const segment=id.split('/').at(-2)||'';
  const label=sources[segment]||segment;
  if(!grouped.has(label))grouped.set(label,{source:segment,label,items:[]});
  grouped.get(label)!.items.push({id,label:modelLabel(id),efforts:levels.map(effortLabel).join(' · '),selected:id===input.current});
 }
 const groups=[...grouped.values()];
 const words=input.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
 const source=input.source||groups.find(g=>g.items.some(i=>i.selected))?.source||groups[0]?.source;
 const visible=words.length?groups.map(g=>({...g,items:g.items.filter(i=>words.every(w=>(i.id+' '+i.label+' '+g.label).toLowerCase().includes(w)))})).filter(g=>g.items.length):groups.filter(g=>g.source===source);
 if(input.current&&!Object.hasOwn(input.models,input.current)&&words.every(w=>(input.current+' '+modelLabel(input.current)).toLowerCase().includes(w)))visible.unshift({source:'current',label:copy.当前模型,items:[{id:input.current,label:modelLabel(input.current),efforts:'',selected:true,disabled:copy.这个模型已不在可用清单里}]});
 return {sources:groups.map(g=>({id:g.source,label:g.label,count:g.items.length})),groups:visible,...(!visible.length?{empty:copy.没有匹配的模型}:{})};
}
export function moveActive(view:PickerView,active:string|undefined,key:'ArrowUp'|'ArrowDown'|'Home'|'End'):string|undefined {
 const ids=view.groups.flatMap(g=>g.items.filter(i=>!i.disabled).map(i=>i.id));
 if(key==='Home')return ids[0];
 if(key==='End')return ids.at(-1);
 const index=active===undefined?-1:ids.indexOf(active);
 if(index<0)return key==='ArrowDown'?ids[0]:ids.at(-1);
 return ids[Math.max(0,Math.min(ids.length-1,index+(key==='ArrowDown'?1:-1)))];
}
