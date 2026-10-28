# Repository Guidelines

## Project Structure

```
.
├── SKILL.md                    # 入口文档，Agent 首先读取
├── AGENTS.md                   # 本文件，仅供人类维护者阅读
├── CLAUDE.md                   # 项目指令，被 Claude Code 自动加载
├── README.md                   # 面向用户的使用说明
├── commands/                   # 命令处理指南（9 个，Agent 匹配意图后读取）
├── modes/                      # 数据通道
│   ├── current_mode.txt            # 当前模式（固定为 plugin）
│   └── bridge-execution.md     # 桥模式执行清单 + 决策树 + 脚本工具箱
├── rules/                      # Agent 行为规则（9 个，按阶段读取）
├── schemas/                    # 产物 Schema 文档（5 个）
├── templates/                  # 任务记忆节模板
├── evals/                      # 评测用例
├── examples/                   # 最小 v2 示例产物（见 examples/README.md）
├── scripts/
│   ├── bridge/                 # 桥模式脚本（6 个）
│   │   ├── figma_bridge_server.py      # 桥 HTTP 服务器
│   │   ├── figma_pull.py               # 桥模式数据提取唯一入口
│   │   ├── figma_bridge_to_android.py  # composition → android_tree 适配器（核心转换引擎）
│   │   ├── figma_selected_node.py      # 查询 Figma 选中节点 / 缓存锚定查询
│   │   ├── figma_query_node.py         # 在缓存树中搜索节点 / 切图清单（--assets）
│   │   └── figma_compare_nodes.py      # 跨画板同名节点比对（差异摘要 + 切图内容等价）
│   ├── common/                 # 公共脚本
│   │   ├── figma_validate_tree.py      # android_tree.json 结构校验
│   │   └── figma_selftest.py           # 离线自检（不需 Figma/桥）
│   └── plugin/                 # Figma 插件
│       ├── code.js
│       ├── manifest.json
│       ├── ui.html
│       └── README.md
└── LICENSE.md
```

## 文档语言约定

