# 配置中枢设计讨论记录

> 日期: 2026-11-11
> 性质: **讨论记录 / 决策日志**，不是最终方案。最终方案待单独重新评估。
> 状态: 讨论中，复杂度已明显上升，暂停实现、先行固化
> 关联: `docs/designs/parameter-tiers.md`（业界调研 + 388 旋钮盘点）、
> `docs/CONFIGURATION_GUIDE.md` §v0.41（现有三层配置架构）、
> commit `880e6f07`（已在仓的登记表第一步）

---

## 0. 文档用途

本文按时间顺序记录「统一所有参数到一个文件、由 `foundation/config.py` 统一管理」这一设计的
**全部讨论内容与已做决策**，供后续单独重新评估时直接续接。

阅读约定：

| 标记 | 含义 |
|---|---|
| **D1…Dn** | 已确认决策（用户明确表态） |
| **S1…Sn** | 建议待确认（给出理由与依据，用户尚未拍板） |
| **Q1…Qn** | 未决问题（明确留待讨论） |
| **E1…En** | 证据（业界调研结论 / 代码库实证） |

---

## 1. 任务演进

| # | 用户指令 | 产出 |
|---|---|---|
| 1 | 业界怎么分级配置参数？先调研 | `docs/designs/parameter-tiers.md`（13 系统调研 + 本项目盘点） |
| 2 | 按现有架构分层 L1/L4 来配置更清晰 | 层级归属 = L1–L4；确认业界**不用数字**表示优先级 |
| 3 | 先不用分级，把所有参数汇聚到一个文件，由 `foundation/config.py` 统一管理 | 登记表第一步落地（commit `880e6f07`） |
| 4 | 先讨论配置中枢的方案设计 | 提出职责边界 / 解析链 / API 表面 / 分层三方案 |
| 5 | L3–L1 都 import config 取参数；每层生成一个子类传参；父类负责取全量、处理、分类；可变/不可变/常量全部进中枢 | 类结构设计 |
| 6 | 父类子类都要单例；调研三个子类实现方案；`user_key` 由父类处理；多层共用参数留讨论；写回场景重点讨论 | 单例粒度定案 + 两轮业界调研 |
| 7 | 同意「同一 wiki 同一层只有一个对象」；调研子类实现；**参数下沉 L1**、标 `alias_of`；H1 选 (c)；H2 调研 | 下沉规则改写 + 两份调研 |
| 8 | `alias_of` 两个方案有啥区别 | (i) 纯去重 vs (ii) 解析穿透对比 |
| 9 | **越来越复杂了，需要仔细重新评估，先写入文档** | 本文 |

---

## 2. 已确认决策

### D1 · 单例粒度：每 (wiki_root, 层) 一个对象

**内容**

| 对象 | 生命周期 | 说明 |
|---|---|---|
| `PARAMS` 登记表 | **模块级单例**（建议 `MappingProxyType` 冻结） | 声明，永不实例化 |
| `ParamRegistry` 父类 | **每个 wiki_root 一个**，工厂缓存 | 解析结果，`registry_for(wiki_root)` 唯一 |
| `KernelParams` 等子类 | 同上，**每个 wiki_root 一个** | L2 视图 |

**理由**：真·进程级唯一会与 multi-wiki 冲突 —— 项目支持 `wikis.local[]` / `wikis.remote[]`
（`WikiInstance`、`--multi-wiki`），同进程两个 wiki 可有不同 `.wiki-config.yaml`。

**用户表态**：「同意同一 wiki 同一层，只有一个对象」

**复核点**：工厂缓存的键是 `wiki_root`，需考虑 wiki 被删除/移动后的缓存失效。

---

### D2 · 参数全部下沉 L1，`layer` 只是元数据

**内容**

- 所有参数（含常量）**物理存放**在 `foundation/params.py` 单一文件
- `Param.layer: Literal["L1","L2","L3","L4"]` 记录**语义归属**（定义/使用它的层），不是存放位置
- `alias_of` 记录同义关系
- 即使某参数**只有上层需要**（如 `mcp.port` 仅 L4 用），也下沉到 L1

**理由**：用户「就是想下沉到底层方便大家取」；`foundation` 不能 import `apps`（架构门禁），
但 `params.py` 是**纯数据、零 import**，不构成反向依赖，已由 `scripts/check_architecture.py`
（0 violation）验证。

**用户表态**：「可是我就是想下沉到底层方便大家取，各归各，但登记表标 alias_of；
某参数只有上层需要也要下沉 L1」

**复核点**：`foundation/params.py` 里出现 `chat_*` / `research_*` 前缀，概念上层倒置；
用命名空间前缀标注归属层（`chat.*`=L3，`wiki.*`=L2，`llm.*`=L1）可缓解，但需确认是否接受。

---

### D3 · H1（YAML 写回）选 (c) 最小 diff 编辑

**内容**：读为行列表 → 按缩进定位 section/key → **只替换目标行/块** → 临时文件 + `os.replace`
原子写回。其余逐字节保留。

| 能力 | 状态 |
|---|---|
| 标量键增删改 | ✅ 精确到行 |
| 嵌套键（`search.qmd.port`） | ✅ 按缩进定位 |
| 列表/字典值 | ⚠️ 只能整块替换（**块内注释会丢**） |
| YAML 锚点/别名/多文档 | ❌ 不支持，遇到即报错 |
| 新依赖 | 无（纯文本 + 正则，符合 foundation 零依赖） |

**理由**：`migration` 现用 `pyyaml` 写回会**丢用户手写注释**；(a) 换 `ruamel.yaml` 违背零依赖，
(b) 备份+文档化是放弃。(c) 无新依赖且保住注释。

**用户表态**：「H1：c」

**复核点**：列表/字典块内注释仍会丢，须写进文档；`migrate-config` 现有 `.bak.<ts>` 保留作双保险。

---

### D4 · 多层共用参数 / `user_key` 映射 → 留待讨论

**内容**：这两项明确推迟。

**用户表态**：
- `user_key`：「允许不一样这部分应该由父类处理吧后面还要继续讨论的」
- 多层共用：「后面还需要讨论一下多层共同使用的场景（也要符合 L4/L1 的原则）」

**初步框架（供后续讨论，未定案）**

多层共用只有三种场景，归属应落在**最内层（最靠近 L1）的定义方**：

