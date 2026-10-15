# Manual Test Plan v2 — llmwikify 全基础功能

**Date**: 2026-07-08
**Tester**: <pending>
**Environment**: `dev/refocus-v0.40-2026-07-05`, :8765, single-wiki, auth disabled
**Wiki root**: `/home/ll/llmwikify` (4 pages + 16 raw files)
**LLM**: minimax-M3 configured, PAT present
**Formats**: PASS / FAIL / SKIP / BLOCKED

---

## Phase 0 — Pre-flight (9 tests)

| ID | Test | Command | Expected | Result |
|----|------|---------|----------|--------|
| 0.1 | Server health | `curl -s :8765/api/health` | status=ok | |
| 0.2 | Version match | `jq .version <(curl -s :8765/api/health)` | matches pyproject | |
| 0.3 | LLM metrics | `curl -s :8765/api/llm-metrics` | 200 + JSON | |
| 0.4 | Doctor safe | `python -m llmwikify doctor --skip-llm` | exit 0 | |
| 0.5 | All routes non-5xx | walk 46 routes (categorized) | no 500/502/503 | |
| 0.6 | Port binding | `ss -tlnp | grep 8765` | LISTEN | |
| 0.7 | Unauth me | `curl :8765/api/auth/me` | 401 or null | |
| 0.8 | WebUI static | `curl -s :8765/ | head -10` | `<div id="root">` | |
| 0.9 | Disk sanity | `du -sh wiki/ raw/` | reasonable | |

## Phase 1 — Wiki CRUD CLI (14 tests)

| ID | Test | Command | Expected | Result |
|----|------|---------|----------|--------|
| 1.1 | write_page new | `python -m llmwikify write_page "ManualTest" "Hello"` | file created | |
| 1.2 | write_page nested | `python -m llmwikify write_page "test/nested" "Content"` | nested dir + file | |
| 1.3 | write_page CJK | `python -m llmwikify write_page "中文测试" "Hello 世界"` | CJK filename OK | |
| 1.4 | read_page norm | `python -m llmwikify read_page ManualTest` | "Hello" | |
| 1.5 | read_page 404 | `python -m llmwikify read_page NoSuchPage` | error non-zero | |
| 1.6 | build-index | `python -m llmwikify build-index` | reference_index.json updates | |
| 1.7 | lint | `python -m llmwikify lint` | 0 errors or known-isolated pages | |
| 1.8 | YAML fm escape | write page with `"` `\n` in fm | parse correctly | |
| 1.9 | log append | check log.md after ops | mtime asc | |
| 1.10 | conflict dup | write same page twice with same content | no duplicate | |
| 1.11 | large body | write 1MB content | < 2s | |
| 1.12 | empty body | write page (title only, no body) | accept | |
| 1.13 | CRLF / BOM | write + read with CRLF bytes | content preserved | |
| 1.14 | status | `python -m llmwikify status` | page_count > 0 | |

## Phase 2 — Wikilinks (11 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 2.1 | [[overview]] simple | open `/edit?page=TestCurl` | `<a data-wikilink>` rendered | |
| 2.2 | [[中文页面]] CJK | same page | CJK wikilink anchor | |
| 2.3 | [[alias|显示文本]] label | same page | shows label text | |
| 2.4 | `` in code `` | inspect DOM | NOT an `<a>` | |
| 2.5 | [[不存在]] redlink | click | friendly (no error) | |
| 2.6 | [[factor/momentum]] cross-dir | same page | navigates OK | |
| 2.7 | click redirect URL | click wikilink | `?page=X` changes | |
| 2.8 | dirty confirm | edit + click wikilink | confirm dialog | |
| 2.9 | references CLI | `python -m llmwikify references WIKILINK_TEST` | lists backlinks | |
| 2.10 | fix-wikilinks | `python -m llmwikify fix-wikilinks` | adds prefix if needed | |
| 2.11 | WIKILINK_TEST pass | manually check 4 wikilinks | all `<a data-wikilink>` | |

