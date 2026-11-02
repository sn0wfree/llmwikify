# P4-b 设计：全量 PageSnapshot —— 一次 lint，一份页面快照

**task_id**: `p4b-lint-snapshot` · **decision**: `proceed`
**阶段**：Architect（只读代码 + 写设计；本任务零改动 `src/`）
**上游证据**：`docs/designs/refactor-handoff/p4b-lint-snapshot.recon.json`（C1–C18，全部带 file:line 与实测数字）
**方案依据**：`docs/designs/reuse-and-performance-isolation-plan.md` §P4（576–661 行）
**协议**：`docs/designs/refactor-multi-agent-protocol.md` §2 / §3 / §4 / §7
**前一轮**：`docs/designs/refactor-designs/p4-lint-snapshot.md`（P4-a：context 按需构建 + source 索引 + 有损读）

---

## 0. 决策摘要 + **与编排者给定目标的偏差（必须先读）**

### 0.1 结论

`proceed`。做法：**新增不可变 `PageSnapshot` + `PageSource` 协议**，一次 lint 只把页面正文读一遍，
`Rule` / `CrossPageRule` / `_scan_all_pages` / 4 条覆写 `run()` 的规则共用这一份；
`Rule.run` / `CrossPageRule._load_pages` / `detect` / `detect_all` / `LintEngine.run_all` / `run_rule`
的**既有签名一律不动**，新增的并行入口 `run_with_snapshot(wiki, snapshot)` 只在调用方**真的拿到快照时**才被使用。

### 0.2 偏差：目标是 **311 read / 2 rglob**，不是编排者给的 174 read / 3 rglob

编排者给的消除量是「755 次 = 3 条基础模板规则(3×151) + CrossPageRule 共享加载(151) + `_scan_all_pages`
正文读(151)」，于是 929 − 755 = 174。**这个算式漏掉了快照自身要读的那 151 次**：

* 快照必须把每页正文读一遍（这正是快照的定义）；
* 快照读的那一遍，**替换**掉的是 `analyzer.py:71` 的正文读（本来就存在的 151 次），**不是凭空多出来的 151 次**。

逐项重算（cold 口径，recon C3 的同一合成 wiki：151 页 + 14 个 source 页 + 8 个 raw）：

| 阶段 | 改动前 read / rglob | 改动后 read / rglob | 依据 |
|---|---|---|---|
| 快照构建（**新增阶段**） | — | **151 / 1** | 新增；枚举复用 `wiki._wiki_pages()`（C12） |
| `_scan_all_pages` | 302 / 1（`status.py:31` 裸读 151 + `analyzer.py:71` 正文读 151） | **151 / 0**（只剩 `status.py:31`；正文来自快照） | status.py 本轮不碰（硬约束 6） |
| `run_all`（8 条规则） | 627 / 8 | **9 / 1**（`dated_claim` 8 个 raw + `knowledge_gap` 1 个 wiki.md；rglob 只剩 raw 那 1 次） | C1 / C2 / C4 / C5 |
| **合计（本次验收口径）** | **929 / 9** | **311 / 2** | 2.98× / 4.5× |

**174 只有在 `status.py:31` 的 151 次 `_should_exclude_orphan` 裸读也被消除时才成立**
（174 = 151 + 14 + 1 + 8，正是「status 151 + knowledge_gap 14 + wiki.md 1 + raw 8」）。
而 `kernel/wiki/mixins/analysis/status.py` 本轮由并行 writer 持有 → **不可碰**（硬约束 6）。
因此本轮可承诺的目标是 **311 / 2**；**174 / 3 登记为后续项**（等 status.py 的 owner 释放该文件，
把 `_should_exclude_orphan` 改成读快照内容，即可落到 160 / 2 —— 见 §14 R-3）。

> 反过来说：本设计**比**编排者的目标更好——`knowledge_gap` 的 14 次 source 页裸读也被消掉
> （纳入快照且统一有损读），所以 311 里已经没有那 14 次。

### 0.3 子任务拆分（每个子任务源文件 ≤ 3）

| 子任务 | 源文件 | 内容 |
|---|---|---|
| **P4-b-1 建边界** | `kernel/wiki/snapshot.py`（新）、`kernel/wiki/lint/__init__.py` | `PageSnapshot` + `PageSource` + 内存上限/降级；`run_with_snapshot` 并行入口（**默认实现 = 现状**） |
| **P4-b-2 接入** | `kernel/wiki/engines/analyzer.py`、`kernel/wiki/lint/__init__.py` | 一次构建快照，供规则 / `_scan_all_pages` / `_build_lint_context` 共用 |
| **P4-b-3a 规则层（读正文的两条）** | `kernel/wiki/lint/rules/dated_claims.py`、`rules/knowledge_gaps.py` | `dated_claim` / `knowledge_gap` 消费快照 |
| **P4-b-3b 规则层（只要名字的两条）** | `kernel/wiki/lint/rules/query_page_overlap.py`、`rules/redundancy.py` | `topic_overlap` / `redundancy` 消费快照（消除各自那 1 次 rglob） |

> 编排者给的「P4-b-3」若一次做完要碰 4 个 `rules/*.py` → **超过「每个子任务源文件 ≤ 3」**
> （协议 §5）。故拆为 -3a / -3b，每个 2 个源文件。

---

## 1. 边界（一句话）

**在 `kernel/wiki` 内新增一个不可变的「页面快照」对象与它的来源协议，让一次 lint 运行内
所有消费者（`_scan_all_pages`、8 条规则、`_build_lint_context`）共用同一份页面正文，
把 cold 口径的 929 次读降到 311 次；不改任何既有公开签名、不改规则判定语义（唯一例外见 §9）、
不动 HTTP 层、不碰 `status.py`、不碰 `foundation/`。**

**允许的行为变化（全任务仅此一条）**

| 变化 | 触发条件 | 出现阶段 | 回归测试 |
|---|---|---|---|
| `knowledge_gap` 不再因非 UTF-8 的 source 摘要页而整条失效 | `wiki/sources/**` 下存在非法字节的文件 | **P4-b-3a** | `test_knowledge_gap_survives_non_utf8_source_page`（改写自 `test_knowledge_gap_still_fails_on_bad_source_page`） |

**其余一律保持一致**：8 条规则产出的 issue 字典逐字段相同、`lint()` 返回结构不变、
缓存 key 与 `extra` 语义不变、`_build_lint_context()` 的文本逐字符相同、
`Rule.run` / `CrossPageRule._load_pages` / `detect` / `detect_all` 的签名与调用方式不变。

---

## 2. `PageSnapshot` / `PageSource` 的确切 API（问题 1）

### 2.1 新增文件 `src/llmwikify/kernel/wiki/snapshot.py`

