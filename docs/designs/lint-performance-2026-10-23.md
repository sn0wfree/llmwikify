# lint / knowledge_gaps 性能优化设计

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-23 |
| 状态 | P0 已实施（lint 472s→147s）· P1 进行中 |
| 依据 | `scripts/profile_lint_paths.py` / `profile_lint_deep.py`（CKbase-test 1437 页） |
| 关联 | `docs/issues/llmwikify-服务响应慢诊断与修复方案-2026-10-22.md` |

---

## 1. Profile 结论

| 观测 | 耗时 | 判定 |
|---|---|---|
| `rglob` 页面清单 | 0.13s | 非瓶颈 |
| 读全库正文 ×1 | 4–8s | 中等 |
| `find_orphan_concepts`（SQL） | 0.08s | 快 |
| **`missing_cross_ref` 规则** | **150s** | **主凶：O(页²)×regex** |
| `wiki.lint()` 合计 | **472s** | **规则跑 2 次 + 重复读盘** |

`lint()` 内部重复劳动：

1. `_scan_all_pages` 读盘后，broken_link 段 **再** `_wiki_pages()+read_text` 一遍  
2. `_detect_missing_cross_refs()` 与 `_run_all_rules()` **各跑一次** `missing_cross_ref`（~300s）  
3. orphan 段再扫一遍页面列表  

## 2. 目标

| 指标 | 现状 | 目标 |
|---|---|---|
| `lint()` 首算 | ~472s | **≤30s**（P0+P1） |
| `missing_cross_ref` | 150s | **≤2s** |
| 二次调用 | 仍全量 | **&lt;0.1s**（缓存） |
| 语义 | — | 同内容 issue 列表不变 |

## 3. 方案分层

### P0 — 去重（先做，低风险）

- `lint()` 中 `missing_cross_ref` / 规则结果 **只算一次**，hints 复用  
- broken_link、orphan 与 `_scan_all_pages` **共用一次读盘/清单**  
- 预期：472s → **~150–200s**（未改算法前）

### P1 — 重写 `missing_cross_ref`

- 现：每页 × 每候选页 `re.search(\bcandidate\b)` → O(N²)  
- 改：一次分词/子串索引或集合运算，候选页名单独建索引，避免逐对 regex  
- 预期：150s → **秒级**

### P2 — 指纹缓存（与 graph 共用 `kernel/graph/cache.py`）

- `kind="lint"` / `"gaps"`；TTL 1h；`force` 重算  
- **指纹补 mtime**（否则就地改文件不失效）  
- 预期：二次调用 &lt;0.1s

### 不做（本阶段）

进程池 / 异步 job / 多 worker（视 P0+P1 后首算是否仍 &gt;60s）。

## 4. 验收

1. 同 fixture issue 列表与改前一致（顺序可变）  
2. `lint` 耗时分段记录，P0+P1 后 total **≤30s**（CKbase-test）  
3. 二次调用缓存命中；改 md/links 失效；`force=1` 重算  
4. `tests/test_v023_graph.py` + lint 相关测试通过；`check_architecture.py` 0  
5. 生产对照：tool 矩阵中 lint/gaps 耗时下降且不拖死全站（首算仍占 GIL，可接受一次）

## 5. 实施顺序（git 阶段提交）

1. **docs**：本文档  
2. **P0**：lint 去重 + 共用扫描 → `perf(lint):`  
3. **P1**：missing_cross_ref 重写 + 单测 → `perf(lint):`  
4. **P2**：缓存 + 指纹 mtime → `perf(lint):`  
5. **验收**：profile 对比数据写回本文档
