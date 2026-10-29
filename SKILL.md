---
name: figma-android
slug: figma-android
displayName: Figma Android 设计稿
version: 1.0.2
summary: Figma 设计稿转 Android：本地桥读取节点树/截图/切图，生成布局与页面、改造已有页面并做还原度检查。
license: MIT
description: Figma 设计稿数据读取、解析，提供生成 Android 布局文件指导、切图导出。支持设计稿画板查看、设计评估、图标下载等场景。
argument-hint: '用户意图包括：1. 生成页面（根据设计稿创建新页面）；2. 修改页面（调整已有页面以匹配设计稿）；3. 导出切图（下载设计稿中的图片资源）；4. 检查还原度（对比页面实现与设计稿）；5. 评估（分析设计稿或页面实现）；6. 查看画板（读取或预览 Figma 画板内容）。'
disable-model-invocation: true
---
# figma-android

Figma 设计稿转 Android 代码。通过本地 Figma 桌面端插件拉取设计数据，生成 Android 布局/切图/Activity。

## 能力概览

| 能力层级 | 可以做什么 |
|----------|-----------|
| 不提取就能做（读缓存） | 查节点/切图文件名/文本内容/样式/坐标/view_type、按名称模糊搜索、按 View 类型筛选、列切图清单（`--assets [--md5]`）、多画板同名节点横向对比与切图内容等价判定（`figma_compare_nodes.py`）、校验 android_tree 完整性、按 nodeId 跨缓存查询（`--find-root` 自动定位所属画板）、按画板名/nodeId 过滤缓存清单（`--list-caches --match`） |
| 需提取才能做（触发 `figma_pull.py`） | 画板截图全貌、解析画板内部完整结构、生成布局/Activity/资源、导出切图（xxhdpi PNG 非 SVG）、改造已有页面、还原度检查、编译验证（`./gradlew assembleDebug`）、按 nodeId 提取（自动追溯根画板） |
| 不能做 | 回答设计意图问题、"为什么这么设计"、无 Figma 连接且无缓存时生成代码、凭 URL 提取数据（仅桥模式，无 URL 通道） |

所有脚本、参数、预计耗时、决策树详见 `modes/bridge-execution.md` 脚本工具箱（唯一权威版本，SKILL.md 不再重复）。

## 用户使用流程

```
用户在 Figma 桌面端选中画板 → 对 Claude Code 说出意图
│
├─ 首次使用 / 环境没起来
│   说 "start" / "启动"
│   → Agent 自动检查环境（python/figma/桥服务器/插件连接）
│   → 缺啥补啥，引导装插件（Figma → Plugins → Development → Import plugin from manifest.json）
│   → 右键画板打开 figma-android-bridge 插件 → 自动连接到桥服务器(7789)
│   → 就绪后提示"请告诉我你要做什么"
│
└─ 日常使用（3 个动作）
   1. 在 Figma 中选中要处理的画板或节点
      插件面板蓝底卡片显示 `layername[nodeId]`（如 咨询[2:141] / Avatar[2:152]），
      点击即复制；面板图例详见 modes/bridge-execution.md

   2. 对 Claude Code 说出意图：
       "生成首页" / "改登录页" / "导出切图" / "查看画板"
       "查看 2:152 样式" / "编组-2[1:783] 内部有切图吗"
       "1:200 颜色不对" / "这个背景圆角是多少"

   3. Agent 按节点 id 查缓存或自动拉取 → 回复信息
      或展示页面结构 → 回复"确认" → 生成代码 + 编译验证
```

## Agent 执行流程

> 以下为 Agent 内部参考，不向用户展示。

