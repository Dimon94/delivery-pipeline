"""有界安全模型：一个 work_item、0..3 位置、两通知者、两次 accepted。

分类与 native 观察为有界输入；不证明实际模型身份或原生 exactly-once。
"""
from collections import deque


def explore(length, broken=None, active=False, gate=True, category='tool_or_model', mode=False, selected=True):
    start=(0,0,False,(),(),())
    queue=deque([start]); seen={start}
    repeat=mode or length==0 or category in {'unknown','connection_interrupted'}
    stopped=category in {'cancelled','context_exhausted','outcome_unknown'}
    while queue:
        cursor,count,pending,launched,receipts,edges=state=queue.popleft()
        assert not active or count==0,'active writer claimed'
        assert selected or count==0,'unavailable selected target claimed'
        assert gate or count==0,'unknown native gate claimed'
        assert not stopped or count==0,'stopped category claimed'
        assert len({source for source,target in edges})==len(edges),'double successor'
        assert count<=2,'third accepted replacement'
        assert cursor==(0 if repeat else count) and cursor<=length,'cursor skip/outside list'
        assert len(set(launched))==len(launched),'duplicate launch'
        next_states=[]
        allowed=(not stopped or broken=='classification') and (repeat or cursor<length or broken=='exhausted')
        if not pending and (not active or broken=='writer') and gate and (selected or broken=='selected') and allowed and count<(3 if broken=='budget' else 2):
            for notifier in range(2):
                step=2 if broken=='cursor' else (0 if repeat else 1)
                next_states.append((cursor+step,count+1,True,launched,receipts,edges+((count,count+1),)))
        if pending and broken=='claim':
            next_states.append((cursor,count,True,launched,receipts,edges+((count-1,count+1),)))
        if pending:
            if count not in launched or broken=='launch':
                next_states.append((cursor,count,True,launched+(count,),receipts,edges))
            next_states.append(state)
            if count in launched:
                next_states.append((cursor,count,False,launched,receipts+(count,),edges))
        for nxt in next_states:
            if nxt not in seen:
                seen.add(nxt);queue.append(nxt)
    return len(seen)


def main():
    total=sum(explore(n,active=active,gate=gate,category=c,mode=mode,selected=selected)
              for n in range(4) for active in (False,True) for gate in (False,True)
              for selected in (False,True) for mode in (False,True) for c in ('tool_or_model','startup_failed','unknown',
              'connection_interrupted','outcome_unknown','cancelled','context_exhausted'))
    cases=[('budget',3,{}),('budget',0,{}),('cursor',3,{}),('launch',1,{}),
           ('writer',1,{'active':True}),('claim',1,{}),('exhausted',1,{})]
    cases += [('selected',1,{'selected':False})]
    cases += [('classification',1,{'category':c}) for c in ('cancelled','context_exhausted','outcome_unknown')]
    for variant,n,options in cases:
        try: explore(n,variant,**options)
        except AssertionError: pass
        else: raise AssertionError('model failed to reject '+variant)
    print(f'replacement bounded model: pass ({total} states; {len(cases)} broken variants rejected)')

if __name__=='__main__': main()