## Phase 3 — Search (12 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 3.1 | CLI keyword | `python -m llmwikify search "test"` | hits in result | |
| 3.2 | CLI CJK | `python -m llmwikify search "动量"` | factor/momentum | |
| 3.3 | HTTP JSON | `curl ":8765/api/wiki/search?q=test"` | 200 + shape | |
| 3.4 | multi-wiki filter | `curl "...?wiki_id=..."` | scoped results | |
| 3.5 | SearchBar UI | type in /edit top bar | dropdown ≥1 item | |
| 3.6 | empty query | type "" in searchbar | no dropdown/error | |
| 3.7 | multi-word AND | `search "AI Machine"` | both words | |
| 3.8 | snippet <mark> | inspect search result HTML | highlighted matches | |
| 3.9 | score tiebreaker | two identical matches | deterministic order | |
| 3.10 | long query 1000 chars | `search "A" * 999` | no panic | |
| 3.11 | SQL injection | `search "' OR 1=1 --"` | no data leak | |
| 3.12 | pagination | `search "a"` with many hits | limit/offset work | |

## Phase 4 — Raw Files (11 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 4.1 | ASCII png | curl `/api/wiki/file/raw/test-pixel.png` | 200 image/png | |
| 4.2 | CJK single-encode | curl `/api/wiki/file/raw/中文.png` | path single-encoded | |
| 4.3 | PDF mime | curl `/api/wiki/file/raw/1601.00991v3.pdf` | 200 app/pdf | |
| 4.4 | RFC 5987 | check response header | `inline; filename*=UTF-8''...` | |
| 4.5 | 404 JSON | curl `/api/wiki/file/raw/noexist.txt` | 404 + JSON | |
| 4.6 | Range request | `curl -H "Range: bytes=0-99" ...` | 206 + Content-Range | |
| 4.7 | Stream | `curl --no-buffer ...` | streamed | |
| 4.8 | MIME detection | test svg / json / txt | correct MIME | |
| 4.9 | Path traverse `..` | curl `?path=raw/../etc` | 403 | |
| 4.10 | null byte | curl `?path=%00` | 400 | |
| 4.11 | symlink escape | put symlink → test resolve | 403 | |

## Phase 5 — Ingest & Watcher (12 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 5.1 | md ingest | `python -m llmwikify ingest sample.md` | new page | |
| 5.2 | PDF ingest | `python -m llmwikify ingest raw/1601.00991v3.pdf` | extracted text | |
| 5.3 | batch | `python -m llmwikify batch --help` | supported | |
| 5.4 | revert | ingest then revert-by-id | page removed | |
| 5.5 | ingest log UI | `/agent/tasks` or similar | shows log | |
| 5.6 | watch | daemon mode | auto-ingest | |
| 5.7 | dedup | ingest same file twice | no duplicate page | |
| 5.8 | charset fail | malformed encoding | retryable error | |
| 5.9 | large file | 10MB txt stream parse | no OOM | |
| 5.10 | extractor pick | `--extractor=` flag | uses specified | |
| 5.11 | parallel batch | multi-file concurrent | all finish | |
| 5.12 | watch resume | stop → restart watch | catches backlog | |

## Phase 6 — WebUI Editor (18 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 6.1 | load page | /edit?page=TestCurl | content + tree | |
| 6.2 | URL sync | /edit?page=WIKILINK_TEST | content changes | |
| 6.3 | dirty dot | edit content | ● indicator | |
| 6.4 | Save enabled | after edit | Save button active | |
| 6.5 | persist | Save → F5 → reload | content stays | |
| 6.6 | back/forward | browser Back/Forward | page state correct | |
| 6.7 | wikilink nav | click `[[TestCurl]]` in WIKILINK_TEST | navigates to TestCurl | |
| 6.8 | dirty confirm guard | dirty + wikilink | confirm modal | |
| 6.9 | file tree new | New Page → type name | creates page | |
| 6.10 | EditHistory | toggle history panel | chronological list | |
| 6.11 | file tree nav | click tree node | loads content | |
| 6.12 | Ctrl+S | press Ctrl+S | saves | |
| 6.13 | script XSS | paste `<script>alert(1)</script>` | rendered escaped | |
| 6.14 | large page | open 1MB page | scrollable | |
| 6.15 | undo/redo | Ctrl+Z / Ctrl+Shift+Z | content toggles | |
| 6.16 | auto-save | dirty → wait → reload | draft restored | |
| 6.17 | save toast | Save → observe | "Saved" toast | |
| 6.18 | error toast | network fail → save | error toast | |