```
1. 选择数据通道
   当前阶段仅桥模式，不问 URL，不接受 Figma URL。
   读 modes/current_mode.txt (= plugin) → 立即读取 modes/bridge-execution.md (含脚本工具箱 + 决策树)
   → ⚠️ Agent 在桥模式下做任何操作前，必须先读完 bridge-execution.md 了解有哪些脚本可用
   → Agent 禁止自行编写 Python/Shell 查询脚本，工具箱中已有脚本覆盖所有查询场景
   ⚡ 用户提到"选中节点"/具体元素名 →
     有会话锚定 → 用 figma_selected_node.py --node-id <id> 查询
     无锚定 → 跑 scripts/bridge/figma_selected_node.py 查询再继续

1.5 桥模式前置：start
   用户意图非 start 且当前模式为 plugin 时:
     → 检查桥服务器 localhost:7789 是否运行
     → 未运行: 提示用户先执行 "start"/"启动"/"开始" 初始化环境
     → 已运行: 检查插件连通性，正常则继续

2. 读取平台规则
   当前项目是 Android? → 读取 rules/android-layout-rules.md
   → 同时读取 rules/global-rules.md（始终）
   → 并读取宿主项目根的 CLAUDE.md / AGENTS.md（存在时）：构建命令与 flavor 变体、
     模块划分、页面归属约定（哪个 Fragment/Activity 承载哪个画板）。
     ⚠️ 画板名 ≠ 类名，页面归属必须以此为准并 grep 验证，禁止靠名字猜（见 P1-2 规则）

3. 执行数据提取（按通道执行）
   → 缓存复用判定由 figma_pull.py 内部按三重门槛自动完成
     （三文件齐全 + 适配器含 artboard_width_px + 树含目标节点），Agent 不自行判断、不跳过 pull
4. 产物结构校验：python3 scripts/common/figma_validate_tree.py "<extract_dir>"
   → blocked（exit 2）禁止进入 4.5/5/生成，回报缺失项并建议 --force 重拉

4.5 【意图先行】进入结构确认前，先提炼实现意图：
   页面归属（Fragment/Activity/Dialog/Item）、架构边界（底部 Tab 是否宿主所有）、
   核心交互（列表/横滑/按钮/状态切换）、数据区域（动态/静态/复用 item）、用户明确取舍（保留/排除区域）
   → 产出 `implementation_context`，作为步骤 5a 结构化查询与 5b 截图分析（子 agent prompt）的输入上下文

5. 【阻塞】结构确认 —— android_tree 先行，截图分析后置

   5a. 结构化解读（先行必做）：读 rules/android-tree-guide.md（唯一权威使用指南）
       + rules/visual-grouping-rules.md（结构理解必须）
       → ⚠️ 禁止整文件 Read `android_tree.json`（常达数百 KB）：一律用 `figma_query_node.py`（--id/--name/--type/--children/--deep/--styles）或
         `figma_selected_node.py --node-id` 定向查询取所需节点，
         禁止全量加载占上下文
       → 针对 4.5 的 implementation_context 先做结构化查询定位目标区域：
         - 用户提到具体元素（"底部四个按钮"/tab/某卡片）→ figma_query_node.py --name <关键词> --fuzzy --children 定位
         - 多画板场景（如各 tab 页画板，缓存互不相同）→ 一次用
           figma_compare_nodes.py --name <关键词> --fuzzy --root-ids <画板nodeId,...> [--deep N]
           得到 各板对比表 + 差异摘要 + 内容等价分组；
           ⚠️ 判断切图是否同一张只看内容签名，禁止用 image.file 文件名不同推断视觉不同
           （export_as_image 按节点寻址命名，同一视觉跨画板必然不同名）
           需要单节点下钻时再 figma_query_node.py --root-id <画板nodeId> 限定查询
         - 切图清单/某节点的切图文件 → figma_query_node.py --assets [--md5] 或查询输出的「切图:」行
         - 精确数值（坐标/尺寸/颜色/圆角/切图文件/选中态差异）一律取自 android_tree，禁止目测截图
       → 记录结构化结论：目标区域节点清单 + 精确样式（后续确认摘要的展示基础）

   5b. 截图分析（默认后置必经）：在 5a 结论基础上派发子 agent 读取
       `<extract_dir>/screenshot.png`（主 Agent 不直接 Read 截图，避免 base64 挤占主上下文）。
       派发 prompt、JSON 字段契约与失败降级一律按 rules/screenshot-analysis.md 执行，
       SKILL 不重复模板内容。禁止不看截图就臆断视觉结论。
        → 用子 agent 的结论补 schema_version/design_id/user_intent 等元数据后写入
          <extract_dir>/layout_analysis.json（结构见 schemas/layout-analysis-schema.md）；
          派发规范与失败降级策略见 rules/screenshot-analysis.md
       → 截图分析只补充定性结论（区域划分/容器归属/滚动策略/切图粒度/交互热点），
         精确数值一律以 5a 的 android_tree 结论为准，不得推翻
       → ⚠️ 条件性跳过 5b（同时满足全部三条）：① 用户意图限定为样式更新/配色/图标替换，不涉及布局结构调整；
         ② 目标区域节点 name、style.*、text_color、image.file 等字段齐全且已完整回答用户问题；
         ③ 无容器归属/重叠歧义（children 层级清晰）→ 跳过 5b，直接以 5a 结论进入确认

   → 输出用户确认摘要：先展示 5a 的目标区域结构（节点/容器/选中态、新旧样式差异），
     再补视觉定性结论与待确认歧义（含 confidence 标注与确认项）
   → 等待用户确认后才能继续。例外：用户明确要求“直接改 / 不用确认”时，
     输出结构摘要后继续；但删除/重命名被引用 ID、覆盖既有资源、修改业务逻辑等
     破坏性操作，仍必须先确认

6. 代码生成
   先读取 rules/visual-grouping-rules.md（未读取时必读）
   再读取 rules/slice-atomic-rules.md、rules/resource-naming-rules.md
   最后读取 commands/<command>.md
   → 按确认结构 + visual-grouping-rules + android-layout-rules 生成

7. 编译验证
   读取 rules/verify-rules.md → 构建命令优先取宿主项目根 CLAUDE.md/AGENTS.md 声明的
   （含 flavor 变体），否则 ./gradlew assembleDebug
   → 报错文件不在本次改动集内（并行会话把主干改坏）时，按 verify-rules.md
     「非本次改动导致的编译失败」走四步，结论标 PARTIAL（不得标 PASS、不得代改他人半成品）
```

