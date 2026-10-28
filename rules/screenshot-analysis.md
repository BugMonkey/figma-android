---
name: figma-screenshot-analysis
description: 截图分析规范 — 结构确认环节如何按 Android 视角分析设计稿截图，产出 layout_analysis.json
---

# 截图分析规范

结构确认环节必须分析截图获取全貌（`screenshot.png` 360px 宽预览），但**截图只提供视觉直觉线索，坐标/尺寸/颜色/层级一律以 android_tree.json 为准**（见 `rules/android-tree-guide.md`）。

## 执行路径（唯一）

截图分析由**子 agent** 执行：主 Agent 用 Agent 工具派发一个子 agent 读取 `<extract_dir>/screenshot.png`，子 agent 只回传结构化定性结论。主 Agent 自身不 Read 截图，避免 base64 挤占主对话上下文。

- **触发时机**：步骤 5 结构确认（生成/改造/还原度检查均适用）
- **派发方式**：用 Agent 工具，prompt 固定包含三部分——实现意图（`implementation_context`）、5a 结构化结论（目标区域节点清单要点）、需回答的视觉问题；并明确要求只输出结构化结论，不输出图片内容或逐像素描述：

```text
读取 <extract_dir>/screenshot.png，按 Android 视角做截图分析。
实现意图：<implementation_context 摘要>
5a 结构化结论：<目标区域节点清单要点>
只输出一个 JSON 对象（不要输出其他文字，不要用 Markdown 代码块包裹），字段：
confidence / layout_summary / screen_type / sections / fixed_regions / scroll_strategy /
element_classification / component_groups / constraint_hints / implementation_hints / risk_flags
（字段结构见 schemas/layout-analysis-schema.md）
要求：区域划分覆盖全页从上到下；只做定性判断，禁止编造精确坐标/颜色/字号/圆角/间距；
不确定的项写入 risk_flags。不输出图片内容、base64 或逐像素描述。
若你无法读取这张图片，只输出 {"viewed": false, "reason": "无法读取图片"}，不要输出任何视觉结论。
```

- **产物**：主 Agent 取子 agent 的定性结论，补齐 `schema_version`、`design_id`、`user_intent` 等元数据并与 5a 定性结论合并，写入 `<extract_dir>/layout_analysis.json`（结构见 `schemas/layout-analysis-schema.md`）。
- **主 Agent 职责**：结合 android_tree.json 验证子 agent 的定性结论（bounds/children 确认容器归属与重叠），输出用户确认摘要
- 截图分析只输出定性结论；精确坐标/尺寸/颜色仍以 android_tree.json 为准（Hard Rule 17）

> **严禁在未真正查看过截图的情况下臆断截图内容**：未派发子 agent 或子 agent 未成功读取截图时，不得声称已完成视觉理解。

## 降级策略

子 agent 无法读取截图（返回 `viewed:false`、路径不存在、无法加载图片、无可用读图能力）时，按以下路径降级，不要无限重试：

1. **第 1 次失败**：检查传给子 agent 的截图绝对路径是否正确，修正后重派 1 次。
   子 agent 明确返回 `viewed:false` 时不得把空字段补成看似通过的视觉结论。
2. **第 2 次失败**：降级处理——
   - `layout_analysis.json.confidence` 设为 `low`
   - `risk_flags` 加入 `missing_visual_review`
   - 允许主流程以 `confidence=low` 写入最小骨架（仅 `schema_version`、`design_id`、`layout_summary` 及 android_tree 已确认的定性结论），结构确认摘要中注明"截图视觉分析缺失"
3. **降级后限制**：android_tree 无法回答的视觉问题（渐变质感/指示条颜色/渲染观感等定性判断）必须列入 `confirmation_items` 交由用户决定，禁止臆断；不得声称已完成高还原视觉确认。

## 分析顺序（Android 视角）

必须按**从上到下、从左到右**的顺序拆解，禁止跳区分析（除非布局方向明确为水平排列，如 ViewPager2 横向分页）：

```
1. 定根布局：整页是单屏 / 可滚动（NestedScrollView）/ 列表（RecyclerView）？
2. 从上到下划分横向区域（顶部标题栏 / 中间内容区 / 底部操作区）
3. 每个区域内从左到右识别元素（卡片 / 按钮 / 图标 / 文本）
4. 元素归组：视觉上被同一卡片/背景包住、同对齐、同间距的元素 → 一个容器
5. 判断层级关系：谁在下层（背景）谁在上层（内容/角标），用 android_tree 的 children 顺序验证
6. 判断宿主归属：底部 Tab / 全局导航是否属于宿主 Activity（Fragment 默认不含）
7. 判断动态区域：重复卡片 → RecyclerView / ViewPager2；可复用 item
8. 安全区检查：顶部/底部系统 UI 预留（状态栏已在提取期过滤；底部手势条/刘海以 inset 处理）
```

## Android 布局常识（默认假设）

- Fragment 布局不包含宿主 Activity 的底部 Tab、全局导航、悬浮入口
- Activity 布局可包含完整屏幕固定区域
- 底部固定按钮放在滚动容器外
- 重复结构（3+ 相似项）抽 item_*.xml + RecyclerView
- 背景与内容分离时（背景层 bounds 包含内容层），Android 中重组为同一容器

## 输出维度（layout_analysis.json + 确认摘要，6 项）

1. **视觉区域**：从上到下划分的区域清单（含每区大致 y 范围）
2. **容器重叠**：哪些元素跨区/重叠（如标题浮在容器上方），标出重叠关系（精确值以 android_tree 为准）
3. **元素归组**：哪些元素属于同一卡片/容器，容器推荐类型（LinearLayout / FrameLayout / ConstraintLayout）
4. **滚动策略**：none / NestedScrollView / RecyclerView / ViewPager2，固定区在哪
5. **切图覆盖粒度**：每区三分 — `full`（整卡 PNG）/ `half_bg`（仅背景切图+代码叠加文字/图标，FrameLayout 重组）/ `none`（纯代码绘制）
6. **交互热点**：哪些区域可点击、点击监听应挂在哪个 View（`click_target_hint`）

每条结论标注 `confidence`（high/medium/low）；高风险歧义进 `confirmation_items`；风险进 `risk_flags`。

## 边界与禁止

- 禁止用截图目测坐标/尺寸/颜色替代 android_tree（Hard Rule 17）
- 例外：容器归属、视觉分组等**定性判断**可在 android_tree 验证的基础上参考子 agent 的视觉结论；精确数值（坐标/尺寸/颜色/绘制顺序）必须仅使用 android_tree
- 禁止把整张截图搬进对话或大段文字描述（上下文节制，只输出结构化结论）
- 禁止机械还原截图所有可见元素 — 带用户意图判断"要实现什么"
- 截图无法识别图层名，用视觉描述代替

## 上下文节制

- 中间思考、完整节点表、图片内容不搬进对话
- 结构化结论沉淀到 `layout_analysis.json`；聊天只输出短摘要、阻塞项、必须由用户决定的问题
- 读取设计稿数据优先用 `figma_query_node.py` 轻量查询，禁止整文件 Read 大 JSON

## 与 android_tree 的分工

| 问题类型 | 数据源 |
|----------|--------|
| 精确坐标/尺寸/颜色/圆角/绘制顺序 | android_tree.json（唯一） |
| 区域划分/容器归属/滚动策略/切图粒度/交互热点（定性） | 截图分析（layout_analysis.json）→ android_tree 验证 |
| 渲染质感/溢出观感/美术风格 | 截图（子 agent 视觉结论） |
