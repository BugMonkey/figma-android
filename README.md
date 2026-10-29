# figma-android

Figma 设计稿转 Android 代码。通过本地 Figma 桌面端插件读取节点树、截图和切图，生成可编译的 XML 布局、资源与 Activity，也支持改造已有页面和还原度检查。

> 仅支持桥模式：需要 Figma 桌面端 + 本地插件，不支持 Figma URL 或 MCP。

## 快速开始

1. **在 Android 项目根目录启动 Agent**，说「启动」。
   Agent 会检查 Python、桥服务器和 Figma 插件，缺什么会引导补什么。
2. **在 Figma 桌面端选中画板**，右键 → Plugins → Development → `figma-android-bridge`。
   首次使用先 Import plugin from manifest...，选择 `~/.claude/skills/figma-android/scripts/plugin/manifest.json`。
3. **在 Claude Code 里显式调用**，例如 `/figma-android 生成首页`、`/figma-android 按设计稿改登录页`、`/figma-android 检查还原度`。
   Agent 先展示结构方案，回复「确认」后生成并编译验证。

## 安装

Claude Code 的个人 Skill 目录是 `~/.claude/skills/<name>/SKILL.md`；项目级用 `<android-project>/.claude/skills/<name>/`。下面以个人目录为例，其他 Agent 宿主把路径换成自己的 skills 目录。

### 方式一：GitHub clone（推荐）

```bash
mkdir -p ~/.claude/skills
git clone git@github.com:BugMonkey/figma-android.git ~/.claude/skills/figma-android
```

仓库公开后也可以走 HTTPS：

```bash
git clone https://github.com/BugMonkey/figma-android.git ~/.claude/skills/figma-android
```

### 方式二：从本地目录复制

macOS / Linux：

```bash
mkdir -p ~/.claude/skills/figma-android
rsync -a --exclude .git --exclude __pycache__ \
  /path/to/figma-android/ ~/.claude/skills/figma-android/
```

Windows PowerShell：

```powershell
robocopy "C:\path\to\figma-android" "$HOME\.claude\skills\figma-android" /E /XD .git __pycache__
```

### 方式三：GitHub ZIP

GitHub 仓库页 → Code → Download ZIP，解压到 `~/.claude/skills/figma-android`，确认 `SKILL.md` 直接在目录下。

### 方式四：SkillHub（可选）

```bash
tmp=$(mktemp -d)
skillhub install figma-android --namespace user_140863df --dir "$tmp"
mkdir -p ~/.claude/skills/figma-android
cp -R "$tmp/@user_140863df/figma-android/." ~/.claude/skills/figma-android/
rm -rf "$tmp"
```

`skillhub install` 会下载到 `@user_140863df/figma-android` 命名空间目录，所以要复制到平铺目录。`skillhub list` 不会显示 `--dir` 安装，以实际目录为准。

### 验证

```bash
grep -m1 '^version:' ~/.claude/skills/figma-android/SKILL.md   # 1.0.1
python3 ~/.claude/skills/figma-android/scripts/common/figma_selftest.py
```

在 Claude Code 中执行 `/reload-skills` 或重启。

### Figma 插件

1. 打开 Figma 桌面端。
2. 右键画布 → Plugins → Development → Import plugin from manifest...
3. 选择 `~/.claude/skills/figma-android/scripts/plugin/manifest.json`。
4. Development 菜单里会出现 `figma-android-bridge`。

### 使用

本 Skill 设置了 `disable-model-invocation`，必须用 `/figma-android` 显式调用：

```text
/figma-android 生成首页
/figma-android 按设计稿改登录页
/figma-android 检查还原度
```

## 提示词速查

> 本 Skill 设置了 `disable-model-invocation`，必须用 `/figma-android` 显式调用；下表是 `/figma-android` 后面的意图描述。

| 你想做什么 | 在 `/figma-android` 后说 | 得到什么 |
|-----------|------------|---------|
| 生成完整页面 | 「生成首页」「帮我实现这个登录页」 | XML + 资源 + 切图 + Activity |
| 只要布局 | 「只要布局」「只生成这个弹窗的 XML」 | XML + 资源 |
| 按新设计稿改页面 | 「按设计稿改登录页」「更新首页 UI」 | 改造后的布局 + 改动摘要 |
| 导出切图 | 「导出这个画板的切图」「下载图标」 | xxhdpi PNG + XML 引用更新 |
| 检查还原度 | 「检查还原度」「对比设计稿」 | 差异清单 + 修复建议 |
| 评估画板 | 「评估一下」「查看画板结构」 | 复杂度评估 |
| 编译验证 | 「编译验证」「跑一下 build」 | 编译结果 |
| 首次 / 环境没起来 | 「启动」「start」「初始化」 | 环境检查与插件引导 |

## 三种常见任务

### 生成页面

- 从 0 创建 Fragment、Activity、Dialog、列表 item 或普通布局。
- 产出 XML、shape/切图资源；完整页面会补 Activity。
- 不生成网络、仓储、复杂状态或假数据逻辑。

### 改造已有页面

- 按新设计稿调整已有页面 UI。
- 先做结构比对、引用扫描和影响分析，保留 ID、绑定、点击、埋点和业务逻辑。
- 高风险改动先出计划等确认。

