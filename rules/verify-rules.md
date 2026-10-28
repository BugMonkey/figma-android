---
name: figma-verify-rules
description: 编译验证规则，create-page / restyle-page 默认执行
---

# 编译验证规则

## 构建命令来源

优先采用宿主项目根 `CLAUDE.md` / `AGENTS.md` 声明的构建命令（含 flavor / 变体、模块划分、
页面归属约定）。项目声明的命令优先于本文默认命令——本技能默认命令是最小公约数，
多 flavor 项目下它可能根本不是该模块的验收命令。

```bash
./gradlew assembleDebug
```

该命令不可用时（无此 task、多 flavor 需显式变体），检查 Gradle tasks 选择最接近该模块的
debug 构建命令，并在终端摘要记录实际命令与选择原因。

## 失败重试

生成的代码导致编译失败时：

1. 修复最小安全问题。
2. 重新编译。
3. 循环直到通过或阻塞。

## 阻塞条件

仅以下情况允许把验证标记为 `blocked`：

- 改动前项目本身就编译不过（有改动前基线可比对）。
- 必需的私有依赖不可用。
- 构建命令需要不可得的凭证。
- 用户明确禁止运行编译。

## 非本次改动导致的编译失败

多会话并行改同一个 Trunk 时，`assembleDebug` 会被他人半成品阻塞（典型：报错文件不在本次
改动集内，如某 XML 引用了尚不存在的 `click.selectCategory()`）。这类失败**没有改动前基线
可比对**，因此既不能判 PASS，也不能算 `blocked`。按以下四步处理：

### ① 归属——报错文件是否在本会话改动集内

用版本控制状态 + 文件 mtime 比对，判断每个报错文件的归属：

```bash
svn status          # 或 git status --short
git diff --name-only   # 或 svn diff --summarize
```

逐个报错文件核对：是否出现在本次会话说改动清单里（本会话创建/修改的文件）。
全部不在 → 属他人改动；只要有一个在 → 按「失败重试」修，不得降级。

### ② 不代改——禁止为通过编译补他人半成品

**禁止**为了让 `assembleDebug` 通过而去补别人未完成的代码（新增缺失方法、补缺失资源、
注释掉调用）。理由：那些文件不属于本次改动范围，代改会掩盖他人 WIP 的真实状态、
污染本次改动集，并可能覆盖对方正在编辑的内容。归属分析有结论后直接进入降级取证。

### ③ 降级取证——相关模块最小验证

对**本次改动涉及的模块**跑最小验证命令，证明本次改动自身是自洽的：

| 改动内容 | 最小验证命令 |
|----------|-------------|
| Kotlin / Java 源码 | `./gradlew :<module>:compileDebugKotlin`（Java 用 `compileDebugJavaWithJavac`） |
| 布局 XML + DataBinding 项目 | `./gradlew :<module>:DataBindingGenBaseClassesDebug` |
| 资源文件（drawable / values / layout） | `./gradlew :<app>:process<Flavor>DebugResources` |

多个模块受影响时逐个跑。命令按宿主项目声明的变体调整。

### ④ 收尾义务——工作区恢复后补跑 assembleDebug

降级取证只是临时结论，**不是完成信号**。对方 WIP 合入、工作区恢复可编译后，必须补跑
`assembleDebug`；未补跑不得标 `PASS`。标 `PARTIAL` 时必须写入任务记忆节
（`figma_task_memory.md`，`build: PARTIAL` + `blocker` + `verified_scope` + `open` 记补跑义务）——
补跑义务靠它跨会话传递：后续会话开工按读取契约（`restyle-guardrails.md`「任务记忆层」）
检索，**义务是否履行只看该任务最新节**；处理则按闭合格式写新节
`open: 已补跑 assembleDebug（承接 <日期> 节 PARTIAL）`，未处理则原样承接并注明原因。

## 状态输出

枚举与含义以 `schemas/verify-schema.md` 为唯一权威（共五值，其中 `N/A` 仅用于不涉编译的记忆节）。下方判定表只补「可否声称任务完成」。

| 状态 | 判定条件 | 可否声称任务完成 |
|------|---------|-----------------|
| `PASS` | `assembleDebug`（或宿主项目声明的构建命令）实际执行成功 | 可以 |
| `FAIL_FIXED` | 失败 → 修复 → 最终成功 | 可以 |
| `FAIL_BLOCKED` | 命中「阻塞条件」四条之一 | 不可以，需说明补充什么 |
| `PARTIAL` | 按「非本次改动导致的编译失败」四步走完，最小验证通过且阻塞已证明与本次改动无关 | 不可以，须注明收尾义务未履行 |

标 `PARTIAL` 时措辞固定：

```text
本次改动集通过 <最小验证命令> 验证，整体 assembleDebug 被非本次改动阻塞（<报错文件>:<行>）
```

标 `PARTIAL` 必须同时给出：① 实际执行的最小验证命令与结果；② 阻塞归属证据（报错文件不在
本次改动集内的依据行号）；③ 待补跑 `assembleDebug` 的说明。

## 结果输出

**终端摘要（给人，当场消费）**：

- 编译命令与结果（`PASS` / `FAIL_FIXED` / `FAIL_BLOCKED` / `PARTIAL` 之一；`N/A` 仅用于不涉编译的节）
- 标 `PARTIAL` 时必含 `blocker`（阻塞文件与行号）与 `verified_scope`（已验证范围）
- 错误摘要
- 变更文件清单
- 资源问题（缺资源/命名冲突）
- 布局问题
- restyle 安全性问题（如适用）
- 剩余需人工检查项

**任务记忆节（给后续会话，只落不可重建项）**：`build` / `blocker` / `verified_scope` /
`open`（补跑义务、未验证项、他人 WIP 影响面），写入 `figma_task_memory.md`，
格式见 `templates/task_memory.md`。清单类内容 git 可重建，不进记忆文件。
