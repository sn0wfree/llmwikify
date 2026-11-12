# 参数分级与统一登记 — 业界调研 + 本项目盘点

> 日期: 2026-11-11
> 状态: **调研 + 方案（待评审）**；本文只做梳理与设计，未改代码
> 背景: 任务面板 T134 — 「统一所有参数，对所有参数也分成三级」
> 关联: `docs/designs/refactor-4layer-architecture.md`（4 层架构）、
> `docs/diagnostics/platform-free-2026-11.md`（本轮平台无关化改造）

---

## 1. TL;DR

1. **业界没有「按数字分级配置优先级」的惯例。** 13 个系统的优先级一律用
   *scope 名*（default / user / project / system）或 *source 序列表*
   （Spring 的 PropertySource）。`L0/L1/L2` 在软件里几乎专指**架构分层**。
2. **本项目的 `L1–L4` 已被架构占用**（foundation / kernel / apps / interfaces），
   再复用同一组数字表示「参数优先级」会造成「L2 既是 kernel 层又是优先级级」的歧义。
   → **归属层继续用 L1–L4，优先级另起一轴，用 scope 名而非数字。**
3. **本项目已有 2.5 级的雏形，但只覆盖 ~7% 的旋钮。**
   `apps/research/config_defaults.yaml` 有显式 `mutable:` / `immutable:` 两级分界
   （v0.41 起用于控制 API/UI 暴露面），但它只存在于 L3 的 research/chat 两个 YAML；
   其余 ~360 个旋钮（LLM 配置、env、CLI、dataclass、硬编码常量）**完全无分级**。
4. **盘点发现 6 个真正的病灶**（§6），其中 3 个是本轮平台无关化改造里已踩过的同一类 bug
   （import 期捕获配置路径）。

## 2. 业界调研

### 2.1 十三个系统的分级与优先级

| 系统 | 分级/作用域名 | 优先级（高 → 低） | 机制 |
|---|---|---|---|
| **pytest** | `pytest.toml`/`pytest.ini`/`pyproject.toml`/`tox.ini`/`setup.cfg` + CLI | CLI flags > **首个命中的配置文件**（永不合并，first-match-wins） | 向上遍历找文件 + `Config` 对象 |
| **VS Code** | Default / User / Remote / Workspace / Workspace Folder / **Policy** | Policy > folder > workspace > remote > user > default | 每 scope 一份 JSON，标量覆盖、对象合并 |
| **Spring Boot** | Property *sources*（default props、`@PropertySource`、config data、env、system props、JNDI、`SPRING_APPLICATION_JSON`、命令行、test props、devtools） | 命令行 > `SPRING_APPLICATION_JSON` > JNDI > system props > env > config data > `@PropertySource` > 默认 | `Environment` + 有序 PropertySource 列表 |
| **pydantic-settings** | Init / Env / DotEnv / Secrets / Default | init kwargs > env > dotenv > secrets dir > 字段默认值 | `BaseSettings` + `settings_customise_sources`，**深度合并** |
| **GitLab CI** | Pipeline/policy > manual job > pipeline > project > group > instance > dotenv > `.gitlab-ci.yml` | 如左 | 扁平 env 命名空间，按 job 解析 |
| **npm** | project `.npmrc` > user > global > builtin（+ CLI、env） | CLI > env > project > user > global > builtin | 全部加载后按序解析 |
| **OpenTelemetry** | env vars vs 声明式 config file vs code | `OTEL_CONFIG_FILE` **压过所有 env**；code 配置等效 | env 表 + 默认值；file 模型替代 env |
| **Kubernetes** | ConfigMap + Feature Gates(Alpha/Beta/GA) + `--feature-gates` | feature gate/CLI > config file > ConfigMap > 硬编码默认 | 集群级对象；ConfigMap-as-env **不热更新** |
| **LangChain / LangGraph** | `RunnableConfig`：`tags`/`metadata`/`callbacks`/`max_concurrency`/`recursion_limit`/`configurable` | 每次调用的 config **向下继承**到子调用 | `configurable_fields` / `configurable_alternatives` 标记可运行时覆盖 |
| **LlamaIndex** | 全局 `Settings` vs per-instance | per-instance > 全局 `Settings` | 模块级单例 |
| **Django** | settings 模块 + `settings.py` + env | env 在 `settings.py` 内读取；测试用 `override_settings` | Python 模块导入一次 |
| **Loguru / structlog** | 全局 `logger.configure` + env + 上下文 | contextual `opt(override=)` > bound context > 全局配置 > env 默认 | 全局可变 handler 栈 + `contextvars` |
| **AWS Lambda** | 仅 env（console/CLI/SAM/SDK）— **没有 config file 这一层** | env > 代码默认 | env 是唯一运行时通道 |

