---
name: figma-android-bridge-execution
description: 桥模式执行步骤清单，Agent 进入桥模式后立即读取此文件
---

# 桥模式

**Agent 能力边界：**

| 状态 | 能力 |
|------|------|
| 不提取就能做 | 查看选中节点信息、查看任意已缓存节点的子节点结构和切图文件名与样式、查看切图清单（`--assets`）、查看节点坐标/样式/view_type、搜索节点、多画板同名节点横向对比（`figma_compare_nodes.py`） |
| 需提取才能做 | 查看未提取画板的内部结构、获取截图画板全貌 |
| 不能做 | 回答设计意图问题、MCP 通道操作、根据外部 URL 提取数据 |

---

## 用户端信息（Agent 必须理解）

用户在 Figma 中通过 **figma-android-bridge 插件面板**获取以下信息：

```
plugin 面板:
  ┌────────────────────────────────┐
  │ ● 已连接                       │ ← 状态指示灯
  │ ┌─────────────────────────┐    │
  │ │ 画板                    │    │ ← 灰底区域（显示"画板"或"未选中节点"）
  │ └─────────────────────────┘    │
  │ ┌─────────────────────复制─┐   │
  │ │ 咨询 (FRAME)  [2:141]    │   │ ← 蓝底卡片（选中根画板时）
  │ └──────────────────────────┘   │
  │ ┌─────────────────────复制─┐   │
  │ │ -> Avatar (FRAME)[2:152] │   │ ← 蓝底卡片（选中子节点时）
  │ │   |_ 画板: Header        │   │
  │ └──────────────────────────┘   │
  │ [标记为切图] [下载]            │ ← 子节点时显示的操作按钮
  │ ┌─────────────────────复制─┐   │
  │ │ Android Shape            │   │ ← 选中带填充/描边/圆角的节点时
  │ │ <shape ...>...</shape>   │   │   自动生成可复制的 shape XML
  │ └──────────────────────────┘   │
  └────────────────────────────────┘
```

**用户的操作和对应你的理解：**
- 用户点击蓝底卡片 → 复制 `layername[nodeId]`（如 `咨询[2:141]`、`Avatar[2:152]`）
- 用户点击 Android Shape 代码区 → 复制该节点的 Android shape drawable XML（填充/圆角/描边已换算为 dp）
- 用户口头说的 `"编组-2[1:783]"` = 节点名"编组-2"，nodeId 为 `1:783`
- 用户说 `"查看 2:152 样式"` = nodeId `2:152`
- 用户可以说任意 nodeId，即使当前 Figma 没有选中该节点

Agent 解析用户输入中的 `[nodeId]` 或裸 `数字:数字` 模式作为 nodeId。

---

## 脚本工具箱

Agent 禁止自行编写 inline Python 或 Shell 查询脚本。始终使用以下工具箱中的脚本。

### 环境与数据提取

> 参数详解以「参数速查」为唯一权威；本表只述用途、时机与耗时。

| 脚本 | 用途 | 何时调用 | 预计耗时 | 执行建议 |
|------|------|---------|---------|---------|
| `scripts/bridge/figma_bridge_server.py --port 7789` | 启动桥服务器 | `start` 命令 / `figma_pull.py` 自动调用 | ~3s | 同步执行，timeout 10s |
| `scripts/bridge/figma_pull.py [--port 7789] [--node-id <id>] [--force] --project-root <dir>` | 完整数据提取 (节点树+截图+切图+adapter转换) | 桥模式数据提取唯一入口。无参数=按选中提取；`--node-id`=按ID提取。**默认先查缓存复用**：命中「三文件齐全 + 适配器已含 `artboard_width_px` + 树中含目标节点」的缓存则秒级返回，不请求插件；`--force` 跳过复用强制重拉（设计稿已更新时用）。**`--node-id` 传子节点 ID 也可以**：plugin 会向上追溯所属根画板，按整块画板提取，dp 基准始终是画板宽度。**`--project-root` 必须显式传会话工作目录**（`.figma/` 缓存落盘位置），禁止依赖默认 `os.getcwd()`（会受 Agent cd / skill 符号链接影响）。产物 `screenshot.png` (360px，全貌预览/子 agent 读图用)；`screenshot.png` 自动压缩到 360px 宽（未装 PIL 则保留原图）。**插件空闲不再直接判失败**：iframe 不可见时浏览器会把插件轮询节流到约 60s 一次，此时 `connected` 为 false 但插件仍在线，只要距上次轮询 <90s（`PLUGIN_IDLE_TOLERANCE`）就继续等待而非退出；将 Figma 置于前台并保持插件面板可见可显著加速 | ~10-60s（缓存命中 ~1s；插件被节流时每次需多等一个轮询周期，可达 60s+） | 同步执行，timeout 300s（脚本内部等待窗口为 240s，勿小于它） |
| `scripts/bridge/figma_traverse_list.py [--port 7789] [--width <N>]` | 轻量遍历所有画板，返回元数据清单（名称/ID/类型/尺寸/所在页面） | `start` 命令步骤 7 浏览画板清单时调用。**不导出截图/节点树**，秒级返回。脚本内部检查上次结果是否可用（避免重复触发插件遍历）。**`--width` 按规范宽度过滤**：只保留该宽度的画板，被剔除项记入 `filtered_out` 字段（不静默丢弃）。设计稿规范宽度由项目决定（二手交易为 1080px），非规范宽度的画板多为废弃稿，且会因 dp 基准错误污染产物 | ~2-8s（缓存命中）；插件被节流时可达 ~60s | 同步执行，timeout 90s（脚本内部等待 75s，需覆盖一次节流轮询） |

