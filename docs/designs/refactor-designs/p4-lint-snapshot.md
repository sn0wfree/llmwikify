# P4-a 设计：lint context 按需构建 + source 索引去 O(raw×sources) + 非 UTF-8 不再崩

**task_id**: `p4-lint-snapshot` · **decision**: `proceed`
**阶段**：Architect（只读代码 + 写设计；本任务不改任何 `src/`）
**上游证据**：`docs/designs/refactor-handoff/p4-lint-snapshot.recon.json`（候选 C1 / C2 / C9）
**方案依据**：`docs/designs/reuse-and-performance-isolation-plan.md` §P4（576–661 行）、§9 批次 3.4（840 行）
**协议**：`docs/designs/refactor-multi-agent-protocol.md` §2 / §3 / §4 / §7
**范围**：§P4 自己在 659–660 行建议的拆分 —— **P4-a**
**明确不含**：P4-b、C3、C10、C4、C5、C6、C7、C8

---

## 1. 问题与证据

### 1.1 C1 —— 缓存命中也白算一份 context

| 项 | 值 |
|---|---|
| 位置 | `kernel/wiki/engines/analyzer.py:500` `context = self._build_lint_context()` |
| 关键点 | 该语句在 `if core is None:`（:401 开始、:492 `cache_put("lint", ...)` 结束）**之外** |
| 唯一消费者 | :508 `self._llm_detect_gaps(context, missing_cross_refs=...)` → :319 `registry.get_messages("direct_lint", lint_context=context)` |
| 浪费条件 | :503–:506 `cache_get("lint_llm_gaps", wkey, fp, extra=llm_extra, ttl_s=_LINT_TTL_S)` 命中 → :508 不执行 → context 算完即被丢弃 |
| recon 实测 | core + lint_llm_gaps 双缓存命中时 `_build_lint_context` 仍被调用 **1 次**；本机（`wiki/` 仅 3 个 md 页）该次调用 2.6 ms |

**本次复核（读码，非推翻 recon）**：`context` 在 analyzer.py :498–:532 之间只出现在 :500 与 :508；`generate_investigations` 分支（:514–:532）只读 `core["contradictions"] / core["data_gaps"]`，**不读 context**。→ 把 :500 移进 `if llm_gaps is None:` 分支不改变任何输出，只是把一次无用计算变成按需计算。

### 1.2 C2 —— O(raw × sources) 嵌套扫描

| 项 | 值 |
|---|---|
| 调用点 | `analyzer.py:250-252`：`for f in sorted(raw_files)[:limit]: rel = …; source_page = self.wiki._find_source_summary_page(rel)`（最多 20 个 raw） |
| 实现 | `kernel/wiki/mixins/io/source_analysis.py:22-46` `_find_source_summary_page` |
| 快速路径 | source_analysis.py:34-36 `candidate = sources_dir / f"{slug}.md"` + `candidate.exists()` → 命中即返回，**0 次读** |
| 慢路径 | source_analysis.py:39-44 `for page in sources_dir.rglob("*.md")` + 逐页 `page.read_text(encoding="utf-8")`，命中 `source_ref in content or source_path in content`（:43） |
| 复杂度 | O(min(20, raw) × sources) 次读；每次未命中快速路径的 raw 触发一次**全目录扫** |
| recon 实测 | 合成 wiki（361 页 / 120 raw / 60 sources / 400 relations）：`_build_lint_context()` = 72.18 ms，其中 20 次 `_find_source_summary_page` = **62.35 ms（约 86%）**；单次全扫 60 个 source 页 = 4.87 ms；20 个 raw 中 **8 个无同名 source 页 → 8 次全目录扫**（20 次全 miss 约 97.48 ms） |

### 1.3 C9 —— 无效重试 + 非 UTF-8 崩溃（且崩溃面比 recon 列的更大）

**事实核对（本次实测，已复现）**：

```
UnicodeDecodeError.__mro__ = (UnicodeDecodeError, UnicodeError, ValueError, Exception, BaseException, object)
safe_read_text(<含 \xff 的文件>) → RAISED UnicodeDecodeError
except (ValueError, OSError) → caught by (ValueError, OSError): UnicodeDecodeError
```

→ `UnicodeDecodeError` **不是 `OSError` 的子类**，但**是 `ValueError` 的子类**。方案文档 §P4 第 629 行「项目里已有正确写法：`foundation/io.py:50-66` `safe_read_text`」**只有一半对**：`safe_read_text` 只 `except OSError`（foundation/io.py:62-65），对非 UTF-8 文件照样抛。详见 §4。

**recon 实测**：写入含 `\xff` 非法字节的页面后，`analyzer._scan_all_pages()` 与 `wiki.lint()` 均 `RAISED UnicodeDecodeError`（lint 崩溃 → HTTP 500）；而 `_run_all_rules()` 中 contradiction / data_gap / missing_cross_ref / potentially_outdated 4 条规则抛出的 `UnicodeDecodeError` 被 `lint/__init__.py:188-189` 的 `except Exception` 吞掉只留 warning → **一个坏页面静默关掉 4/8 条规则，而 lint 仍返回「成功」**。

