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

- PDF 上传存入 `raw/`（取消 `~/.llmwikify/papers/`）
- 提取结果写入 `quant/`，不写入 `wiki/`

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/routes.py` | upload_dir 改为 raw_dir |
| `src/llmwikify/interfaces/server/http/paper.py` | 写入重定向到 quant_wiki |

### 3.1 PDF 上传存入 raw/

**修改** `routes.py:573`

```python
# 当前
upload_dir = Path.home() / ".llmwikify" / "papers"

# 改为
upload_dir = raw_dir
```

**修改** `paper.py` upload 端点（第 407-430 行）

- 上传的 PDF 存入 `raw/` 而非 `~/.llmwikify/papers/`
- 删除 `mkdir(upload_dir)` 逻辑（`raw/` 由 `llmwikify init` 创建）

### 3.2 提取结果写入 quant/

**修改** `_run_paper_extraction()` 第 216-232 行

```python
# 当前：所有 page 写入 wiki/
for page in pages:
    wiki.write_page(page["page_name"], page["content"], page_type=page.get("page_type"))

# 改为：按 page_type 分流
for page in pages:
    pt = page.get("page_type", "Source")
    if pt == "Source":
        quant_wiki.write_page(page["page_name"], page["content"], page_type="papers")
    elif pt == "Factor":
        factor_library.write_factor_yaml(factor_name, factor_data)
    elif pt == "Strategy":
        quant_wiki.write_page(page["page_name"], page["content"], page_type="strategies")
```

### 3.3 读取重定向

**修改** `get_paper()` 和 `list_paper_artifacts()`（旧端点）

| 当前 | 改为 |
|---|---|
| `wiki.read_page(name)` | `quant_wiki.read_page(name, page_type="papers")` |

---

## Phase 4：Factor 分离

### 目标

Factor 读写全部从 `quant/` 获取。

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/factor.py` | API 从 quant/factors/ 读取 |
| `src/llmwikify/reproduction/extract_factors.py` | 标记旧函数废弃 |

### 4.1 回测结果写入 quant/

**修改** `_persist_factor_result()` 第 204 行

| 当前 | 改为 |
|---|---|
| `wiki.write_page(slug, md, page_type="FactorBacktest")` | `quant_wiki.write_page(slug, md, page_type="factorbacktest")` |

同时修改第 207/209 行硬编码路径：

```python
# 当前
wiki_page = f"wiki/factor/{backtest_slug}.md"
# 改为
wiki_page = f"quant/factorbacktest/{backtest_slug}.md"
```

### 4.2 因子列表读取

**修改** `GET /api/factor/list` 端点

| 当前 | 改为 |
|---|---|
| `_list_factors(wiki)` 扫描 `wiki/factor/*.md` | `factor_library.list_factors()` 读取 `quant/factors/index.yaml` |

### 4.3 因子详情读取

**修改** `GET /api/factor/{slug}` 端点

| 当前 | 改为 |
|---|---|
| `read_factor_from_wiki(wiki, slug)` 读取 `wiki/factor/{slug}.md` | `factor_library.read_factor_yaml(slug)` 读取 `quant/factors/{slug}.yaml` |

### 4.4 回测时读取因子

**修改** `backtest_factor()` 第 234 行

| 当前 | 改为 |
|---|---|
| `read_factor_from_wiki(wiki, slug)` | `factor_library.read_factor_yaml(slug)` |

从 YAML 中提取 `factor_class` 和 `factor_params`。

### 4.5 extract_factors.py 废弃旧函数

| 函数 | 处理 |
|---|---|
| `read_factor_from_wiki()` | 标记废弃，内部调用 `factor_library.read_factor_yaml()` |
| `list_factors()` | 标记废弃，内部调用 `factor_library.list_factors()` |
| `build_factor_pages()` | 改为生成 6 层 YAML 结构 |

---

## Phase 5：Strategy 分离

### 目标

Strategy 从 `quant/strategies/` 读取。

### 修改文件

| 文件 | 变更 |
|---|---|
| `src/llmwikify/interfaces/server/http/strategy.py` | 从 quant/strategies/ 读取 |

### 5.1 列表读取

**修改** `GET /api/strategy/list` 端点

| 当前 | 改为 |
|---|---|
| `wiki.wiki_dir / "strategies"` 文件系统扫描 | `quant_wiki.list_pages("strategies")` |

### 5.2 详情读取

**修改** `_read_strategy_from_wiki()` 函数

| 当前 | 改为 |
|---|---|
| `wiki.wiki_dir / "strategies" / f"{slug}.md"` 直接读取 | `quant_wiki.read_page(slug, page_type="strategies")` |

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
| Phase 3 | | `paper.py`, `routes.py` |
| Phase 4 | | `factor.py`, `extract_factors.py` |
| Phase 5 | | `strategy.py` |
| Phase 6 | `FactorDetail.tsx` + 3 子组件 | `App.tsx`, `api.ts` |

**不动的文件**：知识库核心代码、共享组件、回测引擎。

---

## 已完成状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 | ✅ | quant-init CLI 命令 |
| Phase 1 | ✅ | quant_wiki.py 存储模块 |
| Phase 2 | ✅ | factor_library.py YAML 读写 |
| Phase 3 | ⏳ | 待执行 |
| Phase 4 | ⏳ | 待执行 |
| Phase 5 | ⏳ | 待执行 |
| Phase 6 | ✅ | 因子详情页 UI |
