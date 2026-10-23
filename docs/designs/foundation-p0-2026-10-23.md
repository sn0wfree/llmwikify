# foundation P0 优化设计

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-23 |
| 状态 | **P0 已完成**（F1/F2/F3） |
| 范围 | foundation 热路径（lint/gaps LLM 层） |

## 问题

| ID | 问题 | 位置 |
|---|---|---|
| F1 | `_get_prompt_registry()` 每次 new → 模板 YAML 重读 | `kernel/wiki/mixins/core/utility.py` |
| F2 | `LLMClient.from_config` 每次重建 | `analyzer._llm_*` 等 |
| F3 | `extractors/text.py` `read_text()` 无 encoding | `foundation/extractors/text.py` |

## 方案

| | 改法 | 预期 |
|---|---|---|
| F1 | Wiki 缓存 PromptRegistry 实例（provider 变则重建） | 重复 LLM 调用不重读 YAML |
| F2 | 进程内 memo `from_config`（按 config 摘要/可 invalidate） | 少解析、少建 HTTP 客户端 |
| F3 | `read_text(encoding="utf-8")` | Windows 稳定 |

## 不做

streamable 拆分、双 LLM 栈合并、migration 挪位（P1）。

## 验收

- lint LLM 层连续调用不再重复加载 prompt 文件  
- 单测 / 架构检查通过  
