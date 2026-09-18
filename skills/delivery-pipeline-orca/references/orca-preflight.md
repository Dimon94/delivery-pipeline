# Orca 机械 preflight

由 `delivery-pipeline-orca` SKILL.md 的「机械 preflight」节引入；本文件承载逐字段合同。
Orca executable 已由「每次进入操作前」第 1 步固定，本 helper 不自行寻找 binary。

运行：

```bash
python3 scripts/preflight.py run --payload <json>
```

## Request 字段

```json
{
  "coordinator_runtime": "orca-terminal",
  "operation": "dispatch|recovery|provider-mutation|browser-automation|remote-publication|fan-in|cleanup|monitor",
  "cli": {
    "executable": "<exact argv prefix, e.g. orca or absolute path>",
    "version_output": "<first line of --version or Unknown>",
    "guides_read": ["skills get orca-cli", "skills get orchestration"],
    "references_read": ["<guide section or operation reference>"]
  },
  "runtime": {
    "env_present": true,
    "agent_context": "<verbatim `orca agent-context` output summary>",
    "target_host": "<exact current host>",
    "terminal": "<current Orca terminal id>",
    "status_target": "<status target>",
    "status_runtime_id": "<status runtimeId>"
  },
  "discovery": {
    "installed_filter": "<exact `skills installed --json` filter>",
    "bundle_entrypoints": ["cli", "codexApp", "orca", "setup"],
    "install_dirs": ["<manifest install dirs>"],
    "owner_skill_path": "<absolute SKILL.md realpath>",
    "provider_ids": ["<id>"],
    "source_kind": "<kind>",
    "source_label": "<label>"
  },
  "worker_policy": {
    "agent": "pi|codex|claude",
    "model": "<configured>",
    "effort": "<configured>",
    "evidence": "<same-session probe>",
    "config_source": "<absolute config path>",
    "validation_command": "<exact model_config.py command>"
  },
  "capability": {
    "guide_sections": ["<version-matched guide sections read for this operation>"],
    "request_fields": ["<fields required by current operation>"],
    "receipt_fields": ["<fields coordinator must read back>"]
  }
}
```

`operation` 必选，但 helper 只做结构核验。`worker-start` 前的 native dispatch readiness
按 `references/orca-dispatch.md` 的 `worker-start --terminal` receipt 字段核验。

## 结果语义

字段缺失/格式非法 → `blocked`；dispatch 请求缺证据 → `dispatch unavailable`；结构成功仅
`preflight-ready`，并输出 `authority: false`。机械 helper 不能证明原生 provenance；
`authority: false` 是恒定语义——coordinator 必须核验原生 source provenance。
它不授权 dispatch 或推进项目 gate。

## CLI 探测顺序（推断可执行时）

`which -a orca`；每个 candidate 取 `realpath`、`--version` 首行、
`orca skills get <name> --full`（native discovery）；证据不足记 Unknown。