| 场景 | 例子 | 归属 |
|---|---|---|
| 多层**读同一参数** | `llm.timeout` 被 L1 client、L3 chat、L4 doctor 都读 | **L1**（定义方），其它层通过子类 `get()` 间接拿 |
| 多层**各自定义同义参数** | L3 `research_mutable.max_retry_attempts` vs L1 `llm_retry_max_attempts` | **各归各**，但登记表标 `alias_of` |
| 某参数**只有上层需要** | `mcp.port` 只有 L4 用 | **L4**，不得下沉到 L1「方便大家取」 |

⚠️ **注意**：上表第三行与 **D2 直接冲突** —— D2 要求「只有上层需要也要下沉 L1」，
本表第三行写的是「L4，不得下沉」。**此冲突未解决**，是重新评估时的首要待决项。

---

### D5 · `alias_of` 语义 —— 业界调研后**两项均判反模式，改用第三框架 (iii)**

> ⚠️ **本节已修订**。原记录为「(i)/(ii) 对比，用户判定过复杂暂停」。
> 后续业界调研（E5）显示 (i) 与 (ii) **都不是业界做法**，现改录第三框架。

**内容**

业界实际有**三种机制**，我们上一轮把它们混为一谈：

| | 机制 | 代表系统 | 冲突处理 |
|---|---|---|---|
| **M1** | 名字规范化 / relaxed binding | Spring（`first-name` ≡ `firstName` ≡ `first_name`） | 规范化后**一个规范键**；按 source 优先级（后写覆盖），不是双键 |
| **M2** | **输入别名** | pydantic `AliasChoices` / Click 多 flag / argparse `dest` / clap `alias` | pydantic：**`AliasChoices` 里第一个赢**；Click：source 层级 > 显式默认 > 最后声明 |
| **M3** | **跨键解析穿透**（读 A 时去查独立键 B） | **未在任何一手资料中找到** | 无标准规则 |

**M3 判定：不存在 / 反模式。** 主流框架从不保留两个独立注册键、共享默认值后还让它们各自走一遍解析链。

**我们的 (i) 与 (ii) 分别对应**：

| 我们的选项 | 对应 | 判定 |
|---|---|---|
| **(i)** 共享默认值，键各自解析 | — | **反模式**。同一概念在进程里有两个活值，正是「两个配置键表示同一设置」「改名后的键被静默忽略」这类 bug 报告的成因 |
| **(ii)** 读规范键时穿透查别名 | M3 | **目标对，框架错**。真实系统是「**一个注册项 + 若干输入别名**，**加载时一次性解析成一个值**」，不是读时两个键互相窥探 |

**第三框架 (iii)：规范键 + 弃用别名，加载时解析**

| 步 | 行为 |
|---|---|
| 1 | 注册**一个规范键**（canonical），默认值只写在这里 |
| 2 | 旧名/别名登记为 **deprecated alias**，加载时**一次性**解析进规范键 |
| 3 | 使用旧名时**告警**（pydantic `Field(deprecated=...)` / Spring `@DeprecatedConfigurationProperty` / K8s Warning header） |
| 4 | 新旧同时存在 → **规范键或第一个别名赢**（pydantic），或**显式报错**；**不做 last-writer-wins**、**不静默存成两个真值** |
| 5 | 公告窗口后移除（K8s：GA ≥12 个月或 2 个版本；Django：多版本弃用时间线） |

**(iii) 与 (ii) 的关键区别**：解析发生在**加载时**而非读时。加载后每个概念只有一个值，
无需「族 + 读时优先级」这套机制，调试只需看一个键。这正是 (ii) 想要的效果，但成本低得多。

**对本项目 7 个「轮次」名字的落法**

| 键 | 默认 | 处理 |
|---|---:|---|
| `chat_mutable.max_chat_rounds` | 4 | → **规范键的用户可写别名**（写回落这里） |
| `ChatRunSpec.max_iterations` | 10 | → 弃用别名，加载时解析进规范键 |
| `BaseSpec.max_iterations` | 10 | → 弃用别名 |
| `DEFAULT_MAX_TOOL_ITERATIONS` | 8 | → 弃用别名 |
| `orchestrator` 兜底 10 | 10 | → **删掉硬编码兜底**，改读规范键 |
| **`subagent_manager.max_iterations`** | **5** | → **独立键**（不同 scope，不是别名） |
| **`dream.max_iterations`** | **10** | → **独立键**（不同 scope） |

规范键 `agent.max_iterations` 默认取 **4**（用户可见旋钮的值），顺带消灭 10 vs 4、30 vs 120 两处矛盾。

**关键反例（族不能乱划）** —— `subagent_manager.max_iterations=5` 是**刻意**小于主 agent 的 4；
把它划成主 agent 规范键的别名 = 取消「子 agent 单独调小」这个能力。

**术语**：业界最标准的是 **alias**（pydantic `AliasChoices`、clap `Arg::alias`）指输入别名；
**relaxed binding / name normalization**（Spring）指格式变体；
**deprecated property**（Spring/Django/K8s）指改名 + 向后兼容。
`alias_of` 作登记表字段名没问题，但文档应写成「规范键 + 加载时解析的别名」。

**URL**：docs.spring.io/spring-boot/reference/features/external-config.html ·
docs.pydantic.dev/latest/concepts/alias/ ·
docs.pydantic.dev/latest/concepts/settings/ ·
click.palletsprojects.com/en/stable/options/ ·
kubernetes.io/docs/reference/using-api/deprecation-policy/ ·
docs.djangoproject.com/en/stable/internals/deprecation/

**状态**：**调研完成，(i)/(ii) 判死，(iii) 待用户确认**。

---

## 3. 建议待确认

### S1 · 子类实现：B（手写 + 契约测试）+ `@dataclass_transform` ✅ **已确认**

**依据（E1 业界调研）**：见 §5.1。结论是 **Python 业界规范是 B**；A（纯动态生成）
成熟项目几乎从不单独用；C（动态 + `.pyi`）是「给动态库 API 发类型」的规范，
配套 `mypy stubtest` 做过期检测。

**建议形态**

