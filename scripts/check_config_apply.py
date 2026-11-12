"""DD-377 R2–R6：桌面公开命令与 setup 共享事务。"""
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from check_config_transaction import m, SCRIPT, FAULT_RUNNER
import sys


def check():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'config.json'
        ev = Path(tmp)/'evidence.json'
        base = m.valid_fixture()
        path.write_text(json.dumps(base))
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        evidence = {'request_id':'save', 'observed_at':'now', 'sources':{'pi':{'status':'ok'}}, 'capabilities':{'pi':{'binary':True,'models':{'provider/model':['low','medium','high']}}}}
        ev.write_text(json.dumps(evidence))
        def args(command='apply', fault=None):
            a = [sys.executable,str(SCRIPT)] if not fault else [sys.executable,'-c',FAULT_RUNNER,str(SCRIPT),fault]
            return a+[command,str(path),'--base-hash',digest,'--request-id','save','--evidence',str(ev)]
        def run(candidate, fault=None):
            p = subprocess.run(args(fault=fault),input=json.dumps(candidate),text=True,capture_output=True)
            assert p.stdout, p.stderr
            return p.returncode,json.loads(p.stdout)
        code,result = run(base)
        assert code == 0 and result['changed'] is False, result
        assert path.read_bytes() == raw
        for section in ('modes','work','review','old'):
            candidate=copy.deepcopy(base)
            if section=='modes': candidate['work']['coordinator']={'agent':'pi','model':'provider/model','effort':'low'}
            elif section=='work': candidate['work']['planning']['extra']='forbidden'
            elif section=='old': candidate['version']=4
            else: candidate['transport']='codex-app'
            code,result=run(candidate)
            assert code==1 and result['status']=='rejected',result
            assert path.read_bytes()==raw
        candidate=copy.deepcopy(base);candidate['work']['planning']['effort']='low'
        for fault in ('pre','temp'):
            code,result=run(candidate,fault)
            assert code==1 and result['status']=='rejected' and path.read_bytes()==raw,result
        evidence['request_id']='old';ev.write_text(json.dumps(evidence))
        assert run(candidate)[1]['error']['code']=='capability_unavailable'
        evidence['request_id']='save';ev.write_text(json.dumps(evidence))
        # 两个独立调用者、同一基线，只允许一个提交。
        procs=[subprocess.Popen(args(c,'delay'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for c in ('apply','configure')]
        results=[p.communicate(json.dumps(candidate)) for p in procs]
        assert sorted(p.returncode for p in procs)==[0,1],results
        assert any(json.loads(out)['error']['code']=='base_conflict' for p,(out,_) in zip(procs,results) if p.returncode==1)
        path.write_bytes(raw)
        code,result=run(candidate,'post')
        assert code==3 and result['status']=='commit_unverified',result
        assert json.loads(path.read_text())==candidate
        path.write_bytes(raw)
        code,result=run(candidate)
        assert code==0 and result['config']==candidate and result['base_hash']==hashlib.sha256(path.read_bytes()).hexdigest(),result
        assert run(base)[1]['error']['code']=='base_conflict'
        path.unlink()
        assert run(base)[0]==1 and not path.exists()
    print('desktop apply: pass')

if __name__=='__main__':check()