**本次复核补强（recon 未列全，但都在本轮 3 个文件内）**：

| 崩溃点 | 属谁 | 处置 |
|---|---|---|
| `analyzer.py:60` `self.wiki._should_exclude_orphan(name, page)` → `status.py:30-31` 裸 `read_text(encoding="utf-8")` | **这是 `_scan_all_pages` 的第一个崩溃点**（在 :64 之前） | status.py 因 C4 有他人未提交改动 → 本轮不可改 → **在 analyzer.py:60 调用点兜底**（§3.2 D4） |
| `lint/__init__.py:68` `Rule.run` 的 `content = page.read_text(encoding="utf-8")` | **6 条普通规则的入口**（recon 只列了 :118-121） | 同文件同改法（§3.2 D5） |
| `lint/__init__.py:118-121` `Rule._load_pages` | 2 条 CrossPageRule 的入口（`lint/__init__.py:182`） | 同上 |
| `analyzer.py:231` `wiki_md_file.read_text(encoding="utf-8")` | context 构建 | 同文件，1 行（§3.2 D6，标注为可选加固） |
| `source_analysis.py:42` source 页裸读 | context 构建 | 本轮本来就要重写这段（§3.3） |
| `source_analysis.py:68` `_get_cached_source_analysis` 的 `except (ValueError, OSError)` | **已经安全** —— `UnicodeDecodeError` 是 `ValueError` 子类 → `backend.py:280` 的读被兜住，返回 `None` → context 记 `[NOT ANALYZED]` | 不动 |

**「无效重试」**：analyzer.py:63-66 与 lint/__init__.py:118-121 两处 `except TypeError:` 分支的实参与 `try` 块**完全相同**（都传了 `encoding=`）→ 永不生效。方案文档 §P4 第 622-631 行已记录，本设计把它和「不捕获 `UnicodeDecodeError`」合并成一处改动。

---

## 2. 边界（一句话）

**在 `kernel/wiki` 内做三件事**：① lint 的 LLM context 只在 `lint_llm_gaps` 缓存未命中时构建；② source 摘要页查找由「每个 raw 扫一遍 sources 目录」改为「一次扫描 → 映射」；③ lint 路径上的页面读取改为有损 UTF-8 读取，使非 UTF-8 页面不再让 lint 崩溃、也不再静默关掉规则。**不引入快照对象、不改 8 条规则签名、不动 HTTP 层、不动 foundation。**

**允许的行为变化（仅此两处）**

| 变化 | 触发条件 | 回归测试 |
|---|---|---|
| 不再崩溃 | 存在非 UTF-8 的 wiki 页面 / source 页面 | `test_lint_survives_non_utf8_page` |
| 不再做无效计算 | `lint_llm_gaps` 缓存命中 | `test_context_not_built_when_llm_gaps_cached` |

**其余一律保持一致**：context 文本逐字符不变、`lint()` 返回结构不变、缓存 key 与 extra 不变、`_find_source_summary_page` 的签名与逐路径语义不变。

---

## 3. 决策与目标文件（3 个源文件）

| # | 文件 | 改动 | 现状行号 |
|---|---|---|---|
| 1 | `src/llmwikify/kernel/wiki/engines/analyzer.py` | D1 context 位置 / D4 兜底 / D5 有损读 / D6 wiki.md / D7 一次映射 | :60, :63-66, :231, :250-252, :498-511 |
| 2 | `src/llmwikify/kernel/wiki/lint/__init__.py` | D5 有损读（**两处**） | :68, :118-121 |
| 3 | `src/llmwikify/kernel/wiki/mixins/io/source_analysis.py` | D7 新增映射构建器 + 委托 + 有损读 | :22-46, :42 |

### 3.1 D1 —— context 只在需要时构建（analyzer.py:498-511）

现状：

```python
500:  context = self._build_lint_context()
501:  llm_extra = self._llm_cache_extra("direct_lint", limit)
502:  llm_gaps = None
503:  if not force:
504:      llm_gaps = cache_get("lint_llm_gaps", wkey, fp, extra=llm_extra, ttl_s=_LINT_TTL_S)
507:  if llm_gaps is None:
508:      llm_gaps = self._llm_detect_gaps(context, missing_cross_refs=core.get("missing_cross_refs", []))[:limit]
511:      cache_put("lint_llm_gaps", wkey, fp, llm_gaps, extra=llm_extra)
```

改后（**只移动一行**，不新增分支）：

```python
     llm_extra = self._llm_cache_extra("direct_lint", limit)
     llm_gaps = None
     if not force:
         llm_gaps = cache_get("lint_llm_gaps", wkey, fp, extra=llm_extra, ttl_s=_LINT_TTL_S)
     if llm_gaps is None:
         context = self._build_lint_context()          # ← 移到这里
         llm_gaps = self._llm_detect_gaps(context, missing_cross_refs=core.get("missing_cross_refs", []))[:limit]
         cache_put("lint_llm_gaps", wkey, fp, llm_gaps, extra=llm_extra)
```

等价性：`context` 只有一个消费者（:508），且 :508 只在 `llm_gaps is None` 分支执行 → 移动后 `context` 的取值时机与内容不变，只是缓存命中时不再计算。