```python
from typing_extensions import dataclass_transform

@dataclass_transform()
class _ParamView:
    """Base for per-layer config views; __init__ synthesized by checkers."""
    LAYER: ClassVar[str]
    def __init__(self, registry: ParamRegistry): ...

class KernelParams(_ParamView):
    LAYER = "L2"
    max_iterations: int
    similarity_threshold: float

# tests/test_foundation_params.py — 契约测试（漂移门禁）
def test_kernel_view_matches_registry():
    expected = {k for k, p in PARAMS.items() if p.layer == "L2"}
    actual = {f for f in KernelParams.__annotations__ if f != "LAYER"}
    assert actual == expected, actual ^ expected   # 对称差非空即漂移
```

**三个方案对比**

| | **A 动态生成** | **B 手写+漂移测试** | **C 动态+`.pyi`** |
|---|---|---|---|
| 类型检查 | ❌ mypy 报 unknown attr | ✅ 完整 | ✅（靠 stub） |
| IDE 补全 | ❌ | ✅ | ✅ |
| 单一来源 | ✅ | ⚠️ 靠测试挡 | ✅ |
| 加一个参数 | 只改登记表 | 改登记表 + 对应子类 | 改登记表 + 重生成 stub |
| 工具链 | 无 | 无 | 生成脚本 + stub 过期检测 |
| 报错时机 | 运行时 `AttributeError` | **写代码时** | 写代码时 |

**用户表态**：「S1：B + @dataclass_transform」 ✅

---

### S2 · H2（配置变更通知）最小模型 ✅ **已确认**

**依据（E2 业界调研）**：见 §5.2。

**建议形态**

```python
config.reload()                 # 重解析 + 清缓存，应用前校验（nginx 式，失败保旧）
config.on_change(fn) -> unsub   # reload 成功后回调，参数 = 变更键集合（Spring 式）
# 不可热更的 key 标 hot_reloadable=False（Spring 的 never-refreshable）
```

**三分法**（业界收敛点）：

| 情形 | 模型 | 例子 |
|---|---|---|
| 值便宜、每次取 | **Pull / 用时重读** | 大多数 `get_param` 调用 |
| 派生对象贵、要精确失效 | **Push / 事件** | LLM client 重建 |
| 结构性设置 | **Restart-only** | 端口、transport、`mcp.host` |

**⚠️ 关键补充（用户指出）**：ClickHouse 的 `changeable_without_restart` 是**唯一手维护**的部分
（`collectChangeableServerSettings()` map，带开发者注释要求手工更新）——
**连 1000+ 参数的项目都没能把「可变性」完全 codegen**。
→ **`hot_reloadable` 字段必须手写，不要试图从声明推导。**

**用户表态**：「S2:就是我 S2 的内容，有依据。注意：ClickHouse 的 changeable_without_restart 是手维护的…
说明 hot_reloadable 字段应该手写，不要试图从声明推导」 ✅

---

### S3 · 写回（`set_param`）设计

**依据**：写回场景只有 S1/S2/S3 三个真实场景，全部由 **L4** 触发；S4/S5（运行时覆盖、
测试隔离）**不落盘**，走 `runtime` scope，不属写回。

| 项 | 建议 |
|---|---|
| `set_param` 位置 | 父类实现，**只在 `InterfacesParams` 导出** |
| 可写判定 | 有 `user_key` 且 `mutable=True` |
| 校验 | 未知键 / 类型 / 不可变 → 一律拒绝 |
| 写回原子性 | 临时文件 + `os.replace` |
| 未知键 | **保留**（按键 merge，不整体覆盖 section） |
| YAML 注释 | **D3 = (c)** 最小 diff |
| 通知 | **写回不通知**，调用方显式 `reload()` |

**状态**：**建议已给出，用户尚未拍板**。

---

### S3 · 写回（`set_param`）→ 业界建议：**不要建通用 `set_param`** ✅ **调研完成**

**依据（E7 业界调研）**：见 §5.7。

**核心结论**：**业界绝大多数系统根本没有程序化写回。**

| 系统 | 有写回？ | 谁写 |
|---|---|---|
| Django settings | **无** | 只有人改 settings 文件 |
| Prometheus | **无** | 人改 YAML；`/-/reload`、SIGHUP **只重读** |
| Spring Cloud Config | **无** | server **只读** git，文档原话「never makes changes to the remote」 |
| nginx | **无** | 人改；HUP 重读 + 语法检查 + 失败回滚 |
| OpenTelemetry SDK | **无** | 初始化时读 |
| K8s ConfigMap（应用侧） | **无** | 控制面/kubectl 经 API；pod 是 `readOnly=true` 挂载；env 需重启 |
| **K8s API / SSA** | **有** | **CLI/UI/controller**（`fieldManager`），**不是工作负载应用** |
| VS Code settings.json | **有** | 设置编辑器 / UI |
| Terraform / Consul / Ansible | **有** | **CLI / 控制面**，**不是应用代码** |

**Django 的措辞最强（业界最明确的「应用不得写回」规则）**：

> *「You shouldn't alter settings in your applications at runtime… The only place you
> should assign to settings is in a settings file.」*

**技术规则**（若将来要写）：
- **原子性**：`os.replace` 是 Python 标准（同文件系统要求；跨设备失败；Windows 上优于 `rename`）
- **写前校验**：类型/范围/未知键 —— Prometheus 拒绝坏 reload、Spring 校验 git、pydantic/JSON Schema 编码约束
- **备份/审计**：用 git（Spring「for auditing changes」）或 K8s `managedFields`，**不是 `.bak`**
- **并发**：last-writer-wins 或乐观 CAS（K8s 冲突、Consul CAS）；小工具很少用文件锁

**→ 结论：不建通用 `set_param`。** 保留 `Config.save()` 作唯一写路径（现有 CLI/UI 调用点够用）。
若将来要暴露，强制四条：校验 → 保留未知键 → 同目录原子 `os.replace` → last-writer-wins + 审计日志。

**用户表态**：上一轮要求「写回场景重点讨论」，本轮业界给出「不要建」的结论。

---

### S4 · `Param` 字段集 ✅ **调研完成**（`layer` 用户已要求保留）

**依据（E7 业界调研）**：见 §5.7。

**关键发现**：**业界没有标准的 owner/layer 字段。**

