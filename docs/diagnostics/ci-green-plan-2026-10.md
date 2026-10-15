# CI 转绿 & 合并 main 专项（B2）— 调查与执行计划

> 日期: 2026-10-13
> 范围: `dev/refocus-v0.40-2026-07-05 @ 97d3347` → `main` 的 PR 门禁（Tests / Lint / E2E）
> 数据: black 541 文件待重排 · ruff 113 错 · mypy 684 错/140 文件 · pytest 52 failed / 4819 passed
> 状态: **调查完成，执行暂缓**（7 步执行计划已定稿，见 §7）

---

## 1. TL;DR

main 的 CI 从 **2026-07-03 起全红**（Tests / Lint / E2E 三个 workflow 都倒在 `pip install -e ".[dev]"`）。
✅ **根因已在本机干净环境复现**：py3.12 → `error: resolution-too-deep`；py3.10 → 25 分钟超时仍在
starlette/anyio 版本回退（见 §3.6）。
即使安装修复，lint 三件套也全部不达标：**black 从未整体格式化过**（541 文件）、ruff 113 错、
mypy 684 错（其中挖出 **4 个真 bug**）。pytest 全量摸底 **52 failed**，可归为三类：
Playwright e2e（12，缺 marker 过滤）、无 mock 的真 LLM 连接（25，缺 marker 门禁）、真实断言漂移（15）。

结论：合并前需要一个「CI 转绿」专项，方案见 §7。

## 2. 分支拓扑（2026-10-13 实测）

```
origin/main          d9156f9
local main           b89494b   (+2 本地未推送 docs 提交: 5a3c68d, b89494b)
dev/refocus-v0.40    97d3347   = origin/main + 146 commits（含上述 2 个）
```

- `git rev-list --left-right --count origin/main...HEAD` → `0  146`（**纯快进可行，零冲突**）
- GitHub main **无分支保护**；`gh` CLI 已登录 `sn0wfree`（owner）
- 合并方式：PR 流程（`gh pr create` → checks 全绿 → `gh pr merge --merge`）

## 3. CI 现状调查

### 3.1 main 历史红灯

- 最近 4 次 main 推送（`a77b5db` / `160f57f` / `372353b` / `d9156f9`，07-03 ~ 07-04）：
  **Tests、Lint and Type Check、E2E 全部 failure**。
- 三个 workflow 共同倒在第一步 **「Install dependencies」**；旧日志已过期（GitHub 保留 90 天）。
- jaraco pin（`d6abd37`，07-01）已在 main 上，先于失败 → 不是该问题。
- dev 分支已删除 `quantnodes` extra（`2937f24` 等）→ **已证伪**：干净环境仍然失败（见 §3.6）。

### 3.2 本地门禁实测（dev @ 97d3347，与 CI 同版本工具）

| 检查 | 命令 | 结果 |
|---|---|---|
| black | `black --check src/llmwikify tests`（26.3.1） | **541 files would be reformatted**（107 unchanged） |
| black 版本对照 | 24.10.0 / 25.1.0 / 26.3.1 | 均 ~541 → **非版本漂移，是代码库从未整体格式化** |
| ruff | `ruff check src/llmwikify tests`（0.15.20） | **113 errors**（30 可自动修） |
| mypy | `mypy src/llmwikify`（1.20.1） | **684 errors / 140 files**（共 401 源文件） |

### 3.3 ruff 113 项分布

```
 30  I001 unsorted-imports [*]
 29  F841 unused-variable          ← 全在 tests
 28  E712 true-false-comparison    ← 全在 tests
  6  E402 / 6 F821 / 4 B007 / 3 B017 / 2 E741 / ...
```

`src/llmwikify` 内 F841=0、E712=0 → ruff 修复集中在 tests。

### 3.4 mypy 684 项分布

按包：`apps 369 · kernel 188 · interfaces 75 · foundation 52`

