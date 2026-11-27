"""DD-411：公开 CLI 的有序重复、显式迁移与证据计数合同。"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from check_config_transaction import m, SCRIPT


def check():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'config.json'
        evidence = Path(tmp)/'evidence.json'
        a = {'agent':'pi','model':'provider/model','effort':'high'}
        b = {**a,'effort':'low'}
        old = {'version':5,'work':{n:dict(a) for n in ('planning','design','frontend','backend','testing')},'modes':{},'review':{s:{x:dict(a) for x in ('standards','spec')} for s in ('implementation','whole-change')}}
        path.write_text(json.dumps(old)); raw=path.read_bytes()
        def run(command, candidate=None, *args):
            p=subprocess.run([sys.executable,str(SCRIPT),command,str(path),*args],input=json.dumps(candidate) if candidate is not None else None,text=True,capture_output=True)
            return p.returncode,json.loads(p.stdout)
        assert run('show')[1]['file_state']=='unsupported_version'
        assert path.read_bytes()==raw
        assert run('migrate')[0]==0
        migrated=json.loads(path.read_text())
        expected=copy.deepcopy(old);expected.update(version=9, model_families={}, dispatch={'parallel':4,'max_turns':100})
        for task, c in expected['work'].items():
            c['fallbacks']=[]
            c.update(m.DEFAULT_TASK_META[task])
        for axes in expected['review'].values():
            for c in axes.values():c['candidates']=[]
        assert migrated==expected
        stat=path.stat();assert run('migrate')[0]==0
        assert path.stat().st_mtime_ns==stat.st_mtime_ns
        candidate=copy.deepcopy(expected);candidate['work']['planning']['fallbacks']=[b,a,b,a]
        ev={'request_id':'save','observed_at':'now','sources':{'pi':{'status':'ok'}},'capabilities':{'pi':{'binary':True,'models':{'provider/model':['high','low']}}}}
        evidence.write_text(json.dumps(ev))
        def apply(c):return run('apply',c,'--base-hash',hashlib.sha256(path.read_bytes()).hexdigest(),'--request-id','save','--evidence',str(evidence))
        code,result=apply(candidate);assert code==0,result
        assert json.loads(path.read_text())==candidate and result['config']==candidate
        # 排序/删除可保留 unavailable 原值，增加重复次数必须有本次能力。
        ev['sources']['pi']['status']='unknown';evidence.write_text(json.dumps(ev))
        reordered=copy.deepcopy(candidate);reordered['work']['planning']['fallbacks']=[a,b,a,b]
        assert apply(reordered)[0]==0
        bad=copy.deepcopy(reordered);bad['work']['planning']['fallbacks'].append(b)
        raw=path.read_bytes();assert apply(bad)[0]==1 and path.read_bytes()==raw
        for change in ('extra','review','stale'):
            bad=copy.deepcopy(reordered)
            if change=='extra':bad['work']['planning']['fallbacks'][0]['extra']=True
            elif change=='review':bad['review']['implementation']['spec']['candidates']=[a]
            else:ev['request_id']='old';evidence.write_text(json.dumps(ev))
            assert apply(bad)[0]==1 and path.read_bytes()==raw
    print('fallbacks: pass')

if __name__=='__main__':check()
