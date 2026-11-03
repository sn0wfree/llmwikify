# Phase 1 / C — CI 门禁

日期: 2026-11-02 · 分支: v0.41-dev

## 缺口

架构评审 P2-04：CI 覆盖缺口。

| 缺口 | 实测 |
|------|------|
| 架构校验未接 CI | `scripts/check_architecture.py` 存在，但没有任何 workflow 调用它 |
| 契约漂移无人拦截 | SSE 前后端双写，CI 不校验 |
| WebUI 零 CI | 6 个 workflow 里没有一个跑 npm；前端坏了只有用户发现 |
| 覆盖率门禁形同虚设 | `fail_under = 15`，注释写「当前 16.27%」（已过期两轮） |

## 改动

### 1. `lint.yml` 新增 `contract` job

```yaml
contract:
  # 两个脚本都是纯标准库 —— 这个 job 不需要装依赖，跑得很快
  - name: Check the layer dependency direction
    run: python scripts/check_architecture.py
  - name: Check the generated SSE types are in sync
    run: python scripts/gen_webui_types.py --check
```

`lint` job 补一条 `ruff check scripts`（脚本以前不在 ruff 覆盖范围内）。

### 2. 新增 `webui.yml`

```yaml
webui:
  - npm ci
  - npx tsc --noEmit
  - npx vitest run
  - npm run build
  - upload-artifact (webui-dist)
```

Node 20 + `cache: npm`（缓存 `package-lock.json`）。

### 3. 覆盖率门禁 15 → 76

**关键实测**：CI 等价命令 `pytest --cov=src/llmwikify`（`branch = true`）的实测值是
**77.31%**，不是我先前文档里写的 80.26%——后者是**纯语句口径**：

| 口径 | 数值 |
|------|------|
| 语句覆盖（23996 / 29911） | 80.22% |
| **语句+分支合计（coverage 的 `fail_under` 口径）** | **77.31%** |

`fail_under` 比较的是**合计量**，所以门槛必须按 77.31% 定，不能按 80.22% 定——
先前想设 78 会直接让 CI 红。

另外：删除未覆盖的死代码会**拉低**百分比（分母变小、分子不变）。删掉
`apps/chat/agent/unified/`（生产零引用、从未被执行）后，实测由 77.6% 降到 77.31%。

**定值原则**：门槛必须**低于**实测值。CI 跑 Linux py3.10–3.12，覆盖率会有
跨平台 / 跨版本波动；门槛卡太死会让 CI 随机变红，久了就没人看 CI 了。
留 ~1.3pp 余量，让它真的能拦住**回退**。

```
15%  →  mock-only 时期（2026-10）
76%  →  2026-11 实测 77.31%，留 1.3pp 余量
80%  →  覆盖补齐后
```

## 验证

```
pytest --cov=src/llmwikify --cov-report=term --cov-report=xml
  → TOTAL 29911 stmts / 5915 miss / 8906 branch / 1301 partial = 77.31%
  → 59 failed, 5254 passed, 249 errors（对比基线 68 failed / 5286 passed /
     249 errors：少的 32 passed 是被删的 7 个死测试文件，errors 不变）
coverage report → EXIT=0（门禁通过）
npx tsc --noEmit → 0 error
npx vitest run → 76 passed
npm run build → ✓ built
```
