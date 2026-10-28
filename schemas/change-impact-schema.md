---
name: figma-change-impact-schema
description: 老页面改造影响分析的结构定义（会话内输出），及落任务记忆节的字段映射
---

# Change Impact Schema

老页面改造前必须输出影响分析。本文档定义**分析结构**（会话内输出 + 终端摘要供用户审批，
不全量落盘）；落盘部分的写入与读取约定见 `rules/restyle-guardrails.md`「任务记忆层」。

## 顶层结构

```json
{
  "schema_version": "2.0",
  "page": {
    "page": "HomeFragment",
    "code_entry": "app/src/main/java/.../mod_trade/TradeHomeFragment.kt",
    "host_binding_proof": "app/src/main/java/.../BaseMainActivity.kt:24 setTab(TradeHomeFragment())"
  },
  "figma_source": {
    "fileKey": "string",
    "nodeId": "string"
  },
  "risk_level": "low | medium | high | blocked",
  "target_files": [],
  "referenced_ids": [],
  "protected_views": [],
  "risky_bindings": [],
  "adapter_dependencies": [],
  "forbidden_changes": [],
  "planned_changes": [],
  "compile_risks": [],
  "manual_confirmations": []
}
```

## 字段说明

### `page`

页面归属。**画板名 ≠ 类名**，必须 grep 证明目标页被宿主实际引用后再填：

| 字段 | 说明 |
|------|------|
| `page` | 用户口中的页面名 / 画板名（如"首页"） |
| `code_entry` | 实际承载该页面的 Fragment / Activity / Custom View 文件路径 |
| `host_binding_proof` | **宿主引用证据**（`文件:行号` + 命中的调用形式，如 `setTab(` / 实例化 / Manifest 注册）。找不到证据 → 列入 `manual_confirmations`，不得开改 |

存在同名死代码时，终端摘要显式列「已排除：<文件>（无引用证据）」，并写入任务记忆节
`excluded` 字段——防止后续会话把死代码重新纳入。

真实反例：画板"首页"实际是 `mod_trade/TradeHomeFragment`（`BaseMainActivity.kt` 注册），
app 模块遗留的同名 `HomeFragment` 是死代码；四个 tab 画板有三个类名与画板名不一致。

### `risk_level`

| 值 | 定义 | 行为 |
|----|------|------|
| `low` | 主要是静态样式、尺寸、间距调整 | 可执行，报告风险 |
| `medium` | 涉及局部结构、资源、少量代码引用 | 输出计划后执行 |
| `high` | 涉及 Adapter、复杂绑定、关键 ID 删除或多文件联动 | **必须等待用户确认** |
| `blocked` | 无法定位页面、无法保护逻辑或缺关键输入 | **停止** |

### `target_files`

计划读取或修改的文件：

```json
{
  "path": "app/src/main/res/layout/fragment_home.xml",
  "type": "layout | drawable | source | adapter | viewmodel | other",
  "action": "read | modify | create | delete",
  "reason": "主页面布局"
}
```

### `referenced_ids`

旧布局 ID 引用情况：

```json
{
  "id": "tv_price",
  "declared_in": "app/src/main/res/layout/item_shop.xml",
  "references": [
    {
      "path": "app/src/main/java/.../ShopAdapter.kt",
      "line": 42,
      "usage": "binding.tvPrice.text = item.price"
    }
  ],
  "decision": "keep | migrate | delete | needs_confirm",
  "replacement_id": "tv_subtitle",
  "notes": "设计稿取消价格展示，但代码仍写入价格"
}
```

### `protected_views`

必须保留或兼容的控件：

```json
{
  "id": "btn_submit",
  "reason": "承载点击提交逻辑和埋点",
  "allowed_changes": ["size", "margin", "background", "textColor"],
  "forbidden_changes": ["remove", "rename", "change_click_target"]
}
```

### `risky_bindings` / `adapter_dependencies` / `forbidden_changes`

- `risky_bindings`：`{type, symbol, path, risk, mitigation}`（绑定方式 / 符号 / 文件 / 风险 / 缓解）。
- `adapter_dependencies`：`{adapter, layout, item_types, dependencies, risk}`。
- `forbidden_changes`：`{scope, item, reason}`。

三项均为会话内输出，不落任务记忆节；只把影响后续动作的结论写入 `confirmed` / `excluded`。

### `planned_changes`

计划修改项（**必须标注 diff_type**）：

```json
{
  "file": "app/src/main/res/layout/fragment_home.xml",
  "change": "调整标题栏高度、按钮背景和列表顶部间距",
  "diff_type": "style_update | new_element | removed_element | structural_change | role_change",
  "design_source": "android_tree.<节点路径，如 root/children[2]>",
  "old_element_id": "旧页面中被影响的元素 ID",
  "resource_impact": "none | replace_asset | add_asset | delete_asset | keep_asset",
  "risk": "low | medium | high"
}
```

### `diff_type` 差异分类

取值：`style_update | new_element | removed_element | structural_change | role_change`。
分类判据、默认策略与需用户确认的条件见 `rules/restyle-guardrails.md`「差异分类与默认策略」。

### `resource_impact` 资源影响

| resource_impact | 含义 |
|-----------------|------|
| `none` | 不涉及资源文件变更 |
| `replace_asset` | **保留旧资源名，只替换文件内容**（文件名不变、`@drawable/` 引用不变） |
| `add_asset` | 新增切图或 shape 资源文件 |
| `delete_asset` | 删除切图或 shape 资源文件 |
| `keep_asset` | 不改变资源文件，但不再引用 |

`replace_asset` 是硬规则 9「切图拷贝前必须重命名」的**例外**：重命名针对 Figma 导出名
（hash / `img_<nodeId>` / 无意义名）；替换既有资源时改名会打断所有引用点，必须保留项目原名。
覆盖前按硬规则 8 检查同名引用，多处引用先问用户。判定表见
`rules/resource-naming-rules.md`「替换既有资源」。

### `compile_risks`

编译风险：

```json
{
  "risk": "删除 tv_price 后 ViewBinding 仍生成旧引用",
  "affected_files": ["ShopAdapter.kt"],
  "check": "rg \"tvPrice|tv_price\" app/src/main"
}
```

### `manual_confirmations`

需要用户确认的问题：

```json
{
  "question": "设计稿删除价格字段，是否同步移除价格展示逻辑？",
  "default_action": "保留隐藏控件或设置 gone",
  "required": true
}
```

## 输出分层

**终端摘要（用户当场审批，不落盘）**：

```markdown
- Page / Code Entry / Host Binding Proof: <…>
- Risk Level: low | medium | high | blocked

| File | Change | Diff Type | Resource Impact |
|------|--------|-----------|-----------------|
```

**任务记忆节（落 `figma_task_memory.md`，只存不可重建项）**：`attribution`（← `page`）、
`excluded`（← 排除结论）、`asset_overwrite`（← `replace_asset` 覆盖记录）、
`confirmed`（← `manual_confirmations` 拍板结论）、`build`/`blocker`/`verified_scope`/`open`。
`target_files`/`planned_changes` 等改动清单 git diff 可重建，**不进记忆节**。
节格式与字段约束见 `templates/task_memory.md`。