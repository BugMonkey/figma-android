---
name: figma-android-layout-analysis-schema
description: layout_analysis.json 标准结构，供结构确认环节（步骤 5）产出与消费，按 Figma 桥模式适配。
---

# layout_analysis.json Schema

`layout_analysis.json` 是 figma skill 结构确认环节的核心中间产物：步骤 5b 派发的子 agent 读取截图并回传定性结论，主 Agent 补齐元数据、与 5a 结构化结论合并后写入本文件；主 Agent 读取它 + android_tree.json 综合出结构确认结论。

> 消费方说明：本文件当前**无脚本级机器消费者**，读取方是主 Agent 自身（结构确认 5b→确认摘要）；
> 定位 = 定性结论的结构化沉淀与审计痕迹。若后续要把它纳入跨会话记忆，须先接入
> `figma_task_memory.md` 的读契约，再谈落盘必要性（参照四份旧报告被收敛的判据）。

> ⚠️ 本文件只存**定性结论**（区域划分/容器归属/滚动策略/切图粒度/交互热点）。**精确坐标/尺寸/颜色/层级一律不存本文件**，以 `android_tree.json` 为准（见 `rules/android-tree-guide.md`）。

## 产物位置

```text
<extract_dir>/layout_analysis.json
```

## 顶层结构

```json
{
  "schema_version": "1.0",
  "design_id": "string",
  "confidence": "high | medium | low",
  "layout_summary": "string",
  "screen_type": "fragment | activity | dialog | item | header | footer | unknown",
  "user_intent": {},
  "android_layout_assumptions": [],
  "confirmation_items": [],
  "root_layout_recommendation": {
    "type": "ConstraintLayout | LinearLayout | FrameLayout | NestedScrollView | RecyclerView",
    "reason": "string"
  },
  "sections": [],
  "fixed_regions": [],
  "scroll_strategy": {},
  "element_classification": [],
  "component_groups": [],
  "constraint_hints": [],
  "implementation_hints": [],
  "risk_flags": []
}
```

## 字段说明

### `confidence`

| 值 | 含义 |
|----|------|
| `high` | 截图清晰、android_tree 完整、区域划分无歧义 |
| `medium` | 部分区域需人工确认 |
| `low` | 截图缺失/模糊、结构不确定 |

### `user_intent`

意图先行环节（SKILL.md 步骤 4.5）的产出，作为截图分析上下文。没有用户描述时显式写 `source: "not_provided"`。

```json
{
  "source": "provided | inferred | not_provided",
  "request_summary": "改版 LifeFragment 生活页，功能不变只换样式",
  "requested_screen_type": "fragment | activity | dialog | item | unknown",
  "core_requirements": ["保留广告位", "3 工具卡移顶部"],
  "explicit_inclusions": [],
  "explicit_exclusions": ["底部 Tab（宿主 Activity 已有）"],
  "interaction_requirements": [],
  "data_regions": [],
  "notes": "string"
}
```

### `android_layout_assumptions`

基于 Android 布局常识形成的低风险假设。高风险歧义进 `confirmation_items`。

```json
{
  "id": "assumption_host_tab_outside_fragment",
  "topic": "host_navigation | dynamic_region | root_layout | resource | binding",
  "assumption": "底部 Tab 属于宿主 Activity，不放入 Fragment",
  "reason": "用户请求的是 Fragment，且底部 Tab 通常由宿主容器管理",
  "confidence": "high | medium | low"
}
```

### `confirmation_items`

需要用户确认的高风险歧义。

```json
{
  "id": "confirm_bottom_tab_scope",
  "question": "截图底部 Tab 是否属于宿主 Activity，Fragment 中不生成？",
  "impact": "决定 fragment_life.xml 是否包含底部导航区域",
  "default_when_unanswered": "exclude_from_fragment | include_in_current_layout | blocked",
  "severity": "high | medium | low",
  "resolved": false,
  "answer": ""
}
```

### `sections`

页面区域划分（从上到下）。

```json
{
  "id": "section_header",
  "name": "顶部渐变区",
  "role": "header | content | footer | card | list | form | overlay",
  "y_range_dp": [0, 225],
  "children": ["3 工具卡", "查快递卡"],
  "implementation": "LinearLayout | FrameLayout | ConstraintLayout",
  "notes": "string"
}
```

### `fixed_regions`

固定区域（滚动容器外）。

```json
{
  "id": "bottom_tab",
  "position": "top | bottom | left | right | overlay",
  "reason": "底部 Tab 属于宿主 Activity",
  "scope": "host_layout | current_layout"
}
```

### `scroll_strategy`

滚动策略。

