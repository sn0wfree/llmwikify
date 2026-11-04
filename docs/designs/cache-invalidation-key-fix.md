# 缓存失效 key 对齐 + fingerprint 错误哨兵

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查高优 #2

## 问题 1：显式失效永不命中（正确性）

- `_STORE` 的 key 来自 `wiki_cache_key(wiki)` = `str(wiki.root)`
- `cache_invalidate(str(self.wiki_dir))` 传的是 `wiki_dir`（`root/wiki`）
- 两者永不匹配 → `put_page` / `delete_page` 后的显式失效形同虚设，
  只能靠 fingerprint 变化或 TTL 兜底

`_FP_MEMO` 两边都用 `wiki_dir`，不受影响。

## 问题 2：sqlite 错误指纹与空库相同

`graph_fingerprint` 在 `sqlite3.Error` 时返回 `0:0|0:0|0:0`，
与空库指纹一致 → DB 锁定时可能把空分析结果当真缓存。

## 修复

1. `wiki_cache_key` 优先 `wiki_dir`（与 `cache_invalidate` 调用方对齐），
   回退 `root`，再回退 `id(wiki)`
2. `graph_fingerprint` 错误时返回 `-1:-1` 哨兵，与空库区分

## 验证

- 新增：`test_wiki_cache_key_matches_invalidation`（端到端 put→invalidate→miss）、
  `test_sqlite_error_distinct_from_empty_db`
- `test_graph_cache` 18 passed；`test_foundation_p0` 6 passed
- graph/lint 广回归与 stash 基线一致（17F/38P/18E，均为既存）