### 3.2 D4 / D5 / D6 —— 非 UTF-8 不再崩（有损读）

**统一采用 `read_text(encoding="utf-8", errors="replace")`**（理由见 §4）。落地三处：

**(a) analyzer.py:58-67 `_scan_all_pages`**

```python
for page in self.wiki._wiki_pages():
    name = self.wiki._page_display_name(page)
    try:
        excluded = self.wiki._should_exclude_orphan(name, page)   # status.py:31 可能抛 UnicodeDecodeError
    except UnicodeDecodeError:
        excluded = False        # fail-open：读不动 frontmatter ⇒ 不排除该页
    if excluded:
        continue
    page_names.append(name)
    content = page.read_text(encoding="utf-8", errors="replace")  # 替代 :63-66 的无效重试
    contents.append((name, content))
```

* `except UnicodeDecodeError` 只可能来自 `_should_exclude_orphan`（status.py:30-31），因为本页自己的读已是有损读。
* **fail-open 的理由**：无法解码 ⇒ 无法判定 frontmatter 排除键 ⇒ 选择「不排除」，这样该页仍进入 `page_names` / `contents`，与规则侧（有损读后仍然处理该页）保持一致；否则会出现「规则处理了 N 页、扫描只处理 N-1 页」的口径分裂。
* **不改 status.py**（C4：他人未提交改动，本轮不碰）。

**(b) lint/__init__.py:68 `Rule.run`**

```python
content = page.read_text(encoding="utf-8", errors="replace")
```

**(c) lint/__init__.py:118-121 `Rule._load_pages`**

```python
pages[name] = page.read_text(encoding="utf-8", errors="replace")
```

（删除永不生效的 `except TypeError:` 分支 —— 它是死代码，保留会让读者以为还有兜底。）

**(d) analyzer.py:231（标注为「同文件 1 行加固」，实现者可与 (a)(b)(c) 一并做）**

```python
wiki_md = self.wiki.wiki_md_file.read_text(encoding="utf-8", errors="replace")
```

理由：`wiki.md` 非 UTF-8 时 `wiki.lint()` 同样会 500，属于 C9 的同一崩溃面；改动在同一个文件、同一个函数内，1 行。

### 3.3 D7 —— source 摘要页：一次扫描 → 映射

**新增（`kernel/wiki/mixins/io/source_analysis.py`，层：kernel）**

```python
def _build_source_summary_map(
    self, source_paths: Sequence[str]
) -> dict[str, Path | None]:
    """Map each raw source path → its Source summary page (None if none).

    One pass over ``wiki/sources`` shared by every path, instead of one
    full-directory scan per path. Per-path semantics are identical to
    :meth:`_find_source_summary_page`:

    1. slug fast path  — ``sources/<slug>.md`` exists → that page;
    2. otherwise the first page (in ``rglob`` order, skipping excluded
       paths) whose content contains ``(raw/<basename>)`` or the source
       path itself.
    """
```

**改写（同一文件）**

```python
def _find_source_summary_page(self, source_path: str) -> Path | None:
    """(docstring 不变) —— 委托给映射构建器，语义逐路径不变。"""
    return self._build_source_summary_map([source_path]).get(source_path)
```

签名**不变** → 另两个调用点（`source_analysis.py:105` `analyze_source`、`engines/synthesis.py:108`）零感知。

**算法（保持与原 :34-44 逐字同构）**

```
result = {}; pending = []
for p in source_paths:                       # 保持入参顺序
    cand = sources_dir / f"{_slugify(Path(p).stem)}.md"
    if cand.exists():                        # 原 :34-36 快速路径
        result[p] = cand
    else:
        pending.append(p)
if pending:                                  # 只有确实需要才扫目录
    for page in sources_dir.rglob("*.md"):   # 原 :39 的 rglob 顺序
        if is_path_excluded(page): continue  # 原 :40-41
        content = page.read_text(encoding="utf-8", errors="replace")   # 原 :42（有损读）
        for p in list(pending):
            if f"(raw/{Path(p).name})" in content or p in content:   # 原 :43 同谓词
                result[p] = page
                pending.remove(p)
        if not pending: break
for p in pending: result[p] = None
return result
```

**等价性论证（逐条）**

1. **优先级**：快速路径先于慢路径 —— 与原 `_find_source_summary_page`（:34-36 在 :39 之前）一致。
2. **匹配谓词**：`(raw/{basename}) in content or source_path in content` —— 与原 :43 **逐字相同**（含 `source_ref = f"(raw/{Path(source_path).name})"`，原 :38）。
3. **并列取舍**：原实现对每个路径独立扫、返回 rglob 顺序里第一个命中的页；新实现同样按 rglob 顺序、对每个 pending 独立取第一个命中的页 → 结果一致。
4. **读次数**：新 = `max_p(命中页序号+1)`；原 = `Σ_p(命中页序号+1)` → **新 ≤ 原，永不更多**。全部走快速路径时原读 0 次，新也读 0 次（`pending` 为空 → 不扫目录）。
5. **遍历次数**：`sources_dir.rglob` 由「每个未命中快速路径的 raw 一次」（recon 实测 8 次）降为**最多 1 次**。

