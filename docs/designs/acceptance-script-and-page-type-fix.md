# 真实 LLM 验收脚本 + ingest page_type 缺陷修复

> 分支 `feat/auto-doc-ingest` · 2026-07
> 对应「阶段 2 真实场景验收」遗留项

## 1. 验收脚本 `scripts/acceptance_real_llm.py`

原验收只在文档里留了执行结果，脚本没入库，key 恢复后无法一键复跑。
现在固化为脚本：

```bash
python scripts/acceptance_real_llm.py              # 临时 wiki，跑完即删
python scripts/acceptance_real_llm.py --keep       # 保留 wiki 目录
python scripts/acceptance_real_llm.py --wiki-root DIR
```

**关键约束：LLM 环节不做任何降级模拟。** key 无效 / provider 不可达
时 preflight 直接失败退出（exit 2）——验收的意义就在于验证真实 LLM
链路，模拟会让验收结论失真。

步骤：preflight → ingest_source → 真实 `_llm_process_source` →
`execute_operations` → `KnowledgeEnricher.enrich` → index + lint 复查。

**当前阻塞**：`~/.llmwikify/llmwikify.json` 的 `llm.api_key` 是 7 字符
占位符（`sk-tes...`），`api.minimaxi.com` 返回 401
（`authorized_error` / 1004）。换成真 key 后直接跑上面的命令即可。

脚本本身已用本地 mock OpenAI 端点验证过全链路（步骤 0-5 全通）。

## 2. ingest 丢弃 page_type（Track C 的致命缺陷）

### 现象

`generate_wiki_ops` 提示词明确要求 LLM 输出「纯名 + page_type」：

```
- Use page_type to specify directory (from wiki.md Page Types table):
  Standard: page_type="Source", page_type="Entity", page_type="Concept" ...
- The page_name should be the pure name WITHOUT "wiki/" prefix
[{"action": "write_page", "page_name": "...", "page_type": "...", ...}]
```

但 `execute_operations` 调的是 `write_page(page_name, content)` ——
**`page_type` 被丢弃**。

### 后果

1. 页面落到 wiki 根目录，而不是 `concepts/`、`sources/`
2. `collect_units` 按目录前缀分桶（`enricher.py`），前缀丢失 → **识别出
   0 个知识单元** → 补链 0 条 → **Track C 的价值整体归零**
3. `index.md` 无法按类型分组

之前用「带目录前缀的模拟 operation」做验收，恰好绕过了这个缺陷，
所以一直没暴露。真实 LLM 按提示词输出纯名，立刻触发。

### 修复

1. `page_io._resolve_page_path(page_name, page_type)` — 抽出目录解析
   逻辑（`write_page` 与 `execute_operations` 共用）
2. `relation.execute_operations` — 把 `op["page_type"]` 传给
   `write_page`，并在结果里回报**真实落盘路径**（`concepts/Risk Parity`）
   而不是 LLM 给的裸名
3. `enricher.collect_units` — 裸名页（LLM 省略 page_type）仍计入
   concept 桶，但排除 wiki 自身的结构页（index / log / overview）

### 验证

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 页面落盘位置 | wiki 根目录 | `sources/` `concepts/` |
| index 分组 | 全部平铺 | `Concepts: 1 \| Sources: 1` |
| 补链识别单元 | concepts=0 sources=0 | concepts=1 sources=1 |

- 新增 `tests/test_ingest_page_type.py`（10 tests）
- `test_maintenance_enricher.py` 28 tests 全过（原有分类契约保持）
- 受影响测试集 235 passed / 2 failed（失败为既知 CLI 未入 PATH 的
  退出码 9009）
- `test_api_routes.py` 的 400 错误契约保持不变（pydantic 校验失败
  显式转 400，不改 422）
