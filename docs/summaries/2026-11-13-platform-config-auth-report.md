# 会话工作报告 — 平台无关化 · 配置中枢 · Auth 缺陷清零

> 日期: 2026-11-11 → 2026-11-13
> 分支: `main`（本报告落笔时 ahead `origin/main` **39 commits，未 push**）
> 状态: **三阶段主体完成**；全量测试 **5115 passed / 0 failed** · mypy **412 files 0 错** · 架构门禁 **0 violation**
> 关联文档:
> - `docs/diagnostics/platform-free-2026-11.md` — Phase 1 细节
> - `docs/designs/config-hub-design-log.md` — Phase 2 决策日志 D1–D7 / Q1–Q7
> - `docs/designs/parameter-tiers.md` — 388 旋钮盘点 + 业界调研
> - `docs/llmwikify-auth-缺陷清单.md` — Phase 3 的 25 条缺陷与修复批注

---

## 0. 一页总览

| 阶段 | 目标 | 状态 | 代表 commit |
|---|---|---|---|
| **Phase 1 平台无关化** | Windows ↔ POSIX 行为一致 | ✅ 完成 | `0d3c2d1f` `ca763d2a` `9f9dd8f1` |
| **Phase 2 配置中枢** | 全部参数进登记表，`foundation/config.py` 统一解析 | ✅ 步 1–6 完成；Q1–Q7 全关闭 | `880e6f07` … `13616df7` |
| **Phase 3 Auth 缺陷** | 25 条缺陷按 P0→P1→P2 清零 | ✅ **22/25 已修**，3 条挂起有据 | `02e3f36c` … `a5918fe3` |

```
Phase 1 ──► Phase 2（设计 9 轮 → 实现 6 步）──► Phase 3（审计 25 条 → 分批修复）
                │                                    │
                └─ 步 6 与 Phase 3 并行收尾          └─ Q3/Q4 拍板 + 覆盖 162 条
```

**最终数字**

| 指标 | 值 |
|---|---|
| 全量测试 | **5115 passed** / 106 skipped / 2 xfailed / 0 failed |
| mypy | **0 errors**（412 source files） |
| 架构门禁 | **0 violation**（4 层 + apps peer + 1833 imports） |
| 登记表 `PARAMS` | **162** 条（apps 101 · kernel 47 · foundation 8 · interfaces 6） |
| Auth 缺陷 | P0 **5/5** · P1 **7/7** · P2 **10/13**（P2-3/9/12 挂起） |
| 复现脚本 | `tools/auth_defect_verify.py` **4/4 NOT reproduced**；`exploit_check_wikis_claim.py` 授权面已拦 |

---

## 1. Phase 1 · 平台无关化

### 1.1 问题

Windows 上跑全量测试暴露两类平台耦合（详见 `platform-free-2026-11.md`）：

