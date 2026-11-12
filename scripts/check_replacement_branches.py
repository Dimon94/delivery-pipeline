"""DD415 独立预期来自票 AC：原样、位置、停止和重拆，穿过唯一 Registry。"""
from copy import deepcopy
from pathlib import Path
import tempfile
from check_replacement import registry, observation, launch

A=dict(agent='pi',model='A',effort='high')
B=dict(agent='pi',model='B',effort='low')

def initial(path, fallbacks, source='work'):
    row=dict(lane_id='a',work_item=str(path),role='frontend',mode='explicit' if source=='explicit_mode' else 'none',
             runtime='herdr-pi-pane',state='blocked',**A,
             recovery_plan=dict(plan_version=1,source=source,primary=A,fallbacks=fallbacks),
             recovery_progress=dict(current_index=None,next_cursor=0))
    registry.write(path,row)
    return row

def claim(path,lane,category='tool_or_model',observe=observation):
    _,rev=registry.read(path,lane)
    return registry.claim(path,lane,rev,'failure-'+lane,category,observe)

def reject(path,lane,category,expected,observe=observation):
    before=path.read_bytes()
    try: claim(path,lane,category,observe)
    except ValueError as e: assert expected in str(e), str(e)
    else: raise AssertionError('unexpected successor: '+category)
    assert path.read_bytes()==before

def main():
    with tempfile.TemporaryDirectory() as td:
        for source in ('work','explicit_mode'):
            path=Path(td)/(source+'.md'); initial(path,[],source)
            lane='a'
            for i in range(2):
                nxt=claim(path,lane)
                assert {k:nxt[k] for k in A}==A
                assert nxt['recovery_progress']==dict(current_index=None,next_cursor=0)
                assert nxt['recovery_plan']['fallbacks']==[]
                assert nxt['mode']==('explicit' if source=='explicit_mode' else None)
                assert claim(path,lane)==nxt
                launch(path,nxt['lane_id'],observation,lambda _:dict(status='failed',receipt={'positive':'failure'}))
                lane=nxt['lane_id']
            reject(path,lane,'startup_failed','budget')
            assert len(registry.rows(path))==3
        for category in ('unknown','connection_interrupted'):
            path=Path(td)/(category+'.md');initial(path,[B,A,B])
            reject(path,'a',category,'inspect',lambda _:dict(writer='active'))
            nxt=claim(path,'a',category)
            assert {k:nxt[k] for k in A}==A
            assert nxt['recovery_progress']==dict(current_index=None,next_cursor=0)
            assert nxt['failure_category']==category
        for category,action in [('outcome_unknown','inspect'),('cancelled','stop'),('context_exhausted','resplit')]:
            path=Path(td)/(category+'.md');initial(path,[B])
            reject(path,'a',category,action)
            assert len(registry.rows(path))==1
        path=Path(td)/'positions.md';initial(path,[B,A,B]);lane='a'
        for expected,cursor in [(B,1),(A,2)]:
            nxt=claim(path,lane)
            assert {k:nxt[k] for k in A}==expected
            assert nxt['recovery_progress']==dict(current_index=cursor-1,next_cursor=cursor)
            assert nxt['recovery_plan']['fallbacks']==[B,A,B]
            launch(path,nxt['lane_id'],observation,lambda _:dict(status='failed',receipt={'positive':'failure'}))
            lane=nxt['lane_id']
        reject(path,lane,'startup_failed','budget')
        path=Path(td)/'exhausted.md';initial(path,[B]);nxt=claim(path,'a')
        launch(path,nxt['lane_id'],observation,lambda _:dict(status='failed',receipt={'positive':'failure'}))
        try: claim(path,nxt['lane_id'],'startup_failed')
        except ValueError as e: assert str(e)=='exhausted'
        else: raise AssertionError('exhausted repeated final entry')
        assert registry.read(path,nxt['lane_id'])[0]['state']=='blocked'
        assert len(registry.rows(path))==2
        path=Path(td)/'lost.md';initial(path,[]);nxt=claim(path,'a')
        def lost(_): raise OSError('response lost')
        try: launch(path,nxt['lane_id'],observation,lost)
        except OSError: pass
        reject(path,nxt['lane_id'],'unknown','inspect')
        assert registry.recover_launch(path,nxt['lane_id'],lambda _:dict(status='unknown'))['replacement_intent']['status']=='launching'
    print('DD415 Registry branches: pass')

if __name__=='__main__': main()
