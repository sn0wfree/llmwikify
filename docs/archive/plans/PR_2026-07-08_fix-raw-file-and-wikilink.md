# PR: fix(raw-file) + wikilink/img 渲染修复 + 测试补全

## 目标

修复 4 类 WebUI/服务端的 bug，并补齐长期缺失的回归测试。

**Bug 修复（Commit 1）**：
1. **raw 文件链接双编码** → `unquote()` + 前端 `decodeURIComponent` 防双重编码
2. **wikilink 点击内容不更新** → 真正根因是 react-markdown `urlTransform` 把 `wiki-page://` 当 unsafe scheme 整个过滤掉，链接节点被删只剩纯文本
3. **img 标签走不到 file route** → 跟之前 wikilink 是同源问题，加 `img:` 组件
4. **XSS via `data:` / `javascript:`** → `isExternalUrl` 收紧为白名单 `/^(https?|mailto):/i`

**测试补全（Commit 2）**：
- `tests/test_wiki_file_route.py` +5：CJK 文件名、media-type、RFC 5987、inline disposition
- `WikiMarkdown.test.tsx`（新文件）：26 个测试覆盖 wikilink / img / regular-link / edge
- `Editor.test.tsx` +4：URL-sync + dirty-confirm
- `WikiDreamProposals.test.tsx`：mock 命名空间过时 (`dream` → `wikiDream`)，现在 3/3 通过
- `test_04_chat_react.py`：拆 test_4_3/4_4 为 `_unit` (mock) + `_e2e` (real LLM)，新增 `_get_real_jwt` 显式 PAT 验证

**测试 fixture（Commit 3）**：
- `wiki/WIKILINK_TEST.md`：常驻回归样本，访问 `/edit?page=WIKILINK_TEST` 可一键验证

## 差异

```
  3 commits ahead of origin/dev/refocus-v0.40-2026-07-05
  109e3ff  fix(ui+api): 修 raw file 双编码 + wikilink/img 渲染 + XSS 收紧
  7fdc476  test(wiki+chat): CJK 文件名 + Wikilink/img/Editor + 拆 ChatReAct
  817a506  chore(wiki): 加 WIKILINK_TEST 回归测试 fixture
```

**统计**：4 source files (fix) + 5 test files (incl 1 NEW) + 2 wiki files = 11 files, +648 / -61

## Test 验证

| 套件 | 状态 | 说明 |
|------|------|------|
| `vitest run` | ✅ 76/76 | 新 WikiMarkdown 26 + Editor 9 + 已有的 41 |
| `pytest tests/test_wiki_file_route.py` | ✅ 14/14 | 含 5 个新 CJK / RFC 5987 用例 |
| `pytest tests/scenarios/test_04_chat_react.py` | ✅ 7/7 | 2 个单元 (mock) + 2 个 e2e (real LLM) + 3 个原有 |
| `ruff check` (changed files) | ✅ clean | 91→89 errors（实际改善 2 个） |
| `tsc --noEmit` | ✅ clean | WikiMarkdown.tsx 修改无类型错误 |
| Playwright headless 手动验证 | ✅ | 之前确认过：wikilink 渲染 (24 anchors) / URL 同步 / 内容切换 / dirty-confirm 行为 |

## 关键设计决策

### 1. Bug 2 真因 ≠ 最初怀疑方向

最初以为是 `useSearchParams` 同步问题（GitHub Issue 的 dead-end）。playwright headless 测试发现 wikilink **根本没渲染成 `<a>`**——react-markdown 的 `defaultUrlTransform` 用 `safeProtocol = /^(https?|ircs?|mailto|xmpp)$/i` 白名单过滤，`wiki-page://` 被返回 `''`，整个 link 节点被替换成纯文本。

所以 "preprocessed markdown → wiki-page scheme → URL + custom handler" 的整个链路要保留，关键 fix 在 `urlTransform` 让 scheme 通过：

```ts
const urlTransform = useCallback((url: string) => {
  if (url.startsWith(WIKILINK_SCHEME)) return url;
  return defaultUrlTransform(url);
}, []);
```

### 2. fileUrl 双编码 — 测试暴露的隐藏 bug

Bug 1 修了 ASCII 路径，但 H2 测试写 CJK 时发现 fileUrl 在 `urlTransform` 已编码的 URL 上又调 `encodeURIComponent`，产生 `%25E4%25B8%25AD` 双编码。

**修复**：`decodeURIComponent` → `encodeURIComponent`（idempotent normalize + re-encode），原始路径和已编码路径都产生一致输出。

### 3. ChatReAct 测试拆分 (mock + e2e 分离)

旧测试用 hardcoded `Bearer test-token`，永远 401。修复策略：

- **`_unit` tests**：用 `httpx.MockTransport` 验证 request shape + SSE 解析，**0 token 成本**
- **`_e2e` tests**：标 `@pytest.mark.llm`，conftest 自动 skip if no API key；运行时显式 `_get_real_jwt(server_url)` 拿真 token
- PAT 缺失 → **hard-fail**（不 silent skip，符合"强制要求"原则）

这让 CI 在无 LLM key 时仍能跑单元测试，e2e 通过 `@pytest.mark.llm` 自动 skip。

### 4. WikiDreamProposals 长期静默 bug

API 表面 `dream` → `wikiDream` 改名后没更新测试 mock，所以：
- `should show loading state initially`：mock 不生效 → catch 分支 → 直接 empty state
- `should render proposal items`：mock 不生效 → proposals 从未被设置 → empty state

修复一行就 3/3 pass。**说明 **：测试 mocking 名称与实际调用名称漂移是常见隐蔽 bug——本次发现的元教训。

## 检查清单

- [x] 改动通过 `vitest run` 76/76
- [x] 改动通过 `pytest tests/` 21/21（test_wiki_file_route + test_04_chat_react）
- [x] `ruff check` 在改动文件上 clean
- [x] `tsc --noEmit` clean
- [x] 已手动重启 server 加载新 routes.py
- [x] Working tree clean
- [x] 本地 branch 与 origin 同步（push 完成）
- [x] pre-existing 失败（2 个 e2e + 1 个 ruff error 流）不在本 PR 范围内