| 系统 | 字段列表 | 有 owner/layer？ |
|---|---|---|
| ClickHouse `DECLARE` | type, name, default, description, flags(成熟度 tier \| IMPORTANT), alias, history | **无**（flags 只有 tier） |
| pydantic `Field` | default, alias/validation_alias, title, description, examples, deprecated, ge/le/gt/lt, pattern, … | 无 |
| Spring `spring-configuration-metadata.json` | name, type, description, sourceType, defaultValue, deprecation{level,reason,replacement,since}, hints | **无**（sourceType 是声明类，不是 layer） |
| JSON Schema 2020-12 | title, description, default, examples, deprecated, readOnly/writeOnly, enum, min/max | 无 |
| K8s API field | description, default, format, enum, deprecated；运行时归属靠 `managedFields` 的 **writer** | 无（writer ≠ config layer） |
| `pg_settings` | name, setting, unit, category, context, vartype, source, min/max, enumvals, … | 无（category/context 是文档+运行时） |
| VS Code contribution | type, default, description, enum, **scope**(user/workspace/application), deprecationMessage | scope ≈ **在哪可设**，不是 owner |

**归属在业界用结构化表达**（独立的声明文件/家族/命名空间）。最接近的：
PG `category`（逻辑分组）、Spring `groups`（命名空间）、VS Code `scope`（设置位置）、Envoy `category`（文档分组）。

**字段集判定（含先例标注）**

| 字段 | 先例 | 判定 |
|---|---|---|
| `key` | 普遍 | ✅ 必备 |
| `default` | 普遍 | ✅ 必备 |
| `type` | CH/pydantic/Spring/JSON Schema | ✅ 必备 |
| `doc` | 普遍 | ✅ 必备 |
| constraints（enum/range/pattern） | pydantic/JSON Schema/PG | ✅ 建议加 |
| `deprecated` + replacement | Spring/JSON Schema | ✅ 建议加（D5 的 (iii) 需要） |
| `mutable` / context | **部分** —— PG `context`、JSON Schema `readOnly` | ✅ 有先例 |
| **`layer`** | **不常见** —— 无标准；Spring `groups` 只是命名空间 | ⚠️ **hub-specific，但用户明确要求保留** |
| **`env`** | **不常见作元数据** —— 业界把 env 当 **source** 而非字段属性 | ⚠️ hub-specific（对我们有用） |
| `user_key` / `alias_of` | **部分** —— pydantic `alias` | ✅ 有先例（改名场景） |
| `scope`（可选） | VS Code | 可选 |

**→ 建议**：保留 `key, default, type, doc`；**加** constraints + deprecated；
`layer`/`env` 标注为 hub-specific（业界无先例，但对我们有价值）；`alias_of` ≈ pydantic alias。

**用户表态**：「然后S4 需要layer」 ✅ `layer` 保留。

---

## 4. 未决问题

| # | 问题 | 选项 | 倾向 | 阻塞什么 |
|---|---|---|---|---|
| **Q1** | **`alias_of` 语义** | ~~(i) 纯去重~~ / ~~(ii) 解析穿透~~ / **(iii) 规范键 + 弃用别名，加载时解析** | **(iii)**（见 D5，业界调研后 (i)(ii) 均判反模式） | 登记表字段设计、D5 落地 |
| **Q2** | **族的划分规则** | ~~待设计~~ | **(iii) 下大幅简化**：无需「读时族 + 优先级」，只需判断「哪些键是规范键的弃用别名」vs「哪些是独立 scope 的键」 | Q1 落地 |
| **Q3** | **`user_key` 映射规则** | 待设计（父类处理） | — | 写回落点、D2 层归属 |
| **Q4** | **多层共用参数的归属** | 待设计（须符合 L4→L1） | — | **与 D2 冲突**，见 §2 D4 复核点 |
| **Q5** | `alias_of` 语义 (i)/(ii) 是否过复杂 | ✅ **已解决** | 调研后改用 (iii)（见 D5） | — |
| **Q6** | **`layer` 字段是否过度** | 保留 `layer` / 改用 family 分组 / 由 `prefix` 推导 | ✅ **已解决**：用户「S4 需要 layer」→ **保留**；E7 确认业界无此标准，标为 hub-specific | — |
| **Q7** | **是否建通用 `set_param`** | 建 / 不建 | ✅ **已解决**：E7 业界几乎都**没有**程序化写回（Django 明确禁止）→ **不建**，保留 `Config.save()` | — |

---

## 5. 证据附录

### 5.1 E1 · 子类实现方式的业界调研

调研 12 个系统（pydantic-settings、django-stubs、Spring Boot 注解处理器、client-go、
config-rs、viper、zod、TypeBox、SQLAlchemy、VS Code、PEP 561/681）：

| 系统 | 机制 | 手写/生成 | 漂移怎么抓 |
|---|---|---|---|
| pydantic-settings | `BaseSettings` 注解字段 | **手写** | 单一来源；PEP 681 合成 `__init__` |
| SQLAlchemy 2.0 | `Mapped[int] = mapped_column()` | **手写** | 注解即 schema |
| Spring `@ConfigurationProperties` | 手写 bean + 注解处理器生成 metadata | 类手写，metadata **构建时生成** | 不可能漂移 |
| client-go | 手写 struct + json tag | **手写** | 生成 deepcopy |
| Rust `config` crate | `try_deserialize::<T>()` | 用户 struct **手写** | serde 形状校验 |
| Go viper | `Unmarshal(&C)` + mapstructure | **手写** | `UnmarshalExact` 拒未知键 |
| zod / TypeBox (TS) | schema-first，类型从值推导 | **无独立类** | 不可能漂移 |
| Django + django-stubs | `.pyi` 手写 + mypy 插件读活模块 | stub 手写 | `stubtest` |
| VS Code settings | JSON Schema | schema-first | 客户端补全/悬停 |

**三条结论**：
1. **Python 规范是 B（手写 + 漂移测试）**
2. **A 成熟项目几乎从不单独用** —— 正是 PEP 681 要解决的痛点
3. **C 是「给动态库 API 发类型」的规范**，配套 `mypy stubtest`

**给生成类标类型的优先级**（PEP 681 / PEP 561）：

| 优先级 | 手段 |
|---:|---|
| 1 | 不生成，手写 + `@dataclass_transform()` |
| 2 | 生成 + 发 `.pyi` + CI 跑 `stubtest` |
| 3 | 类型检查器插件（django-stubs，仅 mypy） |
| 4 | `Protocol` / `__getattr__` + overloads（降级 `Any`，最后手段） |

