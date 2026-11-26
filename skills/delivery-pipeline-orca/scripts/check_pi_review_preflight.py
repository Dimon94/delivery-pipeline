"""DD508 R5/R6：仅 native process I/O 替身，不允许预检启动或重发。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import review_dispatch as d


def check():
    target = dict(agent='pi', model='provider/exact', effort='xhigh')
    pools = dict(standards=[target, target], spec=[target])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        resources = root/'Orca.app/Contents/Resources'
        exe = resources/'bin/orca'; exe.parent.mkdir(parents=True)
        exe.write_text('fixture'); exe.chmod(0o755)
        app = resources.parent/'Info.plist'
        import plistlib
        app.write_bytes(plistlib.dumps({'CFBundleShortVersionString':'1.4.258'}))
        out=resources/'app.asar.unpacked/out'
        for name in ('shared/agent-launch/choices/agent-launch-model-preferences.js',
                     'shared/agent-session/options/agent-session-option-catalog.js',
                     'shared/agent-launch/catalog/tui-agent-config.js'):
            p=out/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('// native fixture')
        pi=root/'pi/dist/bundle/cli.js'; pi.parent.mkdir(parents=True); pi.write_text('fixture')
        package=pi.parent.parent.parent
        paths=['package.json','dist/cli/args.js','dist/core/model-config.js','dist/core/model-resolver.js','node_modules/@earendil-works/pi-ai/dist/models.js']
        for name in paths:
            p=package/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text('{}')
        (package/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':'1.5.2'}))
        models=root/'.pi/agent/models.json'; models.parent.mkdir(parents=True); models.write_text('{}')
        mode='ok'; calls=[]; orca_version='1.4.258'; pi_version='1.5.2'
        def io(argv, **kw):
            calls.append(argv)
            if argv[0]==str(exe):
                if argv[1:]==['--version']: value=orca_version
                elif argv[1:]==['skills','get','orca-cli','--full','--json']:
                    value=json.dumps(dict(name='orca-cli',full=True,markdown='terminal worktree orchestration'))
                elif argv[1:]==['orchestration','worker-start','--help']:
                    value='--terminal --worktree --task' if mode!='transport' else ''
                elif argv[1:]==['terminal','send','--help']: value='--terminal --text --enter --wait-submit'
                elif argv[1:]==['worktree','create','--help']: value='--name --base-branch'
                else: raise AssertionError('native mutation: '+repr(argv))
            elif argv[1:]==['--version']: value=pi_version
            elif '-e' in argv:
                rows={a:[dict(status='unknown',reason='exact native model catalog evidence missing') for t in ts] for a,ts in pools.items()}
                value=json.dumps(dict(rows=rows,sources=[],pi_transport=mode!='transport'))
            else:
                payload=json.loads(kw['input']); selected=payload['identities']
                rows=[dict(identity=t,status='runnable',reason='native parser accepted') for t in selected]
                if mode=='clamp':
                    for r in rows: r.update(status='unavailable',reason='native model thinking level rejected or remapped')
                if mode=='identity': rows[0]['identity']={**target,'model':'outside'}
                if mode=='metadata': return subprocess.CompletedProcess(argv,1,'','missing native parser')
                if mode=='stale': models.write_text('{"changed":true}')
                value=json.dumps(rows)
            return subprocess.CompletedProcess(argv,0,value,'')
        def which(name): return str(pi) if name=='pi' else '/usr/bin/node'
        with patch.dict(os.environ,{'ORCA_CLI_COMMAND':str(exe)}), patch('subprocess.run',side_effect=io), patch('shutil.which',side_effect=which), patch.object(Path,'home',return_value=root):
            got=d.collect_native(pools,'r1')
            assert all(r['status']=='runnable' for rs in got['capabilities'].values() for r in rs), got
            assert got['ordered_pools']==pools and got['request_id']=='r1'
            ids=[r['evidence_id'] for rs in got['capabilities'].values() for r in rs]
            assert len(set(ids))==3, 'duplicate positions lost'
            for failure in ('metadata','clamp','identity','stale','transport'):
                mode=failure
                got=d.collect_native(pools,'r1')
                expected='unavailable' if failure=='clamp' else 'unknown'
                assert got['capabilities']['standards'][0]['status']==expected, (failure,got)
            # 重复只读采集不发 mutation，request 和来源重新绑定。
            mode='ok'
            second=d.collect_native(pools,'r2')
            assert second['capabilities']['standards'][0]['evidence_id']!=ids[0]
            # Harness 升级不阻断：Orca/Pi 版本号变了，能力与原生解析仍在即 runnable。
            orca_version, pi_version = '1.5.0', '1.6.1'
            app.write_bytes(plistlib.dumps({'CFBundleShortVersionString':orca_version}))
            (package/'package.json').write_text(json.dumps({'name':'@earendil-works/pi-coding-agent','version':pi_version}))
            got=d.collect_native(pools,'r3')
            assert all(r['status']=='runnable' for rs in got['capabilities'].values() for r in rs), got
        # 穿过真实共享 JS probe；替身仅为 Pi 安装模块这个外部边界。
        (package/'package.json').write_text('{"type":"module"}')
        (package/'dist/cli/args.js').write_text("export const parseArgs = a => ({model:a[2], thinking:a[4], diagnostics:[], unknownFlags:new Set()});")
        (package/'dist/core/model-config.js').write_text("export class ModelConfig { static async load(){return new ModelConfig()}; getError(){return null}; getProviderIds(){return ['provider']}; getProvider(){return {api:'test',models:[{id:'exact',thinkingLevelMap:{xhigh:'xhigh'}}]}} };")
        (package/'dist/core/model-resolver.js').write_text("export const findExactModelReferenceMatch=(id,ms)=>ms.find(m=>m.provider+'/'+m.id===id); export const resolveCliModel=o=>({model:o.modelRuntime.getModels()[0]});")
        level=package/'node_modules/@earendil-works/pi-ai/dist/models.js'
        (level.parents[1]/'package.json').write_text('{"type":"module"}')
        probe=HERE.parents[1]/'delivery-pipeline-setup/scripts/native_review_probe.mjs'
        payload=json.dumps(dict(package=str(package),models_path=str(models),identities=[target]))
        import shutil
        for clamp,expected in ((False,'runnable'),(True,'unavailable')):
            level.write_text("export const getSupportedThinkingLevels=m=>['xhigh']; export const clampThinkingLevel=(m,e)=>"+("'high'" if clamp else "e")+";")
            raw=subprocess.run([shutil.which('node'),str(probe)],input=payload,text=True,capture_output=True,check=True)
            assert json.loads(raw.stdout)[0]['status']==expected, 'native clamp must refuse requested effort'
    print('pi-agent-argv: pass (native I/O boundary only; mutation forbidden)')

if __name__=='__main__': check()
