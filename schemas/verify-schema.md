---
name: figma-verify-schema
description: 编译验证状态定义，build/blocker/verified_scope 字段写入 figma_task_memory.md 任务记忆节的规范
---

# 验证状态 Schema

编译验证的结果字段定义。落盘统一进会话工作目录 `figma_task_memory.md` 的任务记忆节
（节格式与字段约束见 `templates/task_memory.md`，写入/读取约定见
`rules/restyle-guardrails.md`「任务记忆层」）；明细清单只进终端，不落独立报告文件。
`restore-check` **仅在存在未修复遗留项且用户同意留痕时**写节（`build: N/A`）；
干净通过时不产生任何节，其 Design Verification 对照属会话内输出。

## Build Result

| Build Result | 含义 |
|---|---|
| `PASS` | 构建命令实际执行成功 |
| `FAIL_FIXED` | 失败 → 修复 → 最终成功 |
| `FAIL_BLOCKED` | 命中「阻塞条件」四条之一 |
| `PARTIAL` | 受限范围内验证通过，且阻塞原因已证明与本次改动无关 |
| `N/A` | 本节不涉编译（纯切图导出、还原度留痕节）；此时 `blocker`/`verified_scope` 写「无」 |

**硬约束**：`Build Result` 与记忆节 `build:` 字段必须一致——禁止 `build: PASS`
而同任务记录构建未通过。并行会话阻塞场景写 `PARTIAL` 并填 `blocker` / `verified_scope` / `open`。

## Production Checks（按实填写，不存在的检查项整节跳过）

- **Compile Verification**：`./gradlew assembleDebug` / 宿主项目根 CLAUDE.md 指定的构建命令
- **Resource Verification**：命名冲突 / 缺少切图 / 颜色/dimens 同步
- **Layout Verification**：嵌套深度 / 约束完整性 / 硬编码 px
- **Restyle Safety**（仅 restyle-page）：ID 保留 / 业务代码未改 / 引用仍存在
- **Design Verification**（仅 restore-check）：设计值 vs 实现值逐行对照（会话内输出，仅遗留项进记忆节 `open`）
## 模板

终端摘要用（**不落盘**）：

```markdown
## Compile Verification

- Build Command: `./gradlew assembleDebug`
- Build Result: PASS | FAIL_FIXED | FAIL_BLOCKED | PARTIAL
- Blocker:
- Verified Scope:
```

任务记忆节用（**必填，落 `figma_task_memory.md`，供后续会话 grep**，字段行带 `- ` 前缀）：

```text
- build: PASS | PARTIAL | FAIL_BLOCKED | FAIL_FIXED | N/A
- blocker: <文件:行号；无则写 无>
- verified_scope: <实际跑通的命令与范围；无则写 无>
- open: <补跑义务/未验证项；无则写 无>
```