**调用点改造（analyzer.py:246-252）**

```python
selected = sorted(raw_files)[:limit]                      # 原 :250 的同一集合与顺序
source_pages = self.wiki._build_source_summary_map(
    [str(f.relative_to(self.wiki.root)) for f in selected]
)
for f in selected:
    rel = str(f.relative_to(self.wiki.root))
    source_page = source_pages.get(rel)                   # 原 :252 的等价物
```

`rel` 的构造方式（`str(f.relative_to(self.wiki.root))`）与原 :251 逐字一致；`sorted(raw_files)[:limit]` 与原 :250 一致 → 被查询的 raw 集合与顺序不变。

---

## 4. `safe_read_text` 的处理方式：取舍论证

**结论：不使用 `safe_read_text`，也不修改它；在 lint 侧直接用 `read_text(encoding="utf-8", errors="replace")`。**

### 4.1 事实核对

| 事实 | 证据 |
|---|---|
| `safe_read_text` 只捕获 `OSError` | `foundation/io.py:62-65` `try: return path.read_text(encoding="utf-8") / except OSError: return default` |
| `UnicodeDecodeError` 不是 `OSError` 子类 | MRO = UnicodeDecodeError → UnicodeError → **ValueError** → Exception |
| `safe_read_text` 对非 UTF-8 文件照样抛 | 本次实测 `RAISED UnicodeDecodeError` |
| `safe_read_text` 目前**没有任何生产调用点** | 全仓仅 `foundation/io.py:102` 的 `__all__` 导出 + `tests/test_foundation_io.py:136-152`；无 `src/` 内调用 |
| 真正能处理的是 `errors="replace"` | `kernel/storage/index.py:181` `md_file.read_text(errors="replace", encoding="utf-8")`；另有 `apps/chat/skills/workflows/subagent_worker.py:787`、`scripts/profile_lint_paths.py:46/55/86` |

### 4.2 三个选项

**选项 A —— 扩展 `foundation/io.py::safe_read_text`，让它额外捕获 `UnicodeDecodeError`（方案文档的写法）**

* 好处：一个共享入口，未来调用点自动受益。
* 否决理由：
  1. **语义更差**：`safe_read_text` 失败时返回 `default`（默认 `""`）→ 非 UTF-8 页面会变成**整页空白**，规则看到的是空内容而不是「有效部分 + 替换符」。要修好还得把 `default` 改成 `None` 并让每个调用点自己判空 → 契约变更 + 每个调用点都要改。
  2. **改的是 foundation 的公开工具**：`foundation/io.py` 有 `__all__` 导出（:99-105），属对外契约；改它会波及未来所有调用点，且当前无生产调用点 → 收益为零、风险不为零。
  3. **超出本轮文件预算**（≤3 个源文件）：加 `foundation/io.py` 就是第 4 个。
  4. **多一次 stat**：`safe_read_text` 先 `path.exists()` 再 `read_text` → 2 次文件系统操作；`read_text(errors="replace")` 是 1 次 open+read（热路径上是净收益）。

**选项 B —— lint 侧局部用 `errors="replace"`（与 `kernel/storage/index.py:181` 一致）✅ 采纳**

* 好处：
  1. 与 kernel 内既有的「读可能非 UTF-8 的 markdown」写法**完全一致**（`kernel/storage/index.py:181`）；
  2. 保留页面的**可读部分**（非法字节替换为 `U+FFFD`），既不丢整页（选项 A 的问题）也不丢非法字节（`errors="ignore"`，见 `lint/rules/dated_claims.py:40`）；
  3. **零 foundation 改动** → 无公开契约变更、无跨模块语义漂移，回滚是单文件 revert；
  4. **不新增符号** → 不新增公开接口，不需要动 `protocols.py`；
  5. 与 lint 路径的既有先例一致：`lint/rules/dated_claims.py:40` 早就在用 `read_text(errors="ignore", encoding="utf-8")` —— 说明「规则可以接受有损内容」在本仓已是既定事实，本次只是把其它读点对齐。
* 代价：同一句式出现 5 次（analyzer.py 3 处、lint/__init__.py 2 处、source_analysis.py 1 处 → 实为 6 处调用点）。
  * 对照协议 §7 红线 3「三次出现再抽象」：这里抽出来会得到一个**只包一行 stdlib 调用**的转发函数，不是领域抽象（协议 §7 红线 2 禁止万能工具类），且要放进 `foundation/io.py` 就超预算、放进 `kernel/wiki/lint/__init__.py` 则会被 `mixins/io/source_analysis.py` 反向 import（`lint/__init__.py` 依赖 rules → 有循环 import 风险）。
  * 因此本轮**内联**，并在 §10 记一条后续项：若将来第 4 个文件也要用，正确做法是在 `foundation/io.py` **新增** `read_text_lossy(path) -> str`（而不是改 `safe_read_text` 的契约），单独一个任务做。

**选项 C —— 在 lint 侧用 `errors="ignore"`（`dated_claims.py:40` 的写法）**

* 否决理由：会**静默丢弃**非法字节及其后的内容差异；`replace` 至少保留了「这里原本有个坏字节」的位置信息，且与 `kernel/storage/index.py:181` 一致。