### 节点查询（有缓存时零提取成本）

| 脚本 | 用途 | 何时调用 | 预计耗时 | 执行建议 |
|------|------|---------|---------|---------|
| `scripts/bridge/figma_selected_node.py [--port 7789] --project-root <dir>` | **默认模式**：通过桥服务器查询 Figma 当前选中的节点信息（名称、Figma ID、类型、所属画板等）。如有已提取的缓存还会附一层子节点列表（不依赖 `--enrich`）。**无缓存时脚本内部会自动触发 `figma_pull.py --node-id` 提取根画板，但本决策树 Step 0 仅给 15s timeout（提取进程会被中断）。完整提取由 Step 2 显式执行。** `--project-root` 会透传给内部调用的 `figma_pull.py`，保证缓存落盘正确。 | 用户说"查看我选中的节点" / 决策树 Step 0 无锚定回退 | ~3-6s（仅查询）；含自动提取则更长但会被中断 | **同步执行**，禁止后台化。timeout 15s。超时/无输出时 curl `http://localhost:7789/api/selected-node` 兜底，然后强制进入 Step 2。不用关心脚本内部的自动提取是否成功——Step 2 会独立处理。 |
| `scripts/bridge/figma_selected_node.py --node-id <id> [--root-id <rootId>]` | **缓存锚定模式**：从已提取的缓存中按 nodeId 查询节点信息+子节点列表，**不依赖桥服务器和 Figma 当前选中**。指定 `--root-id` 可限定在某个根画板的缓存中搜索。 | 多会话锚定查询 / 决策树 Step 0 有锚定 / 用户说"看一下 XXX 节点" / 画板已提取但 Figma 选中已切换 | ~1-3s | 同步执行 |
| `scripts/bridge/figma_selected_node.py --enrich <dir>` | **默认模式的辅助参数**：配合默认模式（无 `--node-id`）使用，指定缓存目录来获取更丰富的节点信息（`tree_path`、`android_id`、`dp`）。与 `--node-id` **互斥**——传了 `--node-id` 就不再走桥服务器。 | 默认模式查询时想从指定缓存中获取额外定位信息 | ~3-6s | 同步执行 |
| `scripts/bridge/figma_query_node.py --id <node_id> [--children] [--deep N] [--styles] [--style-raw] [--find-root] [--latest] [--dir <dir>] --project-root <dir>` | [工具箱核心] 查缓存树中<b>任意节点</b>的详情 + 展开 N 级子节点。子节点每行带 `node_id` 与绝对坐标；加 `--styles` 追加精简样式行。输出含切图文件名（`切图: img_x_y.png (drawable-xxhdpi, WxHdp)`）、文本内容、style（background/gradient_colors/text_color/corner_radius_dp/font_size_sp/border_color/border_width/opacity）。不触发提取，只读缓存；自动选择最新缓存且其中不含该 nodeId 时，自动扫描其他缓存定位所属画板。 | 选中节点的子节点展开 / "里面有几个切图" / "Tool Icon Row 下面是什么" / "这个节点是不是切图" / "这个节点的切图文件叫什么" / 任何"查看XX内部结构"的需求 | ~1-3s | 同步执行 |
| `scripts/bridge/figma_query_node.py --name <名称> [--fuzzy] [--children] [--latest --root-id <id>] --project-root <dir>` | 在整棵树中按名称搜索节点 | 用户说"找一下所有 icon-bg" | ~1-3s | 同步执行 |
| `scripts/bridge/figma_query_node.py --text <界面文字> [--children] --project-root <dir>` | 按节点 `text` 内容做大小写不敏感子串搜索 | 图层名与界面文字不一致（如图层名「选择收货地址」、文字「选择收货地址*」），或按名称查不到时 | ~1-3s | 同步执行 |
| `scripts/bridge/figma_query_node.py --type ImageView [--children] [--latest --root-id <id>] --project-root <dir>` | 在整棵树中按 View 类型筛选 | 用户说"页面上有多少 ImageView" | ~1-3s | 同步执行 |
| `scripts/bridge/figma_query_node.py --assets [--md5] [--latest] [--root-id <id>] --project-root <dir>` | 列出该画板的切图清单（node_id / 图层名 / 文件名 / dp 尺寸），`--md5` 附加每个 PNG 的内容签名（文件缺失标 `missing`）。数据源 `assets.json`，不解析节点树。 | "这个画板有哪些切图" / "这个画板的切图文件名是什么" / 判断某切图文件是否真在产物里 | ~1s | 同步执行 |
| `scripts/bridge/figma_query_node.py --list-caches [--match <关键词>] --project-root <dir>` | 列出项目下所有缓存（画板名 / nodeId / 提取时间）。`--match` 按 画板名 / 画板 nodeId / 缓存目录名 做大小写不敏感子串过滤；未命中明确说明。 | 排查"缓存找不到" / 确认某画板是否已提取（画板多时用 `--match` 过滤） | ~1s | 同步执行 |
| `scripts/bridge/figma_compare_nodes.py --name <关键词> [--fuzzy] [--root-ids <id,id,...>] [--deep N] --project-root <dir>` | [跨画板比对] 一次输出：每画板一段同名字段表（`node_id/name/view_type/dp/background/border_color/text_color/image.file/内容签名`）+ 差异摘要（只列不一致字段）+ 内容等价分组（内容签名相同 = 同一张图）。`--root-ids` 省略则扫全部缓存，显式指定未命中即报错退出。 | 多画板选中/未选中态差异对比 / "4 个 tab 画板的图标差在哪" / 判断跨画板切图是否同一张 | ~2-4s | 同步执行 |

