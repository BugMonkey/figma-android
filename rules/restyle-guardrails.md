---
name: figma-restyle-guardrails
description: 老页面改造专用护栏，约束 restyle-page 如何扫描、保护和修改旧页面
---

# 老页面改造护栏

`restyle-page` 必须遵守本文件。目标是在旧页面基础上做 UI 改造，而不是重建页面。

## 改前必须扫描

### 1. 页面入口

- Fragment / Activity / Custom View
- 页面路由、导航参数、Intent 参数
- 页面初始化方法

**【强制】必须 grep 证明目标页被宿主实际引用**——画板名 ≠ 类名，靠名字猜必然改错页：

```bash
# 证明目标页确实被宿主引用（三个典型入口，至少命中其一）
rg "setTab\(|addTab\(|FragmentTransaction|FragmentPagerAdapter" app/src/main/java/
rg "TradeHomeFragment|HomeFragment" app/src/main/java/
rg "HomeFragment" app/src/main/AndroidManifest.xml

# 排查同名死代码：同名类可能有一个是遗留未引用的
rg -l "class HomeFragment" app/src/main/java/
rg "HomeFragment\(" app/src/main/java/    # 实例化点
```

要求：

1. 必须记录证据行号（文件:行号 + 命中的调用形式），不能只写"已确认"。
2. 存在同名类/遗留死代码时，显式列「已排除：<文件>（无引用证据）」，说明为何不选它；
   该结论落任务记忆节 `excluded` 字段（后续会话不得重复踩）。
3. 找不到任何宿主引用证据时 → 列入 `manual_confirmations`，不得直接开改。
4. 页面归属结论写入任务记忆节的 `attribution` 字段（`code_entry=…; host=文件:行号 调用形式`）。

真实反例：画板"首页"对应 `mod_trade/TradeHomeFragment`（`BaseMainActivity.kt` 的 tab 注册处），
而 app 模块遗留的同名 `HomeFragment` 是死代码；四个 tab 画板有三个的类名与画板名不一致。

### 2. 布局文件

- 主布局
- `include` / `merge` 引用
- RecyclerView item
- Dialog、Header、Footer、EmptyView、LoadingView

### 3. ID 引用

扫描所有布局 ID 在代码中的引用：

```text
binding.<id>
findViewById(R.id.<id>)
R.id.<id>
@id/<id>
@+id/<id>
```

任何被代码引用的 ID 都默认是 **protected**。

### 4. 业务逻辑

必须识别并保护：

- `setOnClickListener` 和 XML `android:onClick`
- ViewModel / LiveData / Flow / RxJava 观察逻辑
- Adapter 数据绑定
- 埋点、曝光、日志
- 权限、登录态、弹窗、网络请求

## 不可轻易改动

- ViewModel、Repository、UseCase、网络层（**业务逻辑**，禁止修改）
- Adapter itemType、DiffUtil 判断、payload 结构
- 页面路由参数和返回结果
- 埋点事件名、参数名、曝光触发时机
- 业务判断条件
- 被多处引用的资源名

业务逻辑界限以 `commands/restyle-page.md`「硬约束」为准。

## ID 保护原则

- 旧 ID 能复用时必须复用
- 视觉样式变化不应导致 ID 变化
- 删除控件前必须证明没有业务引用，或提供迁移方案
- 新控件命名应遵守项目现有风格
- DataBinding 表达式引用的 ID 和变量必须额外检查

## 差异分类与默认策略

改造旧页面时，必须先做**结构比对**：将旧页面的元素清单与 Figma 设计数据逐一比对，产出差异清单。每项差异归入以下 5 类之一。

### 差异分类矩阵

| diff_type | 识别方式 | 默认策略 | 需用户确认条件 |
|-----------|---------|---------|-------------|
| `style_update` | 旧有新有，视觉属性变了 | 保留旧 ID 和结构，只更新属性值/切图资源 | 无 |
| `new_element` | 旧无新有 | 按 normalize 规则新增，生成新 ID | 新增影响根布局结构时 |
| `removed_element` | 旧有新无 | 零引用→删除；有引用→`visibility=gone` 并问用户 | 有业务引用时必须确认 |
| `structural_change` | 旧有新有，包裹关系变了 | 最小结构修改，保留所有子元素 ID | 涉及 Adapter itemType 变化时 |
| `role_change` | 旧有新有，交互性变了 | 保留 ID，调整属性和交互性 | 交互性变更涉及点击/埋点绑定时 |