### 2.2 主流词汇

| 类别 | 词 | 说明 |
|---|---|---|
| 公认 | **default → user/project → system/policy** | VS Code、npm、GitLab 都用这套 |
| 公认 | **property sources** / **settings sources** | Spring、pydantic-settings |
| 公认 | **scopes** | VS Code |
| 公认 | **environments** | Django/Rails |
| ⚠️ 歧义 | global / local | "global" 是进程级还是用户级？说不清 |
| ⚠️ 歧义 | base / overlay | 无统一含义 |
| ⚠️ 歧义 | hardcoded / overridable | 描述的是机制不是层级 |
| ⚠️ 歧义 | kernel / app / user | 读起来像**架构**不像**优先级** |
| ❌ 不该用 | **tier** | 业界 "tier" 指服务等级（K8s cluster tier）/严重级别，不是优先级 |

### 2.3 数值分级（L0/L1/L2）是不是惯例？

**不是，是 ad-hoc。** 调研的 13 个系统**没有一个**用数字表示配置优先级。
`L0/L1/L2` 在软件里压倒性地指**依赖/架构分层**（OSI 式）——恰好就是本项目已占用的那套数字。

> 结论：**L1–L4 保持纯架构语义**；优先级另起一轴，且用 scope 名。

### 2.4 八个失效模式 → 本项目实例

| # | 失效模式 | 本项目是否命中 |
|---|---|---|
| 1 | **Config sprawl**（12-factor：配置散落各处各格式） | ✅ 5 个面：全局 JSON / `.wiki-config.yaml` / env / CLI / dataclass |
| 2 | **Import 期捕获**（`os.environ` 与模块常量在 import 时冻结） | ✅ `apps/agent/maintenance/config.py:13` `CONFIG_PATH`；本轮已修 `doctor_cmd.py`、`_keyring.py` 两处同型 |
| 3 | **env 必须在 import 前设**才生效 | ✅ `LLM_USE_RESOLVER` 等在模块顶层读取的开关 |
| 4 | **隐藏全局单例 → 测试顺序依赖** | ✅ `Config` / `ConfigManager` / `get_global_config_manager`；本轮已用 conftest session 隔离兜住 |
| 5 | **first-match-wins 意外** | ⚠️ pytest 同型；本项目是 deep_merge，行为不同但同样未文档化 |
| 6 | **默认值多处重复 → 漂移** | ✅ 「agent 迭代上限」有 **6 个不同默认值**（§6.1） |
| 7 | **env 与 file 无法合并**（OTel：设了 `OTEL_CONFIG_FILE` 就必须忽略其他 env） | ✅ 本项目 `resolver.py:224-245` 正是「env 逐项覆盖 config」的混合语义，未文档化 |
| 8 | **live-config 错觉**（K8s：ConfigMap 转 env 需重启才生效） | ✅ `Config.reload()` 只清缓存，不重建已启动的 client |

### 2.5 参考

- <https://docs.pytest.org/en/stable/reference/customize.html>
- <https://docs.spring.io/spring-boot/reference/features/external-config.html>
- <https://code.visualstudio.com/docs/getstarted/settings>
- <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>
- <https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/>
- <https://12factor.net/config>
- <https://docs.python.org/3/library/os.html>（import 期 `os.environ` 捕获）

## 3. 本项目参数面盘点

| 面 | 旋钮数 | 归属层 | 现状 |
|---|---:|---|---|
| 全局 JSON `~/.llmwikify/llmwikify.json` | ~70 | L1 定义，L1–L4 消费 | 11 段在 `foundation/config.py` `DEFAULT_CONFIG` + 3 段来自模板（`research` 在 `llmwikify.default.json`，`chat_mutable`/`research_mutable` 在 YAML） |
| 每 wiki `.wiki-config.yaml` | ~25（13 段） | L1 解析，L2/L3 消费 | `llm`/`research_mutable`/`chat_mutable`/`mcp`/`prompts` 段 v0.41 已迁走，但仍 merge + 告警 |
| 环境变量 | 15 直读 + ~13 间接 ≈ 28 | L1(12) / L4(10) / L3(3) | 命名不统一：`LLM_*` vs `LLMWIKIFY_*` |
| CLI flags | ~90（34 个命令文件，139 处 `add_argument`） | L4 | 多数**仅运行期生效**，不落配置 |
| MCP 工具参数 | 28 个工具 | L4 | 与 CLI 参数**重复定义** |
| dataclass spec | ~90 字段 / 9 个类 | L1(2) L2(3) L3(4) | `LLMSpec`/`ChatRunSpec`/`BaseSpec`/`RetryConfig`… |
| 硬编码常量 | ~50 | L1(5) L2(14) L3(16) L4(1) | `kernel/wiki/constants.py` 24 条最集中（阈值/上限） |

