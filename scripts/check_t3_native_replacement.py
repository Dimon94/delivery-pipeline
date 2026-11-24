"""DD416 R3/R5/R7/R9：真实 Registry + 原生 I/O 边界；不冒充模型执行。"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import os
import subprocess
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('t3replacement', ROOT/'skills/delivery-pipeline-t3code/scripts/native_replacement.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
r=a.registry
caps=dict(parentThreadId='parent',inheritedProviderInstanceId='codex',providers=[dict(providerInstanceId='codex',canRunChildTask=True,models=[dict(id='B',options=[dict(id='reasoningEffort',values=['high'])])])])

def main():
 with tempfile.TemporaryDirectory() as td:
  previous_cwd=Path.cwd()
  subprocess.run(['git','init','-q',td],check=True)
  os.chdir(td)
  path=Path(td)/'registry.md'
  primary=dict(agent='codex',model='A',effort='low');fallback=dict(agent='codex',model='B',effort='high')
  source=dict(lane_id='source',work_item='DD416-check',runtime='t3-task',state='blocked',output_mode='checks',**primary,
   t3code=dict(task_id='original',child_thread_id='original-thread'),
   recovery_plan=dict(plan_version=1,source='work',primary=primary,fallbacks=[fallback,primary]),recovery_progress=dict(current_index=None,next_cursor=0))
  r.write(path,source)
  calls=[]; lost=[False]
  def io(name,args):
   calls.append((name,args))
   if name=='task_status':return dict(taskId='original',childThreadId='original-thread',status='completed',hasPendingChildRuns=False,providerInstanceId='codex',model='A')
   if name=='delegate_task':
    if lost[0]:raise OSError('response lost')
    return dict(taskId='successor-task',childThreadId='successor-thread')
   original=args['threadId']=='original-thread'
   return dict(thread=dict(threadId=args['threadId'],parentThreadId='parent',relationshipToParent='subagent',status='completed',activeRunId=None,
    providerInstanceId='codex',model='A' if original else 'B',worktreePath=str(Path.cwd())),recentRuns=[dict(executedModel='B')])
  adapter=a.NativeReplacement(io,caps)
  _,rev=r.read(path,'source');n=r.claim(path,'source',rev,'failure','tool_or_model',adapter.observe);lane=n['lane_id']
  adapter.execute(path,lane,'readonly nonce')
  launches=[args for name,args in calls if name=='delegate_task']
  assert launches==[dict(task='readonly nonce',target=dict(providerInstanceId='codex',model='B',options=dict(reasoningEffort='high')),isolation='worktree',clientRequestId=lane,mode='async',role='test')],launches
  adapter.execute(path,lane,'changed packet must not relaunch')
  assert len([x for x in calls if x[0]=='delegate_task'])==1
  row,_=r.read(path,lane);receipt=row['replacement_intent']['receipt']
  assert receipt['executedModel']=='B' and receipt['applied_effort']=='Unknown'
  assert row.get('worktree')==str(Path.cwd()) and row.get('t3code',{}).get('task_id')=='successor-task', 'startup not visible to lifecycle caller'
  # 无能力/活跃 writer：原字节不变，无 mutation。
  for bad in ('capability','disabled','writer','lost'):
   p=Path(td)/(bad+'.md');r.write(p,source);_,v=r.read(p,'source')
   n=r.claim(p,'source',v,'f','tool_or_model',adapter.observe)
   before=p.read_bytes();calls.clear()
   if bad=='capability':test=a.NativeReplacement(io,{**caps,'providers':[]})
   elif bad=='disabled':test=a.NativeReplacement(io,{**caps,'providers':[{**caps['providers'][0],'canRunChildTask':False}]})
   elif bad=='writer':
    def active(name,args):
     value=io(name,args)
     if name=='task_status':value['status']='running'
     return value
    test=a.NativeReplacement(active,caps)
   else:test=adapter;lost[0]=True
   try:test.execute(p,n['lane_id'],'nonce')
   except (ValueError,OSError):pass
   else:
    assert bad=='lost', 'unsafe launch accepted'
   if bad!='lost':assert p.read_bytes()==before and not any(x[0]=='delegate_task' for x in calls)
   else:
    calls.clear();adapter.execute(p,n['lane_id'],'must not retry')
    assert not calls
    row,_=r.read(p,n['lane_id']);assert row['replacement_intent']['status']=='launching'
    assert row['recovery_progress']==dict(current_index=0,next_cursor=1)
  # 独立预期：启动回执先保存，读回故障恢复后只能采用同一 task。
  saved_path=Path(td)/'saved-response.md';r.write(saved_path,source);_,v=r.read(saved_path,'source')
  n=r.claim(saved_path,'source',v,'saved','tool_or_model',adapter.observe)
  calls.clear();lost[0]=False
  def read_lost(name,args):
   if name=='t3_thread_read' and args['threadId']=='successor-thread':raise OSError('startup read lost')
   return io(name,args)
  a.NativeReplacement(read_lost,caps).execute(saved_path,n['lane_id'],'original packet')
  row,_=r.read(saved_path,n['lane_id']);assert row['replacement_intent']['status']=='launching'
  row=adapter.execute(saved_path,n['lane_id'],'changed packet')
  assert row['replacement_intent']['status']=='completed'
  assert row['replacement_intent']['native_request']['arguments']['task']=='original packet'
  assert len([x for x in calls if x[0]=='delegate_task'])==1
  # 执行身份独立读回不符不能冒充启动成功。
  mismatch=Path(td)/'mismatch.md';r.write(mismatch,source);_,v=r.read(mismatch,'source')
  n=r.claim(mismatch,'source',v,'mismatch','tool_or_model',adapter.observe)
  def wrong_model(name,args):
   value=io(name,args)
   if name=='t3_thread_read' and args['threadId']=='successor-thread':value['recentRuns']=[dict(executedModel='WRONG')]
   return value
  row=a.NativeReplacement(wrong_model,caps).execute(mismatch,n['lane_id'],'nonce')
  assert row['replacement_intent']['status']=='launching', 'executed model mismatch reported success'
  no_receipt=Path(td)/'before-receipt.md';r.write(no_receipt,source);_,v=r.read(no_receipt,'source')
  n=r.claim(no_receipt,'source',v,'no-receipt','tool_or_model',adapter.observe)
  r.bind_request(no_receipt,n['lane_id'],dict(coordinator_thread_id='parent',arguments={}),adapter.observe)
  def crash(_):raise OSError('crash before receipt')
  try:r.launch(no_receipt,n['lane_id'],adapter.observe,crash)
  except OSError:pass
  calls.clear();row=adapter.execute(no_receipt,n['lane_id'],'never relaunch')
  assert row['replacement_intent']['status']=='launching', 'missing receipt reported completed'
  assert not calls
  ag_caps=dict(parentThreadId='parent',inheritedProviderInstanceId='antigravity',providers=[dict(
   providerInstanceId='antigravity',canRunChildTask=True,canRunCrossProviderChildTask=True,
   models=[dict(id='gemini-4-neon',options=[dict(id='thought_level',values=['low','medium','high','xhigh'])])])])
  assert a.NativeReplacement(io,ag_caps).target(dict(agent='antigravity',model='gemini-4-neon',effort='xhigh'))==dict(
   providerInstanceId='antigravity',model='gemini-4-neon',options=dict(thought_level='xhigh'))
  os.chdir(previous_cwd)
 print('T3 native Adapter checks: pass')

if __name__=='__main__':main()
