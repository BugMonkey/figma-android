# export-assets — 导出切图资源

匹配："导出切图"、"下载图标"、"导出图片"

## 前置

`figma_extract_prepared/` 存在且含 `assets.json` + `drawable-xxhdpi/*.png`。

## 步骤

0. **读任务记忆**：`test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"`（文件不存在或无输出 = 无历史记录，直接继续；路径锚定 $(pwd)；同一任务多节以时间靠后的节为准）。
   命中同画板旧节时看 `asset_overwrite`——目标资源曾被覆盖过，二次覆盖前先确认覆盖链，
   别把上一轮的覆盖源当设计基准。
1. 读取 `assets.json` 获取切图清单（node_id、name、file）。用
   `figma_query_node.py --assets [--md5]` 直接列出清单与内容签名；需要知道某个节点对应哪个 PNG 时，
   用 `figma_query_node.py --id <nodeId>`（输出含「切图:」行），**不要手工解析 assets.json**。
2. **【阻塞】重命名映射**：为每个切图生成功能性名称，必须完成以下步骤后才能拷贝：
   a. 检查 `file` 字段：若为 `img_<12位hash>.png` → 必须重命名
   b. 检查 `name` 字段：若含 `rectangle`/`group`/`vector`/`unnamed`/中文 → 必须重命名
   c. 按 `rules/resource-naming-rules.md` Prefix Rules 选择前缀：
      ```
      图标(icon)        → ic_<name>.png
      背景(bg)          → bg_<name>.png
      插画/商品图(img)  → img_<name>.png
      ```
   d. 输出映射表：`{原文件名} → {新文件名}`
3. 按映射表从缓存目录拷贝并重命名：
   ```bash
   cp <extract_dir>/figma_extract_prepared/drawable-xxhdpi/<原文件名> app/src/main/res/drawable-xxhdpi/<新文件名>.png
   ```
4. 检查同名文件冲突，等效则复用，不等效则创建更具体名称。
   **例外——替换既有资源**：若目标资源已存在且语义不变（同一位置/同一用途，只是图案变了），
   走 `replace_asset` 路径：**保留项目原文件名直接覆盖，不重命名、不改 `@drawable/` 引用**；
   覆盖前按硬规则 8 检查同名引用，多处引用先问用户。判定表见
   `rules/resource-naming-rules.md`「替换既有资源」。
5. 同步更新 XML 中的 `@drawable/` 引用，与新文件名一致（走 `replace_asset` 覆盖时引用本就不变，
   无需修改；只有新增/改名才需要同步）。
6. 终端输出命名映射与冲突处理结果，并显式提示一行：「回滚账本已写入 figma_task_memory.md
   的 asset_overwrite（旧文件 → 来源）」；**有覆盖既有资源（replace_asset）时**用 `cat >>`
   向 "$(pwd)/figma_task_memory.md" 按节追加任务记忆（禁止 Edit/Write 整文件改写），
   `asset_overwrite` 字段记「旧文件 → 覆盖来源（图层名/nodeId，可得时补 md5）」——
   回滚账本是本命令唯一落盘理由，映射表本身 git 可重建不进 md。
   节格式见 `templates/task_memory.md`；纯导出不涉编译时 `build` 填 `N/A`（枚举内取值，
   不写「无」），`blocker`/`verified_scope` 写「无」。

## 禁止

- 禁止不经重命名直接 `cp` 到 app 目录（**替换既有资源时例外**：保留项目原名覆盖，
  见「替换既有资源」判定表）
- 禁止文件名含 hash（如 `img_a1b2c3d4e5f6.png`）出现在 app 目录
- 禁止文件名含无意义词（rectangle、group、vector、unnamed）
- 禁止把"替换既有资源"当成改名场景处理——改名会打断该资源的所有引用点