| 错误码 | 数量 | 含义 | 性质 |
|---|---|---|---|
| no-any-return | 226 | 返回 Any（duck-typed 透传） | 噪音为主 |
| no-untyped-def | 99 | 缺类型注解 | 补注解即可 |
| attr-defined | 71 | 访问不存在的属性（动态属性） | 多为 duck-typing，**混有真 bug** |
| arg-type | 42 | 实参类型不匹配 | 部分真实 |
| misc | 37 | 生成器返回类型注解不符等 | 注解问题 |
| var-annotated / has-type | 27 / 26 | 无法推断变量类型 | 噪音 |
| func-returns-value | 22 | 使用「只返回 None」函数返回值 | 模式噪音 |
| return-value / assignment / override | 21 / 21 / 20 | 返回值/赋值/覆写 | 部分真实 |
| union-attr | 15 | Optional 未收窄 | 部分真实 |
| unused-ignore | 13 | 多余的 `# type: ignore` | 可直接删 |
| 其余（index/operator/valid-type/import-*/call-* 等） | ~44 | 混杂 | 含真问题 |

### 3.5 pytest 全量摸底（本机，19m16s）

```
52 failed, 4819 passed, 68 skipped, 1 xfailed in 1156.92s
（LLMWIKIFY_DATA_DIR=/tmp/opencode/pytest-data，-p no:cacheprovider）
```

**失败分类**：

| 类别 | 数量 | 文件分布 | 说明 |
|---|---|---|---|
| Playwright e2e | 12 | `tests/e2e/test_{insights,searchbar,editor,debug}.py` | 需要浏览器/已构建的前端；pyproject 已声明 `e2e` marker 但 addopts **未排除**（设计意图是 `pytest -m e2e` 才跑） |
| 真 LLM 连接 | 25 | `test_v018_integration.py`(12) · `test_v019_harness_regression.py`(11) · `test_wiki_core.py`(3) | 直连 `localhost:11434`(Ollama)/`api.openai.com`，无 mock；应标记 `llm` 并默认排除，或改为 mock |
| 真实断言漂移 | 15 | `test_v019_wiki_synthesize`(2) · `test_wiki_ops`(2) · `test_v020_markitdown_extractor`(2) · `test_v016_investigations`(2) · `test_source_analysis`(2) · `test_sink_flow`(1) · `scenarios/test_02`(1) · `scenarios/test_10`(1) · `test_wiki_routes_token_body`(1) | 需逐个调查修复（KeyError `entities` / `is_sink`、503、extractor fallback、synthesis 空结果等） |

### 3.6 安装失败复现与隔离（✅ 2026-10-13）

干净 venv 执行 `pip install -e "/home/ll/llmwikify[dev]"`：

| Python | 结果 | 证据 |
|---|---|---|
| 3.12 | **`error: resolution-too-deep`** | pip 明确放弃：*Dependency resolution exceeded maximum depth*；日志显示它在遍历 `starlette 0.40→0.52` × `fastapi 0.130→0.132` 全候选组合 |
| 3.10 | 1500s **超时**（仍在回退） | 反复下载 `starlette 0.44→0.52` / `anyio 3.4→3.7` 组合，耗尽 25 分钟预算 |

判定与隔离（逐个 extra dry-run，超时 240s）：

| extra | 结果 |
|---|---|
| `[web]` | ✅ 18s |
| **`[mcp]`（fastmcp>=3.0.0）** | ❌ **240s 超时 ← 第一爆炸点** |
| `[extractors]` | ✅ 127s（偏慢） |
| `[agent]` / `[graph]` / `[watch]` / `[config]` / `[llm]` | ✅ 19s / 26s / 13s / 11s / 9s |

初步修复验证（p312）：

| 测试 | 结果 |
|---|---|
| `fastmcp==4.1.0` | ✅ 22s |
| `fastmcp>=3.0,<4`（加界） | ✅ 22s |
| `.[mcp,extractors]` / `.[web,mcp]` / flat 全 extras / flat+llm（均加 `fastmcp<4`） | ❌ 4 组全部 240s 超时（真正原因见 §3.7） |

关键背景（2026-10 检查 PyPI 元数据）：

- `starlette` 已到 **1.7.0**，出现新包 **`httpx2`**；`mcp` SDK 已到 **2.3.0**
  （要求 `pydantic>=2.12`、`sse-starlette>=3.0`→`starlette>=0.49.1`、`httpx2>=2.10`）；
  `fastmcp` 已到 **4.1.0**（拆分出 `fastmcp-slim`）。
- 项目 pyproject：`starlette>=0.27`、`fastapi>=0.104`、`fastmcp>=3.0` —
  **全无上界**，pip 需要遍历 `starlette 0.27→1.7` × `fastapi 0.104→0.143` × `fastmcp 3.x/4.x`
  的交叉网格，直接爆炸。