## Phase 7 — Insights / Dashboard (11 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 7.1 | Dashboard load | /dashboard | KnowledgeGrowth renders | |
| 7.2 | No console error | /dashboard | no JS error | |
| 7.3 | Insights load | /insights | overview renders | |
| 7.4 | Graph analysis | /insights → click graph | calls API | |
| 7.5 | synthesis suggestions | suggest-synthesis CLI | table output | |
| 7.6 | Dream list | /insights/dream | proposals listed | |
| 7.7 | Dream approve single | approve proposal | status changes | |
| 7.8 | Dream reject single | reject proposal | status changes | |
| 7.9 | Dream batch-approve | batch approve | multiple changed | |
| 7.10 | Dream apply | apply proposals | pages created | |
| 7.11 | Sink status | /insights/sink | buffer status | |

## Phase 8 — Graph (10 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 8.1 | graph-analyze | CLI analyze | PageRank output | |
| 8.2 | community-detect | CLI detect | communities found | |
| 8.3 | knowledge-gaps | CLI gaps | isolated pages listed | |
| 8.4 | export HTML | `export-graph` | .html file | |
| 8.5 | export JSON shape | export-graph --format=json | valid JSON | |
| 8.6 | export CSV | export-graph --format=csv | valid CSV | |
| 8.7 | graph-query page-level | `graph-query "TestCurl"` | neighbors shown | |
| 8.8 | graph-query path | `graph-query "TestCurl" --to "momentum"` | path found | |
| 8.9 | graph-query community | `graph-query --community 0` | members listed | |
| 8.10 | unexpected connections | `report` CLI | anomalies listed | |

## Phase 9 — Chat / Agent (19 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 9.1 | new session | POST /api/chat | session_id returned | |
| 9.2 | simple Q | "2+2=?" real LLM | "4" response | |
| 9.3 | tool call | "read wiki/TestCurl.md" | file content returned | |
| 9.4 | SSE reconnect | kill client mid-stream | auto-retry | |
| 9.5 | session history | GET /sessions | list + messages | |
| 9.6 | abort | POST abort mid-stream | stream stops gracefully | |
| 9.7 | revert | POST revert | message reverted | |
| 9.8 | /study skill | POST "/study" | research skill triggered | |
| 9.9 | confirm dialog | tool requiring confirm | dialog shown | |
| 9.10 | settings page | /agent/settings | model/temp visible | |
| 9.11 | skill loader | list available skills | skills shown | |
| 9.12 | subagent call | ask "use subagent X" | delegated | |
| 9.13 | parallel tools | 2 tools same turn | both executed | |
| 9.14 | microcompact marker | large tool result | `[Tool result compacted]` | |
| 9.15 | tool error | call nonexistent tool | error message | |
| 9.16 | WebSocket channel | ws connect | real-time events | |
| 9.17 | memory persist | after restart | facts retained | |
| 9.18 | prompt trimming | very long history | trimmed context | |
| 9.19 | message edit | PUT message | content updated | |

## Phase 10 — Auth (9 tests) — *needs `--auth` restart*

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 10.1 | Register | POST /register | admin created | |
| 10.2 | Create PAT | auth create-token | PAT returned | |
| 10.3 | No PAT | curl without token | 401 | |
| 10.4 | Bad PAT | curl with fake token | 401 | |
| 10.5 | /me identity | curl with PAT | user info | |
| 10.6 | Revoke | revoke-token | 401 after | |
| 10.7 | Re-sign | auth token | new JWT | |
| 10.8 | Logout | auth logout | token invalid | |
| 10.9 | UI redirect | / without auth | /login | |

## Phase 11 — CLI Subcommands (28 tests)