### 4.3 副作用声明

`errors="replace"` 只影响**非 UTF-8 文件**的内容；UTF-8 文件的读取结果**逐字节不变** → 对正常 wiki 零行为差异。

---

## 5. 接口签名（新增/变更符号全表）

**不新增公开接口。** 新增的 1 个符号是下划线私有的 mixin 方法，与既有 `_find_source_summary_page` 同级。

| 符号 | 层 / 文件 | 签名 | 状态 |
|---|---|---|---|
| `_build_source_summary_map` | `kernel` / `kernel/wiki/mixins/io/source_analysis.py`（`WikiSourceAnalysisMixin`） | `def _build_source_summary_map(self, source_paths: Sequence[str]) -> dict[str, Path | None]:` | **新增** |
| `_find_source_summary_page` | 同上 | `def _find_source_summary_page(self, source_path: str) -> Path | None:` | 签名不变，改为委托 |
| `WikiAnalyzer._build_lint_context` | `kernel` / `kernel/wiki/engines/analyzer.py` | `def _build_lint_context(self, limit: int = 20) -> str:` | 签名不变，内部改用映射 |
| `WikiAnalyzer._scan_all_pages` | 同上 | `def _scan_all_pages(self) -> tuple[dict[str, int], set[str], list[dict]]:` | 签名不变 |
| `WikiAnalyzer.lint` | 同上 | `def lint(self, mode: str = "check", limit: int = 10, force: bool = False, generate_investigations: bool = False) -> dict:` | 签名不变 |
| `Rule.run` / `Rule._load_pages` | `kernel` / `kernel/wiki/lint/__init__.py` | 不变 | 内部读法变 |

* `Sequence` 需 `from collections.abc import Sequence`（stdlib，不影响分层）。
* `Wiki` 在 `kernel/wiki/wiki.py:31-37` 已继承 `WikiSourceAnalysisMixin` → `self.wiki._build_source_summary_map(...)` 在 analyzer.py 里可直接解析（analyzer.py:16-17 的 `TYPE_CHECKING` 导入给出 `Wiki` 类型）→ **不需要改 `kernel/wiki/protocols.py`**（该文件本就未声明 `_find_source_summary_page`，见 protocols.py:63-84）。
* `_build_source_summary_map` 的 `max_params` = 2（含 self）≤ 3 ✓。

---

## 6. 数据流

**改动前**

```
lint()
 ├─ cache_get("lint")            ──命中──► core
 ├─ (core is None) _scan_all_pages / _run_all_rules / sink
 ├─ context = _build_lint_context()          ← 无条件（:500）
 │    ├─ wiki.md read (:231)
 │    ├─ _get_existing_page_names()  (utility.py:143 rglob)
 │    ├─ raw_dir.rglob("*")
 │    └─ for raw in top20: _find_source_summary_page(rel)      ← :250-252
 │         └─ (slug miss) sources_dir.rglob + 逐页 read_text     ← source_analysis.py:39-44
 └─ cache_get("lint_llm_gaps")  ──命中──► llm_gaps（context 白算）
```

**改动后**

```
lint()
 ├─ cache_get("lint")            ──命中──► core
 ├─ (core is None) _scan_all_pages / _run_all_rules / sink
 ├─ cache_get("lint_llm_gaps")
 │    └─ 命中 ──────────────────────────────► llm_gaps（**不再构建 context**）
 │    └─ 未命中 ► context = _build_lint_context()
 │                  ├─ wiki.md read (:231, 有损)
 │                  ├─ _get_existing_page_names()  (utility.py:143 rglob)
 │                  ├─ raw_dir.rglob("*")
 │                  └─ _build_source_summary_map(rels)   ← **一次扫描**
 │                       ├─ per-raw slug 快速路径（0 次读）
 │                       └─ pending 非空 ⇒ sources_dir.rglob 1 次 + 逐页读 1 次
 └─ _llm_detect_gaps(context, ...)  (仅未命中分支)
```

**C9 数据流**

```
wiki 页（非 UTF-8）
 ├─ _scan_all_pages → _should_exclude_orphan → status.py:31
 │      ⇒ UnicodeDecodeError ⇒ analyzer.py 调用点捕获 ⇒ fail-open（不排除该页）
 ├─ analyzer.py:64 有损读 ⇒ 内容保留可读部分
 ├─ lint/__init__.py:68 / :119 有损读 ⇒ 8 条规则全部执行，不再被 :188 静默吞掉
 └─ lint() 正常返回（HTTP 200），不再 500
```

---

## 7. 依赖方向

* 三个目标文件全在 `kernel/` 内；**不新增任何跨层 import**：
  * `source_analysis.py` 已有 `from llmwikify.kernel.storage.backend import is_path_excluded`（:7）→ 复用，不新增；
  * 新增的 `collections.abc.Sequence` 是 stdlib；
  * `analyzer.py` → `self.wiki._build_source_summary_map(...)` 是同层 mixin 调用。