- 本机能用只因依赖是历史上**增量安装**的，从未做过一次全新解析 —— 这就是 CI 每次挂在
  「Install dependencies」的直接原因。

### 3.7 根因定位（🎯 已找到硬冲突）

**`llmwikify` base 依赖 `keyring>=21.2.0,<24` 与 `fastmcp>=3.0` 直接冲突**：

```
llmwikify[base]            keyring>=21.2.0,<24
fastmcp>=3.0               → fastmcp-slim[client,server]==X
                           → py-key-value-aio[filetree,keyring,memory]>=0.4.4,<0.5.0
                           → keyring>=25.6.0          ← 硬冲突
```

一致性解释（此前所有现象都吻合）：

- `fastmcp>=3.0,<4` **单独**解析 ✅ 22s（没有 keyring 约束，pip 直接选 keyring 25.6+）；
- 放进 `[mcp]` / `[dev]`（含项目 base 依赖 `keyring<24`）立刻 ❌ 超时/too-deep；
- pip 为化解冲突遍历 `fastmcp 3.x/4.x` × `starlette 0.27→1.7` × `fastapi 0.104→0.143`
  全组合 → `resolution-too-deep`（py3.12）/ 25 分钟超时（py3.10）。

关键元数据证据：

- `fastmcp-slim 3.4.8 [client,server]`：`starlette>=1.0.1`、`mcp>=1.24,<2.0`、
  `httpx>=0.28.1,<1.0`、`py-key-value-aio[filetree,keyring,memory]<0.5,>=0.4.4`
- `py-key-value-aio 0.4.6 [keyring]`：**`keyring>=25.6.0`**
- 项目 `keyring<24` 的由来：2026-07 的 twine/jaraco 生态 workaround（注释自称寿命 6-12 个月）
- 旁证：`uv`（PubGrub 解析器，通常秒级）对**原始** pyproject 的 `[dev]` 解析
  同样 **900s 超时** → 冲突真实存在，不是 pip 单方面缺陷

**修复方向（已基本验证）**：解除/上调 `keyring` 上限（候选 `keyring>=25.6,<28`），
复核 `twine>=4,<5` / jaraco pin 是否还需要；`auth/_keyring.py` 只用
`get_password/set_password`（跨版本稳定 API），升级风险低。p312 验证结果：

| 测试 | 结果 |
|---|---|
| `fastmcp>=3.0,<4` + `keyring<24`（复现组） | ❌ 64s 失败：pip 为化解冲突退到 dbus-python 源码构建，环境缺系统库中止（冲突存在的又一佐证） |
| `fastmcp>=3.0,<4` + `keyring>=25.6,<28`（修复组） | ✅ **37s 通过** |
| `fastmcp>=3.0,<3.3` + 原 keyring pin（V1 保守绕行） | ❌ **317s `ResolutionImpossible`**：pykv 0.4.4/0.4.5/0.4.6 **全部**要求 `keyring>=25.6` → **keyring 上限必须解除，无退路** |
| 沙盒全量 `[dev]`（仅 sed keyring → `>=25.6,<28`） | ✅ **p312 101s / p310 128s / p311 380s 三版本通过** |
| **V1b：keyring 解禁 + `fastmcp<3.3` + `starlette<1`（对齐本机栈）** | ✅ **106s 通过（🎯 推荐）** |

> 备注：本机 env 的 `pykw 0.4.4 + keyring 23.13.1` 是**增量安装留下的元数据不一致状态**
> （运行时未触发被违反的约束所以能跑）——这正是"本机可用、全新解析必炸"的原因。

> 结论：**安装修复 = 3 行 pin 改动**（keyring 必改 + `fastmcp<3.3` / `starlette<1` 对齐本机栈），
> 沙盒端到端验证通过（p312 106s / p310 128s / p311 380s）；CI「Install dependencies」从此可解。
> 执行时在真实 pyproject 上复测 ×3 版本 + 复核 twine/jaraco pin 是否可一并清理。

### 3.8 ⚠️ CI 全新安装 vs 本机开发环境的版本漂移