| ID | Test | Command | Expected | Result |
|----|------|---------|----------|--------|
| 11.1 | status | `python -m llmwikify status` | output | |
| 11.2 | wikis list | `python -m llmwikify wikis list` | list | |
| 11.3 | dict | `python -m llmwikify dict --help` | help | |
| 11.4 | db | `python -m llmwikify db --help` | help | |
| 11.5 | qmd | `python -m llmwikify qmd --help` | help | |
| 11.6 | log | `python -m llmwikify log --help` | help | |
| 11.7 | references TestCurl | `python -m llmwikify references TestCurl` | list | |
| 11.8 | build-index | `python -m llmwikify build-index` | builds | |
| 11.9 | sink-status | `python -m llmwikify sink-status` | status | |
| 11.10 | fix-wikilinks | `python -m llmwikify fix-wikilinks` | fixes | |
| 11.11 | report | `python -m llmwikify report` | report | |
| 11.12 | export-graph | `python -m llmwikify export-graph` | exports | |
| 11.13 | knowledge-gaps | `python -m llmwikify knowledge-gaps` | gaps | |
| 11.14 | community-detect | `python -m llmwikify community-detect` | communities | |
| 11.15 | graph-analyze | `python -m llmwikify graph-analyze` | analysis | |
| 11.16 | graph-query --help | `python -m llmwikify graph-query --help` | help | |
| 11.17 | suggest-synthesis | `python -m llmwikify suggest-synthesis` | suggestions | |
| 11.18 | synthesize | `python -m llmwikify synthesize --help` | help | |
| 11.19 | analyze-source | `python -m llmwikify analyze-source --help` | help | |
| 11.20 | batch | `python -m llmwikify batch --help` | help | |
| 11.21 | ingest | `python -m llmwikify ingest --help` | help | |
| 11.22 | watch | `python -m llmwikify watch --help` | help | |
| 11.23 | write_page | `python -m llmwikify write_page --help` | help | |
| 11.24 | read_page | `python -m llmwikify read_page --help` | help | |
| 11.25 | search | `python -m llmwikify search --help` | help | |
| 11.26 | doctor | `python -m llmwikify doctor --skip-llm` | exit 0 | |
| 11.27 | init | `python -m llmwikify init --help` | help | |
| 11.28 | init-llm | `python -m llmwikify init-llm --help` | help | |

## Phase 12 — Resiliency (12 tests)

| ID | Test | How | Expected | Result |
|----|------|-----|----------|--------|
| 12.1 | XSS render safe | write `<script>` page | escaped in HTML | |
| 12.2 | large page perf | open 1MB page | < 2s | |
| 12.3 | concurrent edit | two curl PUTs same page | first wins | |
| 12.4 | restart persist | kill → restart | data intact | |
| 12.5 | old schema compat | old wiki.md format | loads fine | |
| 12.6 | watcher OOM guard | many files | bounded | |
| 12.7 | LLM rate-limit retry | hit rate limit | backoff retry | |
| 12.8 | LLM 5xx → 503 | force 5xx | 503 to client | |
| 12.9 | network timeout | curl --max-time 1 | timeout error | |
| 12.10 | disk full | simulate df 100% | graceful error | |
| 12.11 | malformed YAML | write bad yaml | no crash | |
| 12.12 | JSON injection | write `{"$where":1}` | no injection | |

---

## Extended Phases (Phase 13-23)

*Executed after Phase 0-12 completes.*

| Phase | Tests | Priority | Layer |
|-------|-------|----------|-------|
| 13 — Memory & Dream | 10 | medium | app memory |
| 14 — Sink / Buffer | 6 | medium | kernel sink |
| 15 — Watcher | 5 | medium | kernel watch |
| 16 — MCP Integration | 8 | low | interface mcp |
| 17 — WebSocket | 6 | low | interface ws |
| 18 — Skill Pipeline | 10 | low | app chat skill |
| 19 — Multi-Wiki | 10 | low | kernel multi_wiki |
| 20 — OpenAI Compat | 6 | low | interface openai |
| 21 — Performance | 5 | low | cross-cutting |
| 22 — Security Audit | 6 | low | cross-cutting |
| 23 — i18n / Encoding | 8 | low | cross-cutting |

---

## Execution Priority

```
必跑 (smoke)         Phase 0-5 + 11        ≈ 100 tests  ~1.5h
强烈推荐 (core)      + Phase 6-10          ≈ 70 tests   ~1.5h
扩展 (full)          + Phase 13-23         ≈ 70 tests   ~2h
──────────────────────────────────────────────────────────
Total v2             Phase 0-23            ≈ 240 tests  ~5h
```

## Output

Results appended inline below as tests are executed. At end → `plan/MANUAL_TEST_RESULTS_2026-07-08.md`
