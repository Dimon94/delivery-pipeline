import {test, expect} from 'bun:test';
import {Window} from 'happy-dom';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, writeFileSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('v7 页面改预算，确认后配置事务写入 v8，新进程读取相同预算', async()=>{
 const dir=mkdtempSync(join(tmpdir(),'budget-ui-'));
 const config=join(dir,'config.json'), evidence=join(dir,'evidence.json');
 const scripts=new URL('../../../skills/delivery-pipeline-setup/scripts/',import.meta.url).pathname;
 const python=(args:string[],input?:string)=>execFileSync('python3',args,{cwd:scripts,input,encoding:'utf8'});
 const win=new Window(), doc=win.document;
 try {
  const original=python(['-c',`import json, model_config as m; print(json.dumps(dict(m.valid_fixture(),version=7,model_families={})))`]);
  writeFileSync(config,original);
  const call=async(name:string,...args:unknown[])=>{
   if(name==='Host.AppInfo')return {config_path:config,config_kind:'test'};
   if(name==='Host.ReadConfig')return JSON.parse(python(['model_config.py','show',config]));
   if(name==='Host.ProbeCapabilities')return {request_id:args[0],observed_at:'now',gateway:{status:'ok'},sources:{},capabilities:{}};
   if(name==='Host.Apply'){
    writeFileSync(evidence,JSON.stringify({request_id:'save',observed_at:'now',sources:{},capabilities:{}}));
    return JSON.parse(python(['model_config.py','apply',config,'--base-hash',String(args[1]),'--request-id','save','--evidence',evidence],JSON.stringify(args[0])));
   }
   throw Error(name);
  };
  Object.assign(globalThis,{window:win,document:doc,navigator:win.navigator,mygo:{call}});
  doc.body.innerHTML='<div id="app"></div>';
  await import('./main?budget'); await win.happyDOM.waitUntilComplete();
  const field=(key:string)=>doc.querySelector<HTMLInputElement>(`[data-budget="${key}"]`)!;
  const set=(key:string,value:string)=>{field(key).value=value;field(key).dispatchEvent(new win.Event('input',{bubbles:true}));};
  const button=(id:string)=>doc.querySelector<HTMLButtonElement>('#'+id)!;
  expect([field('parallel').value,field('max_turns').value]).toEqual(['4','100']);
  set('parallel','0');expect(button('diff').disabled).toBe(true);
  set('parallel','2');set('max_turns','7');button('diff').click();
  expect(readFileSync(config,'utf8')).toBe(original);
  expect(doc.querySelectorAll('.diff-panel article').length).toBe(2);
  button('save').click();await win.happyDOM.waitUntilComplete();
  expect(JSON.parse(readFileSync(config,'utf8'))).toEqual({...JSON.parse(original),version:8,dispatch:{parallel:2,max_turns:7}});
  const observed=python(['-c',`import json, sys, model_config as m; from pathlib import Path; print(json.dumps(m.read_limits(m.load_document(Path(sys.argv[1])))))`,config]);
  expect(JSON.parse(observed)).toEqual({parallel:2,max_turns:7});
 } finally {await win.happyDOM.close();rmSync(dir,{recursive:true,force:true});}
});
