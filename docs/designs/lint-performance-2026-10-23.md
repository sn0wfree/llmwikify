# lint / knowledge_gaps 性能优化设计

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-23 |
| 状态 | **P0+P1+P2 已实施**（首算 27–31s，二次 ~2s） |
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
2. **P0**：lint 去重 + 共用扫描 → `perf(lint):` **472s→147s**  
3. **P1**：missing_cross_ref 重写 + 单测 → `perf(lint):` **150s→5.8s / lint 27s**  
4. **P2**：缓存 + 指纹 mtime → `perf(lint):`  
5. **验收**：profile 对比数据写回本文档

## 6. 实测（CKbase-test 1437 页）

| 阶段 | lint | missing_cross_ref | 备注 |
|---|---|---|---|
| 基线 | 472s | 150s | 规则×3 + 重复读盘 |
| P0 去重 | 147s | 150s（仍慢） | 规则只跑 1 次 |
| P0+P1 | **27s** | **5.8s** | 子串预筛 + 预编译 |
| **P0+P1+P2 二次** | **~2s** | — | 缓存命中（含 mtime 指纹） |

## 7. 第二轮瓶颈与计划（B1–B4）

| ID | 现状 | 目标 | 手段 |
|---|---|---|---|
| **B1** | 热路径 `file_fingerprint` 2.1s | **&lt;0.2s** | `os.walk` 单遍 stat；可选与 inventory 共用 |
| **B2** | `_scan_all_pages` 11.8s | **~5s** | page-name set 判存在；减少 `_resolve_wikilink_target` |
| **B3** | `missing_cross_ref` 6.0s | **~2s** | 候选预过滤（长度/路径） |
| **B4** | `outdated`+`contradiction` 8.5s | **~3s** | 复用已读正文，避免二次 IO |

顺序：B1 → B2 → B3/B4；每步实测后 `git` + 回填。

### 实测（B1–B4）

| ID | 结果 |
|---|---|
| B1 | 指纹：热 **0s**（2s memo）/ 冷 1.1s（scandir） |
| B2 | `_scan_all_pages` 11.8s → **9.4s** |
| B3 | `missing_cross_ref` 6.0s → **5.2s** |
| B4 | `run_all` 16.5s → **13.8s**（CrossPage 共用正文） |
| 合计 | lint 冷 **25.8s**，热 **0–1.2s** |

附带修复：Windows 下 `as_posix()` 页名/索引路径（破链与 fix_wikilinks 测试）。

## 8. 缓存策略定案（10 分钟复核）

| 项 | 定案 |
|---|---|
| TTL / 复核周期 | **600s** |
| 到期行为 | **验指纹**：相同 → 续期用旧结果；不同 → 重算 |
| 主动失效 | 写路径 + watcher `cache_invalidate` |
| `force=1` | 始终重算 |
| 预热/落盘 | 不做 |

```text
age < 600s  → 命中
age ≥ 600s  → 算指纹 → 同则续期 / 异则重算
写或 watch  → 立即失效
```

### 实测（S1–S3）

| 场景 | 结果 |
|---|---|
| lint 连打（缓存） | **~2–4ms** |
| 到期验指纹 | 指纹同 → 续期，不重算 |
| put_page / fix / build-index | 立即 `cache_invalidate` |
| watcher | `recursive=True` + debounce 2s → invalidate |

### 实施

| 步 | 内容 | 状态 |
|---|---|---|
| S1 | `cache_get` 到期验指纹续期；TTL=600s | ✅ |
| S2 | 写路径 invalidate | ✅ |
| S3 | wiki 目录 watcher → invalidate | ✅ |
| S4 | 测试 + 实测 | ✅ |
