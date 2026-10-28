# start — 启动桥服务器 + 环境引导

匹配："start"、"启动"、"开始"、"setup"、"初始化"、"reset"、"重置"、"重启"

## 前置

桥模式 (modes/current_mode.txt = plugin)

## 步骤

0. 用户意图含 "reset"/"重置"/"重启" 时，强制重启桥服务器。

   Agent 先按操作系统选择停止命令：

   macOS / Linux:
   ```bash
   pkill -f bridge/figma_bridge_server.py 2>/dev/null
   sleep 1
   ```

   Windows (PowerShell):
   ```powershell
   Get-Process python* | Where-Object {$_.CommandLine -like "*figma_bridge_server*"} | Stop-Process -Force
   Start-Sleep 1
   ```

   然后重新启动：
   ```bash
   python3 <skill_dir>/scripts/bridge/figma_bridge_server.py --port 7789 &
   sleep 2
   curl -s http://localhost:7789/health | grep -q ok && echo "restart:ok" || echo "restart:fail"
   ```

   重启成功后跳到步骤 5 输出状态。

1. 快速就绪检查（Agent 根据操作系统选择命令）：

   macOS / Linux:
   ```bash
   python3 --version >/dev/null 2>&1 && echo "python:ok" || echo "python:fail"
   pgrep -i figma >/dev/null 2>&1 && echo "figma:ok" || echo "figma:fail"
   test -f ~/.figma-android/plugin_configured && echo "configured:ok" || echo "configured:fail"
   curl -s http://localhost:7789/health 2>/dev/null | grep -q ok && echo "server:ok" || echo "server:fail"
   ```

   Windows:
   ```powershell
   python --version 2>&1 | Out-Null; if ($?) { "python:ok" } else { "python:fail" }
   Get-Process -Name "Figma*" -ErrorAction SilentlyContinue | Out-Null; if ($?) { "figma:ok" } else { "figma:fail" }
   if (Test-Path "$env:USERPROFILE\.figma-android\plugin_configured") { "configured:ok" } else { "configured:fail" }
   try { $r = Invoke-WebRequest -Uri http://localhost:7789/health -TimeoutSec 3; if ($r.Content -eq "ok") { "server:ok" } else { "server:fail" } } catch { "server:fail" }
   ```

2. 核心项全部 `ok`（python/figma/configured/server）→ 进入步骤 6 继续。
   不在本步骤输出环境就绪提示，继续走完整流程。

3. 核心项有 `fail` → 按缺失项分别处理：

   | 缺失项 | 操作 |
   |--------|------|
   | `python:fail` | `blocked`，提示安装 Python >= 3.8 |
   | `figma:fail` | 提示用户启动 Figma 桌面应用 |
   | `configured:fail` | 执行首次配置引导（见下方） |
   | `server:fail` | 自动启动桥服务器，等 10s 确认 `/health`，再检查插件连通性 |

4. 服务器启动后检查插件连通性：

   ```bash
   curl -s http://localhost:7789/api/plugin-status | python3 -c "import sys,json; d=json.load(sys.stdin); print('connected' if d.get('connected') else 'disconnected')"
   ```

   未连接 → 提示用户安装并打开插件:
   ```
   Figma 插件尚未连接。
   请确保已安装并打开 figma-android-bridge 插件：
     1. [首次需要] Figma → Plugins → Development → Import plugin from manifest...
        选择: {skill_dir}/scripts/plugin/manifest.json
     2. 右键画板 → Plugins → Development → figma-android-bridge（插件打开后自动连接）
   ```

   已连接时额外提醒（提示用户 plugin 代码变更需关闭重开面板才生效）：
   ```
   提示：plugin 代码（ui.html/code.js）改动需在 Figma 中关闭并重开插件面板才会生效。
   旧 plugin 仍能正常工作，但新版中的失败诊断（extract_last_error 回填）等新特性
   需要关闭后重开面板才生效。如 extract_last_error 始终为空、诊断能力不可用，
   请关闭插件面板后重新打开。
   ```

