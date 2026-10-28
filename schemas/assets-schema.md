---
name: figma-android-assets-schema
description: assets.json 标准结构（figma_bridge_to_android.py 实际产出）
---

# assets.json Schema

## 用途

记录画板切图资源清单，由 `figma_bridge_to_android.py` 自动生成，位于 `<extract_dir>/figma_extract_prepared/assets.json`。

## Schema 结构（与适配器实际产出一致）

```json
{
  "schema_version": "1.0",
  "assets": [
    {
      "name": "Avatar",
      "file": "img_92da4168cb1a.png",
      "src": "plugin://92da4168cb1ad6610ab8748b09a6a229ddd8a25e",
      "node_id": "1:156",
      "w": 34.0,
      "h": 34.0,
      "format": "png"
    }
  ]
}
```

## 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Figma 图层名 |
| `file` | string | 切图文件名，位于 `drawable-xxhdpi/` 下（PNG） |
| `src` | string | 切图来源标识（`plugin://{imageHash}`） |
| `node_id` | string | Figma 元素节点 ID |
| `w` / `h` | number | dp 尺寸（已按 PNG 实测像素由 `figma_pull.py` 回写修正） |
| `format` | string | 固定为 `"png"`（产物不含 SVG / VectorDrawable） |

## 说明

- 切图由 Figma 插件导出 PNG、经桥服务器落盘、`figma_pull.py` 拷贝到产物目录，全程脚本自动完成，Agent 无需手动干预。
- 拷贝到 Android 项目前必须按 `rules/resource-naming-rules.md` 重命名（禁止 hash 名直接入库）。