| 包 | 本机（开发/验证环境） | CI 全新安装（修复后 p312 解析） | 风险 |
|---|---|---|---|
| fastmcp | **3.2.3** | **4.1.0** | 🔴 大版本（API 可能不兼容） |
| starlette | **0.52.1** | **1.7.0** | 🔴 大版本 |
| mcp | 1.27.0 | 2.3.0 | 🔴 大版本 |
| fastapi | 0.135.1 | 0.143.0 | 🟡 小版本 |
| keyring | 23.13.1 | 25.7.0 | 🟡 API 稳定 |
| pydantic | 2.12.5 | 2.14.1 | 🟡 |
| black / ruff / mypy | 26.3.1 / 0.15.10 / 1.20.1 | **26.10.1 / 0.17.0 / 2.4.0** | 🟡 直接影响 lint 修复结果 |

含义（B2 第 5 步路线选择——已实测）：

- **🎯 推荐 V1b（锁旧 + keyring 必改）**：`keyring>=25.6,<28` + `fastmcp>=3.0,<3.3` + `starlette>=0.45,<1`。
  沙盒实测 106s 通过，解析栈几乎与本机一致：
  `fastmcp 3.2.4 · starlette 0.52.1 · mcp 1.30 · fastapi 0.143 · keyring 25.7 · pykv 0.4.6`（178 包）。
- 备选 V2（只改 keyring）：CI 装 `fastmcp 4.1 / starlette 1.7 / mcp 2.3` —— 三个大版本 API 风险，不推荐。
- 注意：lint 工具版本差异（black 26.10.1 / ruff 0.17.0 / mypy 2.4.0）**两条路线都躲不开** →
  lint 修复必须在"修复后 pyproject 的干净 venv"里跑，与 CI 版本严格一致。

## 4. ⭐ mypy 挖出的 4 个真 bug（已人工验证）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| 1 | `foundation/utils.py:87` | `from .config import get_config` — **该函数不存在**（只有 `load_config`/`get_default_config`），调用被 try/except 吞掉 | 用户配置 `ssrf_protection` 段永远不生效 · ✅ **已修复（2026-10-14，见 [ssrf-config-fix-2026-10.md](ssrf-config-fix-2026-10.md)）** |
| 2 | `apps/agent/maintenance/gap_filler.py:305` | `WebSearch()` 缺必填 `config`（签名 `WebSearch(config: dict)`） | gap filler 的 web 搜索永远静默失败 · ✅ **已修复（2026-10-14，见 [gap-filler-websearch-fix-2026-10.md](gap-filler-websearch-fix-2026-10.md)）** |
| 3 | `apps/chat/research_agent.py:70` | `ResearchEngine(llm_client=...)` 缺必填 `wiki`/`db` | 该路径执行即 TypeError · ✅ **已修复（2026-10-14，见 [legacy-wrappers-fix-2026-10.md](legacy-wrappers-fix-2026-10.md)）** |
| 4 | `interfaces/server/__init__.py:13` | `create_unified_server` 传 `agent=` 给 `WikiServer`（无此参数） | 弃用包装器完全不可用 · ✅ **已修复（2026-10-14，见 [legacy-wrappers-fix-2026-10.md](legacy-wrappers-fix-2026-10.md)）** |

## 5. 决策记录（用户已确认）

| 项 | 决策 |
|---|---|
| black | **全量格式化一次** + `.git-blame-ignore-revs` |
| mypy | **修 4 个真 bug（配复现测试）+ 清 13 个 unused-ignore**；其余 140 文件 per-module `ignore_errors` baseline |
| ruff | 清零（30 自动 + 手工） |
| 验收范围 | **Tests + Lint + E2E 三门禁全绿** |
| 合并方式 | PR：`gh pr create` → checks 全绿 → `gh pr merge --merge` |
| 执行位置 | **dev 分支追加提交**（单 PR，避免二次合并冲突） |

排除项：`prompt_quality.yml`（路径过滤器指向已不存在的旧目录，不触发；`scripts/eval_prompts.py` 已不存在）、
`version-bump.yml`（手动触发）、`dependency-review.yml`（自动绿）。

## 6. 已知风险

- **安装修复已去风险**：沙盒验证 = 改一行 `keyring` pin（见 §3.7）；其余为常规复测。
- black 全量格式化产生大 diff（541 文件）；用 `.git-blame-ignore-revs` 缓解 blame 污染。
- pytest 的 15 个真实断言失败是**剩余最大不确定性**（逐个人工排查）。
- e2e.yml 是 docker 流程（wheel → 镜像 → `00→01→02→03` 脚本链），失败原因未排查。
- mypy baseline 是过渡方案，需要 TODO 跟踪后续逐模块收紧。