```python
"""Immutable snapshot of the wiki pages, read once per lint run."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol

if TYPE_CHECKING:
    from .wiki import Wiki          # 仅类型导入，避免 wiki→lint→snapshot→wiki 循环

logger = logging.getLogger(__name__)

# ── 内存上限（依据见 §6） ───────────────────────────────────────────
SNAPSHOT_MAX_PAGE_BYTES = 1 * 1024 * 1024        # 1 MiB：单页上界
SNAPSHOT_MAX_TOTAL_BYTES = 64 * 1024 * 1024      # 64 MiB：磁盘字节预算（驻留约 1.15×）


@dataclass(frozen=True)
class PageSnapshot:
    """一次 lint 运行内所有页面内容的不可变快照。

    键是 **display name**（``wiki._page_display_name``：posix 相对路径、去掉 ``.md``）。
    它对不同路径是单射（recon C13 实测 151 页 0 重名）→ 可以安全当键。

    不变式
    ------
    * ``names`` / ``paths`` / ``relative_names`` 覆盖 **全部** 页面（与 ``wiki._wiki_pages()`` 一一对应）；
    * ``contents`` 是 ``names`` 的**子集**：只有被缓存进内存的页面才有内容；
      未缓存的页面记在 ``omitted`` 里（内存上限触发，见 §6）；
    * 本对象**不做任何页名过滤**（不做 ``Query:`` 过滤）——过滤是消费者的事（recon C11）。
    """

    names: tuple[str, ...]            # display name，按 wiki._wiki_pages() 顺序
    contents: Mapping[str, str]       # display name → 正文（有损 UTF-8）
    paths: Mapping[str, Path]         # display name → 绝对路径
    relative_names: tuple[str, ...]   # 相对路径 + ".md"（原生分隔符），= _get_existing_page_names 的格式
    omitted: tuple[str, ...] = ()     # 未进缓存的页面（降级）
    byte_size: int = 0                # 已缓存正文的字节数

    def content_of(self, name: str) -> str | None:
        """返回该页正文；未缓存（降级）时返回 None。"""
        return self.contents.get(name)

    def path_of(self, name: str) -> Path:
        """返回该页的绝对路径。"""
        return self.paths[name]

    @property
    def degraded(self) -> bool:
        """True = 有页面因内存上限没进缓存（消费者需回退到逐页读）。"""
        return bool(self.omitted)


class PageSource(Protocol):
    """提供页面快照。实现决定如何枚举与读取页面。"""

    def snapshot(self) -> PageSnapshot: ...


@dataclass(frozen=True, eq=False)
class WikiPageSource:
    """默认 PageSource：通过 Wiki 自己的页面枚举读一次盘。

    枚举 **必须** 复用 ``wiki._wiki_pages()``（recon C12）：``is_path_excluded`` 判的是
    绝对路径的每一段，页面集合依赖 wiki 根目录的绝对路径；另处重新枚举会得到不同的集合。
    """

    wiki: Wiki
    max_total_bytes: int = SNAPSHOT_MAX_TOTAL_BYTES
    max_page_bytes: int = SNAPSHOT_MAX_PAGE_BYTES

    def snapshot(self) -> PageSnapshot:
        ...
```

* `frozen=True` → 不可变；`contents` / `paths` 用 `MappingProxyType` 包住 → **深度只读**。
* 快照只持有不可变数据 → **可跨线程共享、无锁**（硬约束 3）。
* `WikiPageSource` 是 `PageSource` 的默认实现；`WikiAnalyzer.__init__` 接受一个可选的
  `page_source: PageSource | None = None`（默认 `WikiPageSource(wiki)`）→ 协议在生产路径上**真的被用到**，
  测试可注入假 source。

### 2.2 为什么键用 display name（问题 1 的最后一问）

* **单射**：`_page_display_name` = `relative_to().as_posix()[:-3]`，对不同相对路径去掉**定长 3 字符**
  不可能相等 → 151 页 0 重名（recon C13 实测，win/posix × hot/cold 四种配置均为空）→ 以它为键安全。
* **不能只用 `stem`**：`topic_overlap` 今天用的是 `page.stem`（不含目录）→ 不同目录同名会撞
  （recon C13 实测 `stem_duplicates_query_pages` 非空，该规则会 `pair_key=(X, X)` 自比）。
  所以快照的键必须是 display name；`stem` 由消费者从 `snapshot.path_of(name).stem` 现取
  （`Path.stem` 与今天 `page.stem` 逐字相同），**不在快照里另存一份**。
* **不能自己重新枚举**：必须 `wiki._wiki_pages()`（recon C12）。

### 2.3 「同一个页面只有一个键」如何保证

1. 枚举源唯一：`wiki._wiki_pages()`（C12）。
2. 键唯一：display name 单射（C13）。
3. 构建器用 `dict` 累积；**若出现重复键则保留先出现的并记 WARNING**（理论上不可能，
   但 FS 大小写不敏感 / 符号链接场景下 `a/A.md` 可能造成 `as_posix()` 同名）→ 不静默覆盖。
4. `names` 是 tuple（有序、不可变）→ 顺序 == `_wiki_pages()` 顺序 → 规则的结果顺序与今天一致。

### 2.4 快照**不做**的事

* **不做 `Query:` 过滤**（recon C11）：`kernel/path_codec.py:23-31` 在 Windows 上把 `:` 映射成全角 `：`
  → `startswith("Query:")` 恒为 False → Windows 上 S2 = S1 = 151、`topic_overlap` 找到 0 个 Query 页（死代码）；
  POSIX 上 S2 = 143、`topic_overlap` 找到 10 个。**哪些页被跳过是平台相关的** → 过滤必须留在消费者。
  而且 S2（display name 前缀）与 S3（`page.stem` 前缀）本来就是**两个不同的谓词**（recon C6 notes），
  快照把它们统一成一个过滤会改变行为。
* **不读 `raw/`**：`dated_claim` 的 raw 扫描（8 读 + 1 rglob）不在页面快照范围（recon C8），
  raw 不是 wiki 页。
* **不替消费者做 orphan 排除**：`_should_exclude_orphan` 在 `status.py`（本轮不碰）。

---

## 3. 快照怎么从 analyzer 传到规则（问题 2）

### 3.1 三个候选方案与否决理由

| 方案 | 做法 | 结论 |
|---|---|---|
| **A. `run(self, wiki, snapshot=None)` 加可选参数** | 引擎调 `rule.run(wiki, snapshot)` | **否决**：引擎一旦传第二个参数，`tests/test_lint_handles_non_utf8_page.py:111-121` 的 `wrapper(self, wiki)` 立刻 `TypeError`（位置参数多一个；`snapshot=` 关键字同样炸）→ 站点 ② 直接失败。硬约束 1 也要求「不得让现有调用点抛 TypeError」 |
| **B. 并行入口 `run_with_snapshot(self, wiki, snapshot=None)`** | 引擎**只在拿到快照时**调它；没有快照时走与今天逐行相同的旧分支 | **采纳**：`run` / `_load_pages` 签名一字不动；`snapshot=None` 时旧路径 100% 保留 → 站点 ①②③ 全部不受影响 |
| **C. 带外投递**（规则实例属性 / wiki 属性 / thread-local） | 不改调用形状，另有通道传快照 | **否决**：① `RULES` 是**模块级单例**（recon C8/C18）→ 实例属性是**跨请求进程级状态**，并发 lint 会互相串快照；② wiki 属性在并发请求下同样有竞态；③ thread-local 是隐藏通道，且本仓没有「一次 lint 必定在一个线程内完成」的硬保证 |

### 3.2 采用的接口（全部是**新增可选参数**，既有调用一律继续可用）

```python
# kernel/wiki/lint/__init__.py
class Rule:
    def run(self, wiki: Wiki) -> list[dict[str, Any]]:            # 签名不变
        ...                                                       # 行为不变

    def run_with_snapshot(self, wiki: Wiki, snapshot: PageSnapshot | None = None
                          ) -> list[dict[str, Any]]:
        """快照入口。snapshot 为 None 时等价于 run(wiki)。"""

class CrossPageRule(Rule):
    def run(self, wiki: Wiki) -> list[dict[str, Any]]:            # 签名不变
        ...

    def _load_pages(self, wiki: Wiki) -> dict[str, str]:          # 签名不变
        ...

    def run_with_snapshot(self, wiki: Wiki, snapshot: PageSnapshot | None = None
                          ) -> list[dict[str, Any]]:
        ...

    def _pages_from_snapshot(self, wiki: Wiki, snapshot: PageSnapshot) -> dict[str, str]:
        """快照 → {display_name: content}（与 _load_pages 逐项同构）。"""

class LintEngine:
    def run_all(self, snapshot: PageSnapshot | None = None) -> list[dict[str, Any]]:
        ...

    def run_rule(self, name: str, snapshot: PageSnapshot | None = None
                 ) -> list[dict[str, Any]]:
        ...
```

