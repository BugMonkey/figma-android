# verify — 编译验证

匹配："编译一下"、"验证"、"跑一下 build"

## 执行

1. **先读任务记忆**：`test -f "$(pwd)/figma_task_memory.md" && grep -n "^## 任务" "$(pwd)/figma_task_memory.md"`（文件不存在或无输出 = 无历史记录，直接继续；路径锚定 $(pwd)，禁止裸相对文件名）。
   无画板锚定时（用户只说"编译一下"，无 nodeId 上下文）：先列出全部**最新节**中未履行的
   `open` 补跑义务，让用户指定本次兑现哪些，或在本次节内声明覆盖范围；不得无视，也不得把
   全部历史义务无差别重复补跑。
   存在 `build: PARTIAL` 且最新节 `open` 记有补跑义务时，本次 `assembleDebug` 通过即为该义务的兑现。
2. 构建命令优先采用宿主项目根 `CLAUDE.md` / `AGENTS.md` 声明的命令（含 flavor / 变体）；
   未声明时用：

```bash
./gradlew assembleDebug
```

3. **收尾写任务记忆**：终端给出结果后，用 `cat >> "$(pwd)/figma_task_memory.md" <<'EOF' … EOF`
   单次追加本次验证节（禁止 Edit/Write 整文件改写；模板 `templates/task_memory.md`）。
   `build`/`blocker`/`verified_scope`/`open` 必填，其余字段按实（无锚定时节头画板位写 `不适用`）。
   兑现历史义务时 `open` 必须写承接格式——成功
   `已补跑 assembleDebug（承接 <YYYY-MM-DD> 节 PARTIAL）`，失败
   `未履行，承接 <YYYY-MM-DD> 节：<本次阻塞原因>`；`open: 无` 只闭合本节范围，不承接历史义务。

## 失败时

1. 修复最小安全改动
2. 重新编译
3. 重复直到通过或 `blocked`
4. 报错文件**不在本次改动集内**（并行会话把主干改坏）→ 不要代改他人半成品，
   按 `rules/verify-rules.md`「非本次改动导致的编译失败」走四步（归属 → 不代改 → 降级取证 → 收尾义务）

## 状态

枚举见 `schemas/verify-schema.md`（共五值，`N/A` 仅用于不涉编译的节）；判定条件、`PARTIAL`
固定措辞与收尾义务见 `rules/verify-rules.md`。