* `kernel` 不 import `apps` / `reproduction`；`foundation` **完全不动** → 依赖方向不变。
* **验收**：`D:\tools\python312\python.exe scripts/check_architecture.py` 必须仍报 **0 violations**（实现者提交前必跑）。

---

## 8. 成功如何度量（计数型基准）

> 本机 `wiki/` 只有 3 个 md 页（recon 已记录），墙钟不可信 → **门禁指标必须是计数**，墙钟只作辅助信号。

### 8.1 新增测试文件 `tests/test_lint_read_counts.py`（建议命名）

| 测试 | 断言（计数） | 改动前 | 改动后 |
|---|---|---|---|
| `test_sources_directory_scanned_at_most_once` | monkeypatch `pathlib.Path.read_text` / `Path.rglob` 计数：context 构建期间 `wiki/sources/**` 的 **rglob 次数 == 1**、**read_text 次数 ≤ source 页数** | rglob **9** 次（recon C10，151 页 / 30 sources 合成 wiki）；read ≈ **8×60=480** 次（recon C2，361 页 / 60 sources 合成 wiki，20 个 raw 中 8 个无同名 source 页） | rglob **1** 次、read **≤ source 页数** |
| `test_context_not_built_when_llm_gaps_cached` | 预热 `lint_llm_gaps` 缓存后调 `wiki.lint()`，`_build_lint_context` **调用次数 == 0** | 1 次（recon 实测） | **0 次** |
| `test_lint_survives_non_utf8_page` | 写入含 `\xff` 的页面 → `wiki.lint()` **不抛异常**；`caplog` 中**没有** `"lint rule … failed"` 记录（证明 8/8 条规则都跑了，不是 4/8） | 抛 `UnicodeDecodeError`；4 条规则被静默吞掉 | 不抛；8/8 规则执行 |
| `test_source_summary_map_matches_per_path_lookup` | 固定 fixture（slug 命中 / 正文引用命中 / 无命中 / 嵌套 raw 路径）→ 映射结果与逐路径期望**逐项相等** | — | 恒等 |
| `test_context_text_unchanged_for_known_layout` | 20 raw（12 个有同名 source 页、8 个没有）→ context 中 12 条走 `[NOT ANALYZED]`/`[NO SOURCE PAGE]` 的**标记分布与改动前逐字一致** | — | 逐字一致 |

### 8.2 基准命令（写进 `design.json.performance_constraints.benchmark_command`）

```powershell
D:\tools\python312\python.exe -m pytest tests/test_lint_read_counts.py -q -s --rootdir=D:\Github\llmwikify
```

该测试用 `-s` **打印**计数器（sources rglob 次数 / sources read_text 次数 / `_build_lint_context` 调用次数 / 执行了的规则数），Benchmarker 在**改动前后的同一个 commit 序列**上各跑一次 → 得到同口径的 before/after 数字写进 `p4-lint-snapshot.bench.json` 的 `before` / `after`。

辅助（非门禁）墙钟信号，需一台有 1400 页真实 wiki 的机器：

```powershell
D:\tools\python312\python.exe scripts/profile_lint_paths.py --wiki <真实 wiki 路径>
```

### 8.3 计数型复杂度声明（design.json 同款）

* **改动前**：sources 目录读次数 `O(min(20, raw) × sources)`（recon 实测 8 次全扫 ≈ 480 次读）；`lint_llm_gaps` 缓存命中时仍 1 次 `_build_lint_context`。
* **改动后**：sources 目录读次数 `O(sources)`（**最多 1 次扫描**）；`lint_llm_gaps` 缓存命中时 `_build_lint_context` **0 次**。

---

## 9. 回滚策略

* **无 feature flag、无开关**（协议 §8：回退策略改为「独立 commit 可 revert」）。
* 拆成 **3 个自洽 commit**，每个 ≤3 文件、可独立 revert：

| commit | 内容 | 文件 | revert 后回到 |
|---|---|---|---|
| A `fix(lint): 非 UTF-8 页面不再让 lint 崩溃` | D4/D5/D6（analyzer.py + lint/__init__.py + source_analysis.py 的有损读） | 3 | 崩溃行为（但 C2 尚未引入） |
| B `perf(lint): LLM context 仅在缓存未命中时构建` | D1 | 1 | 现状（context 无条件构建） |
| C `perf(lint): source 摘要页一次扫描去 O(raw×sources)` | D7 | 2 | 现状（逐 raw 全扫） |

  * A 与 C 都会碰 `analyzer.py` / `source_analysis.py` → 顺序执行，不并行（协议 §5）。
  * 任意一个 commit revert 后，代码仍自洽：A 依赖 C2 之前也成立；C 依赖 A 也成立。
* **commit 纪律**（AGENTS.md + 协议 §6）：`fix` 与其测试同一个 commit；提交前 `git status`（报告 6 个既有未提交改动 + 本任务的 2 个新文件）+ `git diff --stat` + `ruff check` + `pytest` + 用户确认清单；行尾按 `git ls-files --eol` 复核 `i/lf w/crlf`。

---

## 10. do_not 清单

**协议 §2 / 方案文档已要求的（必须遵守）**

