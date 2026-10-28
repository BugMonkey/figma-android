# inspect-node — 按 nodeId 查看节点详情

匹配："查看 \<nodeId\> 样式/颜色/圆角"、"XX[\<nodeId\>] 内部有切图吗"、"\<nodeId\> 布局有问题"

## 常用对话示例

| 用户说 | Agent 行为 |
|--------|-----------|
| "查看 2:152 样式" | 解析 nodeId=2:152 → 查缓存 → 返回样式 |
| "编组-2[1:783] 内部有切图吗" | 解析 nodeId=1:783 → 查缓存 → 返回子节点列表 |
| "1:200 颜色不对" | 解析 nodeId=1:200 → 查缓存 → 返回背景/文字颜色 |

## 步骤

### 1. 解析 nodeId

用户输入可能格式：
- `"查看 2:152 样式"` → 正则提取 `2:152`
- `"编组-2[1:783] 内部有切图吗"` → 提取括号内 `1:783`
- `"1:200 颜色不对"` → 提取 `1:200`

### 2. 查询缓存

```bash
# 查缓存，自动定位所属画板
python3 scripts/bridge/figma_query_node.py --id <nodeId> --find-root --children --deep 1
```

- 有缓存 → 直接输出节点信息给用户
- 无缓存 → 走步骤 3

### 3. 无缓存时拉取

```bash
# --node-id 支持子节点 ID，plugin 自动追溯根画板提取
# --project-root 必传：会话工作目录（.figma/ 缓存落盘位置），见 bridge-execution.md「调用约定」
python3 scripts/bridge/figma_pull.py --node-id <nodeId> --project-root "$(pwd)"
```

**拉取期间的用户提示**：

Agent 必须先告知用户等待，再执行拉取（非异步）：

```
"正在从 Figma 拉取设计数据，请稍候（约 10-60 秒）..."
```

拉取时间取决于画板复杂度。如果超时（脚本内部等待 240s，Bash timeout 须 ≥300s），按 `bridge-execution.md` 决策树步骤 2 诊断。

提取完成后，再查缓存：

```bash
python3 scripts/bridge/figma_query_node.py --id <nodeId> --children --deep 2 --find-root --project-root "$(pwd)"
```

### 4. 输出信息给用户

输出内容至少包含：
- 节点路径（所属画板 > ... > 节点名）
- view_type 和 android_id
- dp 坐标和尺寸
- 样式（背景色、圆角、文字颜色、字号等）
- 是否含切图 [IMG]
- 是否含文本 [TEXT]
- 子节点列表（有的话）

## 禁止

- 禁止无缓存时直接报错，应尝试拉取
- 禁止拷贝切图到 app 目录（只读操作）
- 禁止修改任何项目文件