* `max_params`：`run_with_snapshot` = 3（含 self）✓ ≤ 3（design.json 约束）。
* **`detect` / `detect_all` 的签名一律不动**——recon C9 实测 `detect` / `detect_all` 期间的 IO 恒为 0，
  它们本来就只做纯计算；`detect(page_name, content, wiki, results)` 本来就带 `content`（recon C1 notes）。

### 3.3 引擎内部（`LintEngine.run_all`）

```python
def run_all(self, snapshot: PageSnapshot | None = None) -> list[dict[str, Any]]:
    all_issues: list[dict[str, Any]] = []
    shared_pages: dict[str, str] | None = None
    for name in self.rule_names:
        rule = self._rules[name]
        try:
            if snapshot is not None:
                # 快照路径：普通规则与跨页规则都从同一份快照取数据
                all_issues.extend(rule.run_with_snapshot(self.wiki, snapshot))
            elif isinstance(rule, CrossPageRule):
                # 旧路径：跨页规则共享一次 _load_pages（今天的优化，必须保留）
                if shared_pages is None:
                    shared_pages = rule._load_pages(self.wiki)
                results: list[dict[str, Any]] = []
                rule.detect_all(shared_pages, self.wiki, results)
                all_issues.extend(results[: rule.max_results])
            else:
                all_issues.extend(rule.run(self.wiki))
        except Exception as e:
            logger.warning("lint rule %r failed: %s", name, e)
    return all_issues
```

* `snapshot is None` 的分支与今天的实现**逐行相同** → 站点 ② 的三个 wrapper 全部照旧命中 ✓。
* `snapshot is not None` 时不再需要 `shared_pages` 这个**跨规则缓存**：内容共享自同一份快照；
  但每条跨页规则仍经 `_pages_from_snapshot` **各建一份** `{name: content}` 字典壳
  （壳不共享对象，收益极小，不值得再优化）。

`run_rule(name, snapshot=None)`：

```python
def run_rule(self, name: str, snapshot: PageSnapshot | None = None) -> list[dict[str, Any]]:
    if name not in self._rules:
        return []
    rule = self._rules[name]
    if snapshot is None:
        return rule.run(self.wiki)          # 旧路径
    return rule.run_with_snapshot(self.wiki, snapshot)
```

### 3.4 基类的两条模板

```python
class Rule:
    def run_with_snapshot(self, wiki, snapshot=None):
        if snapshot is None:
            return self.run(wiki)
        if type(self).run is not Rule.run:
            # 这条规则自己覆写了 run()（例如 dated_claim 先扫 raw），
            # 通用模板不能绕过它 —— 除非它显式覆写 run_with_snapshot（P4-b-3）。
            return self.run(wiki)
        if not wiki.wiki_dir.exists():
            return []
        results: list[dict[str, Any]] = []
        for name in snapshot.names:
            if _is_query_page(name):        # 与 _iter_pages 同一个谓词
                continue
            content = snapshot.content_of(name)
            if content is None:             # 降级：该页没进缓存 → 回退到逐页读
                content = snapshot.path_of(name).read_text(
                    encoding="utf-8", errors="replace")
            self.detect(name, content, wiki, results)
            if len(results) >= self.max_results:
                break
        return results[: self.max_results]
```

```python
class CrossPageRule(Rule):
    def run_with_snapshot(self, wiki, snapshot=None):
        if snapshot is None:
            return self.run(wiki)
        if type(self).run is not CrossPageRule.run:
            return self.run(wiki)
        if not wiki.wiki_dir.exists():
            return []
        pages = self._pages_from_snapshot(wiki, snapshot)
        results: list[dict[str, Any]] = []
        self.detect_all(pages, self.wiki, results)
        return results[: self.max_results]
```

**关键点**

1. **模板与旧路径逐项同构**：同样的页序（`_wiki_pages()` 顺序）、同样的 `Query:` 谓词、同样的
   `max_results` 提前 break、同样的有损读、同样的 `results[:max_results]` 截断 →
   `run(wiki)` 与 `run_with_snapshot(wiki, snapshot)` 产出**完全相同**的 issue 列表
   → 由 §8 的契约测试守住。
2. **`type(self).run is not Rule.run` 这个反射检查**是必要的：4 条规则覆写了 `run()`
   （`dated_claims` / `knowledge_gaps` / `query_page_overlap` / `redundancy`），
   在它们迁移（P4-b-3）之前，通用模板不能绕过它们 → 回落到旧路径，**行为不变**。
   迁移后它们各自覆写 `run_with_snapshot`，这段检查不再对它们生效。
   （用反射而不是加类属性，是为了**不改这 4 个文件**就能保持默认实现 = 现状。）
3. `Query:` 谓词抽成 `lint/__init__.py` 里的模块级 `_is_query_page(name)`：
   `_iter_pages`（:77）、`_load_pages`（:117）、新模板三处共用同一个谓词 → 不会出现两套过滤。
   `topic_overlap` 用的是**另一个**谓词（`page.stem` 前缀）→ 留在它自己的文件里，不合并（recon C6/C11）。

### 3.5 analyzer 侧的数据流（P4-b-2）

```python
# WikiAnalyzer.__init__
def __init__(self, wiki: "Wiki", page_source: PageSource | None = None) -> None:
    self.wiki = wiki
    self._page_source = page_source or WikiPageSource(wiki)
    self._lint_engine = LintEngine(wiki, rules=RULES)     # 不变

# WikiAnalyzer.lint()
snapshot: PageSnapshot | None = None
if core is None:                                          # :414
    snapshot = self._page_source.snapshot()                # ← 一次构建
    link_counts, orphan_candidates, broken_links = self._scan_all_pages(snapshot)   # :418
    ...
    all_rule_results = self._run_all_rules(snapshot)       # :448
    ...
    "total_pages": len(snapshot.names),                    # :498  省掉一次 _wiki_pages() rglob
...
if llm_gaps is None:                                      # :521
    context = self._build_lint_context(snapshot=snapshot)  # :522
```

* `snapshot` 是**一次 lint 内的一份**，`_scan_all_pages` / `_run_all_rules` / `_build_lint_context` 共用。
* `core` 命中缓存时（:410-412）**不建快照** → 零额外开销 ✓。
* 生命周期：recon C18 —— `LintEngine` 的唯一消费者是 `WikiAnalyzer`，`wiki.py:124` 把 analyzer 缓存在
  Wiki 实例上 → 快照的存活期天然落在**一次 lint 调用内**，不跨请求、不进 Wiki 实例状态 ✓
  （P4-a 的 do_not #11「不把页面内容跨请求缓存」继续成立）。

### 3.6 单规则路径 `run_rule(name)` 怎么办（问题 2 的最后一条）

**结论：`run_rule` 接受可选快照，但 analyzer 的 `_run_rule` 默认**不**建快照。**

理由（用 recon 的实测数字）：

| 路径 | 现状读次数 | 建快照后 | 判定 |
|---|---|---|---|
| `run_all`（8 条） | cold 627 / hot 189（recon C3、C14） | 151 + 9 = **160** | **两种口径都更优** → 建快照 |
| `run_rule('data_gap')` 单条 | hot **2** 次（recon C14：命中即 break） | 151 + 0 = **151** | **更差** → 不建快照 |