> **数据源优先级（必读）**：`android_tree.json` 是桥模式下结构/位置/样式/切图归属的**唯一权威来源**。
> 任何"节点是什么 / 在哪 / 什么颜色 / 是否切图 / 谁盖住谁 / 重复组怎么排"的问题，
> 一律用上表脚本查 JSON，**禁止看截图目测数值**。
> 截图（screenshot.png）仅用于全貌预览与质感评估，且由子 agent 读取。详见 `rules/android-tree-guide.md`。

### 标准输出格式（关键字段）

Agent 只需识别状态与关键字段，不需要逐字符匹配完整格式。

- `figma_selected_node.py`：节点名称 / Figma ID / 类型 / 所属画板 / 根画板；子节点含 `view_type`、`name`、`dp(w x h)`、`[IMG] -> 切图文件名`、`style`。
- `figma_query_node.py --id/--name/--type`：`node_id`、`name`、`view_type`、`android_id`、`dp(x,y)`、`dp(w,h)`、`style`、`切图: 文件名 (drawable-xxhdpi, WxHdp)`、`路径`。
- `figma_query_node.py --assets --md5`：按 `序号 / node_id / 图层名 / 文件名 / dp(w x h) / 内容签名(md5)` 输出，文件缺失标 `missing`。
- `figma_compare_nodes.py`：三段——① 每画板字段表（`node_id/name/view_type/dp/background/border_color/text_color/image.file/内容签名`）；② 差异摘要；③ 内容等价分组（签名相同 = 同一张图）。

`figma_compare_nodes.py` 出现以下三种「没比成」输出时，结论**不完整**，不能当成「无差异」：

- 「未形成任何交叉比对」
- 「仅在 1 个画板命中」
- 「以下画板一个同名节点都没命中」


### 验证与对比

