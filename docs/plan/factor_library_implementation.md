# 因子库实施计划

> 基于设计讨论文档，本文档定义 6 个 Phase 的实施步骤。

---

## 前置条件

- 设计讨论文档已完成：`docs/designs/factor_library_design_discussion.md`
- 6 层框架 YAML 模板已创建：`quant/factors/stock/price/momentum_20d.yaml` 等

---

## Phase 0：quant-init 命令

### 目标

`llmwikify quant-init` 创建 quant/ 目录结构。

### 新建文件

| 文件 | 说明 |
|---|---|
| `src/llmwikify/interfaces/cli/commands/quant_init_cmd.py` | CLI 命令实现 |

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/cli/commands/__init__.py` | 导入 quant_init_cmd |

### 创建内容

```
quant/
├── papers/                   ← 论文理解结果
├── factors/                  ← 因子库 6 层 YAML
│   ├── index.yaml            ← 空因子索引
│   ├── stock/price/
│   └── stock/fundamental/
├── factorbacktest/           ← 回测结果
├── strategies/               ← 策略定义
├── datacache/                ← OHLCV 缓存
└── index.md                  ← 量化研究索引
```

同时创建空的 `quant/factor.duckdb`，含 `factor_values` 表。

### 行为

- 已存在则跳过（幂等）
- 输出创建的目录列表

---

## Phase 1：Quant Wiki 模块

### 目标

复用 wiki 引擎，指向 quant/ 目录。

### 新建文件

| 文件 | 说明 |
|---|---|
| `src/llmwikify/reproduction/quant_wiki.py` | quant wiki 实例管理 |

### 接口

```python
def get_quant_root() -> Path:
    """返回 quant/ 路径（相对于项目根目录）"""

def get_quant_wiki() -> Wiki:
    """返回指向 quant/ 的 Wiki 实例"""
```

---

## Phase 2：Factor Library 模块

### 目标

因子库 6 层 YAML 读写。

### 新建文件

| 文件 | 说明 |
|---|---|
| `src/llmwikify/reproduction/factor_library.py` | 因子库读写模块 |

### 接口

```python
def list_factors() -> list[dict]:
    """读 quant/factors/index.yaml，返回因子列表"""

def read_factor_yaml(name: str) -> dict:
    """读 quant/factors/{path}.yaml，返回解析后的 dict"""

def write_factor_yaml(name: str, data: dict) -> None:
    """写 quant/factors/{path}.yaml"""

def list_factors_by_category() -> dict:
    """按类别分组返回因子列表"""
```

---

## Phase 3：Paper 分离

### 目标

Paper 提取结果写入 quant/，不写入 wiki/。

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/paper.py` | wiki.write_page → quant_wiki.write_page |
| `src/llmwikify/reproduction/extract_factors.py` | 生成 6 层 YAML 而非 wiki markdown |

### 关键变更

- `_run_paper_extraction()` 中 `wiki.write_page()` → `quant_wiki.write_page()`
- `build_paper_pages()` 写入 `quant/papers/`
- `build_factor_pages()` 生成 6 层 YAML 到 `quant/factors/`
- 策略提取结果写入 `quant/strategies/`

---

## Phase 4：Factor 分离

### 目标

Factor 读写从 quant/ 获取。

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/factor.py` | API 从 quant/factors/ 读取 |
| `src/llmwikify/reproduction/extract_factors.py` | 删除 wiki 读取函数 |

### 关键变更

- `GET /api/factor/list` → 从 `quant/factors/index.yaml` 读取
- `GET /api/factor/{slug}` → 从 `quant/factors/` 读取 YAML
- `_persist_factor_result()` → 写入 `quant/factorbacktest/`
- 新增 `/api/factor-library/*` 端点
- 删除 `read_factor_from_wiki()` / `list_factors()`

---

## Phase 5：Strategy 分离

### 目标

Strategy 从 quant/ 读取。

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/strategy.py` | 从 quant/strategies/ 读取 |

### 关键变更

- `GET /api/strategy/list` → 从 `quant/strategies/` 读取
- `GET /api/strategy/{slug}` → 从 `quant/strategies/` 读取
- `_read_strategy_from_wiki()` → 从 quant wiki 读取

---

## Phase 6：因子详情页 UI

### 目标

展示 6 层 YAML 内容。

### 新建文件

| 文件 | 说明 |
|---|---|
| `ui/webui/src/components/factor/FactorDetail.tsx` | 6 层 Tab 主页面 |
| `ui/webui/src/components/factor/HypothesisList.tsx` | L4 假设列表 |
| `ui/webui/src/components/factor/OverallAssessment.tsx` | L5 综合评估 |
| `ui/webui/src/components/factor/RiskRadar.tsx` | L6 风险雷达 |

### 修改文件

| 文件 | 变更 |
|---|---|
| `ui/webui/src/App.tsx` | 新增 `/agent/factor-library/:name` 路由 |
| `ui/webui/src/api.ts` | 新增 `api.factorLibrary.*` 函数 |

---

## 执行顺序

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
```

每个 Phase 完成后可独立验证，不依赖后续 Phase。

## 文件变更汇总

| 阶段 | 新建 | 修改 |
|---|---|---|
| Phase 0 | `quant_init_cmd.py` | `commands/__init__.py` |
| Phase 1 | `quant_wiki.py` | |
| Phase 2 | `factor_library.py` | |
| Phase 3 | | `paper.py`, `extract_factors.py` |
| Phase 4 | | `factor.py`, `extract_factors.py` |
| Phase 5 | | `strategy.py` |
| Phase 6 | `FactorDetail.tsx` + 3 子组件 | `App.tsx`, `api.ts` |

**不动的文件**：知识库核心代码、共享组件、回测引擎。