→ 批量路径建快照、单规则路径不建，是**由实测数字决定的**，不是随意取舍。
`analyzer._run_rule(name)`（被 `Wiki._detect_X()` 与 `apps/chat` 的 detect 动作调用）保持旧路径 →
**站点 ① 因此完全不受影响**。

---

## 4. `_scan_all_pages` 与 `_build_lint_context` 怎么复用快照（问题 3）

### 4.1 `_scan_all_pages` —— **要存 Path**

```python
def _scan_all_pages(self, snapshot: PageSnapshot | None = None
                    ) -> tuple[dict[str, int], set[str], list[dict]]:
    ...
    if snapshot is None:
        snapshot = self._page_source.snapshot()
    for name in snapshot.names:
        page = snapshot.path_of(name)
        try:
            excluded = self.wiki._should_exclude_orphan(name, page)   # 仍需 Path
        except UnicodeDecodeError:
            excluded = False                                          # P4-a 的 fail-open
        if excluded:
            continue
        page_names.append(name)
        content = snapshot.content_of(name)
        if content is None:                                            # 降级回退
            content = page.read_text(encoding="utf-8", errors="replace")
        contents.append((name, content))
```

**快照里要不要存 Path？→ 要。** 理由：

1. `_should_exclude_orphan(name, page)`（`status.py:16`）的第二个形参就是 `page_path`，
   本轮**不能改 status.py** → 调用点必须能拿到 `Path`。
2. 降级回退（§6）也要用 Path 现场读那一页。
3. `topic_overlap` 需要 `str(page)`（issue 里的 `file` 字段）与 `page.stem` → 都从 Path 取。

**代价**：多一个 `name → Path` 的字典（151 项，每项一个 Path 对象 ≈ 151 × ~100 B ≈ 15 KB）→ 可忽略。

**行为等价性**：页序、`_should_exclude_orphan` 的调用与顺序、`page_names` / `contents` 的内容全部不变 →
`link_counts` / `orphan_candidates` / `broken_links` 逐项相同 ✓。
唯一差别：**被 orphan 排除的页现在也会被快照读一次**（今天 `analyzer.py:71` 不会读它）→
多读几页，但换掉的是规则那 5×151 次 → 净赚（默认配置下排除数为 0，两边相等）。

### 4.2 `_build_lint_context` —— **复用「页面名列表」，但不碰其它**

`_build_lint_context` 现在读的东西（recon C10 实测 `read_text=16、rglob=3`）：

| 内容 | 是否页面正文 | 本轮处置 |
|---|---|---|
| `wiki.md`（:236） | 否 | 不动（1 次读） |
| 页面名列表 `_get_existing_page_names()`（:241） | 否（只有名字） | **改用快照的 `relative_names`**（省 1 次 rglob） |
| `raw_dir.rglob("*")`（:250） | 否（raw 文件） | 不动 |
| source 摘要页（P4-a 的 `_build_source_summary_map`） | **是**（`wiki/sources/**`） | **本轮不动** → 登记为后续项（§14 R-1） |

**为什么可以改页面名列表而不改文本**：recon C7 实测 `_get_existing_page_names`（utility.py:143-153）与
`_wiki_pages`（:155-165）的**过滤条件逐字相同**（`rglob("*.md")` + stem 不在 (index, log) +
`".sink" not in str(p)` + `not is_path_excluded(p)`），只是名字格式不同：
`_get_existing_page_names` = `str(p.relative_to(wiki_dir))`（**原生分隔符 + `.md` 后缀**），
`_page_display_name` = posix 相对路径**去掉** `.md`。
→ 快照必须**同时**带这两种名字形态（§2.1 的 `names` 与 `relative_names`），
`_build_lint_context` 用 `relative_names` → **输出文本逐字符不变**（同样的字符串、同样的 `sorted()[:100]`、
同样的 `len(pages)`）。

```python
def _build_lint_context(self, limit: int = 20,
                         snapshot: PageSnapshot | None = None) -> str:
    ...
    pages = (list(snapshot.relative_names) if snapshot is not None
             else self.wiki._get_existing_page_names())
```

* `snapshot is None`（core 命中缓存、llm_gaps 未命中的场景）→ 回落旧路径，**不多建一次快照**
  （否则会白读 151 页，比省下的一次 rglob 亏得多）。
* `mixins/analysis/llm.py:279-281` 的 `self._analyzer._build_lint_context(limit)` 是位置调用 → 仍然可用 ✓。

> P4-a recon 的 C10 notes 说「`_get_existing_page_names` 与 `_wiki_pages` 的排除规则不同」——
> **该说法有误**（recon C7 已纠正：两边逐字相同）。本设计以 C7 为准。

---

## 5. `kernel/wiki/lint/__init__.py` 的具体改动清单（P4-b-1）

| # | 改动 | 行号（现状） |
|---|---|---|
| 1 | `from ..snapshot import PageSnapshot`（仅类型 + 运行期 isinstance 不需要，纯类型注解 → 仍需 import） | 新增 |
| 2 | 模块级 `_is_query_page(name: str) -> bool`（`name.startswith("Query:")`），`_iter_pages` / `_load_pages` / 新模板共用 | :77 / :117 |
| 3 | `Rule.run_with_snapshot(wiki, snapshot=None)`（§3.4） | 新增 |
| 4 | `CrossPageRule.run_with_snapshot(wiki, snapshot=None)` + `CrossPageRule._pages_from_snapshot(wiki, snapshot)` | 新增 |
| 5 | `LintEngine.run_all(snapshot=None)`（§3.3） | :161 |
| 6 | `LintEngine.run_rule(name, snapshot=None)`（§3.3） | :189 |
| 7 | `Rule.run` / `CrossPageRule.run` / `_load_pages` / `detect` / `detect_all` **签名与行为一律不动** | :58 / :100 / :112 / :80 / :121 |

**P4-b-1 落地后的默认行为 = 现状**：新入口全部存在但**没有任何生产调用方**使用它们；
`run_all()` / `run_rule(name)` 不传快照 → 逐行走旧分支 → 8 条规则产出的 issue 与今天完全相同。

---

## 6. 内存上限与降级路径（问题 4）

### 6.1 依据（recon C17）

| 观测 | 数值 |
|---|---|
| 合成 wiki 151 页正文均值 | 628.8 B（cold）/ 889.4 B（hot） |
| 合成 wiki p90 / 最大 | 1055 / 1161 B（cold）、1368 / 1477 B（hot） |
| 本机真实 wiki 的**唯一**内容页 | 1551 B |
| 仓库 `raw/` 15 个文档 | 均值 6070.9 B、p90 19,997 B、最大 **27,631 B** |
| 方案文档「1400 页 × 4KB ≈ 5.6 MB」 | 本机既不能证实也不能证伪 |

→ **上限必须按「页数 × 单页上界」定，不能按均值定**（长文 wiki 会超）。
方案文档的 5.6 MB 只是「按均值的乐观估计」；按观测最大单文件外推的上界是
1400 × 27.6 KB = **38.7 MB**。

### 6.2 取值

```python
SNAPSHOT_MAX_PAGE_BYTES  = 1 * 1024 * 1024     # 1 MiB   —— 单页上界
SNAPSHOT_MAX_TOTAL_BYTES = 64 * 1024 * 1024    # 64 MiB  —— 磁盘字节预算
                                                # （实际驻留最多约 1.15×，
                                                #  astral 字符 UTF-8 str 开销最坏）
有效预算 budget = min(SNAPSHOT_MAX_TOTAL_BYTES, 页数 × SNAPSHOT_MAX_PAGE_BYTES)
```