```json
{
  "type": "none | NestedScrollView | RecyclerView | ViewPager2",
  "scroll_region": "section_content",
  "fixed_outside_scroll": ["bottom_tab"],
  "reason": "内容区超屏，广告位插入后可滚动"
}
```

### `element_classification`

元素分类（含切图粒度与交互热点）。

```json
{
  "layer": "视觉描述（图层名无法从截图识别）",
  "id_hint": "iv_check_express",
  "meaning": "查快递大卡片",
  "category": "icons | backgrounds | buttons | images | text | container | divider | input | list",
  "android_view": "ImageView",
  "interactive": true,
  "click_target_hint": "整个卡片可点击",
  "slice_granularity": "full | half_bg | none",
  "has_slice": true,
  "resource_prefix": "img_",
  "implementation_priority": "core | supporting | decorative | host_outside | excluded",
  "scope": "current_layout | host_layout | item_layout | resource_only | unknown",
  "confidence": "high | medium | low",
  "notes": "string"
}
```

#### `slice_granularity`（切图覆盖粒度）

| 值 | 含义 | Android 实现 |
|----|------|-------------|
| `full` | 整张 PNG 覆盖全部视觉（含文字/图标） | 单个 ImageView `fitXY` |
| `half_bg` | 仅背景/容器是切图，文字/图标是独立图层 | FrameLayout：ImageView 底 + TextView/ImageView 叠加 |
| `none` | 纯代码绘制（shape/颜色/文字） | 无切图 |

### `component_groups`

组件分组。

```json
{
  "id": "group_tool_cards",
  "name": "顶部 3 工具卡",
  "role": "card | list_item | toolbar | form_group | action_bar",
  "children": ["大小写", "折扣", "成本"],
  "repeatable": true,
  "recommended_container": "LinearLayout horizontal",
  "scope": "current_layout | host_layout | item_layout | unknown",
  "data_binding_hint": "string"
}
```

### `constraint_hints`

约束建议（定性，不带精确数值）。

```json
{
  "type": "left_align | right_align | top_to_bottom | center_horizontal | baseline_align",
  "source": "iv_local_title",
  "target": "bg_local_card",
  "relation": "title 悬浮于容器上方，重叠区域以 android_tree 坐标验证",
  "confidence": "medium"
}
```

### `implementation_hints`

工程实现建议。

```json
{
  "scope": "xml | resource | binding | adapter | interaction | inset",
  "message": "底部 Tab 属于宿主 Activity，不生成",
  "priority": "high | medium | low"
}
```

### `risk_flags`

风险标记。

```json
{
  "code": "missing_screenshot | missing_visual_review | uncertain_grouping | complex_list | host_navigation_uncertain | dynamic_region_uncertain | inset_uncertain | context_bloat_risk | requires_manual_confirm | short_screen_clip_risk | width_stretch_risk | font_scale_risk | scaled_block_child_drift_risk",
  "severity": "high | medium | low",
  "message": "string",
  "blocked": false
}
```

## 最小有效示例

```json
{
  "schema_version": "1.0",
  "design_id": "生活_9_1223",
  "confidence": "medium",
  "layout_summary": "顶部绿色渐变区（3 工具卡+查快递卡）+ 本地生活宫格区 + 底部宿主 Tab",
  "screen_type": "fragment",
  "user_intent": {
    "source": "provided",
    "request_summary": "生活页改版，功能不变只换样式，广告位保留",
    "requested_screen_type": "fragment",
    "core_requirements": ["保留广告容器", "3 工具卡移到顶部"],
    "explicit_inclusions": ["广告位"],
    "explicit_exclusions": ["底部 Tab"],
    "interaction_requirements": [],
    "data_regions": [],
    "notes": ""
  },
  "android_layout_assumptions": [
    {
      "id": "assumption_fragment_excludes_host_nav",
      "topic": "host_navigation",
      "assumption": "Fragment 布局不包含宿主级底部导航",
      "reason": "用户请求的是 Fragment，底部 Tab 在 activity_main.xml 已有",
      "confidence": "high"
    }
  ],
  "confirmation_items": [],
  "root_layout_recommendation": {
    "type": "NestedScrollView",
    "reason": "内容区（渐变区+广告+宫格）可能超屏，需可滚动"
  },
  "sections": [],
  "fixed_regions": [
    {
      "id": "bottom_tab",
      "position": "bottom",
      "reason": "宿主 Activity 的底部 Tab",
      "scope": "host_layout"
    }
  ],
  "scroll_strategy": {
    "type": "NestedScrollView",
    "scroll_region": "全部内容",
    "fixed_outside_scroll": ["bottom_tab"],
    "reason": "广告位动态插入，内容高度不确定"
  },
  "element_classification": [],
  "component_groups": [],
  "constraint_hints": [],
  "implementation_hints": [],
  "risk_flags": []
}
```
