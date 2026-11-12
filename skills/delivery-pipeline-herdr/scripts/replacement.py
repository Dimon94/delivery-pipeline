"""Herdr replacement Adapter：仅消费共享 claim，不解析 work 配置。

observe 必须读取原生 writer/identity/capability/gate；未有版本匹配证据时禁止调用。
unknown 的 agent start 不自动重发。reconcile 使用原 pane/name/request 坐标，由宿主读回。
"""
import importlib.util
from pathlib import Path
import subprocess
import json
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


def execute(path, lane, observe, pane_id, evidence, verify_target, native_start=None):
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
    lane_registry.bind_request(path,lane,{'argv':argv,'pane_id':pane_id,'agent_name':lane},native_observation,runtime=dispatch.RUNTIME[claimed['agent']])
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
