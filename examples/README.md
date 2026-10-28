# 示例产物

唯一的示例是 `android_tree_sample/`，目录结构即缓存真实结构：

```text
android_tree_sample/
├── figma_extract_prepared/
│   ├── android_tree.json   最小 v2 产物（可直接过 figma_validate_tree.py，当前为 warning：
│   │                        无切图/无 source_meta，属示例范围的预期缺失）
│   └── assets.json
```

校验命令：

```bash
python3 scripts/common/figma_validate_tree.py examples/android_tree_sample
```

字段语义一律以 `schemas/android-tree-schema.md` 为准；本示例只用于直观展示结构与
分隔线（`dp.h=0 + border_width`）等易错表达。
