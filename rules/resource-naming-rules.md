# Resource Naming Rules

## General Rules

- 使用小写字母、数字和下划线
- 禁止中文名
- 禁止无意义导出名
- 覆盖已有资源前必须检查冲突
- 优先语义名，其次视觉名

## Density Directory Rules

| Density | Scale | Directory |
|---------|-------|-----------|
| xxhdpi | 3 | drawable-xxhdpi（推荐默认） |
| xxxhdpi | 4 | drawable-xxxhdpi |

## Prefix Rules

| Prefix | Asset Type | Format | Directory |
|--------|------------|--------|-----------|
| `ic_` | icon | PNG | drawable-xxhdpi |
| `ic_` | icon (简单) | XML (vector) | drawable |
| `bg_` | background | PNG | drawable-xxhdpi |
| `img_` | photo/illustration | PNG | drawable-xxhdpi |
| `shape_` | simple shape | XML | drawable |
| `selector_` | state drawable | XML | drawable |

## Forbidden Names

```text
figma_export_123
icon1
image2
rectangle_1
group_3
新图标
按钮背景
```

Agent 生成页面时，若 `image.file` 落在上述模式或包含 `rectangle` / `group` / `vector` / `unnamed` 等无意义词，应主动重命名为功能性名称（如 `ic_back`、`bg_header`），同步 `mv` 文件并更新 `@drawable/` 引用。

## 替换既有资源（rename 禁令的例外，必须区分）

重命名规则针对的是 **Figma 导出名**（hash / `img_<nodeId>` / 无意义名），不是项目既有资源名。

判定与做法：

| 场景 | 做法 | `resource_impact` |
|------|------|-------------------|
| 目标资源在项目中**已存在**且语义不变（同一位置、同一用途，只是图案/内容变了） | **保留项目原文件名，直接覆盖文件内容**；文件名不变，`@drawable/` 引用不变 | `replace_asset` |
| 目标资源不存在，或既有资源语义不同（不同用途） | 按 Prefix Rules 起新名，新增文件 | `add_asset` |
| Figma 导出名是 hash / `img_<nodeId>` / 无意义名，且要落到新资源 | 必须重命名（即下方 Forbidden Names 规则） | `add_asset` |

替换既有资源的具体约束：

1. 覆盖前按硬规则 8 检查同名引用：既有资源被**多处**引用时先问用户（换内容会影响所有引用点）。
2. 保留原文件名意味着**不 `mv`、不改 XML 引用**——改名会同时打断所有引用点，是破坏性操作。
3. 覆盖前确认新图与旧图用途一致（同为底图/同为图标），尺寸差异大时同步更新 `layout_width` / `layout_height`。
4. 在影响分析的 `planned_changes` 中标注 `resource_impact=replace_asset`，
   并在任务记忆节（`figma_task_memory.md`）`asset_overwrite` 字段记录被覆盖的旧文件（回滚账本）。

> 交叉引用：`schemas/change-impact-schema.md` 的 `resource_impact` 字段定义了五值语义；
> `rules/restyle-guardrails.md`「替换背景切图」给出了 restyle 场景的执行细则。

## Conflict Handling

1. 检查已有资源是否等效
2. 等效 → 复用
3. 不等效 → 创建更具体的名字
4. 冲突与处理结果在终端摘要说明；涉及覆盖既有资源的写入任务记忆节 `asset_overwrite` 字段

## Export Format Selection

| Asset Type | Recommended Format |
|------------|-------------------|
| 图标 | PNG（Figma exportAsync 直接导出 @3x，无 SVG 中间态） |
| 背景图片 | PNG @ 3x |
| 插画/照片 | PNG @ 3x |
| 简单形状 | XML shape |
