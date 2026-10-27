# handoff artifact 目录

本目录**只放 handoff artifact**，不放任务板或笔记——任务板在
`docs/designs/refactor-tasks.json`，会话笔记在
`docs/designs/refactor-session-notes.md`。

## 命名

```
<task_id>.<stage>.json
```

`<stage>` ∈ `recon` / `design` / `implement` / `review` / `bench` / `audit`。
文件名里的 stage 后缀是校验器 `scripts/validate_handoff.py` 推断阶段的依据，
**不要改名**。不是 handoff 形状的 JSON 在目录扫描时会被跳过并显式报告
（不静默丢弃）。

## 校验

```powershell
D:\tools\python312\python.exe scripts/validate_handoff.py docs/designs/refactor-handoff
D:\tools\python312\python.exe scripts/validate_handoff.py <file> --json
```

各阶段的必填字段与通过条件见
`docs/designs/refactor-multi-agent-protocol.md` §3 / §4。

## 谁可以写

只有该阶段的角色 agent 写自己那一份 artifact；编排者是任务板与索引的唯一
写入方。
