# CLI 命令单测批次 — doctor / lint / qmd / wikis / init

日期: 2026-10-15 · 分支: v0.41-dev

## 范围

| 文件 | 测试数 | 覆盖点 |
|------|--------|--------|
| `test_doctor_cmd.py` | 65 | 全部 12 个 check helper + run_doctor JSON/文本 + DoctorCommand |
| `test_lint_cmd.py` | 29 | _lint_full/brief/recommendations 全分支 + run_lint 四格式 |
| `test_qmd_cmd.py` | 32 | 5 子命令 + subprocess mock（mcp 集成/异常） |
| `test_wikis_cmd.py` | 21 | list/add/remove/scan + registry 内存态配置 |
| `test_init_cmd.py` | 25 | run_init 全 status 分支 + LLM prompt 路径 |

合计 **172 项**（含 doctor 65），全部通过。

## 关键设计

- **doctor**: `CONFIG_PATH`/`CONFIG_DIR` 是模块级常量 → monkeypatch 到 tmp；
  LLM/server 用 fake `httpx` 注入 `sys.modules`，不碰真实 socket。
- **webui**: `Path(__file__).parent.parent.parent` 上三级 → 测试目录需 3 层深。
- **wikis**: `WikiRegistry` 是内存态，条目从 `config['wikis']['local']` 加载，
  不持久化到磁盘；测试直接构造 config 而非先 register 再 list。
- **qmd mcp**: monkeypatch `subprocess.run`，覆盖正常/FileNotFoundError/KeyboardInterrupt。
- **init LLM prompt**: `CONFIG_PATH` 在函数内 `from .init_llm_cmd import`，
  每次调用重新绑定 → patch `init_llm_cmd.CONFIG_PATH` 即可。

## 验证

```
pytest tests/interfaces/cli/ -q  → 164 passed（含既有 test_db_cmd 27）
ruff check 新 5 文件             → clean
```

## 未做

- e2e 测试（独立批次）
- 剩余 CLI: migrate_config_cmd / init_llm_cmd / graph_analyze / knowledge_gaps
- apps / interfaces-server 层缺口
