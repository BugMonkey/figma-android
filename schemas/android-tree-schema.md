---
name: figma-android-tree-schema
description: android_tree.json 标准结构，从 figma_bridge_to_android.py 实际产出整理
---

# android_tree.json Schema

`android_tree.json` 是 `figma_bridge_to_android.py` 的产物，定义了 Figma 设计转换为 Android 语义树的结构。

## 来源

```text
raw/composition.json（Figma 插件经桥服务器落盘）
  ↓ figma_bridge_to_android.py
android_tree.json
```

## 顶层结构

```json
{
  "schema_version": "2.0",
  "screen": {
    "width_px": 1080, "width_dp": 360.0,
    "height_px": 2400, "height_dp": 800.0,
    "scale": 3,
    "artboard_width_px": 1080,
    "artboard_id": "1:2"
  },
  "root": {},
  "regions": [],
  "repeat_groups": [],
  "colors": {},
  "texts": []
}
```

## 字段说明

### `screen`（必须）

画板尺寸与换算基准（与 `figma_bridge_to_android.py` 实际产出一致）：

| 字段 | 说明 |
|------|------|
| `width_px` / `height_px` | 提取根像素尺寸 |
| `width_dp` / `height_dp` | 换算后的 dp 尺寸（校验器检查 `width_px / scale ≈ width_dp`） |
| `scale` | Figma px → Android dp 换算因子（xxhdpi=3） |
| `artboard_width_px` | **真实根画板宽度**：dp 换算基准，也是"当前版适配器产物"的复用门槛标记；缺失 = 旧适配器，禁止复用 |
| `artboard_id` | 根画板节点 id |

注意：`density` / `coordinate_scale` **不在 android_tree 中**，它们在 `source_meta.json`
（`design.density` / `design.coordinate_scale`）。

### `root`（必须）

根节点结构，也是全树入口。所有子节点递归嵌套。

### `regions`

视觉区域划分（由 figma_bridge_to_android.py 自动识别）：

```json
[
  {
    "id": "region_header",
    "name": "标题栏区",
    "y_range": [0, 44],
    "children": []
  }
]
```

### `colors`

从设计稿中提取的颜色 Token 映射：

```json
{
  "#f5f6fa": "bg_page",
  "#050506": "text_primary"
}
```

### `texts`

全量文本元素索引（Agent 可快速查询页面文本内容）：

```json
[
  {
    "node_id": "1:2702",
    "android_id": "tv_1450_1_2702",
    "text": "大家都在买"
  }
]
```

---

## 节点结构

`root` 和 `children` 中的每个节点遵循统一结构：

```json
{
  "node_id": "1:2680",
  "name": "首页",
  "view_type": "FrameLayout | View | TextView | ImageView",
  "android_id": "fl_首页_1_2680 | view_shape_1_2680 | tv_标题_1_2702 | iv_头像_1_2705",
  "dp": {
    "x": 0.0,
    "y": 0.0,
    "w": 360.0,
    "h": 800.0
  },
  "dp_local": {
    "x": 0.0,
    "y": 0.0,
    "w": 360.0,
    "h": 800.0
  },
  "style": {},
  "image": {},
  "text": "",
  "children": []
}
```

### 字段说明

| 字段 | 必须 | 类型 | 说明 |
|------|------|------|------|
| `node_id` | 是 | string | Figma 节点 ID，如 `"1:2680"`，用于追溯 |
| `name` | 是 | string | Figma 图层名（可能无意义，仅供追溯） |
| `view_type` | 是 | string | Android View 类型映射 |
| `android_id` | 是 | string | Android 资源 ID，前缀指示语义类型 |
| `dp` | 是 | object | **绝对坐标**（相对画板原点），含 x, y, w, h |
| `dp_local` | 是 | object | **局部坐标**（相对父容器），含 x, y, w, h |
| `style` | 否 | object | 视觉样式（背景、字号、圆角、描边等） |
| `image` | 否 | object | 切图引用（src + file） |
| `text` | 否 | string | 文本元素的文字内容 |
| `visible` | 否 | boolean | Figma 节点的 visible 属性，省略或 true 表示可见 |
| `children` | 否 | array | 子节点递归 |

