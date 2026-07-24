# Wayfinder Implementation Dispatcher

[English README](README.md)

一个个人 Codex/Claude skill bundle，只负责把现成的 implementation tickets 自动分配给
相互隔离的 Codex workers。

输入 tracker issue URL 或编号后，它读取当前 dependency 与写足迹，计算
`maximal safe batch`，为每张入选票创建独立 Git worktree 并启动 Codex worker，验证
pane 落点与 cwd，并把每个输入报告为 `dispatched` 或 `deferred`。

验证派发完成后 skill 立即结束。票面准备、执行监控、结果收敛、集成、tracker 写入和远程
发布由调用方或其他 skill 负责。

## 安装

先安装 Matt Pocock 的 `implement` skill，然后运行：

```bash
./scripts/install.sh
```

安装 Claude/Herdr 版：

```bash
./scripts/install.sh --target claude
```

同时安装两个版本：

```bash
./scripts/install.sh --target all
```

所有目标都会软链接到当前 checkout。

## 使用

Codex：

```text
使用 $wayfinder-implement-orchestrator 分配 <issue-url> <issue-url> ...
```

Herdr 中的 Claude：

```text
使用 /wayfinder-implement-orchestrator <issue-url> <issue-url> ...
```

## 校验

```bash
python3 scripts/validate.py
```
