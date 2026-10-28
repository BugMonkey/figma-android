# 任务记忆节模板

唯一落盘的报告/记忆文件：会话工作目录（与 `figma_pull.py --project-root` 同口径）的
`figma_task_memory.md`。不含 `.figma/` 缓存内的中间产物（照旧生成）。
定位、写入/读取契约以 `rules/restyle-guardrails.md`「任务记忆层」为准，本文档只是抄写件。

**复制规则**：只复制下方围栏内的节内容，`<…>` 占位符必须全部替换为实际值后才允许落盘
——占位符原样写入等同伪造记录。首次创建文件时不要复制本文档的标题与说明，只写第一个节。

**追加方式**：`cat >> "$(pwd)/figma_task_memory.md" <<'EOF' … EOF` 单次写入整节；
禁止用 Edit/Write 改写整个文件来追加（多会话并行下会静默丢节）。

**宿主仓库策略**：本文件不随改动集提交。git 宿主进 `.gitignore`；SVN 宿主
`svn propset svn:ignore figma_task_memory.md <项目根>`。

```markdown
## 任务 <任务名> | 画板 <nodeId 或 不适用> | <YYYY-MM-DD>

- build: PASS | PARTIAL | FAIL_BLOCKED | FAIL_FIXED | N/A
- blocker: <报错文件:行号与阻塞原因 | 无>
- verified_scope: <实际跑通的验证命令与范围（如 :app:compileDebugKotlin）| 无>
- attribution: code_entry=<文件>; host=<文件:行号 命中的调用形式> | 不适用（新建页面/无归属判定）
- excluded: <已排除的同名死代码 / 不落地资源 / 未代改的他人文件 + 证据行号 | 无>
- asset_overwrite: <被覆盖的旧资源文件 → 覆盖来源（图层名/nodeId，可得时补 md5）| 无>
- confirmed: <用户拍板过的结论（问题 + 所选答案）| 无>
- open: <后续会话必须接手的遗留 | 无>
```

## 已填写示例（照此格式，勿照抄内容）

```markdown
## 任务 首页tab改版 | 画板 1:200 | 2026-09-29

- build: PARTIAL
- blocker: mod_trade/TradeHomeFragment.kt:88（他人 WIP 引用缺失方法，不在本次改动集）
- verified_scope: ./gradlew :app:compileDebugKotlin + :app:processDebugResources 均通过
- attribution: code_entry=mod_trade/src/main/java/.../TradeHomeFragment.kt; host=app/src/main/java/.../BaseMainActivity.kt:24 setTab(TradeHomeFragment())
- excluded: 已排除 app/src/main/java/.../HomeFragment.kt（rg 无任何实例化/setTab 引用）
- asset_overwrite: drawable-xxhdpi/ic_tab_home.png → Figma 图层 home-icon[1:233]（md5 9f2c…）
- confirmed: 用户确认 tab 文字色选中态用 #FF6200，未选中沿用 @color/text_secondary
- open: 待补跑 assembleDebug（承接本节 PARTIAL；工作区恢复后执行）
```

## 字段约束

| 字段 | 约束 |
|------|------|
| `build` | 枚举与 `schemas/verify-schema.md` 对齐；`PARTIAL` 必须同时有非空 `blocker` + `verified_scope` + `open`（补跑义务），否则记录无效；不涉编译的节（纯导出、还原度留痕）填 `N/A`，此时 `blocker`/`verified_scope` 写「无」 |
| `attribution` | 仅 restyle 场景写；行号必须是 grep 实际命中；新建页面写「不适用」 |
| `asset_overwrite` | 只记 `replace_asset`（覆盖既有资源内容）场景；纯新增资源不记——git 可重建 |
| `confirmed` | 只记需要用户决策的 `manual_confirmations` 结论；结构确认（步骤内已阻塞完成）不重复记。读取方：新会话不得静默推翻已拍板结论，重议须写入新节 |
| `open` | 读契约的主要消费点：凡是「下个会话不读这条就会踩坑」的事实必须进这里。**补跑义务闭合格式**：兑现时写 `已补跑 assembleDebug（承接 <YYYY-MM-DD> 节 PARTIAL）`；仍未履行写 `未履行，承接 <YYYY-MM-DD> 节：<原因>`。`open: 无` 只闭合本节范围，不承接历史义务 |

## 读取与优先级

以 `rules/restyle-guardrails.md`「任务记忆层」为唯一权威（最新节为准、旧节永不修改、
补跑义务闭合格式、读取契约五类消费），本文档不复述；写节时只保证字段名与格式合规。
