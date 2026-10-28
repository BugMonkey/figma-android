# restyle-page — 按设计稿改造已有页面

匹配："改页面"、"按设计稿改样式"、"更新首页 UI"
也覆盖**混合任务**：换切图 + 顺带调布局/少量 UI 代码（切图按 `resource_impact=replace_asset`
处理，不单走 export-assets）。仅换切图不动任何代码时走 `export-assets`。

## 步骤

0. **读任务记忆（硬前置）**：`test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"`（文件不存在或无输出 = 无历史记录，直接继续；路径锚定 $(pwd)；同一任务多节以时间靠后的节为准）。
   读与本次画板 nodeId / 页面名相关的节，四类信息直接影响本任务：`excluded`（上次排除的死代码/资源
   不得重新纳入）、`asset_overwrite`（二次覆盖前先追溯覆盖链）、`build: PARTIAL` + `open`
   （存在未履行的补跑义务必须补跑，或在终端声明仍未履行）、`attribution`（同页归属证据仅作复核起点，不得跳过重新 grep）。
1. 数据提取：按 SKILL.md 链路选择执行通道。
   提取后必须跑产物结构校验：`python3 scripts/common/figma_validate_tree.py "<extract_dir>"`
   （`blocked`/exit 2 → 停止，回报缺失项并建议 `--force` 重拉，不得基于 blocked 产物改造）。
2. 读产物（android_tree 先行）：先读 `android_tree.json`（唯一权威），再用 `figma_query_node.py --id <nodeId>`（注意是 `--id`，不是 `--node-id`）或 `figma_selected_node.py --node-id <nodeId>` 定位目标区域（如底部 tab）取出精确样式（图层名/坐标/颜色/圆角/切图/选中态）；`screenshot.png` 仅作全貌预览（需要时派发子 agent 读取），排在后。
   - 多画板场景（如各 tab 页画板）：一次用
     `figma_compare_nodes.py --name <关键词> --fuzzy --root-ids <画板nodeId,...>` 得到
     各板对比表 + 差异摘要 + 内容等价分组；需要单节点下钻时再逐画板 `--root-id <画板nodeId>` 限定查询，
     对比同一 tab 的选中/未选中样式差异（图层名/填充色/描边色/文字色/切图），汇总差异清单。
     切图是否同一张只看内容签名，禁止用 `image.file` 文件名不同推断视觉不同。
   - 明确本轮是**混合任务**时，切图部分按 `resource_impact=replace_asset` 逐条登记（保留项目原文件名覆盖），
     不另起 export-assets 流程。
3. 扫描旧页面：定位布局文件、ID 引用、业务代码绑定。
   - **页面入口必须证明被宿主实际引用**：画板名 ≠ 类名（"首页"可能是 `mod_trade/TradeHomeFragment`
     而非 app 模块遗留的同名 `HomeFragment`）。用 grep 证明目标 Fragment/Activity 被宿主实际引用：
     `setTab(` / 实例化 / Manifest 注册，记录证据行号（进终端摘要，并落记忆节 `attribution`）；存在同名死代码时显式列「已排除」（进记忆节 `excluded`）。
4. 读 `rules/restyle-guardrails.md` 与 `schemas/change-impact-schema.md`。
5. **【阻塞】结构确认**（android_tree 先行，按 SKILL.md 步骤 5a/5b 执行）：
   - 以 android_tree 精确数据对比新旧样式：旧容器/旧组件 vs 设计稿目标区域（图层名/坐标/颜色/圆角/切图逐一对照）
   - 仅当 android_tree 无法回答的定性歧义（容器归属、视觉分组）才需截图/视觉补位；禁止先看截图
   - 标注保留复用的旧容器、重组的元素新容器
   - 标注受保护的 ID（被代码引用，不可删除/重命名）
   - 确认页面归属（`code_entry` + `host_binding_proof`）后再继续
   - 等待用户确认
6. 按差异分类执行：
   - `style_update` → 保留 ID，只更新属性/切图；切图替换走 `resource_impact=replace_asset`
     （保留项目原文件名覆盖，文件名与 `@drawable/` 引用不变）
   - `new_element` → 新增
   - `removed_element` → 零引用删除，否则 `visibility=gone`
   - `structural_change` → 最小结构修改
   - `role_change` → 保留 ID，调整属性
   - 纯 UI 层代码调整（布局管理器、selector、可见性）允许，须在影响分析 `planned_changes`（终端）逐条列出
7. 终端输出影响分析摘要（Page/Code Entry/Host Binding Proof、Risk Level、改动清单表 File|Change|Diff Type|Resource Impact、待确认项），等待用户确认；**影响分析不全量落盘**。
8. **静态检验**：对照 `rules/android-layout-rules.md` 检查清单和 `rules/restyle-guardrails.md`。
9. 编译验证：构建命令优先取宿主项目根 `CLAUDE.md`/`AGENTS.md` 声明（含 flavor 变体），
   否则 `./gradlew assembleDebug`。报错文件不在本次改动集内时按 `rules/verify-rules.md`
   「非本次改动导致的编译失败」走四步，结论标 `PARTIAL`。
10. **写任务记忆**：用 `cat >> "$(pwd)/figma_task_memory.md" <<'EOF' … EOF` 单次追加一节
    （禁止 Edit/Write 整文件改写，多会话并行下会丢节），固定 8 字段见 `templates/task_memory.md`；
    `build` 以步骤 9 结果为准，`attribution`/`excluded`/`asset_overwrite`/`confirmed`/`open`
    只填本次实际产生的事实，无则写「无」；本次被用户重议推翻的旧 `confirmed` 结论，
    新结论写入本节 `confirmed`（旧节不改，以靠后节为准）。

## 硬约束

措辞统一以本节为准（SKILL.md Hard Rule 7 与 `restyle-guardrails.md` 不再另立粒度）：

- **不修改业务逻辑**：ViewModel / Repository / UseCase / 网络 / 埋点 / 权限 / 登录态 / 数据加载
- **允许纯 UI 层代码调整**：布局管理器切换、selector/state list、可见性、纯展示性属性；
  但必须在影响分析的 `planned_changes` 中逐条列出（含文件与 `diff_type`，进终端摘要）
- **列表/结构类 UI 调整的边界**：
  - 允许（仍须逐条进 `planned_changes` + 终端摘要）：`reverseLayout`、RecyclerView header/footer 化、纯展示性顺序调整。
  - 必须用户确认：上述调整需要改 Adapter `itemType` / DiffUtil / payload，或需要改 DAO/Repository 的查询条件、排序、分页参数。
  - 禁止：修改查询语义、分页逻辑、埋点与业务判断条件。
- 不删除/重命名被代码引用的 ID
- 不修改埋点事件名/参数名/曝光时机、不修改页面路由参数与返回结果
