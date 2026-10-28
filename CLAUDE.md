# figma-android skill

Figma 设计稿 → Android 代码。这是一个 **Claude Code skill 项目**，并非独立 App。
Skill 被用户通过 `/` 命令或自然语言触发时，由 Claude Code 在用户的 Android 项目目录中加载执行。

## 项目根目录说明

```
.                     # skill 源码（本仓库）
├── SKILL.md          # skill 入口定义 — 意图匹配 + 执行流程 + Hard Rules
├── commands/         # 命令处理指南（Agent 匹配意图后读取）
│   ├── start.md         环境初始化/启动引导
│   ├── create-page.md   生成完整页面（含 Activity）
│   ├── create-layout.md 仅生成布局 XML
│   ├── restyle-page.md  按设计稿改造已有页面
│   ├── export-assets.md 导出切图
│   ├── inspect.md       查看/评估画板
│   ├── inspect-node.md  按 nodeId 查看节点详情
│   ├── restore-check.md 对比还原度
│   └── verify.md        编译验证
├── modes/            # 数据通道
│   ├── current_mode.txt         当前模式（固定为 plugin，仅桥模式）
│   └── bridge-execution.md  桥模式执行清单 + 决策树 + 脚本工具箱（唯一权威）
├── rules/            # Agent 行为规则（按阶段读取）
│   ├── global-rules.md          通用规则（始终读取）
│   ├── android-layout-rules.md  布局生成规则
│   ├── android-tree-guide.md    android_tree 使用指南
│   ├── visual-grouping-rules.md 视觉元素归组规则
│   ├── slice-atomic-rules.md    切图资源处理规则
│   ├── resource-naming-rules.md 资源命名规则
│   ├── restyle-guardrails.md    改造保护规则
│   ├── screenshot-analysis.md   截图分析规范
│   └── verify-rules.md          编译验证规则
├── schemas/          # 产物 Schema 文档（android_tree / assets / layout_analysis / change_impact / verify）+ 任务记忆字段规范
├── templates/        # 任务记忆节模板
├── evals/            # 评测用例（evals.json）
├── examples/         # 最小 v2 示例产物（android_tree_sample，可过校验器）
├── scripts/          # Python 工具脚本（Agent 通过 Bash 执行）
│   ├── bridge/                  桥模式脚本（服务器/提取/适配器/查询）
│   ├── common/                  figma_validate_tree.py 结构校验 / figma_selftest.py 离线自检
│   └── plugin/                  Figma 插件（code.js + manifest.json + ui.html）
└── LICENSE.md
```

本仓库为 skill 源码，通过 SkillHub 或 Agent skills 目录安装；修改后升版本并重新安装才能生效。

## 数据通道

仅桥模式：用户无 URL，通过本地 HTTP 桥（7789）+ Figma 插件拉取。核心入口 `scripts/bridge/figma_pull.py`。
禁止要求用户提供 Figma URL，禁止混入其他通道的产物。

## 关键架构约定

1. **脚本工具箱模式**：Agent 禁止自行编写 inline Python/Shell 查询脚本，始终使用 `scripts/` 下已有脚本。
2. **时序**：bridge-execution.md 决策树（节点感知 → 意图解析 → 数据就绪）→ SKILL.md 步骤 4.5-7（意图先行 → 结构确认 → 生成 → 编译）。Agent 不能跳跃或跳过。
3. **结构确认阻塞**：必须等待用户确认结构后才能生成代码。
4. **编译验证**：`create-page` 和 `restyle-page` 默认跑 `./gradlew assembleDebug`，未编译验证不得声称任务完成。
5. **产物格式**：切图全部 xxhdpi PNG，不含 SVG / VectorDrawable，不保留 hash 名。

## 开发指南

### 新增脚本

- 放到 `scripts/bridge/`（桥模式）或 `scripts/common/`（校验类）
- 更新 `modes/bridge-execution.md` 的脚本工具箱表格，标注预计执行时间（如 `~5s`）

### 修改 Agent 行为

- 修改 `rules/` 下对应规则文件，`commands/` 下对应命令文件
- 修改 `modes/bridge-execution.md` 中的决策树
- `SKILL.md` 是入口，修改 Hard Rules 会影响所有流程

### 测试

- 桥模式测试需要本地 Figma 桌面端 + 桥服务器 + 插件连接
- `scripts/common/figma_selftest.py` 离线回归网（dp 换算基准、校验器判定、缓存复用门槛），改脚本后必跑
- `scripts/common/figma_validate_tree.py` 可离线校验 android_tree.json 结构（三值状态，blocked 时 exit 2）