| 脚本 | 用途 | 何时调用 | 预计耗时 | 执行建议 |
|------|------|---------|---------|---------|
| `scripts/common/figma_validate_tree.py <extract_dir>` | 校验产物（android_tree.json / assets.json / source_meta.json 结构与数值）。三值状态：`success`=可直接写布局，`warning`=有可疑项（如提取根非顶层画板、切图文件缺失），`blocked`=禁止据此生成代码 | `inspect` / 结构确认阶段 | ~1-2s | 同步执行。exit 2 = blocked |
| `scripts/common/figma_selftest.py` | 离线自检（不需要 Figma / 桥服务器）：dp 换算基准、校验器判定、缓存复用门槛 | 改动 `scripts/` 下任何脚本后回归 | ~10s | 同步执行。全绿才算改完 |

### 参数速查

**`figma_pull.py`**

| 参数 | 必填 | 说明 |
|------|------|------|
| `--port 7789` | 否 | 桥服务器端口 (默认 7789) |
| `--node-id <id>` | 否 | 按 nodeId 提取，**兼容子节点 ID**（plugin 自动追溯所属根画板，按整块画板提取）。不依赖用户选中。支持逗号分隔多个：`--node-id 9:2258,9:2259`（逐个提取，同一画板命中缓存复用）。示例: `--node-id 2:152`、`--node-id 1:783` |
| `--force` | 否 | 跳过缓存复用强制重新提取。设计稿已更新、或怀疑缓存是旧版适配器产物时用 |
| `--project-root <dir>` | **Agent 必须传** | 项目根目录（`.figma/` 缓存落盘位置）。传**会话工作目录**（用户启动 Claude Code 的项目，即 `pwd`）。**禁止省略**：`os.getcwd()` 默认值会受 Agent `cd` 影响，若 cwd 落在 skill 目录，缓存会跟到 skill 目录。示例: `--project-root /path/to/android-project` |

> **调用约定**：Agent 用**绝对路径**调用 `scripts/bridge/figma_pull.py`、`scripts/bridge/figma_query_node.py` 与 `scripts/bridge/figma_compare_nodes.py`，同时显式传 `--project-root "$(pwd)"`，保持缓存始终落在用户项目根目录。禁止 `cd` 到 skill 目录后执行（skill 目录可能是符号链接，`os.getcwd()` 会返回链接路径）。
>
> 下文决策树/流程片段中的 `figma_pull.py` 简写调用均按本约定执行——**一律补 `--project-root "$(pwd)"`**，本文不复述。

> `figma_pull.py` 内部等待窗口 240s + 适配器转换约 60s，**Agent 层 Bash timeout 必须 ≥300s**
> （取 180s 一类小值会在插件被节流时杀掉本来会成功的提取，且会被误当"插件异常"排查）。
> 超时后按决策树步骤 2 诊断。

**`figma_selected_node.py`**

| 参数 | 必填 | 说明 |
|------|------|------|
| `--port 7789` | 否 | 桥服务器端口 (默认 7789) |
| `--project-root <dir>` | **Agent 必须传** | 会话工作目录（`.figma/` 缓存落盘位置）。默认模式内部自动提取时会透传给 `figma_pull.py`；锚定模式也用它定位缓存。传 `"$(pwd)"`，禁止省略（同 `figma_pull.py` 调用约定） |
| `--enrich <dir>` | 否 | 指定缓存目录。示例: `.figma/figma_extract_xxx/figma_extract_prepared` |
| `--node-id <id>` | 否 | 缓存锚定模式：按 nodeId 查询，不依赖桥服务器。需有已提取的缓存 |
| `--root-id <rootId>` | 否 | 配合 `--node-id`，限定在指定根画板的缓存中搜索 |

**`figma_query_node.py`**

