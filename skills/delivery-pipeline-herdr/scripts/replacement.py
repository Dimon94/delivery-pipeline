"""Herdr replacement Adapter：仅消费共享 claim，不解析 work 配置。

observe 必须读取原生 writer/identity/capability/gate；未有版本匹配证据时禁止调用。
unknown 的 agent start 不自动重发。reconcile 使用原 pane/name/request 坐标，由宿主读回。
"""
import importlib.util
from pathlib import Path
import subprocess
import json
import os
import sys

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / 'delivery-pipeline/scripts'
# 本文件与 canonical replacement.py 同名；不经 sys.modules 的同名导入。
sys.path.insert(0,str(CORE))
import lane_registry
spec = importlib.util.spec_from_file_location('herdr_dispatch', HERE/'dispatch.py')
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)
mc = dispatch.load_model_config()


def execute(path, lane, observe, pane_id, evidence, verify_target, native_start=None, *, native_scope=None):
    if __import__('os').environ.get('HERDR_ENV')!='1':
        raise ValueError('dispatch unavailable: not inside a Herdr pane')
    claimed,_ = lane_registry.read(path,lane)
    if not claimed.get('runtime','').startswith('herdr-'):
        raise ValueError('transport identity mismatch')
    errors=mc.capability_errors(claimed['agent'],claimed['model'],claimed['effort'],evidence)
    if errors:
        raise ValueError('; '.join(errors))
    argv=mc.startup_request({**claimed,'mode':claimed.get('mode') or 'none','capability':'verified'},worker_name=lane,pane_id=pane_id)
    def native_observation(source):
        target=verify_target(pane_id,claimed)
        if target != {'pane_id':pane_id,'identity':'match','shell':'available','scope':'isolated_lane'}:
            raise ValueError('inspect: target pane identity/scope/availability Unknown')
        return observe(source)
    request={'argv':argv,'pane_id':pane_id,'agent_name':lane}
    if native_scope is not None:
        request['scope']=native_scope
    lane_registry.bind_request(path,lane,request,native_observation,runtime=dispatch.RUNTIME[claimed['agent']])
    def start(row):
        # 这个外部 seam 只替代原生 I/O；选序、预算、intent 均走真实 Registry。
        if native_start is not None:
            return native_start(argv,row)
        result = subprocess.run(argv,capture_output=True,text=True)
        if result.returncode != 0:
            raise ValueError('inspect original request: '+result.stderr.strip())
        receipt = json.loads(result.stdout)
        if not isinstance(receipt,dict) or receipt.get('ok',receipt.get('success')) is not True:
            raise ValueError('inspect: native acceptance Unknown')
        return dict(status='completed',receipt={'argv':argv,'native':receipt,'pane_id':pane_id,
                                               'request_id':row['lane_id']})
    return lane_registry.launch(path,lane,native_observation,start)


def start_result(returncode, stdout, stderr):
    """CLI 返回只是请求回执；非零可能是已启动但未 ready，不能当正面拒绝。"""
    return dict(status='unknown', native_reply=dict(returncode=returncode, stdout=stdout, stderr=stderr),
                gap='需要原 pane/name 的独立 agent 读回；无历史请求账本时缺席不能证明未启动')