## 7. 执行计划（✅ 已执行，2026-10-14 全部完成）

| # | 提交 | 内容 | 验收 |
|---|---|---|---|
| 1 | `1631263` + `4051a66` | black 26.10.1 全量格式化（546 文件）+ `.git-blame-ignore-revs` | ✅ black --check 绿 |
| 2 | `8ae8c2b` `d81ac94` `74a19fd` | 4 个真 bug 修复 + 复现测试（1b SSRF / 2 gap_filler / 3 ResearchAgent / 4 server wrapper） | ✅ 相关测试通过 |
| 3 | `61fa079` | ruff 109→0（I001/F841/E712 批量 + B008 FastAPI 豁免 + 24 项手工） | ✅ ruff 绿 |
| 4 | `8edd50f` | mypy baseline：138 存量模块 `ignore_errors`（`__init__` 归一化为包名） | ✅ mypy 全绿 401 files |
| 5 | `e52c90f` + `d9af82d` 等 | keyring 解禁 + fastmcp/starlette 栈对齐 + dev 补 pytest-asyncio/polars + llm/e2e marker 门禁 + 依赖升级兼容（youtube 1.x / markitdown 0.1.8）+ 测试污染修复（PEP 562 实体化）+ flaky 去除 | ✅ 全量 4795 passed / 0 failed |
| 6 | — | e2e docker `run-e2e.sh` | 🔶 执行中 |
| 7 | — | push + PR + CI 三绿 | 待做 |

执行顺序调整：deps 修复（原第 5 步前半）提到最前——black/ruff/mypy 必须在
「CI 同款干净 venv」下执行（`/tmp/opencode/b2-venv`，解析 = CI 完全一致）。

边界：`graphify-out/`、`dist/`、`.pytest_cache` 不入库；每步独立可回滚；全程无 force push。

## 8. 待办 / 进行中

- [x] **干净 venv 安装复现**（py3.10 / py3.12）：✅ 已确认 `resolution-too-deep` / 超时（见 §3.6）
      → 日志：`/tmp/opencode/ci-repro/install-3.10.log`、`install-3.12.log`
- [x] 逐 extra 隔离 + 根因定位：✅ `keyring<24` × `fastmcp`（见 §3.7）
- [x] 沙盒修复验证：✅ V1b（keyring 解禁 + fastmcp<3.3 + starlette<1）p312 106s / p310 128s / p311 380s
- [x] B2 venv 实装：✅ p310 99s，black 26.10.1 / ruff 0.17.0 / mypy 2.4.0（= CI 解析）
- [x] black / ruff / mypy 三门禁本地全绿
- [x] pytest 全绿：4795 passed / 0 failed（36 → 0，含 17 QuantNodes/polars、
      6 llm marker、6 依赖兼容、7 测试污染/PEP 562 实体化、1 flaky）
- [ ] e2e 本地 docker 验证（执行中）
- [ ] PR 后 CI 实际表现（3 版本矩阵 + e2e 容器）

## 9. 证据（关键命令）

```bash
# 拓扑与快进判定
git rev-list --left-right --count origin/main...HEAD        # 0	146
git merge-base --is-ancestor origin/main HEAD; echo $?      # 0
gh api repos/sn0wfree/llmwikify/branches/main/protection    # 404 无保护

# CI 历史
gh run list --branch main --limit 12                        # 07-03..04 全 failure
gh run view <id> --json jobs                                # 失败步骤 = Install dependencies

# 本地门禁（dev @ 97d3347）
/usr/bin/python3 -m black --check src/llmwikify tests       # 541 reformatted
/usr/bin/python3 -m ruff check src/llmwikify tests --statistics
/usr/bin/python3 -m mypy src/llmwikify --cache-dir /tmp/opencode/mypy-check

# pytest 全量
LLMWIKIFY_DATA_DIR=/tmp/opencode/pytest-data \
  /usr/bin/python3 -m pytest -q --tb=short -p no:cacheprovider
# → 52 failed, 4819 passed, 68 skipped, 1 xfailed in 1156.92s

# 环境：/usr/bin/python3 = 3.10.12（editable）；black 26.3.1 / ruff 0.15.20 /
#       mypy 1.20.1 / Docker 29.3.0 / gh 已登录 sn0wfree
```
