# create-page — 生成完整页面

匹配：用户在 Figma 选中画板 + "生成页面"、"帮我实现这个设计"（仅桥模式，不接受 URL）

## 步骤

0. **读任务记忆**：`test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"`（文件不存在或无输出 = 无历史记录，直接继续；路径锚定 $(pwd)；同一任务多节以时间靠后的节为准）。
   命中同画板/同页面名的旧节时重点看 `asset_overwrite`（二次覆盖前追溯覆盖链）与
   `build: PARTIAL` + `open`（存在未履行的补跑义务时先处理或终端声明）。
1. 数据提取：走桥模式唯一通道 `scripts/bridge/figma_pull.py`。**调用必须按 `modes/bridge-execution.md`「调用约定」显式传 `--project-root "$(pwd)"`**。
   提取后必须跑产物结构校验：`python3 scripts/common/figma_validate_tree.py "<extract_dir>"`
   （`blocked`/exit 2 → 停止，回报缺失项并建议 `--force` 重拉，不得基于 blocked 产物生成）。
2. 读产物（android_tree 先行）：先读 `android_tree.json`（唯一权威）核结构，再读 `source_meta.json` + `assets.json`（切图清单）；`screenshot.png` 仅作全貌预览（需要时派发子 agent 读取），排在后。
3. **【阻塞】结构确认**：按视觉区域/容器重叠/元素归组/滚动策略/切图覆盖输出，等待用户确认。
   - 如有 `repeat_groups` 数据，必须逐项提问：每个重复模式使用 RecyclerView 还是内联固定布局。用户只需回答"是"或"否"。
   - 对于 2 项的重复，追问"接口可能返回更多吗"以决定是否使用 RecyclerView。
4. 生成 XML 布局：按 `rules/visual-grouping-rules.md` + `rules/android-layout-rules.md`。
5. 生成资源：shape drawable、colors、dimens。命名规则见 `rules/resource-naming-rules.md`。
6. 生成 Activity/Fragment 骨架：setContentView + ViewBinding 初始化。
7. 切图同步：从缓存目录拷贝到 app，按 `rules/resource-naming-rules.md` 重命名（禁止 hash 名），同步更新 XML 中的 `@drawable/` 引用。
8. 编译验证：构建命令优先采用宿主项目根 `CLAUDE.md`/`AGENTS.md` 声明的（含 flavor 变体），
   否则 `./gradlew assembleDebug`；报错文件不在本次改动集内时按 `rules/verify-rules.md`
   「非本次改动导致的编译失败」走四步，结论标 `PARTIAL`。
9. 终端输出精简摘要（≤30 行：生成/修改的文件 + 风险点）。
10. **写任务记忆**：用 `cat >> "$(pwd)/figma_task_memory.md" <<'EOF' … EOF` 单次追加一节
    （禁止 Edit/Write 整文件改写，多会话并行下会丢节；模板 `templates/task_memory.md`）；
    `build`/`blocker`/`verified_scope` 以步骤 8 结果为准，覆盖既有资源时必填 `asset_overwrite`，
    无值字段写「无」；最新节 `open` 有历史补跑义务时按承接格式处理（见 restyle-guardrails「任务记忆层」）。

## 禁止

- 不创建 ViewModel、Repository、业务逻辑
- 不对 dp 值做二次换算
- 不照搬 Figma 图层嵌套