## 链路选择

| 场景 | 读取 | 说明 |
|------|------|------|
| "start"/"启动"/"开始" | `commands/start.md` | 环境初始化 + 插件配置引导 |
| 其他意图（生成/修改/导出/查看/对比/验证） | `modes/bridge-execution.md` | 先读脚本工具箱 → 按决策树执行 |

## 意图匹配

| 用户说 | 命令 | 说明 |
|--------|------|------|
| "start"、"启动"、"开始"、"初始化" | `start` | 启动桥服务器 + 环境引导 |
| "生成页面" | `create-page` | 完整页面含 Activity |
| "只要布局"、"只改 xml" | `create-layout` | 仅 XML + 资源 |
| "改页面"、"按设计稿改"、"更新页面"、"修改页面"、"换样式"、"功能没有新增"、"功能不变只改样子" | `restyle-page` | 改造已有页面 |
| "换切图 + 顺带调布局/少量 UI 代码"（混合任务） | `restyle-page` | 混合任务走 restyle-page，**不拆分**：切图按 `resource_impact=replace_asset` 处理，不单走 export-assets。理由：restyle-page 的阻塞确认 + ID 保护 + 影响分析正是这类任务的安全网 |
| "导出切图"、"下载图标"、"只换切图不动任何代码" | `export-assets` | 纯切图任务（交叉引用：切图 + 任何 XML/UI 代码改动 → 一律走 restyle-page） |
| "检查还原度"、"对比" | `restore-check` | 差异分析 |
| "编译"、"验证" | `verify` | 编译验证 |
| "查看画板"、"评估" | `inspect` | 快速查看/评估 |
| "查看 \<nodeId\> 样式/颜色/圆角"、"XX[ \<nodeId\> ] 内部有切图吗"、" \<nodeId\> 布局有问题"、" \<nodeId\> 不对" | `inspect-node` | 按 nodeId 查节点详情（有缓存直接查，无缓存自动拉取） |

> 用户口中的 `[nodeId]` 来自 plugin 面板蓝底卡片复制的 `layername[nodeId]` 格式，如"编组-2[1:783]"。Agent 解析括号内的 nodeId 即可。有时用户只说 nodeId 如"查看 2:152 样式"，同样支持。

Agent 匹配意图后读取对应 `commands/<command>.md`。

## 最小必读集

按意图只读必需文件，其余按需再读：

| 意图 | 必读 | 条件必读 |
|------|------|---------|
| 生成页面 | 本文件、bridge-execution、android-layout-rules、android-tree-guide、visual-grouping-rules、commands/create-page | 5b：screenshot-analysis + layout-analysis-schema；碰资源：slice-atomic + resource-naming |
| 仅布局 | 同「生成页面」，命令换 create-layout | 同上 |
| 修改页面 | 生成页面集合 + restyle-guardrails + change-impact-schema + commands/restyle-page | 碰资源时同上 |
| 导出切图 | 本文件、bridge-execution、resource-naming-rules、commands/export-assets | — |
| 还原度检查 | 本文件、bridge-execution、android-tree-guide、commands/restore-check | 有实现截图：screenshot-analysis（子 agent 双图对比） |
| 查看/评估/节点查询 | 本文件、bridge-execution、android-tree-guide | — |
| 编译验证 | verify-rules、commands/verify | — |

