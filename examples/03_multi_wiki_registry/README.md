# 03 — 多 wiki 注册表

> 对应 [docs/TUTORIAL.md §场景 3](../../docs/TUTORIAL.md#场景-3多-wiki-协作)

## 跑法

```bash
cd examples/03_multi_wiki_registry
python play.py
```

预期输出：

```
📌 Registered: personal (local) → /tmp/.../personal
📌 Registered: project (local) → /tmp/.../project
📌 Registered: study (local) → /tmp/.../study

📋 Total wikis: 3
   - personal   Personal Wiki       local
   - project    Project Wiki        local
   - study      Study Notes         local

🎯 Active: project (Project Wiki)

🔍 Cross-wiki search for 'Welcome':
   personal   → 1 hits
      - welcome-personal
   project    → 1 hits
      - welcome-project
   study      → 1 hits
      - welcome-study

🛰️  Discovery scan(/tmp/..., depth=2): 3 wikis
🎉 Done. Registry has 3 wikis.
```

## 涉及 API

| API | 用途 |
|---|---|
| `WikiRegistry(config)` | 构造注册表 |
| `registry.register_wiki(id, name, root)` | 注册 local wiki |
| `registry.list_wikis()` | 列所有 |
| `registry.switch(id)` | 切 active |
| `registry.get_active()` | 读 active |
| `WikiDiscovery().scan(path, depth)` | 目录扫描发现 |

## 启动多 wiki server（CLI 模式）

```bash
# 假设三个 wiki 在 ~/wikis/{personal,project,study}
cat > ~/wikis/personal/.wiki-config.yaml <<'YAML'
wikis:
  default: "personal"
  local:
    - id: "personal"
      name: "Personal Wiki"
      path: "."
    - id: "project"
      name: "Project Wiki"
      path: "../project"
    - id: "study"
      name: "Study Notes"
      path: "../study"
  discovery:
    enabled: true
    scan_paths: ["../", "~/wikis"]
    scan_depth: 2
YAML

cd ~/wikis/personal
llmwikify serve --web --multi-wiki --port 8765
# → Wikis: 3 registered
# → 暴露 26 个 wiki_* 工具 + wiki_search_cross + wiki_switch
```

## 对应 TUTORIAL 节

- §3.2 步骤 1-6
- §3.3 架构图
- §3.4 故障排查
