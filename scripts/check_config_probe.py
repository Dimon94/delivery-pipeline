#!/usr/bin/env python3
"""通过公开 probe 命令核验来源隔离与精确身份；外部来源受控。"""
import json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
tool = root / 'skills/delivery-pipeline-setup/scripts/model_config.py'
raw = {'gateway': {'status':'ok','data':[{'id':'vendor/model@large','supported_reasoning_levels':[{'effort':'low'},{'effort':'high'},{'effort':'max'}]}]},
       'harnesses': {'pi': {'binary':True,'route':True,'models':[{'native_id':'magpie/vendor/model@large','gateway_id':'vendor/model@large','efforts':['low','high']}]},
                     'codex': {'binary':True,'route':True,'models':[{'native_id':'vendor/model@large','gateway_id':'vendor/model@large','efforts':['high','xhigh']}]},
                     'claude': {'binary':False,'route':False,'models':[]}}}
def probe(value):
    p = subprocess.run([sys.executable,str(tool),'probe','--request-id','acceptance'],input=json.dumps(value),text=True,capture_output=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)
p = probe(raw)
assert p['request_id'] == 'acceptance' and p['observed_at']
assert p['gateway'] == {'status':'ok'}, 'Host 传入 ok 时证据必须声明网关可达'
assert p['capabilities']['pi']['models'] == {'magpie/vendor/model@large':['low','high']}
assert p['capabilities']['codex']['models'] == {'vendor/model@large':['high']}
assert p['sources']['pi']['status'] == 'ok' and p['sources']['claude']['status'] == 'unknown'
unmapped = json.loads(json.dumps(raw))
unmapped['harnesses']['codex']['models'] = [{'native_id':'gpt-native-only','efforts':['high']}]
p = probe(unmapped)
assert p['capabilities']['codex']['models'] == {}, '原生 catalog 不能绕过 magpie 来源边界'
assert p['sources']['codex']['status'] == 'unknown'
raw['harnesses']['codex']['route'] = False
p = probe(raw)
assert p['capabilities']['codex']['models'] == {} and p['sources']['pi']['status'] == 'ok'
raw['gateway'] = {'status':'unknown'}
p = probe(raw)
assert p['capabilities']['pi']['models'] == {}
assert p['gateway'] == {'status':'unreachable'}, '网关未知必须区分为 unreachable'
for odd in ({'status':'OK'}, {'status':'error','data':[]}, {}):
    raw['gateway'] = odd
    assert probe(raw)['gateway'] == {'status':'unreachable'}, '只有精确的 ok 才算可达'
del raw['gateway']
assert probe(raw)['gateway'] == {'status':'unreachable'}, 'Host 未传 gateway 时不能当作可达'
print('probe contract: pass')