`global-rules.md` 所有意图始终读取。以上之外的文件按需查阅，不要为「读全」而预加载。

## 通用规则

以下文件按需读取：
- `rules/global-rules.md` — 始终
- `rules/android-tree-guide.md` — 结构定位问题时（节点是什么/在哪/颜色/切图归属），先读它确认 android_tree 能回答
- `rules/screenshot-analysis.md` — 结构确认步骤 5b 触发截图分析时（子 agent 派发 prompt 与 JSON 契约、降级策略、Android 视角分析顺序、切图粒度、交互热点、上下文节制）
- `schemas/layout-analysis-schema.md` — layout_analysis.json 结构约束（5b 子 agent 定性结论 + 主 Agent 元数据合并后写入并消费）
- `rules/visual-grouping-rules.md` — 生成/改造布局时
- `rules/android-layout-rules.md` — 生成/改造布局时
- `rules/restyle-guardrails.md` — 改造已有页面时
- `schemas/change-impact-schema.md` — restyle-page 输出影响分析时（`page` / `diff_type` / `resource_impact` 字段语义与落盘分层约定）
- `rules/slice-atomic-rules.md` — 处理切图时
- `rules/verify-rules.md` — 编译验证时
- `rules/resource-naming-rules.md` — 资源命名时

## Hard Rules

0. 中文简体，禁止表情符号。
1. 当前仅桥模式，无 URL，不走 MCP。— `modes/current_mode.txt` 固定为 plugin。
2. 桥模式不可用（桥服务未运行或插件未连接）→ `blocked`。— 没有桥连接时无法获取 Figma 数据。
3. 缓存完整可复用，否则必须重新提取。— `figma_pull.py` 自动检测缓存状态（三文件齐全 + 适配器已产出 `artboard_width_px` + 树中含目标节点才复用），避免重复拉取；设计稿已更新时加 `--force` 强制重拉。复用的前提是**产物可信**，旧版适配器产物 dp 基准错误，一律不复用。
4. 未编译验证不得声称任务完成。— `./gradlew assembleDebug` 是唯一真实的质量信号，`verify-rules.md` 定义了验证流程。
5. `create-page` / `create-layout` / `restyle-page` 默认跑 `./gradlew assembleDebug`。— 这三类操作改动最大，最易引入编译错误。
6. 编译失败先修复再验证，不能跳过。— 按 `verify-rules.md` 诊断修复。
7. `restyle-page` 不修改业务逻辑、不删除/重命名已有 ID。— 边界与措辞以 `commands/restyle-page.md`「硬约束」为准：**业务逻辑** = ViewModel/Repository/UseCase/网络/埋点/权限/登录态/数据加载（完整的 8 项见 `commands/restyle-page.md`「硬约束」），禁止修改；**纯 UI 层代码调整**（布局管理器、selector、可见性）允许，但须和影响分析一起在终端摘要逐条列出（含文件与 `diff_type`）。`restyle-guardrails.md` 定义了改造边界，保护现有代码。
8. 覆盖已有资源前检查冲突。— 谨慎原则，避免替换项目中已有的同名资源。
9. 切图拷贝到 app 目录前必须按 `resource-naming-rules.md` 重命名。— Figma 导出的是随机 hash 名，不可维护；禁止 hash 名和无意义名（如 `group_3`）。
10. `android_tree.json` 的 dp 值禁止二次换算。— `figma_bridge_to_android.py` 适配器已在内部完成 px→dp 换算（字段用法见 `rules/android-layout-rules.md` 核心原则），二次换算会导致值错误。
11. 非平凡操作必须输出"用户确认"信息。— `create-page` / `create-layout` 在终端打印精简摘要（≤30 行：生成/修改的文件 + 风险点）即可，**不再生成任何人读的落盘报告**（Components/Tokens/Assets 大表是输出 token 大户且用户通常不看，结构已在步骤 5 阻塞确认过）；编译验证状态写入任务记忆节（见 Hard Rule 13）。
12. 还原度检查必须先做静态核对，有实现截图才能声称视觉一致。— `restore-check.md` 定义了核对流程，无截图的"视觉一致"不可信。差异清单直接在终端给用户，**不落盘**。
13. 任务记忆层——唯一落盘的**报告/记忆**文件是会话工作目录（与 `--project-root` 同口径）的 `figma_task_memory.md`（不含 `.figma/` 缓存内中间产物，照旧生成）。**写入义务按命令显式清单**：`create-page` / `create-layout` / `restyle-page` / `verify` 收尾无条件追加一节；`export-assets` 仅发生 `replace_asset` 覆盖时写（回滚账本）；`restore-check` 仅存在未修复遗留项且用户同意留痕时写。**只装 git diff / 重跑恢复不了的事实**：固定 8 字段 `build`（含 `N/A`=不涉编译）`/blocker/verified_scope/attribution/excluded/asset_overwrite/confirmed/open`；每任务一节，用 `cat >>` 单次追加，**禁止 Edit/Write 整文件改写**（多会话并行下会静默丢节）；节头固定 `## 任务 <任务名> | 画板 <nodeId 或 不适用> | <日期>`；**同任务多节以时间靠后的节为准，旧节永不修改**（补跑义务是否履行只看最新节，闭合格式见模板）；**开工前先按读取契约 grep 历史节**（与写入同等强制）。本文件不随宿主改动集提交：git 宿主进 `.gitignore`，SVN 宿主 `svn propset svn:ignore`。模板 `templates/task_memory.md`，完整约定 `rules/restyle-guardrails.md`「任务记忆层」；老页面改造的影响分析结构（会话内输出，不全量落盘）见 `schemas/change-impact-schema.md`。
14. Figma 图层树 ≠ Android View 树，按 `visual-grouping-rules.md` 重组。— Figma 的图层嵌套和 Android ViewGroup 概念本质不同，直接翻译会产生深层嵌套和性能问题。
15. 产物不含 SVG 或 VectorDrawable，全部是 xxhdpi PNG。— `figma_pull.py` 已按此规格导出，`slice-atomic-rules.md` 明确了切图格式。
16. **多会话节点锚定**：数据提取成功后，Agent 必须记下当前画板的 nodeId，后续查询始终使用 `figma_selected_node.py --node-id <id>` 或 `figma_query_node.py --root-id <id>`，禁止再调用无参版本的 `figma_selected_node.py` 查询"当前选中"。— 多个 Claude Code 会话可同时操作不同画板，无参查询会读取其他会话的画板数据。
17. **结构问题只读 android_tree，禁止目测截图**：凡 android_tree 可回答的问题（节点类型/坐标/尺寸/颜色/圆角/文字/层级/重复组/切图归属），一律走 `figma_query_node.py --id <nodeId>`（注意是 `--id`）或 `figma_selected_node.py --node-id <nodeId>` 结构化查询。**例外：容器归属、视觉分组等定性判断可在 android_tree 验证的基础上参考子 agent 的视觉结论；精确数值（坐标/尺寸/颜色/绘制顺序）必须仅使用 android_tree。** 截图仅用于全貌预览与质感评估，且由子 agent 读取。— `rules/android-tree-guide.md` 定义了能力边界与决策规则。