### 背景图/切图专门规则

背景图和切图资源在增删改时有额外规则：

#### 删除背景图 ImageView

即使代码引用为零，也不能直接删除。必须额外检查：

```bash
# 检查切图资源是否被其他布局引用
rg "@drawable/bg_xxx" res/layout/
rg "@drawable/bg_xxx" app/src/main/java/
```

- 切图只被当前页面使用 → 一并删除 ImageView 和切图资源，需在终端摘要注明
- 切图被多个布局引用 → 删除 ImageView，**保留切图资源文件**
- 切图被代码动态引用 → 不能删除切图资源，只能删除 ImageView

#### 替换背景切图（图案变了）

保留旧 ID 和 ImageView 结构，只替换 `drawable-xxhdpi` 中的文件内容；命名与覆盖判定见
`rules/resource-naming-rules.md`「替换既有资源」。覆盖前检查同名引用，尺寸变化时同步更新
`layout_width` / `layout_height`，影响分析标 `resource_impact=replace_asset`，并把被覆盖的旧文件
写入任务记忆节 `asset_overwrite`（回滚账本）。

#### 背景图从有到无

即使零代码引用，也不直接删除——先问用户确认意图：

1. 用户确认"确实不需要" → 删除 ImageView，按上述规则处理切图资源
2. 用户确认"保留但只在某些场景展示" → 设 `visibility=gone`
3. 无法联系用户 → **默认 `visibility=gone`**，写入任务记忆节 `open` 字段标记为待确认

## 删除元素流程

删除任何旧控件前必须完成：

1. 搜索 ID 全局引用
2. 判断引用是否业务必需
3. 能迁移则迁移到新控件
4. 不能迁移则列入用户确认项
5. 删除后运行编译或说明无法编译

## 任务记忆层

唯一落盘的**报告/记忆**文件：会话工作目录（与 `figma_pull.py --project-root` 同一口径）的
`figma_task_memory.md`（模板 `templates/task_memory.md`）。不含 `.figma/` 缓存内的中间产物
（`layout_analysis.json` 照旧生成；`tree_validation_report.md` 仅在显式传 `--write-report` 时生成）。
定位：**给后续/并行会话读的机器可检索记忆**，只装 git diff / 重跑构建**恢复不了**的事实。
给人看的内容一律走终端摘要（≤30 行），不存在"用户去翻 md"的假设。

**宿主仓库策略**：本文件是**工作副本本地态，禁止随改动集提交**。git 宿主首次写入时追加进
`.gitignore`；SVN 宿主首次写入时执行 `svn propset svn:ignore figma_task_memory.md <项目根>`。
换工作副本/新检出读不到历史属预期，不得为"共享记忆"把它提交进交付仓库。

### 写入约定（append-only）

1. **每任务一节**，节头固定格式：`## 任务 <任务名> | 画板 <nodeId> | <YYYY-MM-DD>`；
   无画板锚定的操作（纯导出、无锚定 verify）画板位写 `不适用`，不得留空或写占位符。
2. **追加必须单次写入**：用 `cat >> "<工作目录>/figma_task_memory.md" <<'EOF' … EOF` 一次写完
   整节；**禁止用 Edit/Write 改写整个文件来"追加"**——多会话并行（Hard Rule 16 的运行模式）下
   read-modify-write 会静默丢掉其他会话刚追加的节，且 grep 无法察觉。
3. **同一任务/画板多节以时间靠后的节为准**，旧节仅作历史，永不修改；义务与结论的更新
   一律靠追加新节（含承接引用，见下）。
4. 节内固定 8 字段（`build / blocker / verified_scope / attribution / excluded /
   asset_overwrite / confirmed / open`），键名不得增删改名——读节按 `- <字段>:` 行取值。
5. **可重建内容出清**：改动清单、设计对照大表、完整构建输出、还原度差异明细**不进 md**，
   只进终端；md 只留结论字段。判据：git diff / 重跑命令能恢复的一律不落盘。
6. **机器可检索状态字段**：`build: PASS|PARTIAL|FAIL_BLOCKED|FAIL_FIXED|N/A`（`N/A` =
   本节不涉编译，如纯导出/留痕节），与 `schemas/verify-schema.md` 的枚举对齐，杜绝"PASS
   但同文件记录未通过"复发；`PARTIAL` 必须同时填 `open`（补跑 assembleDebug 义务），否则记录无效。

