
# Android 布局规则

## 核心原则

**不要直接镜像 Figma 的图层嵌套层级。** `android_tree.json` 是 normalize 阶段的产物，所有 dp/sp 值已完成换算（`dp.x/y/w/h`、`dp_local.*`、`style.font_size_sp`、`style.corner_radius_dp`），**直接使用，禁止二次换算，也不要用 `px` 字段生成 XML**。切图节点的 `dp.w/h` 已按 PNG 实测像素回写，直接使用。字号用 `sp`，圆角保留小数（如 `9.7dp`），字号可整数优先；原始像素值仅在追溯时查 `px` / `source_meta.json`。

Figma 图层树 ≠ Android View 树。生成 XML 时必须按视觉归属和交互语义重建结构，**注意布局xml的写法规范**（详见 `rules/visual-grouping-rules.md`）。

---

## 1. Figma → Android 映射

### 1.1 自动布局 → ViewGroup

```text
Figma 自动布局（纵向）  → LinearLayout vertical 或 ConstraintLayout 区域
Figma 自动布局（横向）  → LinearLayout horizontal 或 ConstraintLayout 行
复杂叠层                → （child<3）FrameLayout 或 ConstraintLayout
重复列表                → RecyclerView（3+ 相似项触发）
可滚动内容              → NestedScrollView 或 RecyclerView
```


### 1.2 android_class → View 类型

| android_class | Android View | 使用场景 |
|--------------|-------------|---------|
| `ImageView` | `ImageView` | 有 `image` 字段的元素 |
| `TextView` | `TextView` | 有 `text` 字段的元素 |
| `View` | `View` | 纯装饰形状，用 `android:background` 上色 |

### 1.3 imageTransform → ImageView scaleType / Matrix

`android_tree.json` 中 `image.transform` 是可选字段（2×3 仿射矩阵 `[[a,b,c],[d,e,f]]`），不存在或为单位矩阵时按无变换处理。

#### 取值判定与映射

| image.transform | 图意 | Android ImageView 方案 |
|----------------|------|----------------------|
| 无 / 单位矩阵 `[[1,0,0],[0,1,0]]` | 图片填满节点，无额外变换 | `android:scaleType="fitXY"` |
| 均匀缩放 `[[s,0,c],[0,s,f]]` 且 `s>1` | 图片被裁剪放大（`s>1`→局部） | `android:scaleType="centerCrop"` |
| 均匀缩放 `[[s,0,c],[0,s,f]]` 且 `s<1` | 图片等比缩小居中 | `android:scaleType="fitCenter"` |
| 仅平移 `[[1,0,dx],[0,1,dy]]` | 图片整体偏移 | `android:scaleType="center"` + 正负 margin 微调 x/y |
| 非均匀缩放 `[[sx,0,dx],[0,sy,dy]]` 且 `sx≠sy` | 图片被拉伸变形 | `android:scaleType="fitXY"` + 代码 `View.setScaleX/Y` |
| 含旋转 `[[a,b,c],[d,e,f]]` 且 `b≠0` | 图片被旋转裁剪 | `android:scaleType="matrix"` + 代码 `imageMatrix`（见下方） |

#### 含旋转时代码示例

```kotlin
val matrix = Matrix()
// imageTransform = [[a,b,c],[d,e,f]]
// Android Matrix = [a, b, 0, c]  ← 3×3 齐次矩阵第三列固定
//                   [d, e, 0, f]
//                   [0, 0, 1, 0]
matrix.setValues(floatArrayOf(
    a, b, 0f, c,
    d, e, 0f, f,
    0f, 0f, 1f, 0f
))
imageView.scaleType = ImageView.ScaleType.MATRIX
imageView.imageMatrix = matrix
```

### 1.4 字体映射

```
xxxRegular   → android:fontFamily=""（不写，用系统默认）
xxxMedium    → android:fontFamily="sans-serif-medium"
PxxxSemibold  → android:textStyle="bold"
```


---

## 2. 坐标系统

每个元素有**两套坐标**：

| 场景 | 使用 |
|------|------|
| ConstraintLayout 根布局 | `dp.x` / `dp.y` → `marginStart` / `marginTop`，**仅限叠放与锚定关系**（背景层、悬浮角标、贴边元素） |
| FrameLayout / LinearLayout 嵌套 | `dp_local.x` / `dp_local.y` → 相对父容器偏移，同样仅限叠放与锚定 |
| 尺寸 | `dp.w` / `dp.h` → `layout_width` / `layout_height` |

**纵向先后排列的内容不要逐块写绝对 `marginTop`**：先按视觉归组为流式容器（LinearLayout，或带链的 ConstraintLayout），容器内只写相邻间距，容器整体位置用居中 / 顶锚 / 底锚表达。`dp.y` 的绝对值只用于重叠与贴边；同一布局里绝对定位的区块数量应与重叠组数一致，多出来的就是没做归一化。