1. **不做 P4-b**：不引入全量 `PageSnapshot` / `PageSource`，不改 8 条规则的签名，不改 `Rule.run` / `Rule._load_pages` / `detect` / `detect_all` 的入参形态。
2. **不改 HTTP 路由的 async/sync**：C7（`interfaces/server/http/wiki/wiki_routes.py:118`）归批次 1 的 1.5 项，**不混入本任务**。
3. **不引入 CommonUtils / 万能工具类**（协议 §7 红线 2）。
4. **不做 feature flag / 开关**：回滚靠独立 commit（§9）。
5. **不改公开 API 契约**：`lint()` / `wiki.lint()` 返回结构、缓存 key（`lint` / `lint_llm_gaps` / `lint_llm_invest`）与 `extra` 语义、`_find_source_summary_page` 的签名，全部不变。

**本设计新增的（方案文档 §P4 未写）**

6. **不改 `foundation/io.py::safe_read_text` 的契约**，也不新增 foundation 工具函数（§4 的取舍）。连带不动 `safe_write_text` / `read_json` / `read_yaml`。
7. **不碰 `kernel/wiki/mixins/analysis/status.py`**（C4，有他人未提交改动）→ 改为在 `analyzer.py:60` 调用点兜底（§3.2 D4）。
8. **不碰 `kernel/wiki/lint/rules/*`**（含 `knowledge_gaps.py:63` 的 source 页裸读、`dated_claims.py:40` 的既有 `errors="ignore"`）—— 规则内部改造属 P4-b。
9. **不碰 `kernel/storage/backend.py`**（:280 source cache 读）—— 已由 `source_analysis.py:68` 的 `except (ValueError, OSError)` 兜住（`UnicodeDecodeError` ⊂ `ValueError`）。
10. **不碰 `kernel/wiki/protocols.py`**：新方法是 mixin 私有方法，`Wiki` 已继承该 mixin（`wiki.py:31-37`）。
11. **不新增缓存/记忆化到 Wiki 实例上**：不把页面内容跨请求缓存（避免陈旧读 + 与 P4-b 的快照语义冲突）。
12. **不改 `_build_lint_context` 的输出文本**：context 字符串必须逐字符等价（只允许「不再算」与「有损读」两处差异）。
13. **不引入新模块/新文件**（源文件 ≤ 3；测试文件不计入）。
14. **不做墙钟断言**：门禁基准必须是计数型（§8）。
15. **不在 `apps/` / `interfaces/` / `reproduction/` 加任何代码**；不新增跨层 import。
16. **不重构 `analyzer.py` 里与本任务无关的部分**（`_fallback_detect_gaps`、sink、investigations 等一律不动）。
17. **不改 `_build_lint_context` 的 `limit` 语义**：`limit` 默认仍是 20（recon C2 note：lint() 的 `limit` 只裁 LLM gaps，不传进 context 构建 —— 本轮不改这个行为）。

---

## 11. 已知残留风险（本轮不修，需单独立项）

| # | 风险 | 位置 | 影响 |
|---|---|---|---|
| R1 | 非 UTF-8 的 **source 摘要页**仍会让 `knowledge_gap` 规则抛异常，被 `lint/__init__.py:188` 吞掉 → 该规则静默失效 | `lint/rules/knowledge_gaps.py:63` | 1 条规则失效（不崩）。属 P4-b |
| R2 | 非 UTF-8 页面在 **CLI references** 路径仍会崩 | `interfaces/cli/commands/references.py:28` → `status.py:31` | CLI 崩溃（非 lint 路径）。属 C4 |
| R3 | **analyze-source** 路径读 raw 文件仍用裸读 | `source_analysis.py:19` / `:118` | analyze-source 崩溃（非 lint 路径） |
| R4 | 6 条普通规则仍各自重读全量页面 | `lint/__init__.py:58-72` + `:112-122` | O(规则数 × 页面数) 次读 —— **C3，属 P4-b** |
| R5 | context 内两套遍历仍在 | `analyzer.py:234` vs `utility.py:143` | **C10，属 P4-b** |
| R6 | 真实 wiki（1400 页）上的绝对耗时未测 | — | 本机仅 3 页 wiki；需 `scripts/profile_lint_paths.py --wiki <真实路径>` 在有真实 wiki 的机器上补测（§8.2 辅助） |
| R7 | `wiki.md` 非 UTF-8 时 `wiki.lint()` 的表现 | `analyzer.py:231` | 本轮已按 D6 加固（标注为可选，实施者若不做需在 implement.json 说明） |
| R8 | **fail-open 的连带副作用**：坏字节让 `status.py` 的裸读先抛异常 → `_exclude_frontmatter_keys` 与 `_archive_dirs` **两个排除判定都不执行** → 本该被排除的页面被纳入扫描 | `mixins/analysis/status.py:30-31`（裸读）早于 `:32-34`（frontmatter 排除）与 `:36-40`（archive 排除） | 误报：archive 目录下的页面、带排除键的页面被当成 orphan 候选。详见 §11.1 |
| R9 | **U+FFFD 假阳性**：`errors="replace"` 把非法字节变成正文里的**真实字符** U+FFFD，凭空造出 lint 假阳性 | `lint/__init__.py:68` / `:112-119`、`analyzer.py:71` | 假 `broken_link`（坏字节落在 `[[...]]` 目标内）、假 `value_conflict`（坏字节落在 `key: value` 值尾）。详见 §11.2 |

