"""PROTOTYPE：一次小样本 CLI 对比；不证明 App transport 或模型优劣。"""
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

OUT = Path(__file__).resolve().parent
WORK = None
TOKEN = secrets.token_hex(8)
SPEC = """实现 worker.py 中纯函数 apply(state, event)，只用 Python 标准库，不修改输入。
state 字段：phase、checkpoint、pending、seen；初始值 idle、None、None、[]。
event 含 id、kind，可带 checkpoint。重复 id 返回等值 state。
合法转换：start: idle->starting；ready: starting->ready 且保存非空 checkpoint；
dispatch: ready->switching 且 event.checkpoint 与保存值相等，pending=本 event.id；
unknown: switching 保持 switching；ack: switching->executing，pending=None；
finish: executing->review；approve: review->reviewed；integrate: reviewed->integrated。
所有不合法事件抛 ValueError，失败不改变输入；成功（含 unknown）将 id 追加 seen。
只编辑 worker.py，不建其他文件、不用网络、不安装依赖、不委派、不做 git 操作。
任务结束不意味着可以省略必要验证。"""
INITIAL = "def apply(state, event):\n    raise NotImplementedError\n"
results = []


def run(label, model, effort, prompt, command=None, session=None):
    args = ["codex", "exec"]
    if command:
        args.append(command)
    args += ["--ignore-user-config", "--skip-git-repo-check", "--json",
             "-m", model, "-c", f'model_reasoning_effort="{effort}"',
             "-c", 'service_tier="default"', "-c", "agents.enabled=false",
             "-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"']
    if session:
        args.append(session)
    args.append("-")
    (OUT / f"{label}-prompt.txt").write_text(prompt)
    start = time.monotonic()
    with (OUT / f"{label}.jsonl").open("w") as log, (OUT / f"{label}.stderr").open("w") as err:
        process = subprocess.Popen(args, cwd=WORK, stdin=subprocess.PIPE, stdout=log, stderr=err, text=True)
        try:
            process.communicate(prompt, timeout=180)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    events = []
    for line in (OUT / f"{label}.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    started = next((x for x in events if x.get("type") == "thread.started"), {})
    terminal = next((x for x in reversed(events) if x.get("type") == "turn.completed"), {})
    messages = [x.get("item", {}).get("text", "") for x in events
                if x.get("type") == "item.completed" and x.get("item", {}).get("type") == "agent_message"]
    record = dict(label=label, requested_model=model, effort=effort, seconds=round(time.monotonic()-start, 2),
                  exit=process.returncode, thread_id=started.get("thread_id"), usage=terminal.get("usage"),
                  final="\n".join(messages), token_recalled=TOKEN in "\n".join(messages),
                  runtime_model="Unknown", runtime_service_tier="Unknown")
    if (WORK / "worker.py").exists():
        shutil.copyfile(WORK / "worker.py", OUT / f"{label}-worker.py")
    results.append(record)
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in record.items() if k!='final'}, ensure_ascii=False), flush=True)
    return record


def evaluate(label):
    path = OUT / f"{label}-worker.py"
    spec = importlib.util.spec_from_file_location(label, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        return dict(passed=0, total=8, failures=[repr(error)])
    import copy
    def fresh():
        return dict(phase="idle", checkpoint=None, pending=None, seen=[])
    def step(s, kind, **fields):
        return module.apply(s, dict(id=kind, kind=kind, **fields))
    def ready():
        return step(step(fresh(), "start"), "ready", checkpoint="c1")
    def rejected(s, event):
        old = copy.deepcopy(s)
        try:
            module.apply(s, event)
        except ValueError:
            return s == old
        return False
    checks = [
        ("正常完整路径", lambda: complete(step, fresh)["phase"] == "integrated"),
        ("输入不变", lambda: immutable(module.apply, fresh())),
        ("重复事件幂等", lambda: step(step(fresh(), "start"), "start") == step(fresh(), "start")),
        ("旧检查点拒绝", lambda: rejected(ready(), dict(id="d", kind="dispatch", checkpoint="old"))),
        ("未知结果不能冒充执行", lambda: step(step(ready(), "dispatch", checkpoint="c1"), "unknown")["phase"] == "switching"),
        ("Review 前不能集成", lambda: rejected(ready(), dict(id="i", kind="integrate"))),
        ("空检查点拒绝", lambda: rejected(step(fresh(), "start"), dict(id="r", kind="ready", checkpoint=""))),
        ("确认后清除 pending", lambda: step(step(ready(), "dispatch", checkpoint="c1"), "ack")["pending"] is None),
    ]
    failures = []
    for name, check in checks:
        try:
            assert check()
        except Exception as error:
            failures.append(name+": "+repr(error))
    return dict(passed=len(checks)-len(failures), total=len(checks), failures=failures)


def complete(step, fresh):
    state = fresh()
    for kind in ["start", "ready", "dispatch", "ack", "finish", "approve", "integrate"]:
        state = step(state, kind, **({"checkpoint":"c1"} if kind in ("ready","dispatch") else {}))
    return state


def immutable(apply, state):
    import copy
    old = copy.deepcopy(state)
    apply(state, dict(id="start",kind="start"))
    return state == old


if __name__ == "__main__":
    import sys
    if "--check-only" in sys.argv:
        for label in ("direct-sol", "prewalk-sol", "prewalk-luna"):
            result = evaluate(label)
            print(label, result)
            assert result["passed"] == result["total"]
        raise SystemExit(0)
    WORK = Path(tempfile.mkdtemp(prefix="prewalk-prototype-"))
    (OUT / "workspace.txt").write_text(str(WORK))
    (WORK / "worker.py").write_text(INITIAL)
    direct = run("direct-sol", "gpt-5.6-sol", "high", SPEC+"\n完成全部实现，运行最小验证后结束。")
    if direct["exit"] != 0:
        raise SystemExit("CLI 探针启动失败；保留原始证据，不继续消耗。")
    (WORK / "worker.py").write_text(INITIAL)
    starter = run("astra-start", "gpt-6-astra", "low", SPEC+f"\n仅本起步轮：读取现有文件，制定 TODO，只实现 start 转换与输入不变性，其他转换留给接续轮。运行一个最小 start 检查，然后回复 PREWALK_READY 与剩余 TODO 并停止。会话专属交接口令为 {TOKEN}；不要写入文件，后续会询问它。")
    if not starter["thread_id"] or starter["exit"] != 0:
        raise SystemExit("起步失败，停止。")
    seed = (WORK / "worker.py").read_text()
    prompt = "现在进入接续阶段，起步限制已结束。在相同工作目录沿已有会话的需求、TODO 和首处实现完成 worker.py，运行最小验证。不修改其他文件，不查看会话日志，不用网络、不委派、不做 git 操作。最后回复你从会话记得的交接口令（不要从文件找）和验证结果；不知道口令就写 Unknown。"
    for label, model in [("prewalk-sol", "gpt-5.6-sol"), ("prewalk-luna", "gpt-5.6-luna")]:
        (WORK / "worker.py").write_text(seed)
        run(label, model, "high", prompt, "fork", starter["thread_id"])
    for item in results:
        if item["label"] != "astra-start":
            item["checks"] = evaluate(item["label"])
            item["lines"] = len((OUT / f"{item['label']}-worker.py").read_text().splitlines())
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("PROBE_COMPLETE", flush=True)
