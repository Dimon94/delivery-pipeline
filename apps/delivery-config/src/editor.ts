import {Draft, type Config} from './draft';
export type Snapshot = {base_hash:string|null;file_state:string;config:Config|null;cells:Record<string,{status:string}>};
export type Outcome = {status:'applied';config:Config;base_hash:string;changed:boolean}|{status:'rejected';error:{code:string}}|{status:'commit_unverified';expected_hash?:string|null};
export type State = {kind:'draft'|'preview';draft:Draft;base:Snapshot;retained?:Draft}|{kind:'saving'|'conflict'|'uncertain';draft:Draft;base:Snapshot};
export class Editor {
 state:State;
 constructor(snapshot:Snapshot){this.state={kind:'draft',base:snapshot,draft:new Draft(snapshot.config!)};}
 preview(){if(this.state.kind==='draft'&&this.state.draft.changes().length)this.state={...this.state,kind:'preview'};}
 back(){if(this.state.kind==='preview')this.state={...this.state,kind:'draft'};}
 async save(apply:(candidate:Config,hash:string)=>Promise<Outcome>){
  if(this.state.kind!=='preview'||!this.state.draft.valid())return;
  const {draft,base}=this.state;
  const candidate=structuredClone(draft.config);
  this.state={kind:'saving',draft,base};
  let result:Outcome;
  try{result=await apply(candidate,base.base_hash!);}catch{result={status:'commit_unverified'};}
  if(result.status==='applied')this.state={kind:'draft',base:{...base,config:result.config,base_hash:result.base_hash},draft:new Draft(result.config)};
  else this.state={kind:result.status==='commit_unverified'?'uncertain':result.error.code==='base_conflict'?'conflict':'draft',draft,base};
  return result;
 }
 recover(latest:Snapshot){
  const old=this.state;
  if(!['conflict','uncertain'].includes(old.kind)||latest.file_state!=='ready'||!latest.config)return false;
  // 比较整个文档；当前一致也只说明本次观察。
  if(old.kind==='uncertain'&&equal(latest.config,old.draft.config))this.state={kind:'draft',base:latest,draft:new Draft(latest.config)};
  else this.state={kind:'draft',base:latest,draft:new Draft(latest.config),retained:old.draft};
  return true;
 }
}
function equal(a:unknown,b:unknown):boolean {
 if(a===b)return true;
 if(!a||!b||typeof a!=='object'||typeof b!=='object')return false;
 const x=a as Record<string,unknown>,y=b as Record<string,unknown>;
 return Object.keys(x).length===Object.keys(y).length&&Object.keys(x).every(k=>Object.hasOwn(y,k)&&equal(x[k],y[k]));
}
