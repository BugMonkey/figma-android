---
name: figma-slice-atomic-rules
description: Android XML 中对切图资源的原子化处理规则
---

# 切图原子化规则

## 核心原则

`assets.json` 中标记的每个切图资源对应一个独立的视觉区域。
在 Android XML 中，该区域使用一个 `ImageView` 整体展示，不再拆解切图内部的文字、图标或装饰细节。

## 识别规则

检查 `android_tree.json` 中元素的 `image` 字段：
- 有 `image` → 该元素使用切图资源
- `android_class` 为 `ImageView` → 生成独立 ImageView

## XML 生成规则

### 生成单个 ImageView（标准）

```xml
<ImageView
    android:id="@+id/ivHeader"
    android:layout_width="360dp"
    android:layout_height="196dp"
    android:scaleType="fitXY"
    android:src="@drawable/bg_header" />
```

### 生成单个 ImageView（含 imageTransform）

`image.transform` 存在且非单位矩阵时，按 `rules/android-layout-rules.md` §1.3 选择 `scaleType`。

尺寸来源：
```text
layout_width = android_tree.json dp.width
layout_height = android_tree.json dp.height
```

### 忽略内部细节

有 `image` 字段的元素内部不得继续生成：
- 内部 TextView
- 内部 ImageView
- 内部 shape 背景
- 内部分割线或装饰 View

这些细节已存在于导出的切图中，重复生成会造成视觉重影和点击区域混乱。

## 与视觉分组规则的关系

`rules/visual-grouping-rules.md` 用于修复无切图区域的混乱图层。
同一区域同时满足两者时，优先使用切图原子化。

## 切图内文字

`[IMG]` 节点整张是切图，但 PNG 里可能包含成行文字（常见于推荐问题、活动条、按钮文案）。
文字被烘焙进图片会导致无法改文案、无国际化、无读屏语义。出现以下信号时先向用户确认是否用
TextView 重建：

- 切图尺寸接近整行/整卡宽度，明显大于同类图标
- 图层名含「推荐 / 提示 / 文案 / 按钮」等语义，且 `android_tree` 中该区域没有独立 TextView
- 用户要求改文案或做多语言

纯装饰性插画、艺术字保持切图，不做拆分。

## 禁用行为

- 禁止对含 `image` 字段的元素内部继续生成子 View
- 禁止因为切图上有文字就尝试用 XML 重新排版
- 禁止同时使用切图图片和内部元素造成重复显示

---

## 图片框 + 图片扁平化

Figma 中图片常有两层：
- 底层：纯色背景框（占位图），可能有圆角
- 顶层：图片内容

Android 中**合并为单个 ImageView**，不要生成 FrameLayout 嵌套。

### 识别规则

以下情况属于同一张图，不拆两层：

- 一个纯色/圆角矩形背景，内部有一个 `ImageView`（fill），且两者尺寸相同
- 背景和图片 bounds 完全重合，背景只是占位/兜底用途
- 背景有 `corner_radius_dp`，图片无

### 正确写法

```xml
<!-- 合并后：单个 ImageView -->
<ImageView
    android:id="@+id/ivCover"
    android:layout_width="146.7dp"
    android:layout_height="146.7dp"
    android:scaleType="centerCrop" />
```

圆角和占位图通过加载库处理——Glide 的 `placeholder()` + `transform(RoundedCorners())`，或用 `clipToOutline` + `ViewOutlineProvider`。

### 禁止写法

```xml
<!-- 错误：FrameLayout 嵌套是冗余的 -->
<FrameLayout
    android:layout_width="146.7dp"
    android:layout_height="146.7dp"
    android:background="@drawable/bg_placeholder">
    <ImageView
        android:layout_width="match_parent"
        android:layout_height="match_parent"
        android:scaleType="centerCrop" />
</FrameLayout>
```

FrameLayout 的 `background` 圆角不会裁剪子 View，图片加载后直角图会压住圆角背景——圆角形同虚设。
