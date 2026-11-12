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
assert p['capabilities']['pi']['models'] == {'magpie/vendor/model@large':['low','high']}
assert p['capabilities']['codex']['models'] == {'vendor/model@large':['high']}
assert p['sources']['pi']['status'] == 'ok' and p['sources']['claude']['status'] == 'unknown'
raw['harnesses']['codex']['route'] = False
p = probe(raw)
assert p['capabilities']['codex']['models'] == {} and p['sources']['pi']['status'] == 'ok'
raw['gateway'] = {'status':'unknown'}
p = probe(raw)
assert p['capabilities']['pi']['models'] == {}
print('probe contract: pass')
