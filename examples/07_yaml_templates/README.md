# 07 — 4 个 yaml 配置模板 demo

> 对应 [docs/TUTORIAL.md §Part 3 — 功能 Playbook 索引 (07 yaml_templates)](../../docs/TUTORIAL.md#part-3--功能-playbook-索引)

## 跑法

```bash
cd examples/07_yaml_templates
PYTHONPATH=../.. python3 play.py
```

## 目标

CONFIGURATION_GUIDE.md §Use Case 1-4 列了 4 个 yaml 模板, 但 TUTORIAL
完全没引用 (Agent 3 审计发现)。这个 playbook 把模板搬到子目录并演示
如何复制 + 自定义 + 加载。

## 4 个模板

| 模板 | Use case | 关键配置 |
|---|---|---|
| `personal-kb.yaml` | 个人笔记 (offline) | `llm.enabled=false`, ollama/llama3 |
| `project-docs.yaml` | 项目文档 | OpenAI, exclude `release/^meeting/^rfc` |
| `research-wiki.yaml` | 学术研究 | OpenAI, `timeout: 180` 长超时 |
| `mining-news-wiki.yaml` | 行业新闻 | OpenAI, `^\d{4}-\d{2}-\d{2}$` 日期归档 |

模板含 2 个 section:
- `orphan_detection.exclude_patterns` — regex 跳过孤立页检测
- `orphan_detection.archive_directories` — 历史目录
- `llm.{provider, model, api_key, timeout, enabled}`

## 使用方法 (3 步)

```bash
# 1. 复制模板
cp yaml_templates/personal-kb.yaml my-config.yaml

# 2. 编辑 (改 llm 配置, 调 exclude_patterns 等)
vim my-config.yaml

# 3. 用配置 init (CLI)
llmwikify init --config my-config.yaml /path/to/wiki
```

## 涉及 API

- `yaml.safe_load(text)` — 解析
- `llmwikify.create_wiki(path)` — 用默认配置创建 wiki
- `llmwikify.interfaces.cli.commands.init_cmd.init_cmd(args)` — CLI 入口

## 对应 TUTORIAL

- **CONFIGURATION_GUIDE.md §Use Case 1-4** — 模板来源
- **TUTORIAL.md §0 决策树** — "我有个人笔记" → personal-kb

## 限制

- 当前不展示 `llmwikify init --config my-config.yaml` 完整 CLI 流程
  (需要 argparse mock, 复杂)
- 配置 apply 到 Wiki 实例需要额外 work (create_wiki 不直接读 yaml,
  需手动 parse + apply sections)