**URL**：docs.pydantic.dev/latest/concepts/pydantic_settings/ ·
github.com/typeddjango/django-stubs ·
docs.spring.io/spring-boot/specification/configuration-metadata/annotation-processor.html ·
peps.python.org/pep-0681/ · peps.python.org/pep-0561/ ·
pkg.go.dev/k8s.io/client-go/tools/clientcmd/api#Config ·
pkg.go.dev/github.com/spf13/viper · docs.rs/config/latest/config/ ·
zod.dev/ · docs.sqlalchemy.org/en/20/orm/declarative_tables.html

---

### 5.2 E2 · 配置变更通知的业界调研

调研 10+ 系统（VS Code、K8s、Django、Prometheus、nginx、Spring Cloud、Consul、
OTel、systemd、Vite、Dynaconf）：

| 系统 | 模型 | 粒度 | 谁重建状态 |
|---|---|---|---|
| VS Code extension API | Push：`onDidChangeConfiguration` | **按键**（`affectsConfiguration(section)`） | 消费方 |
| Vite/webpack HMR | Push：HMR API | 每模块 | 框架 + 模块 `accept` |
| K8s ConfigMap（挂卷） | Watch/pull 混合 | 整投影键 | kubelet 投影，**app 须自己重读** |
| K8s ConfigMap（env 注入） | **无** —— 「require a pod restart」 | — | 进程重启 |
| Prometheus | Signal/端点：`POST /-/reload`、`SIGHUP` | 整配置 | server 自己 |
| nginx | Signal：`HUP`，语法错回滚保旧 | 整配置 | master 进程 |
| Spring Cloud | 事件 + DI：`EnvironmentChangeEvent` + `@RefreshScope` | 按键列表，重绑是整 bean | DI 容器 |
| Consul watches | 订阅：blocking query → handler | 按键/前缀 | 外部 handler |
| systemd | `ExecReload=` / `Type=notify-reload` | 整服务 | daemon 自己 |
| Django settings | Pull，**restart-only** —— 「You shouldn't alter settings in your applications at runtime」 | — | 进程重启 |
| OTel SDK | 初始化时读，无 watch/reload API | — | 无人（重建 SDK） |

**两条最有价值的工程细节**：
1. **systemd 明确反对 fire-and-forget**：`kill -HUP $MAINPID` 「is usually not a good choice」，
   推荐同步 reload 或 `notify-reload` 握手（带超时，失败保旧）
2. **Spring 的 partial apply 是显式声明的**：`spring.cloud.refresh.never-refreshable` /
   `extra-refreshable`；构造器绑定的 bean「cannot be refreshed」；失败模式 =
   「a concurrent reader can observe transient, partially-updated state」

**三家为什么选 restart-only**：
- Django：运行时改 settings 是未定义行为
- K8s env 注入：进程环境在容器启动时固定
- OTel：SDK 配置是 builder 的初始化输入，热重配会使 exporter/processor 图失效

**URL**：kubernetes.io/docs/concepts/configuration/configmap/ ·
docs.djangoproject.com/en/stable/topics/settings/ ·
prometheus.io/docs/prometheus/latest/management_api/ ·
nginx.org/en/docs/control.html ·
docs.spring.io/spring-cloud-commons/reference/.../application-context-services.html ·
opentelemetry.io/docs/specs/otel/configuration/api/

---

### 5.3 E3 · 本项目参数面盘点

| 面 | 旋钮数 | 归属层 |
|---|---:|---|
| 全局 JSON | ~70 | L1 定义，L1–L4 消费 |
| `.wiki-config.yaml` | ~25（13 段） | L1 解析，L2/L3 消费 |
| 环境变量 | ~28 | L1(12) / L4(10) / L3(3) |
| CLI flags | ~90（34 个命令文件，139 处 `add_argument`） | L4 |
| MCP 工具参数 | 28 个工具 | L4 |
| dataclass spec | ~90 字段 / 9 类 | L1(2) L2(3) L3(4) |
| 硬编码常量 | ~50 | L1(5) L2(14) L3(16) L4(1) |

**合计 ≈ 388 个旋钮。** 已镜像进登记表 **85 条（22%）**。

---

### 5.4 E4 · 代码库实证（问题与证据）

#### 5.4.1 同义参数家族（`alias_of` 的动机）

| 家族 | 名字数 | 不同默认值 |
|---|---:|---:|
| **轮次/迭代上限** | **7** | **5**（4/5/8/10） |
| **重试次数** | 6 | 2 |
| **超时** | 6+ | 6 |

**轮次家族明细**

| 键 | 默认 | 位置 |
|---|---:|---|
| `chat_mutable.max_chat_rounds` | 4 | `six_step_config_defaults.yaml` |
| `subagent_manager.max_iterations` | 5 | `apps/chat/agent/subagent_manager.py:73` |
| `DEFAULT_MAX_TOOL_ITERATIONS` | 8 | `apps/chat/base.py:106` |
| `ChatRunSpec.max_iterations` | 10 | `apps/chat/agent/spec.py:42` |
| `BaseSpec.max_iterations` | 10 | `kernel/agent/spec.py:42` |
| `dream.max_iterations` | 10 | `apps/chat/memory/dream.py:63` |
| `orchestrator` 兜底 | 10 | `apps/chat/agent/orchestrator.py:817` |

#### 5.4.2 已抓到的矛盾（实证）

| # | 矛盾 | 位置 |
|---|---|---|
| 1 | `llm_retry_call_timeout` **兜底 30.0 vs YAML 120.0**（4 倍差，配置未加载时 LLM 调用 30 秒被掐） | `apps/chat/skills/workflows/tool_executor.py:179` vs `six_step_config_defaults.yaml:22` |
| 2 | `max_chat_rounds` **兜底 10 vs 配置 4** | `apps/chat/agent/orchestrator.py:817` vs 模板 |
| 3 | `base.py:275` 注释写 `Default 4`，`base.py:106` 常量是 `8` | `apps/chat/base.py` |
| 4 | 全局 `research` 段 vs research YAML `immutable` 段 3 个同名 key 默认值不同 | `minimax_api_key`（`""` vs `null`）、`minimax_api_host`（`""` vs URL） |

