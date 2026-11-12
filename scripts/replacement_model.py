"""有界枚举：1 work_item、0..3 个备用（含重复）、2 通知者、2 次认领。

claim、launch 标记与 receipt 为不同步骤；崩溃重启保留持久前缀。
"""
from collections import deque


def explore(length, broken=None, active=False, gate=True):
    # cursor, accepted, pending, launched, receipts；两个通知者争用同一个 source。
    start=(0,0,False,(),(),())
    queue=deque([start]); seen={start}
    while queue:
        cursor,count,pending,launched,receipts,edges=state=queue.popleft()
        assert not active or count==0,'active writer claimed'
        assert gate or count==0,'unknown native gate claimed'
        assert len({source for source,target in edges})==len(edges),'double successor'
        assert count<=2,'third accepted replacement'
        assert cursor==count and cursor<=length,'cursor skip/outside list'
        assert len(set(launched))==len(launched),'duplicate launch'
        next_states=[]
        if not pending and (not active or broken=='writer') and gate and count<min(length,3 if broken=='budget' else 2):
            for notifier in range(2):
                step=2 if broken=='cursor' else 1
                next_states.append((cursor+step,count+1,True,launched,receipts,edges+((count,count+1),)))
        if pending and broken=='claim':
            next_states.append((cursor,count,True,launched,receipts,edges+((count-1,count+1),)))
        if pending:
            if count not in launched or broken=='launch':
                next_states.append((cursor,count,True,launched+(count,),receipts,edges))
            # Unknown 与任意崩溃：不推进；重启读回同状态。
            next_states.append(state)
            if count in launched:
                next_states.append((cursor,count,False,launched,receipts+(count,),edges))
        for nxt in next_states:
            if nxt not in seen:
                seen.add(nxt);queue.append(nxt)
    return len(seen)


def main():
    total=sum(explore(n,active=active,gate=gate) for n in range(4) for active in (False,True) for gate in (False,True))
    for variant,n in [('budget',3),('cursor',3),('launch',1),('writer',1),('claim',1)]:
        try:
            explore(n,variant,active=variant=='writer')
        except AssertionError:
            pass
        else:
            raise AssertionError('model failed to reject '+variant)
    print(f'replacement bounded model: pass ({total} states; 5 broken variants rejected)')

if __name__=='__main__':
    main()