### 铺满判定（简单粗暴）

写布局时看到 `dp.w` 不要直接抄固定宽度。先算左右边距：

```
左边距 = dp.x
右边距 = 父容器宽 − (dp.x + dp.w)
```

**一条直觉**：左右边距差不多（差 ≤ 3dp），且元素够宽（≥ 父宽一半）— 设计意图就是"两边留固定边距，中间撑满"。用 `match_parent` + margin 或 `0dp` + 两端约束，别写死宽度。

| 直觉 | 反面直觉 |
|------|---------|
| 父 360, x=30, w=300 → 左右各 30，铺满，不写 300dp | 父 360, x=130, w=100 → 左右各 130，居中窄元素，写死 100dp |
| 父 360, x=16, w=328 → 左右各 16，铺满，不写 328dp | 父 360, x=0, w=344 → 左 0 右 16，不对称，写死 344dp |
| 父 360, x=−10, w=380 → 超出边界了，用 match_parent 0 margin | |

**代码怎么写**：

- ConstraintLayout → `android:layout_width="0dp"` + 两端 `_toStartOf/_toEndOf` + margin
- LinearLayout / FrameLayout → `android:layout_width="match_parent"` + margin
- 左右边距相等时 → 用 `android:layout_marginHorizontal="<边距>dp"`
- 负边距 → 钳位到 0，直接用 `match_parent`

### 间距计算

元素之间的间距 = 后元素 `dp.x` − 前元素 `(dp.x + dp.w)`。**必须从坐标差值计算，禁止目测给近似整数**。

### merged_from

子节点可能携带 `merged_from: ["1:575"]`，表示它在 Figma 中被无意义包装容器包裹，但已合并掉，现在是直接子节点。

---

## 3. 样式数据源

每个元素的 `style` 字段包含设计稿中的所有视觉属性。**所有颜色、圆角、字号值必须从此字段精确提取，禁止凭截图目测或凭感觉取整**。

| style 字段 | Android 属性 | 注意事项 |
|-----------|-------------|---------|
| `font_size_sp` | `android:textSize` | 直接写入值，如 `12sp` |
| `text_color` | `android:textColor` | 提取为 `@color/xxx` |
| `background` | `android:background` | **只用 `android:` 前缀，禁止 `app:background`** |
| `background_is_gradient` | gradient drawable | 生成 XML gradient |
| `corner_radius_dp` | shape `android:radius` | **保留小数**，如 9.7 就写 9.7dp，禁止取整为 10dp |
| `opacity` | `android:alpha` | 节点不透明度（0~1），如 `0.5` 写 `android:alpha="0.5"`。不存在该字段则不写。注意：`android:alpha` 会影响子 View，容器节点有 opacity 时优先考虑在父容器上设置，或对每个子 View 分别设置。 |
| `border_color` | stroke drawable | 直接提取颜色值 |

---

## 4. 切图处理

有 `image` 字段的元素，XML 只生成一个 ImageView。**内部不拆解** TextView / ImageView / shape，这些细节已在切图中。

此外，**无 `image` 字段也可能需要扁平化**：Figma 中「圆角背景框 + 内容图片」两层结构，Android 中合并为单个 ImageView（圆角和占位通过加载库处理），不生成 FrameLayout 嵌套。详见 `rules/slice-atomic-rules.md`。

### 4.0 尺寸策略

| 图片内容 | layout_width / layout_height |
|----------|------------------------------|
| 图标/静态切图（drawable-xxhdpi PNG） | wrap_content / wrap_content |
| 背景/整卡切图（铺满容器） | 宽度随容器、高度保持原图比例（`adjustViewBounds` 或 ConstraintLayout `dimensionRatio`）；容器与切图比例不一致时禁止 `fitXY`（会横向拉伸），改用等比缩放或可拉伸资源（shape / 9-patch） |
| 动态填充（Glide/Coil 网络图、头像） | 固定尺寸（如 60.7×61dp） |

判断：src 是 drawable 切图 → wrap_content；src 被代码动态替换为网络图 → 固定尺寸。


### 4.01 自适应布局