| # | 症状 | 根因 |
|---|---|---|
| 1 | 页名/sink/index 键跨平台不一致 | `str(Path.relative_to(...))` 在 Windows 返回 `\` |
| 2 | sink `created` vs `sunk` 永远对不上 | `:` 在 NTFS 上是 **ADS**：`Query: Foo.md` 落成 0 字节 `Query`，内容进备用数据流，`rglob("*.md")` 扫不到 |
| 3 | 计时 flaky | `time.monotonic()` 粒度 **~15.6ms**；`time.time_ns()` ~1ms 也不够 → 改 `perf_counter` + 严格递增 |
| 4 | 测试污染真实 HOME | `expanduser("~")` 在 Windows 看 `USERPROFILE` 不看 `$HOME` → 唯一可靠覆盖是 **`LLMWIKIFY_HOME`** |

### 1.2 约定（两条）

| 字符串类型 | 规则 |
|---|---|
| **逻辑路径**（页名 / sink / index / 报给 LLM 的相对路径） | 永远 POSIX（`.as_posix()`），经 `portable_path()` 落盘 |
| **OS 路径**（`exists()` / `read_text()` / `Path` 对象） | 系统原生，不转 |

### 1.3 关键 commit

| commit | 内容 |
|---|---|
| `0d3c2d1f` | 逻辑路径统一 `as_posix`，页名经 `portable_path` 落盘 |
| `ca763d2a` | 运行时长改 `perf_counter` |
| `f4fb450f` | research 事件 `ts` 严格递增 |
| `9f9dd8f1` | home 解析收敛 `global_config_home`；修 PDF 异常穿透 |
| `0492b045` | conftest session 级 `LLMWIKIFY_HOME` 隔离 |
| `76493c81` | `_keyring` 改**调用时**解析 home（同型 import 期捕获第 3 处） |

### 1.4 同型 bug 清单（import 期捕获，全修）

| 位置 | 症状 | commit |
|---|---|---|
| `doctor_cmd.py:26` `CONFIG_PATH` | 不认 `LLMWIKIFY_HOME` | `9f9dd8f1` |
| `auth/_keyring.py` `_SECRET_FILE` | 密钥留在真实 HOME，隔离被打破（P0-4） | `9f9dd8f1` |
| `foundation/config.py` `Config._home/_path` | 单例在 import 时冻结，测试读到真实配置 | `9c05ab3e` |

---

## 2. Phase 2 · 配置中枢

### 2.1 任务演进（9 轮）

| # | 用户指令 | 产出 |
|---|---|---|
| 1 | 业界怎么分级配置参数？先调研 | `parameter-tiers.md`（13 系统 + 388 旋钮盘点） |
| 2 | 按 L1–L4 架构分层更清晰 | 层级 = 架构层；优先级另起 scope 轴 |
| 3 | 先不分级，所有参数汇聚一个文件由 `foundation/config.py` 管 | 登记表步 1（`880e6f07`） |
| 4–7 | 讨论职责边界 / 单例粒度 / 子类 / 写回 | D1–D6 决策 + 两轮业界调研 |
| 8 | `alias_of` 两个方案区别 | 判 (i)(ii) 反模式 → 改 D5 (iii) |
| 9 | **越来越复杂，先写入文档** | `config-hub-design-log.md` |

### 2.2 已确认决策

| # | 决策 | 一句话 |
|---|---|---|
| **D1** | 单例粒度 | 每 `(wiki_root, 层)` 一个；进程级单例会破坏 multi-wiki |
| **D2** | 参数物理存放 | **全部下沉** `foundation/params.py`（纯数据零 import）；`layer` 只是元数据 |
| **D3** | YAML 写回 | **(c) 最小 diff 行编辑** + 原子 `os.replace`；保注释 |
| **D4** | 多层共用 / `user_key` | 初稿留讨论 → **2026-11-13 拍板**（见 §2.5） |
| **D5** | `alias_of` 语义 | **(iii) 规范键 + 弃用别名，加载时解析**；(i)(ii) 业界均判反模式 |
| **D6** | 「一个文件装所有」 | **不现实**（ClickHouse/Postgres/VS Code 都按作用域拆）；单一真相源是**声明/注册表**不是文件布局 |
| **D7**（Q7） | 通用 `set_param` | **不建**（Django 明确禁止应用写回）；保留 `Config.save()` 为唯一写路径 |

### 2.3 问题关闭状态

| # | 问题 | 状态 |
|---|---|---|
| Q1 | `alias_of` 语义 | ✅ D5 (iii) |
| Q2 | 族划分规则 | ✅ (iii) 下大幅简化：只需区分「弃用别名」vs「独立 scope」 |
| Q3 | `user_key` 映射 | ✅ **不建字段**（2026-11-13） |
| Q4 | 多层共用归属 | ✅ **D2 赢**，D4 第三行撤回字面义（2026-11-13） |
| Q5 | (i)/(ii) 是否过复杂 | ✅ 已改 (iii) |
| Q6 | `layer` 是否过度 | ✅ 保留（用户要求 + hub-specific） |
| Q7 | 是否建 `set_param` | ✅ 不建 |

### 2.4 实现 6 步（全部完成）

| 步 | 内容 | commit | 状态 |
|---:|---|---|---|
| 1 | 登记表 + `DEFAULT_CONFIG` 派生 + `get_param()` | `880e6f07` | ✅ |
| 2 | `Param` 加 `layer`/`hot_reloadable`/`deprecated` | `2037bffd` `011bfacf` | ✅ |
| 3 | 4 视图 + `nest()` + 生成式 `params.pyi` + 契约测试 | `c7189831` | ✅ |
| 4 | `ParamRegistry` 解析链 + `reload()`/`on_change()`；修 import 期捕获 | `9c05ab3e` | ✅ |
| 5 | 迭代上限家族收敛 `agent.max_iterations`（7 名 5 值 → 3 scope） | `dcdd49d8` | ✅ |
| 6 | 最小 diff YAML 写回（`yaml_edit` + `Config.save` 原子/deep_merge + `save_wiki_config`） | `dc1a3e1f` | ✅ |

**解析链**（高 → 低）：

```
env  >  per-wiki .wiki-config.yaml  >  global llmwikify.json  >  registry default
```

**写回**（S3 / Q7 收口）：

| 方法 | 行为 |
|---|---|
| `Config.save(data, section=None)` | 全局 JSON：原子 pretty 写；`section` 模式 **deep_merge**（未知键保留） |
| `Config.save_wiki_config(wiki_root, data, delete_keys=None)` | `.wiki-config.yaml` 最小 diff；不通知 registry，调用方显式 `reload()` |
| ~~`set_param`~~ | **不建** |

**新文件**：`foundation/yaml_edit.py`（`set_in_yaml` / `delete_in_yaml` / `write_text_atomic`；锚点/别名/多文档拒绝）。

### 2.5 Q3 / Q4 拍板（2026-11-13）

**Q4 · 多层共用 —— 以 D2 为准**

| 维度 | 结论 |
|---|---|
| 声明存放 | 一律 `foundation/params.py` |
| 语义归属 | `Param.layer` = 谁定义/使用 |
| 实现代码 | 留在原层，经 `param_default` / `registry.get` / 分层视图读取 |
| D4 第三行「L4 不下沉」 | **撤回字面义** —— 它约束的是**实现**，D2 下沉的是**声明** |

**Q3 · `user_key` —— 不建字段**

原用途（写回可写判定）已被 Q7 `不建 set_param` 消解；键即配置路径；改名走 `alias_of`。UI 显示名 YAGNI。

### 2.6 登记表覆盖

| 时点 | 条数 | 说明 |
|---:|---:|---|
| 步 1 首版 | 85 | 模板 JSON 38 + mutable YAML + wiki 阈值 |
| Q3/Q4 批 | **162** | + research immutable 26 + chat immutable 52 |

**分层**：apps 101 · kernel 47 · foundation 8 · interfaces 6。

**config-file 面已满**：模板 JSON 38/38、research/chat mutable 全覆盖。

**刻意不进表**（~388 里约占一半）：CLI flags ~90、dataclass ~90、env ~28、MCP 工具入参 —— 无「配置文件默认值」语义，进表只稀释真相源。

**棘轮**：`tests/test_foundation_params.py` 的 `COVERAGE_BASELINE` 只升不降。

### 2.7 过程中抓到的坑

1. **`.pyi` 遮蔽 `.py`** —— 生成 stub 漏声明会让 mypy 改读 stub → stub 必须声明全部导出名 + 契约测试
2. **`type: type | None`** 字段名遮蔽内建 → stub 写 `builtins.type | None`
3. **`Config` 单例 import 期捕获 home** → `home`/`path` 改属性、调用时解析
4. **PowerShell 5.1 不支持 `&&`**；`git stash show "stash@{0}"` 必须加引号

---

## 3. Phase 3 · Auth 缺陷清零

### 3.1 审计结论

基线 `main @ 3e09b0c3`，方法 = **读代码 + 逐条可复现**（非静态猜测）。**25 条，0 误报**。

复现脚本（已入库 `tools/`，状态全在临时目录）：

```bash
python tools/exploit_check_wikis_claim.py   # P0-1/2/5 授权面
python tools/auth_defect_verify.py          # P1-5/6、P0-3、P1-7
```

### 3.2 修复总表

| 级别 | 总数 | 已修 | 挂起 |
|---|---:|---:|---|
| P0 | 5 | **5** | 0 |
| P1 | 7 | **7** | 0 |
| P2 | 13 | **10** | 3 |

#### P0（全清）

| # | 问题 | 修法 | commit |
|---|---|---|---|
| P0-1 | `wikis` claim 只盖 `/api/wiki/` ⇒ 跨 wiki 越权读 | 校验扩到跨搜索/目录等路由 | `152a8297` |
| P0-2 | `public_read=True` 默认 ⇒ 未认证可读全部 | 默认改回环语义 | `152a8297` |
| P0-3 | 旧 schema 迁移 `DROP TABLE` 静默清库 | `DROP COLUMN` + 备份 + 保留行 | `02e3f36c` |
| P0-4 | JWT 密钥不随 `LLMWIKIFY_HOME` | `_secret_file()` 调用时解析 | `9f9dd8f1` |
| P0-5 | `/api/wikis` 泄漏 `root` 绝对路径 | 对外隐藏 / 纳入 claim | `152a8297` |

#### P1（全清）

| # | 问题 | 修法 | commit |
|---|---|---|---|
| P1-1 | `auto_first_admin` 不查已有 admin ⇒ 可造多管理员 | 新邮箱 → `registration_closed`（对齐 HTTP） | `52dc305e` |
| P1-2 | `create-token` 无 `--user` | 加 `--user`（email/username/id） | `52dc305e` |
| P1-3 | `auth init` 覆盖他人 `local_token` | 归属保护 + `--force` | `52dc305e` |
| P1-4 | `auth token` 恒签 `wikis=["*"]` write | 按 `is_first_admin` 签发；非 admin 只读 | `d21289b1` |
| P1-5 | username 撞名抛裸 `IntegrityError` | `_unique_username` 加 `_2`/`_3`；并发 → `AuthError` | `a5918fe3` |
| P1-6 | 重复 `auth init` 堆同名 PAT | `find_active` 复用，不堆积 | `52dc305e` |
| P1-7 | `/api/auth/me` 本地模式 200 ⇒ 前端不清陈旧 token | `/me` 认 Bearer，无效 → 401；前端带 Bearer + `authenticated:false` 时 clear | `a5918fe3` |

#### P2（10/13）

| # | 问题 | 状态 |
|---|---|---|
| P2-1 | JWT+PAT 双份存 localStorage | ✅ 不再写 `llmwikify_pat` |
| P2-2 | cookie `secure=False` | ✅ `secure = (scheme == https)` |
| P2-3 | logout 不吊销 JWT | ⏸ 需服务端 denylist（另开） |
| P2-4 | CORS `*` + `credentials=True` | ✅ `allow_credentials=False` |
| P2-5 | `expires_at` 字符串比较 | ✅ unix-epoch 整数比较 |
| P2-6 | `_atomic_write` docstring 自相矛盾 | ✅ 与实现一致 |
| P2-7 | `touch_last_login` 从未调用 | ✅ `/me` 成功时调用 |
| P2-8 | 报错指向不存在的 `/auth/login` | ✅ 改 `/auth/verify` |
| P2-9 | `is_local_default(None)==True` | ⏸ **有意保留**（decision 13：未指定 bind=本地；HTTP 路径经 `env_host()` 回落） |
| P2-10 | `decode()` 不校验 `iss` | ✅ `issuer=ISSUER` |
| P2-11 | `create()` check-then-insert 竞态 | ✅ `IntegrityError` → `AuthError` |
| P2-12 | 每次实例化跑 `_init_schema` | ⏸ 性能非安全，优先级低 |
| P2-13 | CLI 调私有 `_connect()` | ✅ 公开 `UserRepository.first_user()` |

另有文档漂移（middleware `?token=`、`core.py` `/auth/login` 注释）已清。

### 3.3 验证

```
tools/auth_defect_verify.py  →  VERDICT: 4 of 4 probes did NOT reproduce
tools/exploit_check_wikis_claim.py → 授权面 4/4 拦截
```

---

## 4. 关键产出文件

| 文件 | 作用 |
|---|---|
| `docs/designs/parameter-tiers.md` | 业界调研 + 388 旋钮盘点 |
| `docs/designs/config-hub-design-log.md` | **设计讨论记录**（D1–D7、Q1–Q7、E1–E7、§6 实现状态、§8 复核清单） |
| `docs/llmwikify-auth-缺陷清单.md` | 25 条缺陷 + 修复批注 |
| `docs/diagnostics/platform-free-2026-11.md` | Phase 1 细节 |
| `src/llmwikify/foundation/params.py` | 参数登记表 **162 条** + `nest()` + 4 分层视图 |
| `src/llmwikify/foundation/params.pyi` | **生成物**（`scripts/gen_params_stub.py`） |
| `src/llmwikify/foundation/yaml_edit.py` | D3 最小 diff YAML 编辑 |
| `src/llmwikify/foundation/config.py` | `Config` / `ParamRegistry` / `registry_for` |
| `tools/exploit_check_wikis_claim.py` | P0 授权面复现 → 现全拦 |
| `tools/auth_defect_verify.py` | P1/P0 复现 → 现 4/4 NOT reproduced |
| `tests/test_foundation_params.py` | 漂移 + 棘轮 + 契约 |
| `tests/test_foundation_yaml_edit.py` | D3 能力与限制 |

---

## 5. 本会话 commit 清单（按主题）

### Phase 1 · 平台

```
0d3c2d1f refactor(platform): 逻辑路径统一 as_posix，页名经 portable_path 落盘
ca763d2a fix(agent): 运行时长改用 perf_counter
f4fb450f fix(research): 事件 ts 严格递增
9f9dd8f1 fix(platform): 统一 home 解析为 global_config_home
0492b045 test(conftest): session 级 LLMWIKIFY_HOME 隔离
76493c81 refactor(auth): home 解析收敛到 global_config_home
```

### Phase 2 · 配置中枢

```
b48c70a9 docs(design): 参数分级调研 + 388 旋钮盘点
880e6f07 refactor(config): 新增参数登记表 params.py
210d6449 docs(design): 配置中枢讨论记录
616712a0 docs(design): alias_of 业界调研 — 改用规范键+弃用别名
6eb025da docs(design): ClickHouse 调研 — 一个文件装所有不现实
196d290e docs(design): S1-S4 全定案
2037bffd feat(params): Param 加 layer/hot_reloadable/deprecated
011bfacf refactor(params): layer 改用实际层名
c7189831 feat(params): nest() + params.pyi + 契约测试
9c05ab3e feat(config): ParamRegistry + 修 Config import 期捕获
279de041 feat(params): alias_of 规范键 (iii)
dcdd49d8 refactor(agent): 迭代上限收敛 agent.max_iterations
dc1a3e1f feat(config): 步6 最小 diff YAML 写回
13616df7 feat(params): Q3/Q4 拍板 + immutable 扩覆盖 84→162
```

### Phase 3 · Auth

```
717457b2 docs(auth): 缺陷清单入库 + 两个复现脚本
02e3f36c fix(auth): P0-3 旧 schema 迁移不再静默清库
152a8297 fix(authz): P0-1/P0-2/P0-5 授权面
d21289b1 fix(auth): P1-4 auth token 按 admin 身份签发
52dc305e fix(auth): P1-1/2/3/6 CLI 组
a5918fe3 fix(auth): P1-5/7 与 P2 十项
```

---

## 6. 仍开放 / 有意不做

| 项 | 性质 | 说明 |
|---|---|---|
| **P2-3** logout 吊销 | 功能缺口 | JWT 无状态，需服务端 denylist；另开任务 |
| **P2-9** `is_local_default(None)==True` | 有意保留 | decision 13；HTTP 路径不会裸传 None |
| **P2-12** `_init_schema` 每次重跑 | 性能 | 非安全，优先级低 |
| **登记表 ~42%** | 渐进 | 剩余 CLI/dataclass/env 多数**不应**进表；若做 parameter-tiers §8 P5 再评估 |
| **Q2 族划分细则** | 设计 | (iii) 下已简化，但「哪些是别名 vs 独立键」仍需逐条判断 |
| **S1 子类 `@dataclass_transform`** | 未拍板 | 业界有据，用户未确认 |
| **D1 registry 缓存失效** | 边界 | wiki 删除/移动后 `registry_for` 如何失效 |
| **stash `knowledge-wip`** | 用户指定暂留 | 评估结论在 session notes；内容已在 `origin/v0.41-dev` |
| **push** | 未做 | 用户未要求；本地 ahead 39 commits |

---

## 7. 验证命令（回归用）

```powershell
$env:PYTHONUTF8="1"
$env:PYTHONPATH="D:\Github\llmwikify\src"
$py = "D:\tools\python312\python.exe"