| 数字 | 依据 |
|---|---|
| 单页 1 MiB | 是观测到的最大 wiki 页（1551 B）的 **676×**、最大 raw 文档（27,631 B）的 **38×** → 正常页面永远触发不到；只有病态大文件才会 |
| 总量 64 MiB | 是「1400 页 × 观测最大单文件」外推上界（38.7 MB）的 **1.65×** → 覆盖观测到的最坏情况，仍比方案文档建议的 200 MB 小 3 倍。按**磁盘字节**计，Python str 驻留最多约 **1.15×**（astral 最坏）→ 不是内存的绝对上限 |
| `min(总量, 页数×单页)` | 满足「按页数 × 单页上界定上限」的要求；磁盘预算只是额外的安全网（页数很多时先触顶） |

### 6.3 算法

```
pages = wiki._wiki_pages()                 # 1 次 rglob（C12：必须复用）
budget = min(max_total_bytes, len(pages) * max_page_bytes)
used = 0
for page in pages:                          # 顺序 == _wiki_pages() 顺序
    name = wiki._page_display_name(page)
    names.append(name); paths[name] = page
    relative_names.append(str(page.relative_to(wiki.wiki_dir)))
    size = page.stat().st_size              # 1 次 stat（不是 read），用于在读之前卡上界
    if size > max_page_bytes or used + size > budget:
        omitted.append(name); continue      # 不缓存
    try:
        content = page.read_text(encoding="utf-8", errors="replace")
    except OSError:
        omitted.append(name); continue      # 读不动 → 交给消费方回退（行为与今天一致）
    contents[name] = content; used += size
byte_size = used
```

* **先 `stat` 再读**：只有在读之前才知道大小，才能真正挡住「一个 500 MB 的页面把内存打爆」。
  代价是每页多 1 次 `stat`（元数据，不是 read；recon 口径里 stat 单列）→ 151 次 stat，可接受。
* **有损读**：沿用 P4-a 统一的 `read_text(encoding="utf-8", errors="replace")`（P4-a §4 选项 B）
  → 不改 `foundation/io.py`（硬约束 7）✓。

### 6.4 降级路径（超限后怎么办）

**降级 = 「这一页不进缓存」，不是「这一页不检查」。**

| 情况 | 行为 | 覆盖面 | 结果 |
|---|---|---|---|
| 单页 > 1 MiB | 该页不缓存 → 记入 `omitted` | **不变** | 消费方回退到 `path.read_text(errors="replace")`（**与今天同一次读**）→ issue 逐项相同 |
| 总量超预算 | 后续页不缓存 → 记入 `omitted` | **不变** | 同上 |
| 某页读失败（OSError） | 不缓存 → 记入 `omitted` | **不变** | 消费方回退读 → 抛同样的异常 → 被 `LintEngine.run_all` 的 `except Exception` 吞掉（与今天一致） |

→ **行为不降级，只有内存有界**。这是刻意的选择：快照是**缓存**不是**过滤器**；
若把超限页直接丢弃，lint 会静默少检查几页（更危险）。
代价：降级时那几页会被读两次（快照没缓存 → 回退读），但只在超限这种异常场景发生。

**日志 / 指标**

* 降级时 `logger.warning("lint page snapshot degraded: %d/%d pages not cached, %d bytes used of %d budget")`
  → 可观测 ✓。
* **不引入新的指标基础设施**（本仓没有 metrics 层，YAGNI）；把 `snapshot.byte_size` / `snapshot.degraded`
  暴露出来，日后接指标时不用改结构。
* `design.json.performance_constraints.extra_copies` 记录了同一组数字 → 供 Benchmarker 复核。

---

## 7. 8 条规则的归属与消费方式（问题 5）

| # | 规则（name） | 覆写 `run()`？ | 今天读什么 | 消费快照的方式 | P4-b-1 | P4-b-2 | P4-b-3 |
|---|---|---|---|---|---|---|---|
| 1 | `DataGapsRule`（`data_gap`） | 否（用 `Rule.run`） | 151 次页面正文（`lint/__init__.py:68`） | 基类 `Rule.run_with_snapshot` 模板：按 `snapshot.names` 迭代、取 `content_of(name)` | 基类模板就位 | ✅ **迁移**（0 次正文读） | — |
| 2 | `OutdatedPagesRule`（`potentially_outdated`） | 否 | 151 次页面正文 | 同上 | 基类模板就位 | ✅ **迁移** | — |
| 3 | `MissingCrossRefsRule`（`missing_cross_ref`） | 是（`CrossPageRule.run`） | 151 次正文（`_load_pages`，与下一条共享 1 次） | `CrossPageRule.run_with_snapshot` → `_pages_from_snapshot` → `detect_all(pages, wiki, results)`（**签名不变**） | 基类模板就位 | ✅ **迁移** | — |
| 4 | `PotentialContradictionsRule`（`contradiction`） | 是 | 共享上一条的 151 次 | 同上（同一份快照 → 共享天然成立） | 基类模板就位 | ✅ **迁移** | — |
| 5 | `DatedClaimsRule`（`dated_claim`） | 是 | **151 次正文**（`super().run(wiki)`）+ 8 个 raw + 1 次 raw rglob | 覆写 `run_with_snapshot`：先跑 raw 扫描（**抽成 `_scan_latest_source_year(wiki)`，`run` 与 `run_with_snapshot` 共用**），再 `super().run_with_snapshot(wiki, snapshot)` | — | ⏳ 仍是 151 次 | ✅ **-3a 迁移**（raw 保持 8 次读 + 1 次 rglob） |
| 6 | `KnowledgeGapsRule`（`knowledge_gap`） | 是 | **14 个 source 页裸读**（严格 `read_text(encoding="utf-8")`，`rules/knowledge_gaps.py:63`）+ 1 次 wiki.md + 1 次 sources rglob | 覆写 `run_with_snapshot`：source 页从快照取（→ 统一有损读）；wiki.md 与关系引擎部分不动 | — | ⏳ 仍是 14 次 | ✅ **-3a 迁移**（**R1 在此修复**，见 §9） |
| 7 | `QueryPageOverlapRule`（`topic_overlap`） | 是 | **0 次读**，但自己 1 次 rglob（`rules/query_page_overlap.py:36`）；用 `page.stem` 与 `str(page)` | 覆写 `run_with_snapshot`：从 `snapshot.paths` 取 `path.stem` / `str(path)`，**保留 stem 前缀谓词**（与 display name 前缀谓词不同！） | — | ⏳ 仍 1 次 rglob | ✅ **-3b 迁移**（0 次 rglob） |
| 8 | `RedundancyRule`（`redundancy`） | 是 | **0 次读**，1 次 rglob（`wiki._wiki_pages()`，`rules/redundancy.py:28`）；只取 display name | 覆写 `run_with_snapshot`：用 `snapshot.names` | — | ⏳ 仍 1 次 rglob | ✅ **-3b 迁移**（0 次 rglob） |

**迁移后各阶段的计数（cold 口径）**

| 阶段 | read | rglob | 相对基线 |
|---|---|---|---|
| 基线（recon C3） | 929 | 9 | — |
| P4-b-1 后 | 929 | 9 | **完全不变**（默认实现 = 现状） |
| P4-b-2 后 | 476 | 6 | 1.95× |
| P4-b-3a 后 | 311 | 4 | 2.99× |
| **P4-b-3b 后（终点）** | **311** | **2** | **2.98× / 4.5×** |