| 参数 | 必填 | 说明 |
|------|------|------|
| `--id <node_id>` | 三选一 | 按 nodeId 精确查询。如 `--id 13:22` |
| `--name <名称>` | 三选一 | 按图层名精确匹配；查不到时改用 `--text` |
| `--text <界面文字>` | 三选一 | 按节点 `text` 内容子串搜索（图层名与界面文字不一致时用） |
| `--type <ViewType>` | 三选一 | 按 view_type 筛选。如 `--type ImageView` |
| `--fuzzy` | 否 | 配合 `--name`，模糊匹配 |
| `--children` | 否 | 列出匹配节点的直接子节点 |
| `--deep N` | 否 | 配合 `--children`，展开 N 级子节点。默认 1。子节点行自带 `node_id` 与绝对坐标 |
| `--styles` | 否 | 配合 `--children`/`--deep`，每个子节点追加一行精简 style（background/text_color/corner_radius_dp/font_size_sp/font_weight/text_style/border_*/gradient_colors/opacity/effects），避免二次查询 |
| `--style-raw` | 否 | 命中节点额外输出完整 style JSON，用于排查白名单字段缺失（如未采集的 effects/属性） |
| `--find-root` | 否 | 配合 `--id`，在所有缓存中扫描定位节点所属根画板。不知道节点属哪个根画板时必传 |
| `--latest` | 否 | 自动使用最新的缓存目录 |
| `--dir <dir>` | 否 | 指定缓存目录。不传则自动选最新 |
| `--root-id <id>` | 否 | 限定缓存目录匹配特定根画板（比对树内 `root.node_id` / `screen.artboard_id`，非目录名）。**未命中直接报错并列出可用缓存，不会回退到最新缓存**——避免多画板场景静默读到别的画板 |
| `--project-root <dir>` | **Agent 必须传** | 项目根（`.figma/` 位置）。同 `figma_pull.py` 调用约定，禁止依赖 `os.getcwd()` |
| `--list-caches` | 否 | 列出项目下所有缓存（画板名 / nodeId / dp 尺寸 / 提取时间），用于排查"缓存到底在哪"与区分同名画板 |
| `--match <关键词>` | 否 | 配合 `--list-caches`。按 画板名 / 画板 nodeId / 缓存目录名 做大小写不敏感子串过滤；未命中明确说明而不是空列表 |
| `--assets` | 否 | 切图清单模式：列出 `assets.json` 的全部切图（node_id / 图层名 / 文件名 / dp 尺寸）。与 `--id/--name/--type` 互斥，命中即输出并退出 |
| `--md5` | 否 | 配合 `--assets`。附加每个 PNG 的内容签名（md5 前 8 位，与 `figma_compare_nodes.py` 同长度，可互相核对），文件缺失标 `missing` |

**`figma_compare_nodes.py`**

| 参数 | 必填 | 说明 |
|------|------|------|
| `--name <关键词>` | **是** | 要比对的图层名。缺失直接报用法并 exit 2（比对全量节点没有意义且会爆上下文） |
| `--fuzzy` | 否 | 配合 `--name` 做大小写不敏感子串匹配。如 `--name "icon_" --fuzzy` 一次覆盖 `icon_闲置`/`icon_闲置_选中` |
| `--root-ids <id,id,...>` | 否 | 逗号分隔的根画板 nodeId，顺序即输出顺序。省略则扫 `.figma/` 下全部缓存（按画板名排序）。**显式指定的画板未命中即报错退出**，不会静默少比一个画板 |
| `--deep N` | 否 | 名称搜索的树深度上限（根的直接子节点为第 1 层）。默认 0 = 不限。只想比浅层元素（如底部 tab）时用它排除深层同名节点 |
| `--project-root <dir>` | **Agent 必须传** | 项目根（`.figma/` 位置）。同上 |

**`figma_bridge_server.py`**

| 参数 | 必填 | 说明 |
|------|------|------|
| `--port 7789` | 否 | 监听端口 (默认 7789) |

---

## 执行流程（Agent 决策树）

