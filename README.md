# figma-android

## 版本记录

| 贡献者 | 贡献内容 | 贡献时间 | 版本 |
|--------|---------|---------|------|
| Edison | 从原 Android 插件独立提取为 `figma-android` 单 Skill 仓库；补齐 SkillHub manifest、LICENSE 和独立维护说明 | 2026-10-27 | 1.0.1021 |
| Edison | 按使用反馈补齐 P1/P2 与流程项：`--text` 按界面文字搜索；`--style-raw` 输出完整 style；适配器 style 补 `font_weight`/`text_style`；`figma_pull.py --node-id` 支持逗号分隔多值；`--list-caches` 补画板 dp 尺寸；SKILL 新增最小必读集矩阵与「用户要求直接改」例外；restyle 明确列表/结构类 UI 调整边界；android-layout-rules 补状态栏/沉浸式处理；slice-atomic 补切图内文字判断；create-page/restyle-page 补 validate_tree 显式步骤 | 2026-10-20 | 1.0.1020 |
| Edison | 按两位使用 Agent 的实测反馈修复 P0：`figma_query_node.py --children/--deep` 子节点行补 `node_id` 与绝对坐标，新增 `--styles` 输出精简样式；`--id` 在自动选最新缓存且不含目标节点时，自动跨缓存扫描定位所属画板；修复适配器 `dp_local` 计算（父节点绝对坐标做差，而非父节点局部坐标）；状态栏识别补裸 `status`；`figma_pull.py` 切图复制提示改为 `<module>` 占位。自检新增 dp_local 三层嵌套、跨缓存自动定位、--children/--styles 断言 | 2026-10-20 | 1.0.1019 |
| Edison | 执行文档去重与瘦身（不改流程语义）：SKILL.md 5b 不再内联 prompt，统一引用 `rules/screenshot-analysis.md`；`modes/bridge-execution.md` 删除三种 `figma_selected_node.py` 完整输出示例、失败诊断分支改为引用「提取失败快速诊断」表；`unit-conversion-rules.md` 并入 `android-layout-rules.md` 后删除；`slice-atomic-rules` 的 imageTransform 表、`restyle-guardrails` 的替换切图细则、`change-impact-schema` 的 diff_type 表改为引用权威文件；`verify-rules` / `commands/verify.md` 状态枚举改为引用 `verify-schema`；`create-layout.md` 改为 create-page 变体；`global-rules` 提取期实现细节压缩为结论；删除 `android-tree-guide` 查询入口表与 `android-tree-schema` 完整示例 | 2026-10-20 | 1.0.1018 |
| Edison | 截图分析改为派发子 agent 读图，skill 不再主动调用 `外部视觉脚本` 视觉脚本：改写 SKILL.md 步骤 5b、`rules/screenshot-analysis.md`（执行路径/降级策略）、`rules/global-rules.md`、`rules/android-tree-guide.md`、`commands/restore-check.md`、`schemas/layout-analysis-schema.md`、`modes/bridge-execution.md`；移除 `commands/start.md` 的 vision-token 环境检查与提醒；`figma_pull.py` 截图压缩注释与输出文案同步。识图 hook 保留自动触发，供不能读图的模型兜底 | 2026-10-19 | 1.0.1017 |
| Edison | 报告体系收敛为「任务记忆层」：四份落盘报告（verify_report/asset_report/change_impact_report/restore_check_report）合并为唯一文件 `figma_task_memory.md`（项目根，每任务一节 append-only，固定 8 字段 build/blocker/verified_scope/attribution/excluded/asset_overwrite/confirmed/open，只存 git/重跑恢复不了的事实）；新增**读取契约**——6 个命令开工前强制 grep 历史节（excluded/覆盖链/PARTIAL 补跑义务/归属复核），写入与消费同等强制；人向内容（改动清单、对照表、差异明细、构建输出）全部只进终端；统一落点口径（消除 README"项目根"vs SKILL"`.figma/` 下"矛盾）；templates 三合一为 task_memory.md；SKILL Hard Rule 11-13、restyle-guardrails「报告分层」→「任务记忆层」、verify/change-impact schema、verify-rules 收尾义务、evals 同步。独立审计后同日修订：`build` 枚举补 `N/A`（纯导出/留痕节不涉编译）、Hard Rule 13 写入义务改命令显式清单（消除"非只读必写"与 export 条件写的冲突）、追加强制 `cat >>` 单次写入并禁止 Edit/Write 整文件改写（并发会话丢节回归）、grep 路径锚定 `$(pwd)`（对照 --project-root 纪律）、无锚定节头画板位写「不适用」、补跑义务闭合格式（`open` 承接引用，同任务以最新节为准，写入正典契约表）、`confirmed` 纳入读取契约、记忆文件不进宿主版本库（git `.gitignore`/SVN `svn:ignore`）、"唯一落盘"限定为报告/记忆文件（.figma 中间产物照旧）、verify-schema 样例补 `- ` 前缀、evals 断言对齐 attribution 字段。第二轮全量体检存量修复：缓存复用口径统一为三重门槛（清 global-rules/SKILL 旧二门槛）、三个查询脚本未知参数与空条件硬失败（exit 2，selftest +4 断言→49）、--list-caches 补 --find-root 提示行（selftest 存量 FAIL 归零转全绿）、find_latest_tree_dir 无锚定回退打印警示、validate_tree 门禁接入 inspect 与 SKILL 流程 4、timeout 口径统一 ≥300s、缓存"确认最新"改为可执行的追问/--force 规则、决策产物要求去除幻影字段 normalize_report/design_tree（禁写回脚本产物）、"派 vision/专职 Agent/SVG 预转换"陈旧措辞清理、examples 幻影示例替换为可过校验器的最小 v2 样本、android-tree-schema 的 screen 字段集对齐适配器真实产出（width_px/scale/artboard_width_px）、统一状态信封与摘要双契约合一、Hard Rule 5 补 create-layout、README 安装位表补 Claude Code 位、evals 状态格式断言对齐、.gitignore 死条目与 figma_pull 死常量清理 | 2026-09-29 | 1.0.1016 |
| Edison | 新增画板遍历能力（更正：端点为 /api/pending，预拉取询问为步骤 6）：`listAllArtboards()` 轻量遍历所有页面画板；新增 `/api/request-list` / `/api/artboard-list` / `/api/pending` 端点；新增 `figma_traverse_list.py` 触发遍历脚本；`start` 命令新增预拉取询问（实为步骤 6） | 2026-09-23 | 1.0.1013 |
| Edison | 修复 5 处静默缺陷：dp 换算基准改用真实根画板宽度（`--node-id` 传子节点不再算错 scale）；`figma_pull.py` 提取失败不再继续跑后续步骤；缓存复用加三重门槛（三文件齐全 + 适配器已产出 `artboard_width_px` + 树中含目标节点）并新增 `--force`；`figma_query_node.py --root-id` 改为按树内字段严格匹配、未命中不再回退到最新缓存，新增 `--project-root` / `--list-caches`；`figma_validate_tree.py` 重写为对桥模式 v2 产物校验（三值状态 success/warning/blocked）。另修：`figma_selected_node.py` 的 f-string 嵌套同类引号语法（Python 3.12 前直接报 SyntaxError，脚本完全无法运行）、`--list-caches` 写在 `--project-root` 之前会忽略后者。新增离线自检 `scripts/common/figma_selftest.py` | 2026-09-18 | 1.0.1010 |
| Edison | 查询脚本补齐切图文件名：`figma_query_node.py` / `figma_selected_node.py` 输出「切图: img_x_y.png (drawable-xxhdpi, WxHdp)」，子节点 `[IMG]` 后追加 `-> 文件名`，style 白名单补 `border_color`/`border_width`/`gradient_colors`/`opacity`；新增 `--assets [--md5]` 切图清单模式（内容 md5），`--list-caches --match` 按画板名/nodeId/目录名过滤。新增 `figma_compare_nodes.py` 跨画板比对（对比表 + 差异摘要 + 内容等价分组，显式提示节点寻址文件名不可比）。编译验证新增 PARTIAL 合法路径：「非本次改动导致的编译失败」四步（归属/不代改/降级取证/收尾义务），PARTIAL 定义在 verify-rules、verify 命令、verify-schema、verify_report 模板四处统一，报告尾部固定 `build:`/`blocker:`/`verified_scope:` 机器可检索字段。`replace_asset`（保留项目原名覆盖）语义写入 resource-naming-rules / restyle-guardrails / export-assets / change-impact-schema。restyle 新增页面归属 grep 证明（`page.code_entry` + `host_binding_proof`）与混合任务路由（换切图 + 改布局一律走 restyle-page）。报告分层：按任务命名 + append-only + 一次性材料不进 md。视觉脚本定位改有序回退链并新增 `../外部视觉脚本/scripts/vision_path.py`（镜像目录不再因 `${CLAUDE_PLUGIN_ROOT}` 未展开而误判不可用）。自检扩到 7 项 45 个断言 | 2026-09-21 | 1.0.1011（**待发版**：本次只改仓库源码，`plugin.json` / `marketplace.json` 版本号与安装位由维护者按发版流程统一升级） |
| Edison | 三处视觉脚本定位片段去掉内联 glob（zsh `nomatch` 会在任一 glob 无匹配时让整条命令失败，冷机器首跑即挂），统一走 `../外部视觉脚本/scripts/vision_path.py`：`SKILL.md` 步骤 5b、`rules/screenshot-analysis.md`、`commands/restore-check.md` | 2026-09-22 | 1.0.1012 |