### 7.1 `dated_claim` 的 `super().run(wiki)` 链怎么处理

`dated_claims.py:52` 现在是 `return super().run(wiki)`。迁移后：

```python
def run_with_snapshot(self, wiki, snapshot=None):
    if snapshot is None:
        return self.run(wiki)
    self._prepare(wiki)                     # raw 扫描 → self._latest_source_year / _current_year
    return super().run_with_snapshot(wiki, snapshot)

def run(self, wiki):                       # 旧入口，签名不变
    if not self._prepare(wiki):
        return []                           # latest_source_year == 0 → 提前返回
    return super().run(wiki)
```

* `_prepare(wiki)` = 现在的 :32-51（raw 扫描 + 写实例属性 + `latest_source_year == 0` 的提前返回判定）。
* **raw 扫描不进快照**（recon C8：raw 不是 wiki 页；且 `RULES` 是模块级单例 →
  `_latest_source_year` 本来就是跨请求的进程级状态，本轮**不碰**这条既有缺陷，登记为 §14 R-2）。

### 7.2 `knowledge_gap` 的 source 页读取（= 已登记的残留风险 R1）

* source 页本来就在 `wiki_dir` 之下 → **本来就在 `_wiki_pages()` 里**（recon C4 实测：
  `MissingCrossRefsRule` 读的 151 个文件里含 14 个 `sources/source-*.md`）→ 快照天然覆盖它们 ✓。
* 迁移后 `knowledge_gap` 从快照取 source 页内容 → **统一有损读** → 不再抛 `UnicodeDecodeError`
  → **R1 被修复** → 站点 ④ 的断言反转 → §9 处置。
* **已知偏差（须登记）**：`_wiki_pages()` 会排除 stem 为 `index` / `log` 的文件，
  而 `knowledge_gap` 自己的 rglob 不排除 → 一个叫 `wiki/sources/index.md` 的摘要页
  将不再被 `knowledge_gap` 检查（其它规则不受影响）。属病态命名，登记为 §14 R-4。

### 7.3 `topic_overlap` 与 `redundancy`：只要名字

* `redundancy`：`wiki._wiki_pages()` → display names → 快照的 `names`（**同一集合、同一顺序**）✓。
* `topic_overlap`：自己 rglob `wiki_dir/**/*.md`，用 `page.stem.startswith("Query:")` 过滤 →
  改为遍历 `snapshot.paths`（= `_wiki_pages()` 的结果）。
  **集合等价性**：两者都用 `rglob("*.md")` + 同样的 `.sink` / `is_path_excluded` 过滤，
  唯一差别是 `_wiki_pages()` 多排除了 stem ∈ (index, log) —— 而 `index` / `log` 不可能以 `Query:` 开头
  → **Query 页集合完全相同** ✓（recon C6/C11 的结论）。
  注意 `topic_overlap` 的谓词是 **stem 前缀**，与其它规则的 **display name 前缀** 不是一回事
  → **不得统一**（recon C6 notes：POSIX 下 `queries/` 子目录里的 `Query: …` 页对 S2 不生效、对 S3 生效）。

---

## 8. 必须新增的测试（问题 6）

recon C15：**基类契约几乎无测试** —— `CrossPageRule._load_pages` **没有任何契约测试**，
`detect` / `detect_all` 也没有通用契约测试 → 「给 run 加可选参数」几乎不会被现有测试网抓住
→ **P4-b 必须补基类契约测试**。

### 8.1 新文件 `tests/test_lint_snapshot.py`（契约 + 行为）

| # | 测试 | 断言 | 守的是什么 |
|---|---|---|---|
| 1 | `test_run_with_snapshot_matches_run_for_every_rule` | 对 8 条规则逐条：`rule.run(wiki) == rule.run_with_snapshot(wiki, snapshot)`（issue 列表逐字段相等） | 模板与旧路径**语义等价**（C15 缺的那层网） |
| 2 | `test_detect_receives_same_page_name_and_content` | 用一条记录型探针规则，比较两条路径喂给 `detect` 的 `(page_name, content)` 序列 | 页名与正文逐字一致（含有损读） |
| 3 | `test_cross_page_pages_match_load_pages` | `_pages_from_snapshot(...) == _load_pages(wiki)`（键集合与内容逐项相等） | 跨页规则的输入等价 |
| 4 | `test_run_all_without_snapshot_is_legacy_path` | `engine.run_all()`（不传快照）与传快照的产出相同，且**不调用** `run_with_snapshot` 之外的任何新路径 | 默认实现 = 现状（硬约束 1） |
| 5 | `test_run_rule_with_snapshot_matches_run_rule` | `run_rule(name)` 两种模式的产出相同 | 单规则路径等价 |
| 6 | `test_snapshot_is_frozen_and_contents_readonly` | 改字段 / 改 `contents` 都抛 | 不可变（硬约束 3） |
| 7 | `test_snapshot_names_match_wiki_pages` | `snapshot.names == [wiki._page_display_name(p) for p in wiki._wiki_pages()]` | 复用 `wiki._wiki_pages()`（C12） |
| 8 | `test_snapshot_keys_are_unique` | 名字无重复 | display name 单射（C13） |
| 9 | `test_snapshot_does_not_filter_query_pages` | 手工构造含 `"Query: X"` 名字的快照 → 快照**保留**它；模板**跳过**它 | 过滤留给消费者（C11，平台相关） |
| 10 | `test_snapshot_memory_cap_omits_pages_but_results_unchanged` | `max_total_bytes=1` → `snapshot.degraded` 为真、`omitted` 非空；**但 8 条规则的产出与不限额时逐项相同** | 降级不改变覆盖面（§6.4） |
| 11 | `test_oversized_page_is_omitted_and_still_detected` | 单页超 `max_page_bytes` → 不进缓存但仍被规则检出 | 同上 |
| 12 | `test_degraded_snapshot_logs_warning` | `caplog` 里有降级 WARNING | 可观测 |
| 13 | `test_each_page_read_at_most_once_during_lint` | 一次 `wiki.lint()` 内，每个页面文件 `read_text` **≤ 1 次**（status.py 的那次除外） | **跨消费者一致性**（C10，见 §10） |
| 14 | `test_context_page_list_unchanged_with_snapshot` | `_build_lint_context(snapshot=...)` 与 `_build_lint_context()` **逐字符相同** | context 文本不变（C7） |
| 15 | `test_snapshot_source_pages_are_lossy` | 坏字节的 source 页在快照里是「可读部分 + U+FFFD」而非抛异常 | R1 的修复形态（§9） |

### 8.2 新文件 `tests/test_lint_snapshot_counts.py`（计数型基准）

* **fixture**：合成 wiki = 151 个页面 + 14 个 `wiki/sources/*.md` + 8 个 raw 文件（含 `2024`，
  让 `dated_claim` 不提前返回）。
* **两套口径**：
  * **cold**：页面内容不触发任何规则（无年份、无长断言行、无 wikilink）→ 上界口径（recon C14 的要求）。
  * **hot**：页面内容触发规则 → 命中即 break。
* **计数**：monkeypatch `Path.read_text` / `Path.rglob` / `Path.stat`，分别统计
  「快照构建 + `_scan_all_pages` + `_run_all_rules`」三个阶段的 read / rglob / stat。
* **同一份测试同时量「旧路径」与「快照路径」** → 自带 before/after（无需另找基线机器）。
* **断言**（门禁口径 = cold）：

| 指标 | 基线 | 目标 |
|---|---|---|
| `read_text` | 929 | **≤ 311** |
| `rglob` | 9 | **≤ 2** |

