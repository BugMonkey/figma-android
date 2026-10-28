# inspect — 快速评估设计稿或查看画板

匹配："看看复杂度"、"评估一下"、"查看画板"、"画板内容"、"看下这个画板"

## 步骤

1. 确认设计数据可用（走桥模式，见 SKILL.md 链路选择）。
2. **结构校验门禁**：对目标缓存跑
   `python3 scripts/common/figma_validate_tree.py "<extract_dir>"`（三值状态 success/warning/blocked，
   exit 2 = blocked）。blocked → 停止评估与任何下游生成，向用户回报缺失项并建议 `--force` 重拉；
   不得基于 blocked 产物给复杂度结论。
3. 读 `android_tree.json`（唯一权威，经查询脚本取数，禁整文件 Read）统计节点数量/类型；
   需要展示画板全貌时派发子 agent 读取 `screenshot.png` 并回传全貌摘要（主 Agent 不直接 Read 截图）。
4. 统计元素分布（Text、Frame、Instance、Image 等）。
5. 识别高风险信号：深层嵌套、Mask、渐变、模糊、非标准字体。
6. 终端输出精简摘要：画板结构分析（视觉区域/容器嵌套/元素归组/滚动策略/切图覆盖）+ 高风险信号清单 + 复杂度评估要点。

## 禁止

- 禁止拷贝切图到 `app/src/main/res/drawable-xxhdpi/`。inspect 只读缓存，不动 app 目录。
- 禁止修改任何项目文件。inspect 是只读操作。