## 概述

Figma 设计稿 → Android 页面，一句话生成。

在 Figma 桌面端选中画板，对 Claude Code 说出意图，Agent 自动提取设计数据、生成可编译的 Android XML 布局 + 资源 + Activity。

---

## 安装

```bash
skillhub install figma-android --namespace user_140863df
```

需要指定宿主 skills 目录时：

```bash
skillhub install figma-android --namespace user_140863df --dir <宿主 skills 目录>
```

---

## 你只需要做这些

```
① 打开 Figma 桌面端，点击选中一个画板（Frame / Component / Instance）
② 回到 Claude Code，说出你要什么（见下方提示词）
③ Agent 展示结构方案 → 你回复"确认" → 自动生成 + 编译验收
```

---

## 提示词速查

对 Claude Code 说左边的就行，Agent 会自动理解：

| 你想做什么 | 对 Claude Code 说 | 会得到什么 |
|-----------|------------------|-----------|
| 生成完整页面 | "生成首页"、"帮我实现这个登录页" | XML 布局 + 资源 + 切图 + Activity |
| 只要布局，不要代码 | "只要布局"、"只生成这个弹窗的 XML" | XML 布局 + 资源文件 |
| 按新设计稿改页面 | "按设计稿改登录页"、"更新首页 UI" | 改造后的布局 + 改动摘要 |
| 导出切图到项目 | "导出这个画板的切图"、"下载图标" | xxhdpi PNG + 更新 XML 引用 |
| 检查实现跟设计是否一致 | "检查还原度"、"对比设计稿" | 差异清单 + 修复建议（对话里给全） |
| 看看画板复不复杂 | "评估一下"、"查看画板结构" | 复杂度评估（对话里给） |
| 编译验证 | "编译验证"、"跑一下 build" | 编译结果 |
| 首次 / 环境没起来 | "启动"、"start"、"初始化" | 完整环境引导 |