```
用户输入
  |
  0a. [快速 nodeId 探测 — 从用户输入提取 nodeId]
      用户可能说"查看 2:152 样式"、"编组-2[1:783] 内部有切图吗"、"1:200 颜色不对"
      尝试正则提取 `数字:数字` 或 `[数字:数字]` 中的 nodeId：
      - 提取到 nodeId → 检查输入中是否有"查看"/"样式"/"颜色"/"圆角"/"内部"/"切图"/
        "布局有问题"/"不对"等关键词出现在 nodeId 附近（前后 15 字以内）。如果有，标记为
        inspect-node 意图，进入步骤 0b。
      - 提取到 nodeId 但无上述关键词（如"帮我改 2:152"）→ 跳过短路径，
        走标准 0-1-2 流程（意图解析阶段会匹配到相应命令）
      - 未提取到 → 走标准 0-1-2 流程
      ⚠️ 避免将 `数字:数字` 误判为 nodeId：纯数字比例（如"16:9 比例"、"2:1 缩放"）不应触发。
        确认提取的字符串前后文有节点相关语义才继续。

  0b. [inspect-node 子流程 — 按 nodeId 查看节点]
      ① figma_query_node.py --id <nodeId> --find-root --children --deep 2
      ② 有缓存 → 输出节点信息给用户，结束
      ③ 无缓存 → figma_pull.py --node-id <nodeId> --project-root "$(pwd)" （plugin 自动追溯根画板提取）
         → 提示用户"正在从 Figma 拉取设计数据，请稍候（约 10-60 秒）..."
         → 提取完成后，再查 figma_query_node.py --id <nodeId> --children --deep 2
         → 输出节点信息
      ④ 禁止碰项目文件，只读操作

  0c. [跨画板比对子流程 — 用户要对比多个画板的同一处]
      触发："4 个 tab 画板的选中态差异"、"这几个画板同一个图标差在哪"、
            "换切图 + 对比各画板"等涉及 >= 2 个画板同一区域的意图
      ① figma_query_node.py --list-caches [--match <关键词>] --project-root "$(pwd)"
         → 确认参与比对的画板是否都已提取（画板多时用 --match 过滤，避免误判"无缓存"）
      ② 缺画板 → 逐个 figma_pull.py --node-id <rootId> --project-root "$(pwd)" 补齐
      ③ figma_compare_nodes.py --name <关键词> --fuzzy \
           --root-ids <id,id,...> [--deep N] --project-root "$(pwd)"
         → 一次得到 对比表 + 差异摘要 + 内容等价分组
      ④ 判断切图差异一律看内容签名，禁止用 image.file 名字不同推断视觉不同
      ⑤ 校验比对是否真的成立：出现「未形成任何交叉比对」/「仅在 1 个画板命中」/
         「一个同名节点都没命中」时，结论**不完整**，禁止据此报"各画板无差异"或收工——
         先修图层名/--deep/补画板后重跑
      ⑥ 需要单节点下钻时再 figma_query_node.py --id <nodeId> --children --deep N
      ⑦ 禁止用截图目测替代上述结构化对比

  1. [标准流程 — 节点感知] 未触发 inspect-node 时进入：
     检查此会话是否已有锚定 nodeId（来自之前 Step 2 的提取结果）：
     - 有锚定 → 优先用 figma_selected_node.py --node-id <anchor_node_id> --root-id <anchor_root_id>
       （直接从缓存查询，不依赖桥服务器，不受当前 Figma 选中节点影响）
     - 无锚定 → 执行以下子步骤获取当前 Figma 选中节点：

       子步骤 A [连通性]：检查桥服务器是否运行
         curl -s http://localhost:7789/api/plugin-status
         → connected=true 才继续
         → 否则提示用户执行 "start"
         ⚠️ 仅判断连通性，不要从 api/status 或 api/plugin-status 提取 nodeId

       子步骤 B [获取选中]：调 figma_selected_node.py（无参，~3-6s，同步执行）
         这是获取"当前 Figma 光标选中节点"的唯一正确方式。
         timeout=15s；超时或无输出时 curl http://localhost:7789/api/selected-node 兜底
         ⚠️ 禁止从 api/status.node_id 获取选中节点！该字段是"上次提取的画板ID"，
            不是"当前光标选中的节点ID"。两个 API 字段含义不同：
            - /api/status → node_id = 上次提取的画板（历史数据，仅用于诊断）
            - /api/selected-node → rootArtboardId = 当前 Figma 光标选中（实时数据）

       子步骤 C [解析结果]：
         a) selected=true + rootArtboardId 非空 → 拿到 rootArtboardId，强制进入步骤 2
         b) selected=false + stdout 中有缓存 rootArtboardId
            → 提取缓存中的 rootArtboardId，**进入步骤 2**
         c) selected=false + 无缓存 → 提示"请在 Figma 中选中一个画板后回复我"，用户确认后重试
     ⚠️ 多会话场景：如果多个 Claude Code 会话操作不同画板，默认 figma_selected_node.py
        返回的是 Figma 当前选中节点，不是本会话锚定的画板。
  |
  1a. [意图解析 — 综合 Step 0 上下文 + SKILL.md 匹配表]
     a) 读取 SKILL.md「意图匹配」章节获取关键词→命令映射
     b) 综合 Step 0 上下文（画板名、rootArtboardId、缓存状态）消解自然语言指代：
        - "当前选中的设计图"/"这个画板"/"这个设计" → 画板名（Step 0 产出）
        - "生成"/"创建" + 画板名为"首页" → create-page
        - "更新"/"改"/"修改"/"换样式" + 有旧页面路径 → restyle-page
        - "功能没有新增"/"功能不变只改样子" → 强化 restyle-page 信号
     c) 按优先级匹配：
        ① 触发词命中 → 确定命令，读取 commands/<command>.md
        ② 上下文推断 → 综合画板名和用户表述推断，输出推断理由
        ③ 模糊 → 弹菜单一次（列出 STEP0 画板名 + 可用命令），记录后不重复
     d) 将 rootArtboardId 和画板名传递给后续步骤
     e) 产出 implementation_context（页面归属/架构边界/核心交互/数据区域/用户取舍，参考 SKILL.md 步骤 4.5），
        随根画板信息一并传给步骤 5 结构确认——5a 结构化查询与 5b 截图分析（子 agent）均以此为准
  |
  2. [数据就绪] 检查缓存是否存在
     - 缓存完整 + 只看/查 -> 跳过提取，走查询
     - 缓存完整 + 生成/改造 -> 缓存只有本地提取时间、无设计侧版本，机器无法判定"最新"：
       用户未声明设计稿已改时追问一句"设计稿自上次提取后有改动吗"，
       答有改动/不确定 -> --force 重拉；答无 -> 直接走结构确认
     - 缓存缺失 -> Agent 自己调 figma_pull.py --node-id <rootId>
       (从步骤 0 的 rootArtboardId 获取，不需要用户手动切换选中)
       figma_pull.py 默认自己会先查缓存复用（三文件齐全 + 树中含目标节点 + 适配器
       已产出 artboard_width_px），命中即秒级返回；设计稿已更新或怀疑缓存陈旧时
       加 --force 强制重拉。figma_query_node.py --list-caches --project-root "$(pwd)"
       只反映**本地提取时间**，不代表设计侧新鲜度。
       成功 -> 继续
       失败(超时/错误):
         → 按「提取失败快速诊断」表判定：先 curl `/api/plugin-status` 与 `/api/status`
           取 last_seen / ready / extract_last_error，再按表格对应行为处理。
         → 【禁止】读脚本源码诊断。
       失败且未配置 -> 步骤 3 (引导)
  |
  2.5 [保存会话锚定] 提取成功或缓存就绪后，Agent 立即记录锚定信息：
     从 source_meta.json 或 status API 获取当前画板的：
     - node_id（画板 nodeId）
     - name（画板名）
     - 缓存目录路径
     （也可从产物内取：android_tree.json 的 screen.artboard_id / root.node_id。
       figma_query_node.py --root-id 就是拿这两个字段校验的，不再用目录名匹配。）
     ⚠️ 此处使用 api/status.node_id 是**安全的**，因为刚完成提取，
        node_id 必然等于当前画板。Step 0 中禁止使用 api/status.node_id
        是因为那时可能刚启动/有旧缓存，node_id 不等于当前选中。
        关键区别在于**时机**：刚提取后 = 可信；其他时机 = 不可信。
     Agent 在本次会话的后续查询中始终使用 figma_selected_node.py --node-id <node_id>
     或 figma_query_node.py --root-id <node_id>，不再依赖 figma_selected_node.py
     查询当前选中。⚠️ 文件只存本次会话，仅用于同一会话内后续查询，不跨会话持久化。
  |
  3. [首次配置] 仅 pull 失败 + 标记不存在时
   读 commands/start.md（首次配置引导见 start.md 步骤 5）-> 引导 -> touch 标记 -> 回步骤 2
  |
  4. [后续流程] 按意图读取 commands/<command>.md -> SKILL.md 步骤 4-7
     缓存复用检查 -> 结构确认(阻塞) -> 代码生成 -> 编译验证
```

