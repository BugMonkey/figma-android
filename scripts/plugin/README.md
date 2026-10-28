# figma-android 插件（桥模式）

用于 Figma 设计稿数据提取。用户选中画板后，Agent 通过桥服务器读取设计数据。

## 首次安装

1. 打开 Figma 桌面应用
2. 右键 Figma 画布 → **Plugins** → **Development** → **Import plugin from manifest...**
3. 选择 `manifest.json` 文件（与本 README 同目录）
4. 安装完成后，即可在 Development 菜单中找到 `figma-android-bridge`

## 使用方式

### 第一步：打开插件 + 选中画板

```
Figma 桌面
  ├── 右键 → Plugins → Development → figma-android-bridge
  └── 选中目标画板 (Frame / Component)

插件面板显示（与 ui.html 实况一致，详见 modes/bridge-execution.md 面板图例）：
  ┌──────────────────────┐
  │ ● 连接状态灯（绿/灰）  │
  │ 画板: <选中图层名>     │
  │ ┌──────────────────┐ │
  │ │ 蓝底卡片          │ │  ← layername[nodeId]，点击复制
  │ └──────────────────┘ │
  │ [标记为切图] [下载]    │
  │ Android Shape 代码区   │
  │ ▓▓▓░ 提取进度条        │
  └──────────────────────┘
```

### 第二步：对 Agent 说需求

插件面板保持打开状态，直接对 Agent 说：

```
"查看这个画板，帮我下载图标"
"查看画板内容"
"这个画板，生成页面"
```

### 第三步：Agent 自动拉取数据

Agent 自动执行 `figma_pull.py`，无需用户提供 Figma URL。

## 交互原理

```
用户选中画板
  └── 插件自动导出 1x 缩略图 → 面板上展示预览

用户对 Agent 说需求
  └── Agent 按 SKILL.md 意图表匹配 → 桥模式（唯一通道）
  └── figma_pull.py
      ├── 通知桥服务器 → 插件收到 pending
      ├── 插件完整提取 (节点树 + 3x截图 + 切图)
      ├── 插件自动发送到桥服务器
      └── Agent 读取数据 → 干活
```

## 注意事项

- **插件面板必须保持打开** — 插件最小化/关闭后不会响应提取请求
- **画板必须选中** — 插件面板显示缩略图才表示选中成功
- **桥服务器由 Agent 自动管理** — 未运行时自动启动，无需手动操作
- **缓存自动清理** — 数据提取完成后自动删除，不会堆积

## 端口

桥服务器默认使用 `localhost:7789`，Agent 自动管理生命周期。