> 所有提示词不必记忆，说自然语言就行。给人看的结果都在对话里；唯一落盘的报告/记忆文件是
> 会话工作目录的 `figma_task_memory.md`（任务记忆，给后续会话的 Agent 读，不需要你翻；
> 属工作副本本地态，已配置为不进版本库，不会混进你的提交）。

---

## 首次使用（只需要做一次）

```
1. 在 Android 项目目录中打开 Claude Code
2. 说 "启动" → Agent 自动检查环境、引导安装 Figma 插件
3. 就绪后提示"环境已就绪"
```

之后每次打开 Claude Code，只要说"启动"就能恢复连接。

---

## 完整例子

```
你：  启动
Agent：环境已就绪

（你在 Figma 中选中「首页 v2」画板）

你：  生成首页
Agent：正在提取数据...
       页面结构分析：
       ┌─ 顶部导航栏 (56dp)
       ├─ Banner 轮播区 (180dp)
       ├─ 功能入口 ×8 (2×4 网格)
       └─ 推荐列表 (RecyclerView)
       
       检测到功能入口为重复模式，用 RecyclerView？(是/否)

你：  是
Agent：→ 生成布局 → 切图 → Activity → 编译验证 ✅
       结果都在上面，任务记忆已更新（figma_task_memory.md）
```