5. 首次配置引导（仅 `configured:fail` 时）：

   ```
   Figma 插件首次配置：
     1. Figma → Plugins → Development → Import plugin from manifest...
     2. 选择: {skill_dir}/scripts/plugin/manifest.json
     3. 导入成功后，右键画板 → Plugins → Development → figma-android-bridge
        （插件打开后自动连接）
   ```

   用户回复"已配置"后：

   macOS / Linux:
   ```bash
   mkdir -p ~/.figma-android && touch ~/.figma-android/plugin_configured
   ```

   Windows (PowerShell):
   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.figma-android" | Out-Null
   New-Item -ItemType File -Force "$env:USERPROFILE\.figma-android\plugin_configured" | Out-Null
   ```

   然后返回步骤 1 重新检测。

6. 浏览画板清单，询问是否后台预拉取缓存（可选，始终不阻塞主流程）。

   本步骤在所有核心项就绪后执行。Agent 运行以下命令获取画板清单：

   ```bash
   python3 <skill_dir>/scripts/bridge/figma_traverse_list.py --port 7789 --width <规范宽度>
   ```

   `--width` 传本项目的设计稿规范宽度（二手交易为 1080px；换项目前先确认，不要沿用）。
   宽度不符的画板通常是废弃稿，且会因 dp 基准错误污染产物，应在遍历阶段就过滤。
   被剔除项会在输出的 `filtered_out` 字段列出，先读一眼确认没有误伤再继续。

   根据结果分岔：

   **成功（exit 0）** → 读取 `total` 值，向用户输出：

   ```
   环境已就绪。请告诉我你要做什么: 生成页面 / 查看画板 / 导出切图 / 改页面 / 检查还原度 / 编译验证

   顺便一提，当前文件共 {N} 个画板（页面1/页面2/...）。
   是否需要在后台预拉取全部画板的缓存？
   预拉取后你后续提到任意画板时无需等待提取，可直接使用。
   预计耗时: 单画板约 10-30s，共约 {N*15}s-{N*30}s。
   （若 Figma 插件面板不在前台，插件轮询会被浏览器节流到约 60s 一次，
     每个画板需多等约 60s；预拉取期间保持 Figma 在前台可显著缩短总时长。）
   选择 Y 后不阻塞，我一边干活一边后台拉取。
   (Y/n)
   ```

   **失败（exit 1）** → 输出：

   ```
   环境已就绪。请告诉我你要做什么: 生成页面 / 查看画板 / 导出切图 / 改页面 / 检查还原度 / 编译验证

   [提示] 后台遍历画板不可用，如需预缓存请确认 Figma 插件面板已打开
   ```

   **用户确认预拉取后**：

   1. 记录画板清单到 Agent 工作变量
   2. 启动后台 Agent 逐个拉取缓存（`run_in_background: true`）：
      后台 Agent 职责：
        - 遍历画板清单，逐个调用 `figma_pull.py --node-id <id> --project-root <session_workdir>`
        - 遇到提取失败则跳过（记录到日志），不阻塞后续
        - 连续多个画板失败时先查 `curl http://localhost:7789/api/plugin-status` 看 last_seen：
          若已 ≥90s 无轮询，说明插件已停摆（面板被关或 Figma 休眠），此时应停止拉取并上报，
          不要继续空跑——否则整批失败会被静默吞掉，只留下一串 FAIL
        - 全部完成后通过自动通知报告结果，必须含成功/失败计数与失败画板清单
   3. 告知用户：
      ```
      好的，已启动后台预加载。你可以继续刚才的操作，
      等用到某个画板时缓存应该已经就绪。完成后会通知你。
      ```

   **用户未确认**（输入 n 或直接说需求）→ 跳过预拉取，正常使用。

## 禁止

- 禁止在此命令中触发全量数据提取（bridge/figma_pull.py，步骤 6 的逐画板预拉取除外）
- 禁止在此命令中执行任何 Android 构建
- 步骤 6 的遍历失败或用户未确认时，禁止阻塞主流程