#### 5.4.3 import 期捕获（已修 2 处，第 3 处仍在）

| 位置 | 状态 |
|---|---|
| `interfaces/cli/commands/doctor_cmd.py:26` `CONFIG_PATH = Path.home() / ...` | ✅ 已修（改 `_config_dir()` 调用时解析） |
| `foundation/auth/_keyring.py:48` `_SECRET_FILE = ...expanduser()` | ✅ 已修（改 `_secret_file()`） |
| **`apps/agent/maintenance/config.py:13` `CONFIG_PATH = Path.home() / ...`** | ❌ **仍在** |

#### 5.4.4 其它病灶

- **同一份配置 3 条独立读取路径**：`foundation/config.py`（`Config` 单例）、
  `foundation/migration.py`（`_load_global_config`）、`apps/agent/maintenance/config.py`（模块常量）
- **`.wiki-config.yaml` 的 `llm` 段已废弃但仍 merge**：`apps/config_manager.py:84-89` 只 `logger.warning`
- **CLI 与 MCP 参数重复定义**：139 处 `add_argument` vs 28 个 MCP 工具，各自写默认值
- **env 命名三套混用**：`LLM_*`(5) / `LLMWIKIFY_*`(7) / 供应商专名(3+)

#### 5.4.5 本轮改造过程中抓到的自伤 bug

| bug | 说明 |
|---|---|
| `section_defaults` 前缀切片 | 用未归一化 `"llm"` 而非 `"llm."`，多出一层 `{"": {...}}` → 由 `DEFAULT_CONFIG` 等价性校验抓到 |
| `get_param` wiki 作用域查错路径 | 查 `rest`（`timeout`）而非完整点号路径（`llm.timeout`），漏 section 层 → 由解析顺序测试抓到 |

### 5.5 E5 · 多名同义配置的业界调研（`alias_of` 依据）

调研 Spring、pydantic(-settings)、Click、argparse、clap、K8s、Django、Dynaconf 一手文档。
**结论见 D5**。要点：

- **M3（跨键解析穿透）不存在** —— 未在任何一手资料中找到；作为设计特性是反模式
- **业界标准做法是 M2（输入别名）+ 弃用改名**：一个注册项、若干输入别名，**加载时一次性解析成一个值**
- **冲突处理**：规范键或第一个别名赢（pydantic）、source 层级优先（Click/Spring）；
  **不是** last-writer-wins，**不**静默存成两个真值
- **弃用窗口**：K8s GA ≥12 个月或 2 个版本、废弃 CLI **必须告警**；Django 多版本时间线；
  pydantic `Field(deprecated=...)` 运行时告警 + JSON Schema 标注
- **术语**：`alias`（输入别名）、`relaxed binding`（格式变体）、`deprecated property`（改名 + BC）

**URL**：见 D5 末尾。

### D6 · 「一个文件装所有」的现实边界（依据 E6 ClickHouse 调研）

**内容**

**单一真相源是「声明/注册表」，不是「文件布局」。** 1000+ 参数的项目**没有一个把所有参数装进一个文件**：

| 项目 | 声明收在哪 | 配置文件怎么分 |
|---|---|---|
| **ClickHouse**（1000+） | X-macro 列表 `src/Core/Settings.cpp` 的 `COMMON_SETTINGS(DECLARE, ...)` | `config.xml` + `config.d/`（服务端）· `users.xml` + `users.d/`（用户/配额）· `<profiles>` · session `SET` · per-query `SETTINGS` |
| **PostgreSQL**（~300） | GUC C 条目 + 文档 | `postgresql.conf` → `ALTER SYSTEM` → session `SET` |
| **VS Code**（~2000） | `package.json` 的 `contributes.configuration` | user → workspace → remote |
| **Spark**（~400） | `SQLConf`/`SparkConf` 的 `ConfigEntry` | spark-defaults → `--conf` → SQL |

**规则**：按**归属作用域**拆文件（服务端全局 / 每用户 / 每次运行），底下共用一个注册表。

**对本项目的推论**：`foundation/params.py` 是**声明/注册表**（唯一真相源），
不是「所有参数都只在一个文件里」——配置文件仍按作用域分（全局 json / 每 wiki yaml / runtime 覆盖）。
**D2 的「下沉 L1」指的是声明收在一处，不是文件只有一份。**

**另两条**：
1. **归属用结构化表达**（每个 family 一份声明列表、嵌套配置路径、scope 列），
   显式的 per-setting「owner」元数据在业界**很少见** —— 与 D2 的 `layer` 字段有张力，需复核
2. **`changeable`（热更/需重启）是 ClickHouse 唯一手维护的部分**（`collectChangeableServerSettings()` map，
   带开发者注释要求手工更新）—— **连 1000+ 参数的项目都没能把「可变性」完全 codegen**，
   我们的 `hot_reloadable` 字段同样应手维护

**状态**：**建议待确认**（与 D2 的 `layer` 字段复核项见上）。

---

### 5.6 E6 · 大项目参数管理调研（ClickHouse 深挖）

**ClickHouse（已验证）**

- **单源声明**：X-macro 列表，`src/Core/Settings.cpp` 的 `COMMON_SETTINGS(DECLARE, DECLARE_WITH_ALIAS)` + `OBSOLETE_SETTINGS`。每条形如
  `DECLARE(Type, name, default, R"(markdown 描述)", flags[, alias][, {"版本", 旧默认, 新默认, 理由}...])`。
  Settings.cpp 内约 1400+ 条 `DECLARE(`，另有 server/format/MergeTree 各自的列表 →「1000+」成立
- **`system.settings` 是生成的**：`Settings::dumpToSystemSettingsColumns()` **在查询时遍历宏列表**生成，无第二份手维护表。
  列：`name, value, changed, description, min, max, disallowed_values, readonly, type, default, alias_for, is_obsolete, tier`
  （`tier` 为 Enum8：Production/Obsolete/Experimental/Beta/PrivatePreview）
- **热更标志**：`system.server_settings.changeable_without_restart` = Enum8 `No=0, IncreaseOnly=1, DecreaseOnly=2, Yes=3`
  （**4 个值，不是 0/1/2**）。**关键**：它**不在 DECLARE 列表里**，是手维护的
  `collectChangeableServerSettings()` map，注释写着 *「If you add a setting which can be updated at runtime,
  please update the 'changeable_settings' map」* —— 不在 map 里一律报 `No`（需重启/重载）