* `-s` 打印两套口径的数字 → Benchmarker 直接取 before/after 写进 `bench.json`。

**基准命令**（写进 `design.json.performance_constraints.benchmark_command`）：

```powershell
D:\tools\python312\python.exe -m pytest tests/test_lint_snapshot_counts.py -q -s --rootdir=D:\Github\llmwikify
```

> 本机 `wiki/` 只有 3 个 md（recon 已记录）→ **墙钟不可信，门禁必须是计数型**
> （P4-a §8.1 的同款纪律）。辅助墙钟信号仍需 `scripts/profile_lint_paths.py --wiki <真实 wiki>`。

---

## 9. R1 的处置（问题 7）

**问：快照把 `wiki/sources/` 纳入并统一有损读，`test_knowledge_gap_still_fails_on_bad_source_page`
的断言从「仍失败」变成「不再失败」——这算不算本任务范围内的行为变化？**

**答：算，而且它是本任务唯一被允许的行为变化。** 但它**不属于 P4-b-1 / -2，只属于 P4-b-3a**。

| 项 | 结论 |
|---|---|
| 性质 | **行为修复**（把「1 条规则被静默关掉」变成「规则正常跑完」），不是测试迁就 |
| 是否在范围内 | 在 —— 但**必须落在 P4-b-3a**（`knowledge_gap` 迁移的那一刻）。P4-b-1 / -2 期间 `knowledge_gap` 仍走旧路径 → 断言不变 → **站点 ④ 在 -1/-2 阶段不需要任何改动** |
| 依据 | P4-a 设计 §11 **R1** 已把「source 摘要页裸读 → 规则静默失效」登记为残留风险，并写明「属 P4-b」；测试自己的 docstring（`tests/test_lint_handles_non_utf8_page.py:18-20` 与 `:220-222`）写着「这是已知残留风险的回归护栏，**不是**期望语义；残留风险被修复（source 页读取变有损）时，本测试必须更新或删除」 |
| 测试怎么改 | 把 `test_knowledge_gap_still_fails_on_bad_source_page` **改写**为 `test_knowledge_gap_survives_non_utf8_source_page`：断言 `rule_spies["failed"] == []` 且 `"knowledge_gap" in rule_spies["completed"]` → **从「钉死 bug」翻转为「钉死修复」**（意图反转，用例名与 docstring 同步改） |
| 风险登记 | 新增残留风险 **R1b**：坏字节的 source 页现在以 U+FFFD 进入 `knowledge_gap` → 若坏字节落在 `[[...]]` 目标内，`isolated_source` 的判定可能与「严格读抛异常」时不同（与 P4-a 的 R9 同类：U+FFFD 假阳性）。**这是本仓已知的取舍**（有损读是 P4-a 统一后的既定事实） |
| 审查要求 | Reviewer 必须确认：① 改写后的测试**仍然断言「规则跑完了」**（不是把断言删掉）；② `implement.json` 里明确登记这条行为变化 |

---

## 10. 4 个测试站点的逐条处置（recon C16）

| # | 站点 | 处置 | 为什么不会破 / 怎么破 |
|---|---|---|---|
| ① | `tests/test_wiki_analyzer.py` 的 `mock_wiki`（MagicMock）+ 3 个用例（`test_detects_outdated_claim` / `test_detects_unlinked_mentions` / `test_detects_similar_names`） | **文件不改** | 这 3 个用例走 `analyzer._detect_X()` → `_run_rule(name)` → `LintEngine.run_rule(name)` **不传快照** → 规则仍通过 `wiki._wiki_pages()` + `page.read_text()` 读盘（§3.6 的数字依据）。另外 `analyzer.lint()` 建的快照只依赖 `_wiki_pages()` / `_page_display_name()` / `stat()` / `read_text()` / `relative_to()` —— 对 MagicMock 安全（`mock_wiki.wiki_dir` 是真 Path，页面都在它下面） |
| ② | `tests/test_lint_handles_non_utf8_page.py` 的 `rule_spies`（`wrapper(self, wiki)` 包 `run`；`wrapper(self, wiki)` 包 `_load_pages`；`wrapper(self, pages, wiki, results)` 包 `detect_all`） | **文件不改** | `LintEngine.run_all()` **不传快照** → 引擎走与今天**逐行相同**的旧分支（`rule.run(wiki)` / `rule._load_pages(wiki)` / `rule.detect_all(pages, wiki, results)`）→ 三个 wrapper 的形参数量与调用点完全一致 → 既不 `TypeError`，`completed` / `load_failures` / `failed` 三个列表的内容也与今天一致。**关键约束（要写进 implement.json）**：`LintEngine.run_all()` **不得**在内部自行构建快照 |
| ③ | `test_rule_read_is_lossy_not_empty` 直调 `MissingCrossRefsRule()._load_pages(wiki)` | **文件不改** | `_load_pages` 的签名与有损读语义原样保留（它仍是旧路径的组成部分）→ 返回的字典仍含 `"Broken Page"` 键、仍含 `U+FFFD` |
| ④ | `test_knowledge_gap_still_fails_on_bad_source_page` | **P4-b-3a 必须改**（改写为 `test_knowledge_gap_survives_non_utf8_source_page`） | 见 §9：这是 R1 的修复，测试自身 docstring 已预告 |

**外加一条**（recon C15 指出、但不在 4 个站点里）：`tests/test_lint_engine.py` 的 20 个用例
（规则可导入、名字唯一、`LintEngine` 机制）全部**不受影响** —— 本轮不删不改任何规则类名与
`name` 属性 ✓。

---

## 11. 依赖方向与架构守卫

* 新增/修改的文件全在 `kernel/` 内：`kernel/wiki/snapshot.py`（新）、`kernel/wiki/lint/__init__.py`、
  `kernel/wiki/engines/analyzer.py`、`kernel/wiki/lint/rules/*.py`（4 个）。
* `kernel/wiki/snapshot.py` **只在 `TYPE_CHECKING` 下** import `Wiki` → 避免
  `wiki → analyzer → lint → snapshot → wiki` 的循环（`lint/__init__.py` 已用同样的写法）。
* 不新增跨层 import；`foundation/` 完全不动 ✓（硬约束 7）。
* **验收**：`D:\tools\python312\python.exe scripts/check_architecture.py` 必须仍报 **0 violations**
  （实现者每个 commit 前必跑）。

---

## 12. 回滚（无 feature flag，靠独立 commit）

| commit | 内容 | 源文件 | revert 后回到 |
|---|---|---|---|
| A `feat(lint): 引入不可变页面快照对象` | `snapshot.py` + `lint/__init__.py` 的并行入口 | 2 | 现状（无任何生产调用方用它 → 行为逐字相同） |
| B `perf(lint): 一次 lint 共用一份页面快照` | `analyzer.py` 接入 + `lint/__init__.py` 的引擎分支 | 2 | 现状（929 / 9） |
| C `perf(lint): dated_claim / knowledge_gap 消费页面快照` | `rules/dated_claims.py` + `rules/knowledge_gaps.py` | 2 | B 之后的状态（476 / 6） |
| D `perf(lint): topic_overlap / redundancy 消费页面快照` | `rules/query_page_overlap.py` + `rules/redundancy.py` | 2 | C 之后的状态（311 / 4） |

* 四个 commit **互相独立可 revert**；每个 revert 后代码自洽（A 之后、B 之后……都成立）。
* **不做 feature flag / 开关**（协议 §8：本仓无 feature flag 体系，回退靠独立 commit）。
* 测试与实现同 commit（AGENTS.md + 协议 §6）；提交前 `git status` + `git diff --stat` + `ruff` + `pytest` + 用户确认清单。