### `dp` 和 `dp_local`

```json
{
  "x": 0.0,
  "y": 0.0,
  "w": 360.0,
  "h": 800.0
}
```

| 字段 | 单位 | 说明 |
|------|------|------|
| `x` | dp | 左上角 x 坐标 |
| `y` | dp | 左上角 y 坐标 |
| `w` | dp | 宽度 |
| `h` | dp | 高度 |

**dp 值已完成 px ÷ coordinateScale 换算，禁止二次换算。**

| 场景 | 使用 |
|------|------|
| ConstraintLayout 根布局 | `dp.x` / `dp.y` → `marginStart` / `marginTop` |
| FrameLayout / LinearLayout 嵌套 | `dp_local.x` / `dp_local.y` → 相对父容器偏移 |
| ImageView 尺寸 | `dp.w` / `dp.h` → `layout_width` / `layout_height` |

### `view_type` → Android View 映射

| view_type | Android View | 使用场景 |
|-----------|-------------|---------|
| `ImageView` | `ImageView` | 有 `image` 字段的元素 |
| `TextView` | `TextView` | 有 `text` 字段的元素 |
| `View` | `View` | 纯装饰形状，用 `android:background` 上色 |
| `FrameLayout` | `FrameLayout` | 容器，用于层叠多个子元素 |

### `android_id` 前缀约定

| 前缀 | 含义 | 示例 |
|------|------|------|
| `fl_` | FrameLayout 容器 | `fl_首页_1_2680` |
| `ll_` | LinearLayout | `ll_列表_1_2690` |
| `cl_` | ConstraintLayout | `cl_卡片_1_2700` |
| `rv_` | RecyclerView | `rv_列表_1_2710` |
| `tv_` | TextView | `tv_标题_1_2702` |
| `iv_` | ImageView | `iv_头像_1_2705` |
| `view_shape_` | 装饰形 View | `view_shape_1_2681` |
| `view_` | 其他类型 | `view_1_2682` |

根节点与其他节点一样走 `make_android_id()`，没有固定的 `root` ID。

---

## `style` 字段

```json
{
  "background": "#f5f6fa",
  "gradient_colors": ["#FFFFFF", "#F5F6FA"],
  "corner_radius_dp": 10.0,
  "font_size_sp": 16.0,
  "font_family": "PingFang_SC:Semibold",
  "text_color": "#050506",
  "border_color": "#E5E5E5",
  "border_width": 1.0,
  "border_style": "solid",
  "opacity": 0.8,
  "flex_dir": "vertical"
}
```

| 字段 | 单位 | 说明 |
|------|------|------|
| `background` | hex | 背景色，如 `"#f5f6fa"`；渐变时取首个色标（完整色标见 `gradient_colors`） |
| `gradient_colors` | array | 渐变各色标（hex），存在时同时置 `background_is_gradient: true` 与 `gradient_positions`。**查询节点的渐变必须读本字段**，只看 `background` 会丢掉渐变 |
| `corner_radius_dp` | dp | 圆角半径，保留设计稿小数 |
| `font_size_sp` | sp | 字号 |
| `font_family` | - | 字体（PingFang_SC:Regular / Medium / Semibold） |
| `font_weight` | - | Figma fontWeight 数值（400 / 500 / 600 / 700） |
| `text_style` | - | Android textStyle 映射（normal / bold / italic） |
| `text_color` | hex | 文字颜色 |
| `border_color` | hex | 描边颜色（Figma `strokes`）。**线性图标/描边形状的唯一颜色来源**，不会出现在 `background` |
| `border_width` | dp | 描边宽度（Figma `strokeWeight` 已换算）。画描边时与 `border_color` 配对使用 |
| `opacity` | - | 节点不透明度（0~1），<1 时存在该字段，生成时映射为 `android:alpha` |
| `border_style` | - | 描边样式（solid / none） |
| `flex_dir` | - | 自动布局方向（vertical / horizontal） |
| `effects` | array | 阴影/模糊效果列表，含 `type`/`offset_x`/`offset_y`/`radius`/`spread`/`color` |
| `shadow_padding` | object | 阴影烘焙偏移补偿 `{left,right,top,bottom}`（dp），仅 DROP_SHADOW 存在 |