class NativeReplacement:
    """生产调用方。scope 是调用者明确授权的坐标，不是观察结果。

    退出证据由同 terminal 的前台 shell + 原生 agent list 共同提供。
    read_cli 仅是外部 I/O 测试边界，正常调用使用有界 CLI。
    """
    def __init__(self, scope, evidence, *, read_cli=None):
        self.scope = dict(scope)
        self.evidence = evidence
        self.read_cli = read_cli or self._cli

    @staticmethod
    def _cli(*args):
        if __import__('os').environ.get('HERDR_ENV') != '1':
            raise ValueError('not inside a Herdr pane')
        result = subprocess.run(['herdr', *args], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise ValueError('native read Unknown: '+result.stderr.strip())
        if args[:2] == ('pane', 'read'):
            # pane read 的公开 CLI 输出是文本，不作为运行态身份 JSON 解码。
            return {'result': {'text': result.stdout}}
        value = json.loads(result.stdout)
        # schema 是 CLI 的静态 JSON Schema 文档，不使用运行态 result envelope。
        if args == ('api', 'schema', '--json') and isinstance(value.get('schemas'), dict):
            return value
        if not isinstance(value.get('result'), dict):
            raise ValueError('native result schema Unknown')
        return value

    def sample(self, scope):
        pane = self.read_cli('pane','get',scope['pane_id'])['result']['pane']
        keys = ('workspace_id','tab_id','pane_id','terminal_id','cwd')
        if not all(scope.get(k) and pane.get(k)==scope[k] for k in keys):
            raise ValueError('native pane identity/cwd mismatch or Unknown')
        process = self.read_cli('pane','process-info','--pane',scope['pane_id'])['result']['process_info']
        agents = self.read_cli('agent','list')['result']['agents']
        if process.get('pane_id')!=scope['pane_id'] or not isinstance(agents,list):
            raise ValueError('native process/agent schema Unknown')
        return pane,process,agents

    @staticmethod
    def available(scope, process, agents):
        foreground = process.get('foreground_processes')
        shell = process.get('shell_pid')
        return bool(shell and foreground and all(p.get('pid')==shell for p in foreground)
                    and not any(a.get('pane_id')==scope['pane_id'] for a in agents))

    def observe(self, source):
        request = source.get('replacement_intent',{}).get('native_request',{})
        scope = request.get('scope') or source.get('herdr',{})
        # 不用当前目标坐标替代原 source 坐标。
        _, process, agents = self.sample(scope)
        receipt=source.get('replacement_intent',{}).get('receipt',{})
        writer_pids=receipt.get('writer_pids') or source.get('herdr',{}).get('writer_pids')
        if not writer_pids:
            raise ValueError('inspect: original writer PID evidence Unknown')
        for pid in writer_pids:
            if not isinstance(pid,int) or pid<=0:
                raise ValueError('inspect: invalid original writer PID')
            try:
                os.kill(pid,0)
            except ProcessLookupError:
                continue
            raise ValueError('inspect: original writer PID still exists or was reused')
        errors = mc.capability_errors(source['agent'],source['model'],source['effort'],self.evidence)
        if errors or not self.available(scope,process,agents):
            raise ValueError('inspect: source writer active or capability Unknown')
        return dict(writer='exited',identity='match',capability='verified',gate='allowed')

    def verify_target(self, pane_id, claimed):
        if pane_id!=self.scope['pane_id']:
            raise ValueError('target outside authorized scope')
        _, process, agents = self.sample(self.scope)
        if not self.available(self.scope,process,agents):
            raise ValueError('target is not an available shell')
        return dict(pane_id=pane_id,identity='match',shell='available',scope='isolated_lane')

    def reconcile(self, row):
        request = row['replacement_intent']['native_request']
        scope = request.get('scope')
        if not scope or scope!=self.scope:
            return dict(status='unknown',gap='原请求缺少或不匹配 terminal scope')
        _, process, agents = self.sample(scope)
        named = [a for a in agents if a.get('name')==request['agent_name']]
        occupants = [a for a in agents if a.get('pane_id')==scope['pane_id']]
        if (len(named)==len(occupants)==1 and named==occupants
                and named[0].get('agent')==row['agent']
                and named[0].get('agent_status') in {'idle','done','working'}
                and named[0].get('interactive_ready') is True):
            foreground=process.get('foreground_processes',[])
            writer_pids=[p.get('pid') for p in foreground if p.get('pid')!=process.get('shell_pid')]
            if not writer_pids or not all(isinstance(pid,int) and pid>0 for pid in writer_pids):
                return dict(status='unknown',gap='原生 agent 无独立前台 writer PID')
            return dict(status='completed',receipt=dict(writer_pids=writer_pids,request_id=row['lane_id'],
                native_request=request,agent=named[0],evidence='independent agent list + pane identity',
                executedModel='Unknown',effort='Unknown'))
        return dict(status='unknown',gap='原 name/pane/kind/ready 无唯一读回；缺席不证明未启动，不重发')

    def execute(self, path, lane):
        row,_=lane_registry.read(path,lane)
        # 重放先恢复原坐标，不再要求目标空闲或再次 bind/start。
        if row['replacement_intent']['status']=='launching':
            return lane_registry.recover_launch(path,lane,self.reconcile)
        if row['replacement_intent']['status']!='accepted':
            return row
        def start(argv, claimed):
            result = subprocess.run(argv,capture_output=True,text=True,timeout=45)
            reply = start_result(result.returncode,result.stdout,result.stderr)
            reconciled = self.reconcile(claimed)
            if reconciled['status']=='completed':
                reconciled['receipt']['start_reply']=reply['native_reply']
            return reconciled
        return execute(path,lane,self.observe,self.scope['pane_id'],self.evidence,
                       self.verify_target,start,native_scope=self.scope)