### 导出切图 / 还原度检查

- 导出切图：输出 xxhdpi PNG，并按 `ic_` / `bg_` / `img_` 规范重命名。
- 还原度检查：对比设计稿标注和实现截图，输出差异与修复建议；没有实现截图时只做静态核对。

## 它会怎么处理

1. 通过插件拉取节点树、截图和切图，落到 `.figma/figma_extract_{name}_{nodeId}/`。
2. 用 `android_tree.json` 做结构、坐标、尺寸、颜色和切图归属的权威来源；截图只用于定性判断。
3. 先输出结构确认摘要，等用户确认后再生成代码。
4. 生成后默认跑 `./gradlew assembleDebug`；编译失败先修复再验证。
5. 每任务在会话工作目录追加一节 `figma_task_memory.md`，记录 build/blocker/verified_scope/attribution/excluded/asset_overwrite/confirmed/open。

## 产物

```text
.figma/figma_extract_{name}_{nodeId}/
├── screenshot.png                  # 360px 宽预览图
└── figma_extract_prepared/
    ├── android_tree.json           # 核心结构树
    ├── assets.json                 # 切图清单
    ├── source_meta.json            # 来源信息
    ├── selected_node.json          # 选中子节点（可选）
    └── drawable-xxhdpi/*.png       # 切图
```

Android 输出：

```text
app/src/main/res/layout/<page>.xml
app/src/main/res/drawable/*.xml
app/src/main/res/drawable-xxhdpi/*.png
app/src/main/java/.../<PageName>Activity.kt
```

人向结果（改动清单、切图映射、还原度差异、编译输出）直接在对话里给；唯一落盘的报告/记忆文件是 `figma_task_memory.md`。

## 边界

- 仅桥模式，不支持 Figma URL / MCP。
- `android_tree.json` 的 dp 值禁止二次换算。
- 切图统一 xxhdpi PNG，不含 SVG / VectorDrawable；禁止保留 hash 名。
- 改造页面不修改业务逻辑、不删除或重命名已有 ID。
- 未编译验证不声称任务完成。
- 还原度检查必须先做静态核对，有实现截图才能声称视觉一致。

## 常见问题

**Q：插件连不上？**
先确认 Figma 桌面端已启动、插件面板已打开，然后用 `/figma-android 启动` 重新检查。首次使用需要 Import `scripts/plugin/manifest.json`。

**Q：有 Figma 分享链接能用吗？**
不能。当前只支持本地桥模式，请在 Figma 桌面端选中画板后，用 `/figma-android` 说意图。

**Q：生成的代码能直接用吗？**
布局和资源经过 `./gradlew assembleDebug` 验证，但不包含 ViewModel、网络、数据层等业务逻辑，需要你自己接入。

**Q：切图命名很乱？**
Figma 导出的是 hash 名，Agent 会按 `ic_` / `bg_` / `img_` 规范重命名，确认映射表即可。

**Q：编译失败怎么办？**
按 `rules/verify-rules.md` 诊断修复；如果报错文件不在本次改动集内，结论标 `PARTIAL`，不代改他人代码。

## 目录结构

```text
figma-android/
├── .claude-plugin/plugin.json    # Skill manifest
├── LICENSE.md
├── README.md
├── SKILL.md                      # 入口：意图匹配 + 流程 + Hard Rules
├── AGENTS.md                     # 维护者指南
├── CLAUDE.md                     # 项目指令
├── agents/                       # 配套 subagent（xml-reviewer 布局交付前审查）
├── commands/                     # 9 个命令说明
├── modes/                        # 数据通道（current_mode.txt + bridge-execution.md）
├── rules/                        # 9 个行为规则
├── schemas/                      # 5 个产物结构
├── templates/                    # 任务记忆模板
├── evals/                        # 评测用例
├── examples/                     # 最小示例产物
└── scripts/
    ├── bridge/                   # 桥服务器 / 提取 / 适配 / 查询 / 比对
    ├── common/                   # 结构校验 / 离线自检
    └── plugin/                   # Figma 插件（code.js + manifest.json + ui.html）
```

## 版本记录

| 版本 | 日期 | 内容 |
|------|------|------|
| 1.0.2 | 2026-10-28 | 坐标映射限定叠放/锚定，纵向流式内容不再逐块写绝对 marginTop；全宽切图比例不一致禁 fitXY；截图分析追加适配风险追问；结构确认新增逐 artifact 四个必答槽位；新增自适应自检；配套 `agents/xml-reviewer.md` |
| 1.0.1 | 2026-10-28 | README 增加 GitHub clone / 本地复制 / ZIP / SkillHub 四种安装方式；明确 Claude Code 路径和 /figma-android 显式调用 |
| 1.0.0 | 2026-10-28 | 从原 Android 插件独立提取为 `figma-android`；重置版本记录；补齐 SkillHub manifest、LICENSE 和使用说明 |

## 维护

- 本仓库是唯一真源。
- 改动后先跑 `python3 scripts/common/figma_selftest.py`，全绿再提交。
- 发布前同步更新 `SKILL.md`、`.claude-plugin/plugin.json` 和本文件版本记录。