`background_is_image`（bool）与 `image_hash`（string）在背景是 IMAGE fill 时存在；`auto_layout` /
`item_spacing` / `padding` / `primary_align` / `counter_align` 反映 Figma 自动布局；
`text_align` / `line_height_px` / `text_auto_resize` 为文本相关样式。完整键集合以
`figma_bridge_to_android.py` 实际产出为准。

**所有颜色、字号、圆角值必须从此字段精确提取，禁止凭截图目测。**
`background` / `gradient_colors` / `text_color` / `corner_radius_dp` / `font_size_sp` /
`border_color` / `border_width` / `opacity` 已由 `figma_query_node.py` / `figma_selected_node.py`
直接打印（见 `rules/android-tree-guide.md`），**不需要、也不允许自行解析 JSON**。

### `shadow_padding` 用法

Figma 的 `exportAsync` 会把 DROP_SHADOW 烘焙进导出的 PNG，导致导出图比节点几何尺寸大、内容在图内产生偏移。`shadow_padding` 记录各方向阴影扩展量（已换算为 dp），供正确设置 View 尺寸/边距。

**ImageView（切图节点，`export_as_image=true`）**：导出的 PNG 已含阴影，ImageView 必须容纳完整图像：

```xml
<!-- ImageView 尺寸 = 几何尺寸 + 阴影 padding -->
<!-- 负 margin 保持视觉位置与设计稿一致 -->
<ImageView
    android:layout_width="{dp.w + pad.left + pad.right}dp"
    android:layout_height="{dp.h + pad.top + pad.bottom}dp"
    android:layout_marginStart="-{pad.left}dp"
    android:layout_marginTop="-{pad.top}dp"
    android:src="@drawable/{file}"
    android:scaleType="center" />
```

**容器节点（FrameLayout 等非切图）**：阴影不烘焙进图，用 Android 原生 `elevation`：

```xml
<FrameLayout
    android:layout_width="{dp.w}dp"
    android:layout_height="{dp.h}dp"
    android:elevation="{effects[0].radius / SCALE}dp"
    android:background="@drawable/card_bg" />
```

---

## `image` 字段

```json
{
  "src": "plugin://92da4168cb1ad6610ab8748b09a6a229ddd8a25e",
  "file": "img_92da4168cb1a.png",
  "transform": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
}
```

| 字段 | 说明 |
|------|------|
| `src` | 切图来源标识（`plugin://{imageHash}`） |
| `file` | 切图文件名，对应 `drawable-xxhdpi/` 下的 PNG（产物不含 SVG） |
| `transform` | 可选。2×3 仿射变换矩阵 `[[a, b, c], [d, e, f]]`，对应 Figma IMAGE fill 的 `imageTransform`。不存在或否单位矩阵时省略。见 `rules/android-layout-rules.md` 的 imageTransform 转换规则。 |

有 `image` 字段的元素，XML 只生成一个 ImageView。内部不拆解 TextView / ImageView / shape。

---

## 硬规则

- `schema_version` 必须为 `"2.0"`。
- `dp` / `dp_local` / `style` 中的数值已完成 dp/sp 换算，Agent 直接使用，禁止二次换算。
- `children` 数组顺序 = 从底到顶的绘制顺序（z-order）。
- `node_id` 用于追溯 Figma 原始数据，不作 Android 资源 ID 使用。
