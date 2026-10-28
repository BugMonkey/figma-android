# restore-check — 检查还原度

匹配："检查还原度"、"对比设计"、"看像不像"

## 前置

- 设计数据可访问（桥模式已执行）
- Android 布局文件可定位
- 有实现截图更佳（`actual_screenshot.png`）
- **读任务记忆**：`test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"`
  （锚定 $(pwd)；多节以时间靠后的节为准），相关节点最新节的 `open` 字段有
  上次遗留的不一致项时，本轮检查须显式覆盖这些点。

## 步骤

1. 获取最新设计数据（走桥模式 `scripts/bridge/figma_pull.py`）。**调用按 `modes/bridge-execution.md`「调用约定」显式传 `--project-root "$(pwd)"`**。
2. 读 `android_tree.json` 获取设计尺寸、颜色、字号、间距。
3. 定位 Android 实现：布局文件 + 资源文件。
4. 静态核对：尺寸/颜色/字号/间距/圆角/描边一致性。
5. 视觉对比（当用户提供了实现截图 `actual_screenshot.png` 时）：派发子 agent 同时读取
   `<extract_dir>/screenshot.png` 与 `<actual_screenshot_path>`，prompt 中给出用户关注点，
   要求只回传"像不像、差在哪"的定性差异结论，不回传图片内容；无法读取图片时只回 `{"viewed": false, "reason": "..."}`。
   主 Agent 把结论融入差异清单（终端输出）。
   失败时不阻塞，静态核对结果照常输出，终端摘要标注"视觉对比缺失"。
6. 差异清单 + 修复建议**直接在终端完整输出，不落盘**（差异明细是可重建信息，md 无消费方）。
   仅当存在「本次未修复、需要下个会话接手」的不一致项且用户同意留痕时，
   用 `cat >>` 向 "$(pwd)/figma_task_memory.md" 追加一节，把遗留项写进 `open` 字段（`build` 填 `N/A`——本命令不涉编译；模板 `templates/task_memory.md`）。
7. 不主动修改任何文件。