### 缓存快捷路径

| 用户意图 | 缓存存在 | 缓存不存在 |
|---------|---------|-----------|
| "查看选中节点" | 有锚定 → `figma_selected_node.py --node-id <id> --root-id <rootId>`（秒级）<br>无锚定 → `figma_selected_node.py`（查询当前 Figma 选中） | `figma_selected_node.py`（~3-6s 获取节点信息，内部提取被中断无影响）→ 强制进 Step 2 |
| "1:805 布局有问题" (给 nodeId) | `figma_query_node.py --id X --children --deep 2 --find-root` (自动扫描缓存) | Step 0 查选中节点 → 缓存缺失 → Step 2 `figma_pull.py` 提取 |
| "里面有几个切图"/"X 里面是什么" | `figma_query_node.py --id X --children --deep 2 --latest --root-id <rootId>` | Step 2 先提取，再查询 |
| "这个画板有哪些切图"/"切图文件名叫什么" | `figma_query_node.py --assets [--md5] --latest --root-id <rootId>` | Step 2 先提取，再查询 |
| "4 个画板的选中态差在哪"/跨画板对比 | `figma_compare_nodes.py --name <关键词> --fuzzy --root-ids <id,id,...>` | 先 `--list-caches --match` 确认各板已提取 → 缺则逐个 Step 2 提取 → 再比对 |
| "缓存找不到"/"这画板提取过吗" | `figma_query_node.py --list-caches [--match <关键词>]` | 同上，先确认再决定是否提取 |
| "找所有 ImageView" | `figma_query_node.py --type ImageView --children --latest --root-id <rootId>` | Step 2 先提取，再查询 |
| "生成页面"/"改页面" | 读缓存 -> 结构确认 | `figma_pull.py` 提取 |