## 产物结构

```text
.figma/figma_extract_{name}_{nodeId}/
├── screenshot.png          360px 宽预览图（全貌预览/子 agent 读图用；原宽 ≤360 保持原尺寸）
├── figma_extract_prepared/
│   ├── android_tree.json      核心
│   ├── assets.json
│   ├── source_meta.json
│   ├── selected_node.json     (桥模式，用户选中子节点)
│   └── drawable-xxhdpi/*.png
```

Android 输出：

```text
app/src/main/res/layout/<page>.xml
app/src/main/res/drawable/*.xml
app/src/main/res/drawable-xxhdpi/*.png
app/src/main/java/.../<PageName>Activity.kt
```

报告与记忆（人向内容一律走终端摘要，见 Hard Rule 11；唯一落盘的报告/记忆文件，不含 `.figma/` 缓存内中间产物）：

```text
figma_task_memory.md         会话工作目录（与 --project-root 同口径），任务记忆层：
                             每操作一节、cat >> 单次追加，
                             固定 8 字段（build/blocker/verified_scope/attribution/
                             excluded/asset_overwrite/confirmed/open）
```

> 任务记忆层：md 是**给后续/并行会话读的机器可检索记忆**，只装 git diff / 重跑构建
> 恢复不了的事实，不是给用户的验收材料，也不随宿主改动集提交（git `.gitignore` /
> SVN `svn:ignore`）。给人看的内容走终端摘要（≤30 行）。
> 完整构建输出、设计对照大表、改动清单、还原度差异明细等可重建材料**不进 md**。
> 开工前先 grep 历史节（读取契约），同任务多节以时间靠后的节为准。
> 详见 `rules/restyle-guardrails.md`「任务记忆层」与 `templates/task_memory.md`。