所有 `.md` 文件（SKILL.md、rules/*.md、commands/*.md、schemas/*.md）统一使用**简体中文**编写，禁止使用表情符号。Python 源码注释使用简体中文。

## Coding Style

- Python 3.10+，无外部依赖（标准库 only）
- 文件名：snake_case（如 `scripts/bridge/figma_bridge_to_android.py`）
- 函数：snake_case，类：PascalCase
- JSON 字段：snake_case（`android_tree.json`、`assets.json`）
- 各脚本可独立运行（含 `if __name__ == "__main__"`）
- 可维护性优先于极致性能；逻辑清晰 > 巧妙技巧

## 添加或修改规则 / 命令

1. 新规则放入 `rules/`，以描述性文件名命名（如 `color-mapping-rules.md`）
2. 新命令放入 `commands/<command-name>.md`
3. 在 `SKILL.md` 的 `通用规则` 章节注册新文件引用
4. 如果新增 schema，在 `schemas/` 下创建对应 `.md`
5. 脚本修改后运行对应验证脚本确认无回归

## 验证流程

```bash
# 离线自检：不需要 Figma、不需要桥服务器，改动 scripts/ 后必跑
python3 scripts/common/figma_selftest.py

# 校验真实产物结构（三值状态：success / warning / blocked，blocked 时 exit 2）
python3 scripts/common/figma_validate_tree.py <extract_dir>/figma_extract_prepared --write-report
```

---

# 核心设计哲学

## 人机边界

这是整个 skill 的基石。脚本负责所有机械的、可确定性完成的工作（解析、换算、过滤、转换），Agent 负责所有需要视觉理解和语义判断的工作（分组、布局决策、代码生成）。不能混淆边界——不要把需要判断的事丢给脚本硬编码，也不要把确定性计算交给 Agent 去猜。

具体分工：

- **脚本侧（确定性产出）**：Figma 数据提取（插件导出）→ 元数据解析 → 无意义层级合并 → px/dp 坐标换算 → 样式注入（颜色、字号、圆角）→ 状态栏过滤 → 切图 PNG 实测尺寸回写。这些环节的产出（`android_tree.json` 中的 dp 值、颜色、字号、`android_class`）Agent 直接使用，禁止二次换算。
- **Agent 侧（智能决策）**：读 `android_tree.json`（结构唯一权威）定位目标区域 → 按 `visual-grouping-rules.md` 重组 Figma 混乱图层为 Android 语义结构 → 按 `android-layout-rules.md` 选型与映射 → 生成 XML 布局 + Activity 骨架 → 编译验证。`screenshot.png` 仅作全貌预览与质感补充，精确数值一律以 android_tree 为准。

## 预置工具原则

除了产出 Agent 直接消费的产物（`android_tree.json`、切图 PNG），skill 还必须预置 Agent 在写页面过程中可能需要的**功能脚本**。核心理念：Agent 在生成页面时不应该"现写代码"——遇到不确定的情况时，应能调用已有脚本获取答案，而不是自己动手写 Python 或 shell 去解析数据。

预置脚本分三类：

- **查询类**：Agent 需要精确查询某个节点的 dp 坐标、样式、层级关系时，调用查询脚本而非手动搜索 JSON。示例：`scripts/bridge/figma_query_node.py`、`scripts/bridge/figma_selected_node.py`。
- **校验类**：Agent 完成某阶段工作后需要验证正确性时调用。示例：`scripts/common/figma_validate_tree.py`（结构合规性）。
- **操作类**：Agent 执行资源同步等机械操作时调用，避免手写 cp 命令出错。

设计预置脚本的判断标准：

1. 某个操作 Agent 在生成页面时可能遇到 >= 2 次 —— 值得封装为脚本
2. 某个查询逻辑涉及 JSON 遍历、正则匹配等容易出错的操作 —— 必须封装为脚本
3. 某个校验逻辑规则明确但检查点多 —— 必须封装为脚本
4. 禁止 Agent 在生成页面时自行编写数据处理代码（如临时 Python 读 JSON、shell 文本解析）

反例（不应出现的情况）：

- Agent 在读 `android_tree.json` 时自己写 `python3 -c "import json; ..."` 去查单个节点 —— 应该已有 `scripts/bridge/figma_query_node.py` 支持
- Agent 不确定产物是否完整时手动 `ls` + 判断文件大小 —— 应该已有校验脚本

---

## 精确拼图原则

脚本产出的所有数据（dp 坐标、sp 字号、颜色值、圆角、切图映射）必须是**精确的拼图说明书**，不允许模糊、近似或猜测。

具体标准：

- **坐标零误差**：`dp.x` / `dp.y` / `dp.w` / `dp.h` 必须精确到小数点后一位，数据来源于 Figma 原始坐标经 scale 换算，不经任何人工修正或"校准"
- **样式全量映射**：Figma 节点中的每一项样式（color、font-size、border-radius、gradient）必须完整提取到 `android_tree.json`，不遗漏、不近似
- **切图一一对应**：`assets.json` 中每一个切图必须精确对应 Figma 中的一个节点，文件名可追溯，同名去重逻辑确定性
- **Agent 零怀疑**：Agent 拿到 `android_tree.json` 后不需要、也不应该怀疑任何数值的准确性。如果数值看起来不对，说明脚本计算逻辑有 bug，应该去修脚本而非让 Agent 手动调整

这意味着脚本开发时的铁律：

1. 新增任何数据字段前，必须在转换引擎 `scripts/bridge/figma_bridge_to_android.py` 中完整实现提取逻辑，不允许让 Agent 从原始产物中自行提取
2. 坐标换算、样式解析等关键路径必须有明确的数学公式（如 `dp = px / scale`），不允许出现 `approx` / `estimate` / `guess` 等模糊行为
3. 每一个 json 字段的来源必须可追溯——要么来自 Figma 节点属性的某个字段，要么来自明确的数学推导
4. 脚本输出的 json 值必须是确定的：同样的 Figma 节点、同样的输入，每次运行必须产出完全一致的结果

---

## 数据可信原则

- `android_tree.json` 中的所有数值（dp 坐标、sp 字号、颜色值、圆角）均为脚本计算产出，Agent 应视为权威数据直接使用
- 如果发现数据不准，去修转换引擎 `scripts/bridge/figma_bridge_to_android.py` 的数据处理逻辑，不要在 Agent 侧打补丁或手动修正数值
- `screenshot.png` 是 Agent 建立视觉认知的唯一图像依据，不可凭空想象页面结构
- 脚本产物的缓存（`figma_extract_prepared/`）完整时可复用，避免重复提取；不完整时必须重新跑管线

## Figma 图层树 != Android View 树

这是整个系统最重要的规则，也是 Agent 生成代码时最容易犯的错误。Figma 的父子层级反映设计师的操作习惯（分组、锁定、复用），不反映 Android 的容器语义。

Agent 必须做两件事：

1. 读懂 `android_tree.json` 的简化树 —— 脚本已经移除了无意义包裹层（Group 1、Frame 2 等），merge 了一些无意义容器
2. 按 `visual-grouping-rules.md` 进一步重组 —— 基于几何关系（bounds 包含、对齐、间距）+ 语义角色 + 命名线索，把散落在不同 Figma 层级的元素合并为同一个 Android 容器；截图仅作辅助直觉，不替代坐标证据

例如：Figma 里按钮文字在一个 Group，按钮背景在另一个 Group。Agent 必须识别出它们的坐标包含关系（背景 bounds 包含文字 bounds），在 Android 中合并为一个可点击容器。

---

# Agent 的工作模型

Agent 在代码生成阶段的工作不是"翻译数据"，而是"看图重组"。完整流程：

```text
1. 读 android_tree.json 的 root.children / regions / colors / texts —— 结构唯一权威（screenshot.png 仅作全貌预览）
2. 按 visual-grouping-rules.md 重组层级
   - 背景 + 内容在视觉上属于同一个组件 -> 合并到一个容器
   - 装饰层 -> 降级为 shape background，不生成独立 View
   - 重复结构 -> 抽成独立 item 布局 + RecyclerView
3. 按 android-layout-rules.md 翻译为 XML
   - 坐标直接映射到 layout_margin / constraint
   - 样式直接映射到 android: 属性
   - 切图引用 drawable-xxhdpi/ 中的 PNG
4. ./gradlew assembleDebug 验证 -> 失败则修 -> 再验证
```

Agent 的核心能力需求：

- **视觉识别**：看图判断哪些元素在视觉上属于同一个组件
- **几何推理**：通过坐标包含关系判断归属
- **Android 布局经验**：LinearLayout vs ConstraintLayout 选型、约束写法、嵌套控制

---

# 常见失败模式

以下是 Agent 使用本 skill 生成页面时最常出错的场景。优化 skill 时优先针对这些方向：

| 失败模式 | 根因 | 应优化方向 |
|---------|------|-----------|
| 按钮背景和文字被拆成两个无关 View | Agent 照搬了 Figma 层级，没有按视觉分组规则合并 | 增强 visual-grouping-rules 的示例和判定逻辑 |
| 卡片背景挂在根布局，卡片内容挂在另一个容器 | 同上，Agent 未识别出空间包含关系 | auto_regions 可扩展为空间聚类或几何包含检测 |
| 深层 FrameLayout 嵌套 | Agent 未做布局扁平化 | android-layout-rules 增加扁平化策略和深度检测 |
| 硬编码 px 值 | Agent 忽略了 dp 已就绪的原则，自行换算 | 规则应更显式地强调 android_tree.json 中的数值可直接使用 |
| RecyclerView 嵌套在 NestedScrollView 里 | Agent 不了解 Android 嵌套滚动冲突 | android-layout-rules 应加入嵌套冲突检测规则 |
| 编译通过但视觉效果偏差大 | Agent 生成时未对照 screenshot 做视觉核对 | 规则应要求 Agent 在生成后逐区域对照截图 |

---

# 优化指引

## 优化优先级

按对生成质量的影响从高到低排序：

1. **视觉分组准确性** — 当前最大的变量，也是最难自动化的环节。优化方向：在 `scripts/bridge/figma_bridge_to_android.py` 中做更多几何分析（空间包含、重叠检测、同行/同列识别），在 `implementation_hints` 中给 Agent 更明确的合并指令
2. **坐标精度** — 目前 dp 换算基本准确，但某些 Figma 布局（缩放、嵌套变换、非整数坐标）可能导致偏移
3. **样式映射完整性** — gradient、shadow、opacity、blend mode 等复杂样式的映射覆盖率
4. **布局选型策略** — LinearLayout vs ConstraintLayout vs FrameLayout 的选择逻辑，recycler 嵌套判断
5. **资源命名规范** — 切图文件名和 Android drawable 命名的一致性，避免 hash 碰撞

## 修改脚本的原则

- `scripts/bridge/figma_bridge_to_android.py` 是核心转换引擎，修改它会影响所有下游产物（`android_tree.json`、`assets.json` 的结构和内容），必须跑 `scripts/common/figma_validate_tree.py` 验证
- **dp 换算基准不变量**：`SCALE` 必须由根画板宽度（插件 `artboardWidth`）算出，不是提取根节点宽度。插件按内层 Frame 提取时，用节点宽度算会得到错误的 dp；改动 scale 相关代码后必须跑 `figma_selftest.py` 第 1、2 项
- `scripts/bridge/figma_pull.py` 是管线编排入口，变更步骤时按编号顺序插入，保持输出格式一致
- `scripts/bridge/figma_bridge_server.py` 是桥 HTTP 服务器，修改时注意与插件的 HTTP 协议兼容性
- 所有脚本保持零外部依赖（Python 3.10+ 标准库 only），不引入 pip 依赖
- 脚本添加新功能时，必须在 `if __name__ == "__main__"` 块中保持可独立运行

## 修改规则的原则

- 规则文件应该给 Agent **确定性的指导**，减少 Agent 靠猜测做决策的空间
- 好的规则 = 明确的触发条件 + 明确的行动指令 + 反面示例
- 规则不应重复 `android_tree.json` 的 schema 定义（那是 `schemas/` 的职责）
- 新增规则时，检查是否与已有规则冲突，并在 `SKILL.md` 的 "通用规则" 章节注册引用
- 规则使用中文简体，代码示例和字段名使用英文

## 测试与验证

- 改动 `scripts/` 下任何脚本后先跑 `python3 scripts/common/figma_selftest.py`（离线，约 10s，全绿才算改完）。
  当前覆盖 7 项 49 个断言：dp 换算基准、老插件回落、校验器 success/blocked、缓存复用三重门槛、
  `figma_query_node.py` CLI（`--list-caches --match` 参数顺序无关 / `--root-id` 严格匹配 /
  切图文件名 / `--assets --md5` / 未知参数与空条件必须 exit 2）、`figma_compare_nodes.py` 跨画板比对（含"没比成"的三种情形）
- 每次修改转换引擎后跑一次完整管线测试（需本地 Figma + 桥服务器 + 插件），对比新旧 `android_tree.json` 差异
- 每次修改规则后用同一个 Figma 设计稿让 Agent 重新生成 XML，对比生成质量
- `scripts/common/figma_validate_tree.py` 检查结构正确性（schema 合规、坐标范围合理、id 唯一性、dp 值无异常）。注意它只对**当前适配器产物**有效：`schema_version` 2.0 + `screen.artboard_width_px` 存在

## 内容签名长度不变量

`figma_query_node.py`（`--assets --md5`）与 `figma_compare_nodes.py` 打印的内容签名必须**同长度**
（均为 md5 前 8 位，各自的 `SIG_LEN`）。两处输出会被 Agent 互相核对；长度不一致会让它误判
"同一张图签名不同"。改任何一处都要同步另一处。

---

# 硬约束速查

这些是跨所有规则和命令的不可违反约束，优化时不能破坏：

1. `android_tree.json` 中的 dp 值禁止 Agent 二次换算
2. 产物不得包含 SVG 或 VectorDrawable，全部图标/切图必须是真实 xxhdpi PNG
3. Figma 图层树不得直接映射为 Android View 树，必须按视觉分组规则重组
4. 未完成 `./gradlew assembleDebug` 编译验证前不得声称任务完成。唯一合法降级是 `PARTIAL`：
   报错文件**不在本次改动集内**时按 `rules/verify-rules.md`「非本次改动导致的编译失败」四步取证，
   标 `PARTIAL` 并留收尾义务（稍后必须重跑 assembleDebug）。信号本身不放松——不得标 `PASS`，
   不得代改他人半成品
5. 缓存完整时可复用，否则必须重新提取
6. 当前仅桥模式（plugin）：不得索取 Figma URL。桥模式不可用且无缓存 → `blocked`
7. 状态栏节点在管线中自动过滤，Android 页面不渲染系统状态栏
8. 桥模式前置 `start` 命令初始化环境：桥服务器 `localhost:7789` 未运行则提示用户先 start