**合计 ≈ 388 个旋钮。** 密度最高：全局 JSON、chat/research YAML 默认、CLI flags。

## 4. 分级方案：两轴正交

### 4.1 轴 A — 归属层（沿用现有架构，数字不变）

| 层 | 包 | 职责 | 典型参数 |
|---|---|---|---|
| **L1** | `foundation/` | 零依赖基础设施 | LLM 连接契约、auth、重试、HTTP、配置解析 |
| **L2** | `kernel/` | 通用框架 | agent loop 步数、wiki 阈值、索引批大小、图缓存 TTL |
| **L3** | `apps/` | 应用域 | chat/research 轮次、并发、抓取条数、写模式 |
| **L4** | `interfaces/` | 入口 | CLI flag、HTTP 请求参数、MCP 工具参数 |

### 4.2 轴 B — 暴露级（新增，用 scope 名，不用数字）

| scope | 含义 | 谁能改 | 典型来源 |
|---|---|---|---|
| `defaults` | 代码默认值 | 只有改代码 | dataclass 字段默认、模块常量 |
| `internal` | 内部调参 | 开发者 / 测试 | 代码常量 + 少数 env（`LLM_USE_RESOLVER` 开关） |
| `user` | 用户参数 | 用户 | `llmwikify.json` 的 `*_mutable` 段、`.wiki-config.yaml`、env、CLI |
| `runtime` | 单次调用覆盖 | 调用方 | 函数入参、HTTP body、CLI flag |

**为什么不用数字**：避免与 L1–L4 撞号；`user`/`internal` 自解释；与 VS Code / pydantic-settings 词汇一致。

### 4.3 定级规则（可机械判定）

```
scope = defaults   若参数默认值写在代码里且无任何外部入口
scope = internal   若参数只被代码读取 / 只经 env 内部开关影响
scope = user       若参数出现在 llmwikify.json / .wiki-config.yaml / env / CLI --flag / HTTP body
scope = runtime    若参数是函数入参或请求级字段
```

**归属层** = 定义该参数的模块所在层（常量/字段声明处，不是消费处）。

### 4.4 与现有 mutable/immutable 的关系

`apps/research/config_defaults.yaml` 的 `mutable:` / `immutable:` **就是 scope 轴的雏形**：
`mutable` ≈ `user`，`immutable` ≈ `defaults`+`internal` 合一。
本方案是把它**拆细并推广到全部四层**：

- `mutable` → `user`
- `immutable` → 按「有无可调入口」拆成 `defaults` 与 `internal`

## 5. 统一优先级链

### 5.1 现状（散在各面，不一致）

| 面 | 实际链 | 出处 |
|---|---|---|
| LLM 配置 | env > 全局 JSON > 模板 > 硬编码兜底 | `foundation/llm/resolver.py:224-245` |
| LLM 配置（含 wiki） | `.wiki-config.yaml` > 全局 JSON > 模板 | `apps/config_manager.py:73`（wiki 段已废弃仍 merge） |
| 其它 JSON 段 | 全局 JSON > 模板默认 | `foundation/config.py` `get()` / `get_default()` |
| env | env 直接盖住 config，无合并规则文档 | `resolver.py:210` |
| CLI / MCP | **旁路**，多数只运行期生效，不落配置 | `interfaces/cli/commands/*` |

### 5.2 目标链（一条通链，逐层收窄）

```
runtime (函数入参 / HTTP body)
  > CLI flag / MCP 参数
  > env 变量
  > 每 wiki .wiki-config.yaml
  > 全局 ~/.llmwikify/llmwikify.json
  > 内置模板 llmwikify.default.json
  > 代码默认值 (scope=defaults)
```

配套三条规则：
1. **每个参数只有一个 scope**，不允许既是 `user` 又是 `internal`（现在 `max_chat_rounds` 两头都有）。
2. **env 只允许覆盖 `user` 级**（业界通例：env 是运维/部署通道，不是业务配置面）。
3. **`.wiki-config.yaml` 只保留 `directories`/`database`/`orphan_detection`/`performance`/`wikis`/`version`**；
   其余段已迁移，删除 merge 分支与告警。

## 6. 已发现的病灶（本次盘点实证）

### 6.1 同一概念、6 个默认值

「agent 迭代上限」：

| 位置 | 默认值 |
|---|---:|
| `apps/chat/base.py:106` `DEFAULT_MAX_TOOL_ITERATIONS` | 8 |
| `apps/chat/agent/spec.py:42` `ChatRunSpec.max_iterations` | 10 |
| `kernel/agent/spec.py:42` `BaseSpec.max_iterations` | 10 |
| `apps/chat/agent/subagent_manager.py:73` | 5 |
| `apps/chat/agent/orchestrator.py:817` `config.get("max_chat_rounds", 10)` | 10 |
| 全局模板 `chat_mutable.max_chat_rounds` | 4 |