---

## 你需要准备

| 依赖 | 说明 |
|------|------|
| **Claude Code** | 在 Android 项目目录中启动，是这个 skill 的运行环境 |
| **Figma 桌面端**（已登录） | 用来选中画板（首次需安装配套插件，Agent 会引导） |
| **Python 3.10+** | 运行数据提取脚本，零外部依赖 |

---

## 你会得到什么

```
# 生成到 Android 项目中的文件
app/src/main/res/layout/<page>.xml
app/src/main/res/drawable/*.xml
app/src/main/res/drawable-xxhdpi/*.png         # xxhdpi PNG 切图
app/src/main/java/.../<PageName>Activity.kt     # 完整页面时

# 任务记忆（会话工作目录，给后续会话的 Agent 读，不是给你看的文档；不进版本库）
figma_task_memory.md         # 每任务一节 append-only：build/blocker/verified_scope/attribution/
                             # excluded/asset_overwrite/confirmed/open 八个固定字段

# 其余结果（改动清单、切图映射、还原度差异、编译输出）全部在对话终端里给，不落盘
# （.figma/ 缓存内的中间产物如 layout_analysis.json 照旧生成，不算报告）
```

---

## 常见问题

**Q：每次都要说 `/figma-android` 吗？**
A：不用。说"生成首页"、"改登录页"这种自然语言就行。`/figma-android` 只在 Agent 没有自动匹配到本 skill 时用来明确指定。

**Q：为什么选中画板后还要等确认？**
A：Figma 的图层结构和 Android 的 View 层级本质不同。Agent 需要把 Figma 的分组重新理解为 Android 的容器（比如背景和文字在 Figma 里是两个 Group，在 Android 中要合并成一个按钮），展示方案让你看一眼再生成，保证质量。

**Q：有 Figma 分享链接也能用吗？**
A：当前版本仅支持桥模式（本地 Figma 桌面端插件直连），URL / MCP 通道暂未启用。请使用 Figma 桌面端选中画板后直接说出意图。

**Q：生成的代码能不能直接用？**
A：布局代码经过 `./gradlew assembleDebug` 编译验证，可以放进项目。但不包含业务逻辑、ViewModel、网络请求等——你需要在此基础上接入数据层。

**Q：切图命名乱怎么办？**
A：Figma 导出的是 `img_a1b2c3d4e5f6.png` 这种 hash 名，Agent 会自动按 Android 规范重命名（`ic_` / `bg_` / `img_` 前缀），你只需要确认命名映射表。

---

## 项目结构（维护者参考）

详细文档见 [`SKILL.md`](SKILL.md) 和 [`AGENTS.md`](AGENTS.md)。

```
figma-android/
├── .claude-plugin/plugin.json  # Skill manifest
├── LICENSE.md
├── SKILL.md      # 入口文档：意图匹配 + 执行流程 + Hard Rules
├── AGENTS.md     # 维护者指南：设计哲学 + 优化指引 + 硬约束速查
├── CLAUDE.md     # 项目指令
├── commands/     # 命令处理指南（9 个）
├── modes/        # 数据通道（current_mode.txt + bridge-execution.md）
├── rules/        # Agent 行为规则（9 个）
├── schemas/      # 产物 Schema 文档（5 个）
├── templates/    # 任务记忆节模板
├── evals/        # 评测用例
├── examples/     # 最小 v2 示例产物（见 examples/README.md）
└── scripts/
    ├── bridge/   #   桥模式脚本（6 个：服务器 / 提取 / 适配器 / 查询 / 比对）
    ├── common/   #   公共脚本（校验 + 离线自检）
    └── plugin/   #   Figma 插件（code.js + manifest.json + ui.html）
```

> 仅桥模式：无 MCP 通道，`scripts/mcp/`、`docs/`、`test/` 等目录已不存在，
> 看到相关引用即为陈旧描述。

### 维护说明

- 本仓库就是唯一真源，不再依赖原插件的符号链接或安装位。
- 改动后先跑 `python3 scripts/common/figma_selftest.py`，全绿再提交。
- 发布前同步更新 `SKILL.md`、`.claude-plugin/plugin.json` 和本文件顶部的版本记录。
- 截图分析由主 Agent 派发子 agent 读图，不依赖外部视觉脚本。
