# ADR-0005: Current-Workspace-First Herdr Dispatch

**Status:** Accepted
**Date:** 2026-08-25
**Decider:** User (Dimon)

在 Herdr 内调用 `delivery-pipeline` 时，Coordinator Pane 当前所在的 Herdr Session 与 Workspace 是新 lane 的默认 dispatch target；只有用户显式要求时才创建新 Workspace。每条 lane 在目标 Workspace 的独立 tab/pane 中运行，并把 cwd 绑定到独立 Execution Worktree。Map Integration Worktree/branch 已存在时恢复，不存在时单独创建；Coordinator Pane 只承担调度，不切换自身 cwd 或 checked-out branch。由此，终端组织复用用户当前上下文，Git 隔离继续由两级 worktree 承担。

本 ADR 取代 ADR-0001 的“一 map 一 Herdr Workspace”条款；已有 active lane 仍按 registry 中的 session/workspace 坐标恢复，后续新 lane 再使用当前 Coordinator Pane 的默认落点。