---

## 提取失败快速诊断

| API 返回值 | 含义 | Agent 行为 |
|-----------|------|-----------|
| `/api/plugin-status` 或 `/api/status` curl 任一失败（connection refused / 无响应 / HTTP 5xx） | 桥服务异常 | → 提示 "start" |
| `last_seen` 距今 <90s（此时 `connected` 通常为 false） | **插件空闲但在线**：iframe 不可见时浏览器把插件轮询节流到约 60s 一次；`connected` 的判定阈值是 5s，故节流态下必为 false，**不代表断开** | → **继续等待**，请求会在插件下一次轮询时被消费，不要提示 "start"；提示用户将 Figma 置于前台可显著加速 |
| `last_seen` 距今 ≥90s 或 `last_seen` 为空 | 插件心跳确已断开（面板未开或已关闭） | → 提示 "start"，或引导用户在 Figma 中打开插件面板 |
| `status.extract_last_error` 非空 | 服务器已记录失败原因 | → 按错误文本引导：文本指向节流 → 提示将 Figma 置于前台；指向提取卡死或版本过旧 → 才提示关闭并重开插件面板 |
| `last_seen` 距今 <90s, `ready` = false, `extract_last_error` 为空 | 插件在线但尚未消费（iframe 被节流 / 残留 pending 占位 409 / 主线程繁忙）。注意 `plugin_iframe_visible` 在节流态下同样为 false，**不可单独据此判断面板未开** | → 等待并重试；提示置 Figma 于前台可加速 |
| `status.ready` = true | 提取已成功完成 | → 继续后续流程 |
| `connected` = true, `status.ready` = true | 提取已成功完成 | → 继续后续流程 |

---

## 禁止行为

- 禁止桥模式中要求用户提供 Figma URL
- 禁止在未收到 composition.json 时伪造 android_tree.json
- 禁止混用 MCP 和桥模式的数据产物
- 禁止在 pull 成功之前执行首次配置引导
- 禁止在意图已解析的情况下重复询问
- 禁止在 pull 之前做预检（figma_pull.py 自带）
- 禁止自行编写 inline Python 或 Shell 查询脚本，始终使用工具箱中的脚本（含 `--assets` 查切图清单、`figma_compare_nodes.py` 做跨画板对比——手工解析 `assets.json` 或逐板 grep 都属于违规）
- 禁止用切图**文件名**不同推断视觉不同：`export_as_image` 节点按节点寻址命名，同一视觉跨画板必然不同名；判断是否同一张图只能看内容签名（`figma_compare_nodes.py` / `--assets --md5`）
- 禁止在读脚本源码（figma_pull.py、figma_selected_node.py、figma_bridge_server.py）中诊断提取失败原因；诊断信息从 `curl http://localhost:7789/api/status` 和 `curl http://localhost:7789/api/plugin-status` 获取
- 禁止在已有锚定 nodeId 的情况下调用 `figma_selected_node.py`（无参版）查询当前选中；有锚定必须用 `--node-id`。否则多会话场景下会读到其他会话的画板
