---
name: figma-android-tree-guide
description: android_tree.json 使用指南 — 桥模式下结构/位置/样式/切图归属的唯一权威数据源
---

# android_tree.json 使用指南

桥模式下，`android_tree.json` 是所有结构、位置、样式、层级、切图归属信息的**唯一权威来源**。凡是它能回答的问题，禁止目测截图、禁止凭截图推断数值。

## 能回答什么（结构定位问题 → 查 JSON）

| 问题 | 字段 / 手段 |
|------|-------------|
| 节点是什么类型（图/文字/形状） | `view_type`（ImageView / TextView / View） |
| 节点在画板哪里、多大 | `dp.x/y/w/h` + `dp_local`（相对父容器偏移） |
| 文字内容 / 字号 / 颜色 | `text` / `font_size_sp` / `text_color` |
| 背景色 / 渐变 / 圆角 / 描边 / 效果 | `style.background` / `gradient_colors` / `corner_radius_dp` / `border_*` / `effects` |
| 图标内容（各 tab 是什么图标、选中态区分） | 图层名 `name`（如 `icon_tab1_sel`，`sel` 后缀 = 选中态；业务名如"特价申请单"也能直接读出） |
| 图标/形状颜色（填充、线性图标描边） | `style.background`（fill）/ `style.border_color`（stroke，线性图标常用）；文字色 `text_color` |
| 是否切图、对应哪个导出文件 | `image.file`（查询脚本直接打印"切图: img_x_y.png"）；全部切图清单用 `figma_query_node.py --assets` |
| 谁在上谁在下（绘制顺序） | `children` 数组顺序 = z-order |
| 重复的卡/格、排列方向、单格尺寸 | `repeat_groups`（`item_size_dp` / `layout_hint` / `y_range_dp`） |
| 固定 / 滚动区域 | `regions` |
| 节点可见性 | `visible` |
| 节点在树中的路径 | `tree_path`（figma_selected_node.py / figma_query_node.py 输出） |

## 不能回答什么（这些才需要看截图）

- 真实渲染质感：渐变过渡是否自然、阴影柔和度、圆角观感
- 文字溢出 / 换行的实际观感
- 插画 / 图标的美术风格、色调是否协调
- 整页全貌的快速印象（结构确认环节由子 agent 读取 screenshot.png 并回传摘要）
- **页面的元素嵌套层级很可能不准！**

## 决策规则

0. **禁止一次性 Read 整个 `android_tree.json`**（产品级画板常达数百 KB，全量加载会挤占上下文且后续查询失效）——一律用下方脚本定向查询所需节点、子节点、样式、切图字段。
1. 用户问"XX 节点是什么 / 在哪里 / 什么颜色 / 是切图吗 / 谁盖住谁 / 重复组怎么排" → 走 `figma_query_node.py --id` / `figma_selected_node.py --node-id` 结构化查询，零成本、秒回。
   查子节点用 `--children --deep N --styles`：一次拿到 `node_id`、绝对坐标与精简样式，不要再逐个 `--id` 二次查询。
   按图层名查不到时改用 `--text <界面文字>`（图层名与界面文字经常不一致）
2. 判断切图对应设计稿位置 → 节点 `dp`/`dp_local` + `children` 顺序 + `repeat_groups`
3. 只有 JSON 无法回答的视觉 / 艺术问题 → 才看 screenshot.png，且一律派子 agent 读取
   （主 Agent 不直接 Read 截图）；禁止不看截图就凭结构数据主观描述观感
4. 禁止：猜结构、用截图目测替代坐标

## 多画板对比（如 4 个 tab 页画板的选中态差异）

每个画板 = 一个独立缓存目录。**首选 `figma_compare_nodes.py` 一次得到横向对比表 + 差异摘要**，
不要逐板查询再自己脑内对齐（画板一多必然漏项）。命令与参数见
`modes/bridge-execution.md` 脚本工具箱。

对比各画板的 `name` / `style.background` / `border_color` / `text_color` / `image.file` /
`切图` 行差异，即可得出选中/未选中样式差异清单，**无需看截图或派子 agent 读图**。
`image.file` 只能用来知道文件名，**不能用来判断视觉是否相同**（见下一节）。
不知道画板 nodeId 时用 `figma_query_node.py --list-caches --match <关键词>` 查看。

### 切图差异怎么判（重要）

**`image.file` 不能当差异判据，必须看内容签名（PNG 内容 md5）。** 导出命名有两条规则：

- `export_as_image` 节点按**节点寻址**命名（`img_<nodeId>.png`）——同一视觉在不同画板必然不同名，
  按名字比对会全部误报；
- `IMAGE fill` 节点按**内容寻址**命名（`img_<imageHash>.png`）——名字相同即内容相同。

所以"两个画板的图标是不是同一张图"只能由内容签名回答：`figma_compare_nodes.py` 已自动给出并归组，
单板清单用 `figma_query_node.py --assets --md5`。**禁止用文件名不同推断视觉不同。**

比对结论成立的前提是"真的比到了"：输出里出现「未形成任何交叉比对」/「仅在 1 个画板命中」/
「一个同名节点都没命中」时，说明该图层名没有跨板对齐，**不能据此报"无差异"**——
先检查图层名是否改过、`--deep` 是否够、画板是否都提取了，补齐后重跑。
两个输出都用同一长度（md5 前 8 位）的内容签名，可以互相核对。

