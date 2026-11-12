#!/usr/bin/env python3
"""两个同基线合作写者的有界交错模型；标准库显式状态穷举，无工具依赖。"""
from collections import deque


def verify(broken=None):
    # (文件版本, 锁owner, 两个pc, 两个结果)。pc: lock/read-check/replace/readback/release/done
    start = (0, -1, (0, 0), ('pending', 'pending'))
    seen = {start}
    queue = deque([(start, ())])
    while queue:
        state, trace = queue.popleft()
        version, owner, pcs, results = state
        assert results.count('applied') <= 1, trace
        for i in range(2):
            pc = pcs[i]
            if pc == 5:
                continue
            options = []
            if pc == 0 and (owner == -1 or broken == 'lock'):
                options.append((version, i, 1, 'pending', '获取锁'))
            if pc == 1:
                if version != 0 and broken != 'hash':
                    options.append((version, owner, 4, 'rejected', 'hash冲突'))
                else:
                    options.append((version, owner, 2, 'pending', '核对基线'))
            if pc == 2:
                options += [(i + 1, owner, 3, 'pending', 'replace'),
                            (version, owner, 4, 'rejected', '提交前失败')]
            if pc == 3:
                options += [(version, owner, 4, 'applied', '精确读回'),
                            (version, owner, 4, 'rejected' if broken == 'post' else 'commit_unverified', '读回失败')]
            if pc == 4:
                options.append((version, -1 if owner == i else owner, 5, results[i], '释放锁'))
            # 崩溃无返回结果；OS 释放该进程锁，replace 后文件保留。
            if pc in (1, 2, 3):
                options.append((version, -1 if owner == i else owner, 5, 'crashed', '进程崩溃'))
            for v, lock, next_pc, result, action in options:
                step = trace + (f'{i}:{action}',)
                if pc == 3 and action == '读回失败':
                    assert result == 'commit_unverified', step
                next_pcs = list(pcs); next_pcs[i] = next_pc
                next_results = list(results); next_results[i] = result
                successor = (v, lock, tuple(next_pcs), tuple(next_results))
                if successor not in seen:
                    seen.add(successor); queue.append((successor, step))
    return len(seen)


if __name__ == '__main__':
    print(f'共享事务模型通过：{verify()} 个状态')
    for mutant in ('lock', 'hash', 'post'):
        try:
            verify(mutant)
        except AssertionError as error:
            print(f'模型拒绝 {mutant}: {error}')
        else:
            raise AssertionError(f'模型未拒绝错误实现 {mutant}')