---

## 13. do_not 清单

1. **不碰 `kernel/wiki/mixins/analysis/status.py`**（并行 writer 持有；`_should_exclude_orphan` 的 151 次裸读因此保留 → 目标 311 而非 174）。
2. **在 P4-b-3 之前不碰 `kernel/wiki/lint/rules/*`**（P4-b-1 / -2 只动 `kernel/wiki/snapshot.py`、`kernel/wiki/lint/__init__.py`、`kernel/wiki/engines/analyzer.py`）。
3. **不引入 feature flag / 开关**（`_use_snapshot` 之类一律不做）；回滚靠独立 commit 可 revert。
4. **不改 HTTP 路由**（`interfaces/**` 零改动）。
5. **不引入 CommonUtils / 万能工具类 / `if/else` 开关式抽象**（协议 §7 红线 2）；抽象按「它做的事」命名（`PageSnapshot` / `PageSource` / `WikiPageSource` / `run_with_snapshot` / `_pages_from_snapshot`）。
6. **不改公开 API 契约**：`Rule.run` / `CrossPageRule.run` / `_load_pages` / `detect` / `detect_all` / `LintEngine.run_all` / `run_rule` / `wiki.lint()` 的签名与返回结构、缓存 key 与 `extra` 语义，全部不变；新增参数一律可选。
7. **不改 `foundation/io.py`**，不新增任何第三方依赖（沿用 P4-a 的 `read_text(errors="replace")` 内联写法）。
8. **不在快照里做 `Query:` 过滤**（平台相关，recon C11）；过滤只留在消费者。
9. **不重新枚举页面**（必须复用 `wiki._wiki_pages()`，recon C12）。
10. **不把 raw 目录纳入快照**（recon C8）。
11. **不改 `_build_lint_context` 的输出文本**（页面名列表换成快照的 `relative_names`，但字符串逐字相同）。
12. **不把页面内容缓存到 Wiki 实例上**（P4-a do_not #11 继续成立；快照只活在一次 lint 调用内）。
13. **不做墙钟断言**（门禁必须是计数型）。
14. **不在 `apps/` / `interfaces/` / `reproduction/` 加任何代码**；不新增跨层 import。

---

## 14. 残留风险

| # | 风险 | 影响 | 处置 |
|---|---|---|---|
| R-1 | `_build_lint_context` 的 source 摘要页仍逐页读盘（P4-a 的 `_build_source_summary_map`） | 一次 lint 仍有 O(sources) 次读（在本次验收口径之外） | 后续项：让 `_build_source_summary_map` 接受快照内容（要改 `mixins/io/source_analysis.py`，与 P4-a 的改动重叠 → 单独立项） |
| R-2 | `DatedClaimsRule._latest_source_year` 是**跨请求的进程级状态**（`RULES` 是模块级单例，recon C8） | 并发 lint 会互相覆盖；`latest_source_year == 0` 时还会保留上次的旧值 | 本轮**不修**（不在快照范围）；建议后续把 `RULES` 改成每次 `LintEngine` 构造时新建实例 |
| R-3 | 目标 174 / 3 需要 `status.py` 的 `_should_exclude_orphan` 也读快照 | 现状目标只能是 311 / 2 | 等 status.py 的 owner 释放该文件后单独立项（改完是 160 / 2） |
| R-4 | `knowledge_gap` 两条路径（旧 `run` / 快照 `run_with_snapshot`）都走 `wiki._wiki_pages()`，因此**一致地**不检查名为 `index.md` / `log.md` 的 source 摘要页（以及 `.sink` 路径下的页） | 病态命名下少检查一页；两接口不再分叉 | 已知偏差，两侧等价，回归测试 `test_knowledge_gap_paths_report_the_same_source_pages` 守住 |
| R-5 | U+FFFD 进入规则（P4-a 的 R9 同类），`knowledge_gap` 的 `isolated_source` 判定可能受影响 | 极小概率误报 | 与 R1b 一并登记 |
| R-6 | 快照把「一次 lint 内同一页被读 6–7 次」收敛为 1 次 → 页面在 lint 运行中途被改写时，scan 与规则会看到**同一版本**（recon C10） | **这是行为变化（变好）**：没有任何消费者要求「读到更新的内容」 | §8.1 第 13 条 `test_each_page_read_at_most_once_during_lint` 已落地并守住 |
| R-7 | 快照构建期每页 1 次 `stat`（151 次）；磁盘字节预算的实际驻留最多约 **1.15×**（astral 字符最坏，UTF-8 str 开销） | 元数据 IO + 内存略超预算，可忽略 | 由 `test_snapshot_stats_every_page` 守住；`bench` 打印 cold/hot 的 stat 计数 |
| R-8 | `_wiki_pages()` 的 `.sink` 路径排除对 `knowledge_gap` 的 source 候选集同样生效，但旧实现（`sources_dir.rglob` + 仅 `is_path_excluded`）会看到 `.sink` 下的页 | 现实性低：sink 目录固定在 `wiki_dir/.sink`，不会出现在 `wiki/sources/` 下 | 登记备查；与 R-4 同源（两侧现均走 `_wiki_pages()`） |
| R-9 | 快照遇重复 display name（病态大小写不敏感文件系统）时保留第一个 + WARNING，被丢的页不进 `contents`/`omitted` → `total_pages` 少计 | 正常文件系统下 `_page_display_name` 是单射，不可达 | 回归测试 `test_duplicate_page_name_keeps_the_first_and_warns` 钉死行为 |

---

## 15. 实施顺序（给 Implementer）

1. **P4-b-1**：写 `kernel/wiki/snapshot.py`（`PageSnapshot` / `PageSource` / `WikiPageSource` / 两个上限常量）
   + `kernel/wiki/lint/__init__.py` 的 4 个新入口 → 跑 `tests/test_lint_engine.py`（20 个用例必须全绿）
   + 新增 `tests/test_lint_snapshot.py` 的第 1–12 条 → **此时 `run_all()` 的产出与改动前逐字相同**。
2. **P4-b-2**：`analyzer.py` 接入（`__init__` 的 `page_source` 参数、`lint()` 里建一次快照、
   `_scan_all_pages(snapshot)`、`_run_all_rules(snapshot)`、`_build_lint_context(snapshot=...)`、
   `total_pages` 用 `len(snapshot.names)`）→ 跑 `tests/test_wiki_analyzer.py`（**站点 ① 必须全绿**）、
   `tests/test_lint_handles_non_utf8_page.py`（**站点 ② ③ 必须全绿**）、`tests/test_lint_read_counts.py`（P4-a 的）。
3. **P4-b-3a**：`rules/dated_claims.py` + `rules/knowledge_gaps.py` 迁移 → 改写站点 ④ 的测试 → 跑
   `tests/test_lint_engine.py` + `tests/test_lint_handles_non_utf8_page.py` + 契约测试第 1/15 条。
4. **P4-b-3b**：`rules/query_page_overlap.py` + `rules/redundancy.py` 迁移 → 跑契约测试第 1 条。
5. 收尾：`tests/test_lint_snapshot_counts.py`（计数基准，cold ≤ 311 / rglob ≤ 2）+
   `python scripts/check_architecture.py`（0 violations）+
   `python scripts/validate_handoff.py docs/designs/refactor-handoff/p4b-lint-snapshot.design.json`。
6. 每个 commit：`ruff check <files> --output-format=concise` + 相关 `pytest`（AGENTS.md 原则 6：改完即验）。
