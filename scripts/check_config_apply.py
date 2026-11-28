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
    _check_v9_task_types()
    print('desktop apply: pass')


def _check_v9_task_types():
    """DD-687：v9 任务类型增删改（S2）与按三元组变更放行能力证据（S5）。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'v9-config.json'
        ev = Path(tmp) / 'v9-evidence.json'
        v9, _ = m.migrate_document(m.valid_fixture())
        path.write_text(json.dumps(v9, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        modes_bytes = json.dumps(v9['modes'], ensure_ascii=False, indent=2).encode('utf-8')

        evidence = {
            'request_id': 'save-v9',
            'observed_at': '2026-11-27T12:00:00Z',
            'sources': {'pi': {'status': 'ok'}},
            'capabilities': {'pi': {'binary': True, 'models': {'provider/model': ['low', 'medium', 'high']}}},
        }
        ev.write_text(json.dumps(evidence), encoding='utf-8')

        def run_cmd(command, candidate=None, base_hash=None, req_id='save-v9'):
            cmd = [sys.executable, str(SCRIPT), command, str(path)]
            if command == 'apply':
                cmd += ['--base-hash', base_hash, '--request-id', req_id, '--evidence', str(ev)]
            p = subprocess.run(
                cmd,
                input=json.dumps(candidate) if candidate is not None else None,
                text=True,
                capture_output=True,
            )
            assert p.stdout.strip(), p.stderr
            return p.returncode, json.loads(p.stdout)

        # S2：v9 新增 work.advisory-doc（purpose artifact），同候选改 modes 被拒且原字节不变。
        advisory = {
            'agent': 'pi',
            'model': 'provider/model',
            'effort': 'high',
            'fallbacks': [],
            'label': '咨询建议',
            'hint': '输出调研与方案建议文档',
            'purpose': 'artifact',
        }
        added = copy.deepcopy(v9)
        added['work']['advisory-doc'] = copy.deepcopy(advisory)

        tampered = copy.deepcopy(added)
        tampered['modes']['standard']['agents']['pi']['direct']['effort'] = 'high'
        code, res = run_cmd('apply', tampered, digest)
        assert code == 1 and res['status'] == 'rejected', res
        assert path.read_bytes() == raw

        code, res = run_cmd('apply', added, digest)
        assert code == 0 and res['status'] == 'applied' and res['changed'] is True, res
        code, shown = run_cmd('show')
        assert code == 0 and shown['file_state'] == 'ready' and shown['validation']['valid'] is True, shown
        assert shown['config']['work']['advisory-doc'] == advisory
        assert 'work.advisory-doc' in shown['cells']
        assert json.dumps(shown['config']['modes'], ensure_ascii=False, indent=2).encode('utf-8') == modes_bytes

        # S5：某类型原模型能力不可用且三元组未改，只改 label/hint 或删另一可选类型不带新证据也 applied；
        # 新增类型或改该类型模型缺本次证据时返回 capability_unavailable 且磁盘原字节不变。
        retired = copy.deepcopy(shown['config'])
        retired['work']['backend']['model'] = 'provider/retired-model'
        path.write_text(json.dumps(retired, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        unavailable_ev = {
            'request_id': 'save-s5',
            'observed_at': '2026-11-27T12:05:00Z',
            'sources': {'pi': {'status': 'unknown'}},
            'capabilities': {'pi': {'binary': True, 'models': {}}},
        }
        ev.write_text(json.dumps(unavailable_ev), encoding='utf-8')

        cur_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        meta_only = copy.deepcopy(retired)
        meta_only['work']['backend']['label'] = '服务端开发'
        meta_only['work']['backend']['hint'] = '负责服务端 API 与数据层'
        code, res = run_cmd('apply', meta_only, cur_hash, req_id='save-s5')
        assert code == 0 and res['status'] == 'applied' and res['changed'] is True, res
        assert res['config']['work']['backend']['label'] == '服务端开发'
        assert res['config']['work']['backend']['model'] == 'provider/retired-model'

        cur_hash = res['base_hash']
        delete_opt = copy.deepcopy(meta_only)
        del delete_opt['work']['design']
        code, res = run_cmd('apply', delete_opt, cur_hash, req_id='save-s5')
        assert code == 0 and res['status'] == 'applied' and res['changed'] is True, res
        assert 'design' not in res['config']['work']

        # Python API 不传证据对象（evidence=None）时，仅改 hint 也 applied。
        cur_hash = res['base_hash']
        hint_only = copy.deepcopy(delete_opt)
        hint_only['work']['backend']['hint'] = '只改说明不改模型'
        direct_res = m.apply(path, hint_only, cur_hash, None, 'save-s5-none')
        assert direct_res['status'] == 'applied' and direct_res['changed'] is True, direct_res

        cur_raw = path.read_bytes()
        cur_hash = hashlib.sha256(cur_raw).hexdigest()
        add_without_ev = copy.deepcopy(hint_only)
        add_without_ev['work']['extra-doc'] = copy.deepcopy(advisory)
        code, res = run_cmd('apply', add_without_ev, cur_hash, req_id='save-s5')
        assert code == 1 and res['status'] == 'rejected' and res['error']['code'] == 'capability_unavailable', res
        assert path.read_bytes() == cur_raw

        change_model_without_ev = copy.deepcopy(hint_only)
        change_model_without_ev['work']['backend']['model'] = 'provider/model'
        code, res = run_cmd('apply', change_model_without_ev, cur_hash, req_id='save-s5')
        assert code == 1 and res['status'] == 'rejected' and res['error']['code'] == 'capability_unavailable', res
        assert path.read_bytes() == cur_raw

        direct_rej = m.apply(path, change_model_without_ev, cur_hash, None, 'save-s5-none')
        assert direct_rej['status'] == 'rejected' and direct_rej['error']['code'] == 'capability_unavailable', direct_rej
        assert path.read_bytes() == cur_raw


if __name__=='__main__':check()
