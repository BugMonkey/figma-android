---
name: figma-global-rules
description: Figma skill 全局规则，所有命令执行前必须读取
---

# 全局规则

## 语言与格式

- 所有文档、报告、对话输出使用中文简体
- 禁止表情符号
- 状态词表分两套，勿混用：校验/运行状态用 `success` / `warning` / `blocked`（本文档与脚本输出）；
  任务记忆节 `build` 字段用 `PASS` / `PARTIAL` / `FAIL_BLOCKED` / `FAIL_FIXED` / `N/A`
  （枚举定义在 `schemas/verify-schema.md`）。`blocked` ≠ `FAIL_BLOCKED`，前者是运行状态，后者是编译结论。

## 缓存复用

**判定由 `figma_pull.py` 内部自动完成，Agent 不要自行判断"缓存是否可复用"。**
三重门槛（缺一不复用，自动重新提取）：三文件齐全（`android_tree.json` + `assets.json` +
`source_meta.json`）+ 适配器已产出 `screen.artboard_width_px`（旧版适配器 dp 基准错误，禁用）+
树中含目标节点。权威描述见 SKILL Hard Rule 3 与 `modes/bridge-execution.md` 调用约定。

## 结构先于视觉细节

代码生成推荐顺序：
1. 根布局和滚动策略
2. 固定区域和滚动区域
3. 容器和组件分组
4. 子元素约束
5. 资源和样式

Figma 图层树 ≠ Android View 树。详见 `rules/visual-grouping-rules.md`。

## 提取期处理（Agent 无需参与）

状态栏过滤、合并组包围盒裁剪到父容器、切图尺寸按 PNG 实测校正，均由插件与 `figma_pull.py`
在提取期完成（实现细节属维护文档，执行时不需要了解）。Agent 只需知道结论：

- `android_tree.json` / `assets.json` / 切图中不含设计稿状态栏。
- 合并节点与切图的 dp、PNG 实际尺寸已经一致，直接使用，无需再校正。

## 结构问题数据源（android_tree 优先）

桥模式下 `android_tree.json` 是节点结构、坐标、样式、切图归属的**唯一权威来源**；截图由子 agent 读取分析（主 Agent 不直接 Read 截图），
主 Agent 补元数据后产出 `layout_analysis.json`。两者能力边界与执行规范见 `rules/android-tree-guide.md` 与 `rules/screenshot-analysis.md`。

## 阶段职责边界

- 脚本：数据提取、dp 换算
- Agent：结构理解、代码生成
- `restyle-page`：必须输出影响分析（会话内 + 终端摘要），并向 `figma_task_memory.md` 追加任务记忆节
- `restore-check`：只输出差异建议，不主动改文件
- `verify`：编译验证

## 必须阻塞的场景

- `figma_pull.py` 运行失败且无完整缓存
- 无法获取设计截图
- 老页面改造前无法定位旧页面
- 老页面改造需要删除被代码引用的关键 ID
- 还原度检查既无实现截图也无可定位的 Android 项目
- 结构确认环节未获用户确认直接跳入代码生成

## 结果输出契约

统一为一套：**终端精简摘要（≤30 行，给人）** + **任务记忆节（`figma_task_memory.md`，给后续会话，
按 Hard Rule 13 的命令清单条件写入）**。不存在其他落盘报告信封。