& $py -m ruff check src/ tests/ scripts/ --output-format=concise
& $py -m mypy src/                          # 应 0 errors
& $py scripts/check_architecture.py         # 应 0 violation
& $py -m pytest tests/ -q --tb=no --timeout=120 --timeout-method=thread
& $py tools/auth_defect_verify.py           # 应 4/4 NOT reproduced
```

**已知 flaky**（间歇性，非恒失败）：`test_autoresearch::TestEventsCursor`、`test_apps_chat_agent_runner_v2::test_run_context_elapsed`（计时类）。

**WebUI 改动后必须**：`cd ui/webui && npm run build`（仅 `tsc` 不会更新 dist hash chunk）。

---

## 8. 经验沉淀（给后续会话）

1. **import 期捕获** 是本仓高频病：模块级常量 / 单例 `__init__` 里解析 path → 一律改**调用时**（属性或函数）。
2. **Windows 测试**必须 session 级 `LLMWIKIFY_HOME` 隔离；`Path.home()` / `expanduser("~")` 都不可靠覆盖。
3. **登记表**的真相源是 `PARAMS`；`.pyi` 是生成物；改 `params.py` 后跑 `scripts/gen_params_stub.py`。
4. **写回**只有 `Config.save*`，没有 `set_param`；YAML 用 `yaml_edit` 保注释，JSON 用原子 pretty 写 + deep_merge。
5. **Auth** 修一条要同步改复现脚本断言 + 缺陷清单批注，否则下次审计会误报「仍成立」。
6. **PowerShell 5.1**：无 `&&`；复杂 git 引号；`$home` 只读。
7. **less is more**：Q3/Q4 这类「看起来要加字段」的问题，先问「现有机制（`alias_of` / `layer` / D2）是否已覆盖」——多数时候答案是不建。
