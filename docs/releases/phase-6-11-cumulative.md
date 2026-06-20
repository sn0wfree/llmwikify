# Changelog — Phase 6/7/8/9/10/11 Cumulative

> 本会话累计交付的 11 个 commit，覆盖 Pre-existing 阻断修复 + nanobot 借鉴
> 借鉴评估 + SkillLoader frontmatter 抽取。

## Pre-existing 阻断修复 (A 阶段)

| Commit | 内容 |
|---|---|
| `b4c40af` | `fix(v019)` — `scripts/eval_prompts.py` `_check_jinja2_rendering` test_vars 补 40+ 变量；`repro_factor_codegen.yaml` / `repro_factor_reflect.yaml` `internal`→`api_call` trigger；`test_v019_principle_checker.py::test_builtins_all_checked` expected 集加 17 个 repro_* |
| `cb56efd` | `fix(chat)` — `tests/test_chat_e2e.py` 重写为 in-process TestClient + `tests/_fixtures/mock_llm/__init__.py` monkey-patch；新建模块 `_V2PersistenceHook(AgentHook)` 修顶层 import 报 AttributeError |
| `42e6852` | `docs(chat)` — `chat_session_repo.py` 模块 docstring 补 metadata 列 + 2 新方法 |
| `5bca148` | `fix(providers)` — `apps/chat/providers/registry.py` 修 pre-existing ruff E402：line 75-76 模块级 import 提升到 TYPE_CHECKING 之下 |
| `c04a8d8` | `fix(tests)` — `tests/test_interfaces_server_autocompact_lifespan.py` 3 个 lifespan test 缺 `enable_rest=False` → `_agent_service is None` → `start_auto_compact` 永远不调；改 setup 加 `enable_rest=False` + `MagicMock` 直接 attach |

## Nanobot 借鉴 (Phase 8-10)

### Phase 8 — `goal_state` + `/goal` slash command

| Commit | 内容 |
|---|---|
| `237dd6e` | `feat(chat)` — `goal_state.py` (Phase 8 helper) + `goal_skill.py` (GoalSkill) |
| `df832e6` | `feat(chat)` — `/goal` slash command 接入 orchestrator（`/goal` / `/goal <obj>` / `/goal done [recap]`） |

### Phase 9 — `AutoCompact` (空闲会话 TTL 压缩) + lifespan wire

| Commit | 内容 |
|---|---|
| `644f404` | `feat(chat)` — `AutoCompact` 借鉴 nanobot `autocompact.py` 空闲会话 TTL 压缩 |
| `5403e5d` | `feat(server)` — AutoCompact lifespan wire：`MemoryConfig.auto_compact` 段 + `WikiServer.enable_auto_compact=True` 默认 + lifespan 启停 |

### Phase 10 — `I` (goal predicate) + `E` (in-process SubagentManager)

| Commit | 内容 |
|---|---|
| `41a4894` | `docs(poc)` — apply-plan §10 设计（I + E 数据结构 + 防递归策略） |
| `3560c50` | `feat(chat)` — `goal_active_predicate: Callable[[], bool]` 接入 ChatRunner；predicate 返回 False → `stop_reason="goal_abandoned"` |
| `dc44749` | `feat(chat)` — `SubagentManager` (in-process agent-as-tool, ~200 LOC) + `spawn_subagent` skill (~200 LOC)；7 护栏（Semaphore / 无 spawn_subagent 递归 / timeout / memory_manager=None / NoOpHook / goal predicate=None / max_iterations 10） |
| `0d7611d` | `feat(chat)` — SubagentManager wire-up：`SkillToolAdapter` 加 `subagent_manager` + `child_tool_registry` 字段；`_get_tool_registry` 缓存 key 加 `expose_subagent` 维；`_chat_via_runner_v2` 构造 SubagentManager + child registry |

## Phase 11 — SkillLoader frontmatter 解析 + /api/skills 端点 (本会话新增)

| Commit | 内容 |
|---|---|
| `1577c75` | `feat(skills)` — `skills/loader.py` 抽出 frontmatter 解析层（`SkillFrontmatter` dataclass + `parse_skill_frontmatter` 纯函数 + 23 cases） |
| `e773a9e` | `feat(skills)` — `plugin_loader._load_skill_md` 重构 + `_plugin_metadata` 旁路字段 + `_register_skills_routes` (`GET /api/skills` / `GET /api/skills/{name}`) + 10 cases |
| `09382a1` | `test(skills)` — 端到端集成测试（tmp PLUGIN_DIR + load_plugins + /api/skills 全链路） + 9 cases |

详细设计与数据对比见 `docs/poc/apply-plan.md` §11。

## 测试累计增长

| 阶段 | cases | delta |
|---|---|---|
| Pre-A baseline | ~2793 | — |
| After A (commits `b4c40af` + `cb56efd` + `42e6852`) | 2793 (本会话跑的 818 subset) | +60 (v019) + 4 (chat_e2e) |
| After D (`c04a8d8`) | +8 lifespan | — |
| After F1 (`1577c75`) | +23 loader unit | — |
| After F2 (`e773a9e`) | +10 routes | — |
| After F3 (`09382a1`) | +9 e2e | — |

## 待办 (本会话范围外)

- **WebSocket 实时 push (Phase 11-E)** — 风险高，SSE 替代决策 + 生命周期管理，待 user 拍板
- **SkillsLoader hot-reload** — registry 后 hot-reload 需要 reload 语义，本期只做 cold-start
- **/api/skills 认证** — 当前无 auth；沿用 WikiServer 全局 auth middleware