- **分层**：`config.xml` + `config.d/*.xml` 字典序合并（带 `replace`/`remove` 属性）；
  `users.xml` + `users.d/`；`<profiles>`（可继承，「latest defined is used」）；
  `SET profile='x'` → session `SET` → per-query `SETTINGS` 覆盖。
  ⚠️ 文档**未给出**一条完整优先级链
- **变更历史**：`SettingsChangesHistory` = 每个 DECLARE 的可选尾部元组 `{"24.4", 旧默认, 新默认, "理由"}`，
  聚合成 `system.settings_changes`，驱动 `compatibility` 设置（回放旧默认值）
- **内省与文档**：`system.settings` / `system.server_settings` / `system.settings_changes` /
  `system.settings_profiles` / `SHOW SETTINGS`；**503 页 settings 文档由源码自动生成**
  （`clickhouse-docs/scripts/settings/autogenerate-settings.sh`）
- **校验**：类型来自 DECLARE；运行时边界走 profile 的 `<constraints>`（`min`/`max`/`disallowed`/`readonly`/`const`），
  违反抛 Code 452；flags 字段带 tier（EXPERIMENTAL/OBSOLETE）+ IMPORTANT

**对照表** ⚠️ 除 ClickHouse 外，其余行**本轮未重新验证一手来源**，仅作线索

| 项目 | ~参数数 | 声明机制 | 生成元数据 | 热更/需重启 | 分层覆盖 | 内省 |
|---|---:|---|---|---|---|---|
| **ClickHouse** ✅ | 1000+ | X-macro `DECLARE` | ✅ system 表 + 文档脚本 | `changeable_without_restart`（**手维护 map**） | config.d → users.d → profiles → SET → SETTINGS | `system.settings*`, `SHOW SETTINGS` |
| PostgreSQL ⚠️ | ~300 | GUC C 条目 | `pg_settings` 视图 | `context` 列 | postgresql.conf → ALTER SYSTEM → SET | `pg_settings`, `SHOW ALL` |
| Redis ⚠️ | ~200 | `redis.conf` + src 参数表 | 部分（`CONFIG GET`） | 逐参数 dynamic 标志 | config → `CONFIG SET` → CLI flags | `INFO`, `CONFIG GET/SET` |
| Envoy ⚠️ | 1000+ | protobuf `bootstrap.yaml` schema | 由 proto 生成 | 多数经 xDS 热更 | 静态 bootstrap + 动态 LDS/CDS | `/config_dump` |
| Nginx ⚠️ | ~300 | `ngx_command_t` 数组 | 文档手写 | SIGHUP 重载 vs 全重启 | conf.d/ include 链，后者胜 | `nginx -T` |
| Spark ⚠️ | ~400 | `SQLConf`/`SparkConf` 的 `ConfigEntry` | 文档半生成 | 多数运行时，少数需重启 | spark-defaults → `--conf` → SQL | `spark.conf`, UI |
| VS Code ⚠️ | ~2000 | `contributes.configuration` | JSON schema + 设置 UI | 逐项「requires reload」标注 | user → workspace → remote | 设置 UI, schema |

**五个综合问题的答案**

1. **主流模式**：**从单一声明列表生成的注册表**。ClickHouse、Spark、VS Code、Envoy 都是；
   **没人手工维护并行表** —— 例外正是 ClickHouse 的 changeable map（公认弱点）
2. **多面不可避免**：1000+ 参数下**没人「一个文件装所有」**。**单一真相源是「声明/注册表」，不是「文件布局」**
3. **归属**用结构化表达（每个 family 一份宏列表、嵌套配置路径、scope 列）；
   显式 per-setting「owner」元数据很少见
4. **工具**：从声明生成的内省表、`SHOW` 命令、同源文档自动生成、变更历史注册表、约束校验、tier/废弃标志
5. **对 388 旋钮的可移植建议**：① 一个 Python 注册表作唯一源 ② **其余全部生成** —— CLI flags、
   JSON schema、文档表、内省命令 ③ **2-3 个作用域层**（global/wiki/session），**不是 7 个 ad-hoc 面**
   ④ 一个轻量改名/默认值变更历史表。
   **过度工程**：四值可变性枚举、兼容回放机制、per-setting XML 路径、生成 C++ 静态结构体

**URL**：clickhouse.com/docs/en/operations/system-tables/settings ·
/operations/system-tables/server_settings · /operations/system-tables/settings_changes ·
/operations/configuration-files · /operations/settings/settings-profiles ·
/concepts/features/configuration/settings/constraints-on-settings ·
github.com/ClickHouse/ClickHouse/blob/master/src/Core/Settings.cpp ·
github.com/ClickHouse/clickhouse-docs/blob/main/scripts/settings/autogenerate-settings.sh

### 5.7 E7 · 写回机制与登记表字段的业界调研

**A. 程序化写回**（结论见 S3）

| 系统 | 有写回？ | 谁写 | 原子？ | 保留未知键？ | 注释？ |
|---|---|---|---|---|---|
| Django settings | **无** | 只有人改 settings 文件 | — | — | Python 文件 |
| Prometheus | **无** | 人改 YAML；`/-/reload` **只重读** | — | 否（拒绝畸形） | YAML 注释保留（文件不重写） |
| Spring Cloud Config | **无** | server **只读** git；「never makes changes to the remote」 | — | — | git 历史 |
| nginx | **无** | 人改；HUP 重读 + 语法检查 + 失败回滚 | — | 否 | 文件保留 |
| OpenTelemetry SDK | **无** | 初始化时读 | — | — | — |
| K8s ConfigMap（应用侧） | **无** | 控制面/kubectl 经 API；pod `readOnly=true`；env 需重启 | API server | 类型化 schema 会裁剪未知字段 | — |
| **K8s API / SSA** | **有** | **CLI/UI/controller**（`fieldManager`），**非应用** | API server | 未拥有字段被删除/默认化 | — |
| VS Code settings.json | **有** | 设置编辑器 / UI | 编辑器写 | ⚠️ 未完全验证 | JSONC 保留 |
| Terraform / Consul / Ansible | **有** | **CLI / 控制面**，**非应用代码** | plan/apply、KV CAS | IaC 合并语义 | HCL 注释 |