其中 `orchestrator.py:817` 的**代码兜底 10** 与**配置默认 4** 直接矛盾 ——
若 `chat_mutable` 未并入 config，agent 会跑 10 轮而非预期 4 轮（LLM 调用量超 2.5 倍）。

### 6.2 import 期捕获（第三处）

```python
# apps/agent/maintenance/config.py:13
CONFIG_PATH: Path = Path.home() / ".llmwikify" / "llmwikify.json"
```
与本轮已修的 `doctor_cmd.py`、`_keyring.py` 同型：不认 `LLMWIKIFY_HOME`，且 import 时定死。

### 6.3 同一份配置被多处独立打开

`llmwikify.json` 至少 3 条独立读取路径：
`foundation/config.py`（`Config` 单例）、`foundation/migration.py`（`_load_global_config`）、
`apps/agent/maintenance/config.py`（模块常量）。缓存语义各不相同。

### 6.4 废弃段仍在生效

`.wiki-config.yaml` 的 `llm` 段自 v0.41 废弃，但仍 `deep_merge` + `logger.warning`
（`apps/config_manager.py:84-89`）—— 文档说废弃，行为说仍然生效。

### 6.5 CLI 与 MCP 参数重复定义

`--limit` / `--backend` / `--host` / `--mode` 等在 CLI（34 个命令，139 处 `add_argument`）
与 MCP（28 个工具）各自写一遍默认值，且 CLI 侧多数不落配置 → 两套真相。

### 6.6 env 命名与语义不统一

`LLM_*`（5 个）vs `LLMWIKIFY_*`（7 个）vs 供应商专名（`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`MINIMAX_API_KEY`）
三套命名；`LLMWIKIFY_SUBAGENT_DRIVER`（L3 内部开关）与 `LLMWIKIFY_DATA_DIR`（L4 部署）混在同一前缀下。

## 7. 参数登记表（设计）

单一真源，每个旋钮登记一次：

```python
@dataclass(frozen=True)
class ParamSpec:
    key: str                    # "chat.max_chat_rounds"
    owner: Literal["L1","L2","L3","L4"]
    scope: Literal["defaults","internal","user","runtime"]
    default: Any
    type: type
    surfaces: tuple[str, ...]   # ("json","env","cli","http") — 可出现的面
    surfaces_used: tuple[str, ...]  # 实际实现的面（用于暴露差异告警）
    doc: str
```

**登记表要回答的 3 个问题**：
1. 这个参数的**唯一**默认值在哪？（消灭 §6.1 的 6 份）
2. 它**能被谁**改？（`scope`）
3. 它**实际**在哪些面可被改？（`surfaces` vs `surfaces_used` 差异即文档缺失）

**落地形态**：登记表放 `kernel/`（L2）供 app 层 import；`foundation` 不能反向依赖，
故 L1 参数的登记表条目由 L2 汇总或下沉到 L1 自己的模块 —— **需在实施时定夺**。

## 8. 落地路线（建议分批，每批可独立验收）

| 批 | 内容 | 风险 |
|---|---|---|
| **P1** | 建登记表骨架 + 录入 L1/L2 参数（~150 个） | 低，纯新增 |
| **P2** | 消灭 §6.1 默认值漂移（收敛到单一常量） | 中，影响 agent 行为，需回归 |
| **P3** | 修 §6.2 import 期捕获第三处 + §6.3 统一配置读取入口 | 低，同本轮已做过的两处 |
| **P4** | 统一优先级链（§5.2）+ env 只覆盖 `user` 级 | 中，需文档化 + 迁移 |
| **P5** | CLI/MCP 参数收敛到登记表（消灭 §6.5） | 高，接口面变更 |
| **P6** | 删 `.wiki-config.yaml` 废弃段 merge 分支（§6.4） | 中，需迁移期 |
| **P7** | env 命名统一（§6.6） | 中，需兼容期 |

## 9. 待决策

1. **登记表放哪**：`kernel/`（L2）会与「L1 参数不可反向依赖」冲突；是放 L1 让 L2 import，还是拆两份？
2. **`.wiki-config.yaml` 是否保留**：它是唯一的「每 wiki」层，与全局 json 职责重叠。
3. **CLI/MCP 参数是否落配置**：现在多数只运行期生效；若要落，需引入 per-wiki 写入路径。
4. **`internal` 与 `defaults` 是否要分开**：分开更精确但登记量翻倍。