| 场景 | 写法 |
|------|------|
| 横向一排等分 | 外层 LinearLayout horizontal + paddingHorizontal 固定边距 + 子项 width="0dp" weight="1" |
| 铺满宽度 | match_parent + 对称 margin（左右边距相近用 layout_marginHorizontal） |
| 顶部背景 + 内部定位元素 | 背景图放底层（见 4.0），**仅锚定到该背景的元素**用 layout_gravity + marginTop 叠放；背景等比缩放时内部元素按重力/百分比跟随，不用屏幕绝对坐标 |
| 组合块（卡面 + 缎带 + 文字等多层切图） | 外层固定比例容器（`dimensionRatio` 或设计尺寸），内部再叠放；整体随宽度缩放，禁止每层各自 match_parent + 固定高 + fitXY |
| 内容超屏 | 根 NestedScrollView，底部固定按钮不放滚动容器 |

### 4.1 切图缺失处理

桥模式中所有切图由 Figma 插件直接导出，不存在 sprite 裁剪问题。如果 `assets.json` 中列出的切图在 `drawable-xxhdpi/` 中找不到，直接报给用户说切图缺失，不要自己用 python/PIL 裁切（缩放因子不匹配会产生错位）。

---

## 5. z-order

`children` 数组顺序 = 从底到顶的绘制顺序。XML 中按此顺序声明视图即可。

---

## 6. 重叠区域处理

当子元素 y 范围落在容器背景范围内时，归入该容器。容器用 FrameLayout 实现层叠（背景 + 内容层分离）。

---

## 7. 重复列表项

3 个以上结构相同（相同 android_class、相同子元素布局、仅 y 坐标和文字不同）的元素 → 抽取为 `item_xxx.xml`，主布局用 `<include>` 引用。

---

## 8. `tools:` 命名空间

生成的布局加上 `tools:` 属性，让 Android Studio 预览能看到内容：

```xml
<!-- 根布局加上 -->

<!-- 给 RecyclerView 指定预览列表和条目数 -->
tools:listitem="@layout/item_xxx"
tools:itemCount="5"

<!-- 给 TextView 设置预览文字（不占真数据） -->
tools:text="预览文字"

<!-- 给 ImageView 设置预览图片 -->
tools:src="@drawable/img_xxx"
```

`tools:` 属性只在 IDE 预览时生效，不影响真机运行。加了可以让开发者在 Android Studio 中立刻看到效果，不用跑一遍项目。

## 9. 编译前检查清单

重点查会崩的，目测偏差交给开发者自己调：

1. 所有 `android:src` 引用的 drawable 是否确实存在于 `drawable-xxhdpi/`
2. `colors.xml` / `dimens.xml` / `strings.xml` 中所有被引用的值是否已定义
3. `android:id` 是否重复
4. `tools:listitem` / `tools:itemCount` 的 layout 文件是否存在
5. 重叠区域的 z-order 是否正确（XML 声明顺序 = children 数组顺序）

### 9.1 自适应自检（交付前必过）

参考屏：宽 320 / 360 / 411dp，高 640dp，字体放大 1.3 倍。逐 artifact（页面、每个弹窗/浮层、每个列表 item）检查：

1. **短屏不裁切**：640dp 高下内容完整可见，或已明确声明可滚动；
2. **切图不变形**：全宽切图在 320 / 411dp 宽下保持原图长宽比；
3. **热区跟随**：点击区域与其视觉目标同容器、同源定位，不随屏幕宽度漂移；
4. **文本可更新**：会随数据变化的文本是独立 TextView，未烘焙进切图。

任一不满足即为交付缺陷，不允许以「目测没问题」放行；确实不适用时在摘要注明原因，不写死结论。

---

## 10. 编译验证

```bash
./gradlew assembleDebug
```

失败时逐个修复，重复直到通过或 `blocked`。

## 11. 设计稿状态栏与沉浸式

`android_tree.json` 的坐标原点 = 画板顶部（含设计稿中被过滤的模拟状态栏区域前的位置），
状态栏节点本身不进树。生成布局时按背景是否延伸到状态栏下分流：

| 设计稿情况 | Android 处理 |
|-----------|-------------|
| 背景色/背景图全屏延伸到状态栏下 | 沉浸式（透明状态栏），直接使用 `android_tree` 绝对坐标，不要再额外加状态栏高度 |
| 背景从状态栏下方开始、页面使用系统默认状态栏 | 非沉浸式，内容坐标需要下移系统状态栏高度 |
| 不确定 | 按项目既有方案处理（宿主 CLAUDE.md 或现有页面），不要自行假设 |

**不要假设系统状态栏高度等于设计稿里的 24dp**：不同设备/刘海屏/手势导航差异很大。
状态栏与导航栏适配优先复用宿主项目已有方案，不要手写固定 padding。

## 12. 资源输出结构

```text
app/src/main/res/layout/<page>.xml
app/src/main/res/drawable/*.xml            (shape/gradient)  **angle属性必须45的倍数**
app/src/main/res/drawable-xxhdpi/*.png
app/src/main/res/values/colors.xml
app/src/main/res/values/dimens.xml
```