### 11.1 R8 —— fail-open 的连带副作用：两项排除机制同时失效

**触发条件**：页面含非法字节（不是合法 UTF-8）**且**该页面命中
`_exclude_frontmatter_keys`（如 frontmatter 里 `draft: true`）
**或**落在 `_archive_dirs`（如 `archive/`）目录下。

**机理**：`_should_exclude_orphan()` 的裸读（`status.py:30-31`）排在两个
排除判定**之前**。坏字节让这次读先抛 `UnicodeDecodeError`，
`analyzer.py:60-67` 的 fail-open 兜底把 `excluded` 置为 `False` ——
两个排除分支于是**都没有机会执行**，页面照常进入扫描。

**实测证据**（探针 `.analysis_tmp/probe_p4_residual.py`，2026-10-28）：

- `_archive_dirs={'archive'}` + `wiki/archive/Old.md` 含 `\xff`：
  `_should_exclude_orphan` 抛 `UnicodeDecodeError`；`orphan_candidates`
  含 `archive/Old`。**同一布局换成合法 UTF-8** → `orphan_candidates`
  不含 `archive/Old`（排除生效）→ 差异只由坏字节引起。
- `_exclude_frontmatter_keys=['draft']` + `wiki/Draft.md`（含
  `draft: true`）含 `\xff`：同样抛异常，`orphan_candidates` 含 `Draft`。

**本轮不修**：`mixins/analysis/status.py` 正被并行 writer 修改，本轮改它
会写冲突；该文件也不在 P4-a 的目标文件清单内（§3）。

**将来该在哪一层修**：修 `_should_exclude_orphan` 内部（`status.py`）——
把裸读换成有损读（`errors="replace"`），或把 archive 判定（只依赖路径，
不依赖文件内容）提到读之前、frontmatter 判定改在有损读上做。修好后
`analyzer.py` 的 fail-open 兜底仍可保留，它就不再影响排除逻辑。

### 11.2 R9 —— U+FFFD 造成的 lint 假阳性

**触发条件**：非法字节落在会被 lint 规则解析的位置——

- 落在 `[[...]]` 链接目标内 → 目标变成 `Target\uFFFD` → 解析不到真实页面
  → 假 `broken_link`；
- 落在 `key: value` 的值尾（如 `latency: 10ms\xff`）→ 值变成 `10ms\uFFFD`
  → 与其它页面的 `10ms` 不相等 → 假 `value_conflict`。

**机理**：`errors="replace"` 的代价是把坏字节**变成正文里的真实字符**，
后续所有规则都分不清它和正常字符的差别。

**实测证据**（同一探针）：

- `wiki/A.md` 含 `[[Target\xff]]` 且 `wiki/Target.md` **真实存在** →
  仍报 `broken_link`，link = `Target\uFFFD`；
- `wiki/P1.md` = `latency: 10ms`、`wiki/P2.md` = `latency: 10ms\xff` →
  报 `value_conflict`（`10ms` vs `10ms\uFFFD`）；**两页都合法 UTF-8 的
  同一布局 → 0 条**。

**本轮不修**：在 lint 输出层做降级（剥掉 U+FFFD 再比对、或给 issue 打
"内容含替换字符"标记）属**行为变更**——P4-a 只承诺"不崩"，不改变 issue
的判定结果，改判定结果超出本轮边界。

**将来该在哪一层修**：应在**内容读取层**统一处理，而不是让每条规则各判
一次：把 `errors="replace"` 换成"读取时记录替换字符位置 / 读取后剥离
U+FFFD 再送进规则"，并在 issue 上带 `degraded: true` 之类标记，让上层能
提示"该页含非法字节，结论可能不准"。属 P4-b。

---

## 12. 实施建议顺序（给 Implementer）

1. **commit A（C9）**：先改 3 个文件里的 6 处读（analyzer.py:60/64/231、lint/__init__.py:68/119、source_analysis.py:42）→ 跑 `tests/test_lint_read_counts.py::test_lint_survives_non_utf8_page` + `tests/test_lint_engine.py` + `tests/test_source_analysis.py` + `tests/test_wiki_analyzer.py`。
2. **commit B（C1）**：analyzer.py:500 移位 → 跑新增的 `test_context_not_built_when_llm_gaps_cached` + `tests/test_wiki_engine_caching.py`。
3. **commit C（C2）**：source_analysis.py 新增 `_build_source_summary_map` + 委托；analyzer.py:250-252 改用映射 → 跑 `test_sources_directory_scanned_at_most_once` + `test_source_summary_map_matches_per_path_lookup` + `test_context_text_unchanged_for_known_layout` + `tests/test_source_analysis.py`。
4. 每次改动后：`ruff check <files> --output-format=concise` + `pytest`（AGENTS.md 原则 6：改完即验，不攒到最后）。
5. 收尾：`python scripts/check_architecture.py`（必须 0 violations）+ `python scripts/validate_handoff.py docs/designs/refactor-handoff/p4-lint-snapshot.design.json`。