**写的技术规则**：
- **原子**：`os.replace` 是 Python 标准（同文件系统要求，跨设备失败；Windows 上优于 `rename`）
- **写前校验**：类型/范围/未知键
- **备份/审计**：git 或 K8s `managedFields`，**不是 `.bak`**
- **并发**：last-writer-wins 或乐观 CAS

**B. 登记表字段**（结论见 S4）

| 系统 | 字段 | owner/layer？ |
|---|---|---|
| ClickHouse `DECLARE` | type, name, default, description, flags(tier \| IMPORTANT), alias, history | **无** |
| pydantic `Field` | default, alias, title, description, examples, deprecated, ge/le/gt/lt, pattern, … | 无 |
| Spring `spring-configuration-metadata.json` | name, type, description, sourceType, defaultValue, deprecation{level,reason,replacement,since}, hints | **无** |
| JSON Schema 2020-12 | title, description, default, examples, deprecated, readOnly/writeOnly, enum, min/max | 无 |
| K8s API field | description, default, format, enum, deprecated；运行时归属靠 `managedFields.writer` | 无 |
| `pg_settings` | name, setting, unit, category, context, vartype, source, min/max, enumvals, … | 无 |
| VS Code contribution | type, default, description, enum, **scope**, deprecationMessage | scope ≈ **在哪可设**，非 owner |

**没有标准 owner/layer 字段**。归属用结构化表达（独立声明文件/家族/命名空间）。

**URL**：docs.djangoproject.com/en/stable/topics/settings/ ·
prometheus.io/docs/prometheus/latest/configuration/configuration/ ·
kubernetes.io/docs/concepts/configuration/configmap/ ·
docs.spring.io/spring-cloud-config/reference/server/environment-repository/git-backend.html ·
nginx.org/en/docs/control.html ·
docs.python.org/3/library/os.html#os.replace ·
docs.spring.io/spring-boot/specification/configuration-metadata/format.html ·
docs.pydantic.dev/latest/api/fields/ ·
www.postgresql.org/docs/current/view-pg-settings.html ·
json-schema.org/understanding-json-schema/reference/annotations ·
kubernetes.io/docs/reference/using-api/server-side-apply/ ·
github.com/ClickHouse/ClickHouse/blob/master/src/Core/Settings.cpp

---

## 6. 实现计划草案（**未执行**，待设计定案后重排）

| 步 | 内容 | 风险 | 状态 |
|---|---|---|---|
| 1 | 登记表 + `DEFAULT_CONFIG` 派生 + `get_param()` + 一致性测试 | **低**（零行为变更） | ✅ **已提交** `880e6f07` |
| 2 | 登记表补全到 ~388 + `Param.layer/mutable/alias_of/user_key` 字段 | 低（纯新增） | ⬜ |
| 3 | 4 个 `@dataclass_transform` 子类 + 契约测试 | 低（新增视图） | ⬜ |
| 4 | `ParamRegistry` 父类：解析链 + 溯源 + `reload()`/`on_change()` | 中（动中枢） | ⬜ |
| 5 | 迁移消费点，消灭 5 个默认值家族的漂移 | 中（改行为，需回归） | ⬜ |
| 6 | 最小 diff YAML 编辑 + 写回 API（只 L4 导出） | 中 | ⬜ |

**当前覆盖率**：登记表 85 条 / ~388 ≈ **22%**。
已镜像旧默认源：模板 JSON 38 / research YAML 7 / six-step YAML 9 = 54 条。
（覆盖率棘轮测试见 `tests/test_foundation_params.py`）

---

## 7. 已在仓里的改动（commit `880e6f07`）

| 文件 | 内容 | 行为影响 |
|---|---|---|
| `foundation/params.py`（新） | 登记表 `Param` + `PARAMS`（85 条）+ `param_default/param_spec/params_under/section_defaults` | 无 |
| `foundation/config.py` | `DEFAULT_CONFIG` 改为**从登记表派生**；新增 `Config.get_param(key, wiki_root=None)` | **无**（`DEFAULT_CONFIG` 与 HEAD 版本逐字节相等，有 AST 等价性测试断言） |
| `tests/test_foundation_params.py`（新） | 11 条：漂移检测 + 覆盖棘轮 + 解析顺序 + 键名合法性 | — |

**校验**：ruff ✓ · mypy 411 files ✓ · 157 配置相关测试 ✓ · `scripts/check_architecture.py` 0 violation ✓

⚠️ **`foundation/params.py` 的 docstring 已注明覆盖率是渐进的**（「Coverage is growing
incrementally」），避免误导为已全量。

---

## 8. 重新评估时的检查清单

重新评估配置中枢方案时，建议按此顺序核对：

1. **先解 Q4**：D2（「只有上层需要也要下沉 L1」）与 D4 初步框架第三行（「L4，不得下沉」）**直接冲突**，必须先定
2. **再定 Q2 族划分规则** —— 它决定 Q1 的 (i)/(ii) 能否成立；划错（如把 `subagent_manager.max_iterations` 拉进主 agent 族）比不做更糟
3. **再看 Q1 `alias_of` 语义** —— 本轮已判定「过复杂，暂停」
4. **核对 S1 子类实现**是否仍按 B + `@dataclass_transform`（有业界依据，但未拍板）
5. **核对 S2/S3** 写回与通知模型是否仍按建议
6. **评估复杂度预算** —— 本轮用户反馈「越来越复杂了」，建议为方案设定复杂度上限
   （如「参数总数 388、子类 4 个、新增类 3 个」），超出即裁剪
7. **复核 D1 单例缓存失效**：`registry_for(wiki_root)` 在 wiki 被删除/移动后如何失效

---

## 9. 相关文档

- `docs/designs/parameter-tiers.md` —— 业界参数分级调研 + 388 旋钮盘点（第 1 轮产出）
- `docs/CONFIGURATION_GUIDE.md` §v0.41 —— 现有三层配置架构（全局 / Wiki / 默认），
  本次设计**不推翻**它，而是在其上加一层登记表
- `docs/diagnostics/platform-free-2026-11.md` —— 本轮平台无关化改造（import 期捕获 bug 的来源）
- `docs/designs/refactor-4layer-architecture.md` —— 4 层架构与依赖规则（L4→L3→L2→L1）