### 读取契约（消费侧，与写入同等强制）

`create-page` / `create-layout` / `restyle-page` / `export-assets` / `verify` / `restore-check`
开工前必须执行（**路径锚定到会话工作目录，禁止裸相对路径**——Agent `cd` 过就会 grep 落空、
把"路径错了"误判成"无历史记忆"）：

```bash
test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"
# 文件不存在 = 无历史记忆；文件存在但无输出 = 无任务记录，两者都直接继续
```

读取与本次画板（nodeId）/页面名相关的节（多节时以时间靠后的节为准），五类信息直接影响本任务动作：

| 字段 | 消费方式 |
|------|---------|
| `excluded` | 上次排除过的同名死代码 / 不落地资源，不得重新纳入 |
| `asset_overwrite` | 二次覆盖前先追溯覆盖链，避免拿上次的覆盖源当设计基准 |
| `build: PARTIAL` + `open` | 见"补跑义务的判定"：以该任务**最新节**为准；最新节 `open` 含「已补跑（承接 …）」即义务已闭合，含未履行义务时本次收尾必须补跑，或在终端声明仍未履行并在自己的 `open` 原样承接 |
| `attribution` | 同页归属证据可作为本次 grep 复核的起点，但不得跳过重新验证 |
| `confirmed` | 上次用户拍板的结论不得被新会话静默推翻；须在其基础上继续，或显式重议并把新结论写进新节 `confirmed` |

**补跑义务的判定（闭合规则）**：旧节永不修改，因此"是否已履行"只看该任务/画板**时间靠后的节**：
补跑成功时新节 `open` 必须写 `已补跑 assembleDebug（承接 <YYYY-MM-DD> 节 PARTIAL）`；
补跑仍失败时新节 `open` 写 `未履行，承接 <YYYY-MM-DD> 节：<本次阻塞原因>`。
`open: 无` 只闭合**本节自己**的范围，不构成对历史 PARTIAL 义务的承接。

### 影响分析必填项（会话内输出 + 终端摘要，不全量落盘）

restyle 的影响分析必须包含以下项（供用户当场审批与执行器对照）：

- `page`：`{page, code_entry, host_binding_proof}`（页面名 / 代码入口文件 / 宿主引用证据行号）
- `risk_level`：风险等级
- `target_files`：将修改的文件
- `referenced_ids`：被代码引用的 ID
- `protected_views`：必须保留或兼容的视图
- `risky_bindings`：绑定风险
- `adapter_dependencies`：列表和 item 风险
- `forbidden_changes`：禁止修改项
- `planned_changes`：计划修改项（必须标注 `diff_type`；切图替换标注 `resource_impact=replace_asset`）
- `compile_risks`：编译风险
- `manual_confirmations`：需要用户确认的问题

其中仅以下项落任务记忆节：`page`（→`attribution`）、排除结论（→`excluded`）、
`replace_asset` 覆盖记录（→`asset_overwrite`）、`manual_confirmations` 拍板结论（→`confirmed`）、
构建状态与遗留（→`build/blocker/verified_scope/open`）；其余字段会话内输出即可。

## 高风险信号

出现以下情况时必须升级为高风险，并输出计划等待确认：

- 多个 itemType 或复杂 Adapter
- 自定义 View 绘制或动态 addView
- DataBinding 双向绑定
- 旧页面有复杂显示隐藏状态
- 同一 ID 被多个文件引用
- 设计稿要求删除承载点击、埋点或数据绑定的控件
- 无法找到项目编译命令

## 改后必须验证

至少执行以下检查：

- XML 资源引用是否存在
- 删除 ID 是否仍被代码引用
- Kotlin / Java 编译或项目可用的最接近编译命令
- 终端摘要列出未验证项和原因；需后续会话接手的同时写任务记忆节 `open` 字段

禁止写"编译通过"，除非命令实际成功。报错文件**不在本次改动集内**（并行会话把主干改坏）时，
按 `rules/verify-rules.md`「非本次改动导致的编译失败」走四步，结论标 `PARTIAL` 并写入任务记忆节
`build:` 字段（`blocker`/`verified_scope`/`open` 同步填）——不得标 `PASS`，也不得代改他人半成品。