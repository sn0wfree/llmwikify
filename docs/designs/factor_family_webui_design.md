# 因子库 WebUI 重设计: 因子族 (Factor Family) 标准

> 日期: 2026-06-24
> 状态: 设计讨论稿 (待评审, 未实施)
> 范围: WebUI `/agent/factor` 因子库展示页重构, draft 模式

## 0. 背景与动机

当前 `/agent/factor` 页面存在三类问题:

1. **数据读不全**: 服务器把 `quant/factors/101_alphas/` 下 99 个成员因子当作零散的
   `category=alpha` 因子, 又把 `stock/composite/factor-101-formulaic-alphas.yaml`
   当成 1 个 `category=composite` 因子, 二者语义重复且互相矛盾。
2. **缺少"因子族"抽象**: 99 个 alpha 本质是一个**因子族 (factor family)**,
   即"一批独立因子的集合", 而非 99 个孤立因子, 也不是 1 个复合因子。
3. **含斜杠 slug 导致详情页 404 (P0)**: 成员路径形如 `101_alphas/stk_alpha_001_f9f371`
   带 `/`, 单段路由 `:name` 无法匹配, react-router 把 `%2F` 当路径分隔。

本方案引入**因子族**概念, 重新设计因子库的层级结构、页面与路由。

## 1. 核心概念模型

```
FactorLibrary (因子库)
  |- FactorFamily (因子族)        <- 有 _meta.yaml 的目录, 如 101_alphas/
  |    \- FactorMember (成员因子)  <- 含 factor.yaml 的子目录
  \- StandaloneFactor (散因子)     <- 不属于任何族的单个 factor.yaml
```

### 1.1 族的两种类型 (隐式判定)

| 类型 | 语义 | 判定依据 | 顶部展示 |
|------|------|---------|---------|
| **collection 集合型** | 一批独立因子的合集 (如 101_alphas) | 族目录**无** `_composite.yaml` | 纯介绍 (无合成公式) |
| **composite 复合型** | 多因子真正合成一个 mega-factor | 族目录**有** `_composite.yaml` | 族级合成因子卡 + 合成公式 |

**判定规则**: 族目录下是否存在 `_composite.yaml` -> 有则 composite 型, 无则 collection 型。
不在 `_meta.yaml` 中额外加 `type` 字段 (零配置)。

> 101_alphas 是 **collection 型** (一批独立 alpha 的集合), 因此**不应有**
> `_composite.yaml`, 也不显示合成卡。

### 1.2 文件职责分工

| 文件 | 放什么 |
|------|--------|
| `_meta.yaml` | **介绍** (族的简介 / 来源 / 描述性内容) |
| `_composite.yaml` | **结果** (合成因子的定义 / 公式 / 回测; 仅 composite 型族有) |

## 2. 数据契约

### 2.1 族元数据 `_meta.yaml` (现状, 已存在)

```yaml
name: 101_alphas                       # slug, = 目录名
display_name: "101 Formulaic Alphas"
description: "WorldQuant 2015 年发表的 101 个公式化 alpha"
source:                                # 可选, 论文溯源
  paper: "101 Formulaic Alphas"
  authors: ["WorldQuant"]
  year: 2015
  url: "https://arxiv.org/abs/1505.04324"
asset_class: stk
category: alpha
factor_count: 99                       # 真实成员数 (允许 < 名义数, 如 101 实为 99)
```

### 2.2 成员 `factor.yaml` (6 层, L5 可选)

- 顶层: `name` (机器名) / `display_name` ("Alpha #1") / `asset_type` /
  `category` / `status` / `version`
- L1 逻辑 / L2 计算 / L3 金融 / L4 含义 / **L5 验证(可选, 验证后生成)** / L6 风险
- 同目录附带: `code.py` (计算代码) / `meta.json` (alpha_index 等) /
  `backtest/latest.json` (回测结果)

### 2.3 成员指标 `backtest/latest.json`

```
metrics: {ic_mean, icir, win_rate, annual_return, longshort_max_dd}
```

**容错标准**: 所有指标可为 `null`, 前端一律渲染为 `-`, 禁止对 null 调用 `.toFixed()`。

### 2.4 状态归一标准

三处来源 (index.yaml / factor.yaml / meta.json) 命名不一致, 定义唯一规范值 + 映射:

| 规范值 (中文) | 同义来源 | Badge variant |
|--------------|---------|---------------|
| `草稿` | draft | outline |
| `已注册` | registered | secondary |
| `已验证` | verified, validated, 已通过 | default (绿) |
| `已废弃` | deprecated | destructive |

后端 API 输出时统一归一; 真源优先级: `factor.yaml.status` > `meta.json.status` > `index.yaml.status`。

## 3. 页面与路由设计

### 3.1 层级总览 (条件性四级)

```
L0   /agent/factor                        库首页 (族卡区 + 散因子区)
L1   /agent/factor/fam/:family            族详情
        - collection: 顶部介绍 + 成员表          (101_alphas)
        - composite:  介绍 + 合成卡 + 成员表
L1.5 /agent/factor/fam/:family/composite   仅 composite 型 (读 _composite.yaml)
L2   /agent/factor/:family/:member         成员单因子 6 层详情 (splat 路由)
```

### 3.2 L0 库首页 - 族卡区 + 散因子区

```
+--------------------------------------------------------------+
| 因子库                       [总览: 1 族 / 99 成员 / N 散因子]|
| [ 搜索族 / 因子名... ]                                        |
+--------------------------------------------------------------+
| 因子族                                                       |
| +------------------------------------+                       |
| | 101 Formulaic Alphas               |  <- 族卡 (点击->L1)   |
| | WorldQuant / 2015 / 论文(链接)     |                       |
| | 99 成员                            |                       |
| | [##########] 已验证 99             |  <- status 分布条     |
| | 平均 IC 0.005 / 覆盖 94/99         |                       |
| +------------------------------------+                       |
+--------------------------------------------------------------+
| 独立因子 (standalone)                                        |
| [momentum_20d price/已注册] [value_60d fund/已注册]  <-点击->L2 |
+--------------------------------------------------------------+
```

- 族卡标识: collection 型 `[alpha 族 / 99 成员]`; composite 型 `[composite 族 / 含合成因子]`
- 散因子卡点击直接进入 L2 成员详情页 (复用同一详情组件)

### 3.3 L1 族详情 - collection 型 (101_alphas 实际形态)

```
+--------------------------------------------------------------+
| <-  101 Formulaic Alphas                         [alpha 族]  |
|   WorldQuant 2015 年 101 个公式化 alpha 集合 (arXiv)         | <- _meta 介绍
|   99 成员 / 已验证 99                                        | <- 实时聚合统计
+--------------------------------------------------------------+
| 成员因子 (99)  [搜索] [状态:全部] [排序:编号/IC]             |
| +--+---------+-------+------+-----+-----+----------+         |
| | #| 名称    | 状态  | IC   |ICIR |胜率 | 层 L1-L6 |         |
| +--+---------+-------+------+-----+-----+----------+         |
| | 1| Alpha#1 | 已验证|0.033 |0.22 |59%  | OOOO.O    | -> L2  |
| | 2| Alpha#2 | 已验证|0.015 |0.10 |52%  | OOOO.O    |        |
| |48| Alpha#48| 已验证|  -   |  -  |  -  | O.....    | 缺层null|
| +--+---------+-------+------+-----+-----+----------+         |
|   层指示: O 有  . 缺   (101_alphas 全族无 L5)                |
+--------------------------------------------------------------+
   无合成卡 / 无 L1.5 (因为没有 _composite.yaml)
```

要点:
- 顶部介绍精简为 header 一两行 (`_meta.description` + `source` + 实时成员统计),
  暂不引用方法论数字 (15.9% 相关性 / sigma^0.76 等), 先做最简版。
- 成员表列: `编号(alpha_index) | 名称(display_name) | 状态 | IC | ICIR | 胜率 | 层指示器`
- 默认按 `alpha_index` 升序; 可切 IC 降序; 支持搜索 + status 筛选
- **6 点层指示器** (L1-L6, 实心=有/空=缺), 直观暴露 6 个仅有 L1 的成员
- IC / ICIR / 胜率为 null -> 显示 `-`
- 行点击 -> L2 成员详情

**指标懒加载 (按可见行分批)**:
- 结构接口先出表格 (名称/状态/层指示器), IC/ICIR/胜率列初始为骨架态
- 前端用 IntersectionObserver 观测可见行, 收集可见 slug 成批 ->
  调 `/families/{family}/metrics?slugs=...` 拉该批指标 -> 填入对应列
- 已加载 slug 进缓存, 滚动复现不重复请求
- 代价: observer + 缓存 + 骨架态 (99 行收益有限, 但对未来上千成员的族可扩展)

### 3.4 L1 族详情 - composite 型 (将来的复合因子族)

```
+--------------------------------------------------------------+
| <-  <复合因子族>                              [composite 族] |
|   <_meta 介绍>                                               |
+--------------------------------------------------------------+
| 族级合成因子                                                 |
| | MegaFactor = Sum(wi * fi) (...)    [查看 6层详情 ->]    | -> L1.5
| | <_composite 结果摘要>                                   |  |
+--------------------------------------------------------------+
| 成员因子表 -> L2                                             |
+--------------------------------------------------------------+
```

### 3.5 L1.5 族级合成因子详情 (仅 composite 型)

- 复用成员详情的 6 层 Tab 组件, 数据源为 `_composite.yaml`
- 仅在族目录存在 `_composite.yaml` 时才有此路由与入口
- collection 型族 (如 101_alphas) **无此页**

### 3.6 L2 成员单因子详情 (核心: 单因子详情)

```
+--------------------------------------------------------------+
| <-  Alpha #1                          [alpha][已验证] v1     | <- 标题兜底 display_name
| (rank(Ts_ArgMax(SignedPower(((returns<0)?stddev..   [验证]  |
| |L1逻辑|L2计算|L3金融|L4含义|L5验证|L6风险|                    |
+--------------------------------------------------------------+
| [L5 验证] (factor.yaml 无 l5 -> 回落 backtest/latest.json)   |
| |IC Mean 0.0326| ICIR 0.2238| 胜率 59.3%| 年化 0.00%|   null->-|
|  最近回测: pipeline_a_001 / 2026-06-23                       |
|  -- IC 时序图(若有) --  -- 分组年化(若有) --                 |
+--------------------------------------------------------------+
   数据源: 101_alphas/stk_alpha_001_f9f371/factor.yaml + backtest
   路由: factor/* splat 取完整路径 (修 P0 含斜杠 404)
```

- 复用现有 `FactorDetail` 组件 (6 层 Tab), 散因子也走此页
- 标题兜底链: `name_cn || display_name || name`
- 缺层 (L2-L6) 显示 EmptyLayer
- L5 无数据时显示 `backtest/latest.json` 摘要, 而非空回测区

**身份判定与 header/返回键 (按后端返回的 `kind`, 前端不猜)**:

详情接口返回 `kind` + `family`, 前端按三种身份分支渲染:

```
kind=member    : 面包屑[族名]  标题=display_name  返回-> /agent/factor/fam/{family.slug}
kind=composite : 面包屑[族名]  标题=...合成因子    返回-> /agent/factor/fam/{family.slug}
kind=standalone: 无族面包屑    标题=display_name  返回-> navigate(-1)
```

### 3.7 导航流转

```
        L0 库首页 (族卡 / 散因子卡)
           |族卡            |散因子卡
           v                |
        L1 族详情           |
        (composite:合成卡 + 成员表)
           |合成卡   |成员行 |
           v         v       v
       L1.5 合成详情  L2 成员单因子详情(6层) <- 散因子也走此页
       (仅composite型)
```

## 4. 后端 API 设计 (family-aware, 泛化支持 N 个族)

| 端点 | 用途 | 返回核心 |
|------|------|---------|
| `GET /api/factor/families` | 库首页 | `{families:[{slug, display_name, source, category, asset_class, type, member_count, status_counts, ic_summary}], standalone:[...]}` |
| `GET /api/factor/families/{family}` | 族详情结构 (快) | `{meta, composite?, members:[{slug, alpha_index, display_name, status, layers_present}]}` (不含 metrics) |
| `GET /api/factor/families/{family}/metrics?slugs=a,b,c` | 成员指标 (分批懒加载) | `{metrics:{slug:{ic_mean, icir, win_rate, ...}}}` 仅返回请求的 slug 子集 |
| `GET /api/factor/library/{path:path}` | 成员/合成/散因子 6 层详情 (已有) | `{name, kind, family, factor}` |

- `type` 由后端按"是否有 `_composite.yaml`"隐式返回 (`collection` / `composite`)
- **结构与指标分离**: `/families/{family}` 只读 index.yaml + factor.yaml 顶层 (首屏秒开); `/families/{family}/metrics` 接受 `?slugs=` 子集, 按前端可见行分批读 backtest/latest.json
- **详情接口新增身份字段**: `kind` (`member` / `composite` / `standalone`) + `family` (`{slug, display_name}` 或 `null`), 供前端确定性渲染 header/返回键, 不靠字符串猜测
- 后端身份判定: 首段目录有 `_meta.yaml` -> 末段 `_composite` 为 composite, 否则 member, family=首段; 以 `standalone/` 开头或首段无 `_meta.yaml` -> standalone, family=null
- `{path:path}` 已支持斜杠 -> 配合前端 splat 路由解决 P0 的 404

## 5. 文件夹结构标准

```
quant/factors/
|- index.yaml              <- 重建: 两级(families + standalone)
|- <family>/               <- 族 = 必有 _meta.yaml
|   |- _meta.yaml          <- 介绍
|   |- _composite.yaml     <- (可选)合成结果; 有=composite型, 无=collection型
|   |- index.yaml          <- 族内成员清单(已有)
|   \- <member>/{factor.yaml, code.py, meta.json, backtest/latest.json}
|- standalone/             <- (建议)散因子统一收口
\- _archive/               <- (建议)归档遗留/废弃
```

规范要点:
- **族必须有 `_meta.yaml`** (唯一识别标志)
- **遗留 composite** `stock/composite/factor-101-formulaic-alphas.yaml`: 与 101_alphas 族语义重复且误导 -> **归档到 `_archive/`** (101_alphas 是 collection 型, 不需要它), 本次不提取其文字
- **status 字段**全仓统一为 2.4 节规范值

## 6. 已知数据问题 (实现时须应对)

| # | 问题 | 应对 |
|---|------|------|
| 1 | 实际 99 个成员非 101, 缺 alpha_057 / alpha_100 | 统计用 `factor_count`, 不硬写 101 |
| 2 | 6 个成员仅有 L1 (#48/63/68/79/93/95) | 成员表 6 点指示器暴露; 详情页 EmptyLayer |
| 3 | status 命名三处不一致 (verified vs 已验证) | 2.4 节归一映射 |
| 4 | 5 个成员 IC=null (#48/63/79/93/95) | null -> `-` |
| 5 | IC 分布: 94 有效, -0.048~0.151, 均值 0.005 | 族详情默认按 IC 可降序 |
| 6 | 全局 index.yaml 未识别此族 (只列 1 个 composite) | update_index() 改造为两级 |
| 7 | 遗留 composite 文件误导 | 归档到 _archive/ |
| 8 | 仅 1 个族, 但 API 应泛化支持 N 个 | 不硬编码 101_alphas |

## 7. 本次范围 (draft 模式)

draft 模式 = 因子族以聚合视图直接从文件系统呈现, 不写入 wiki。
("沉淀到 wiki 再按其他模式" 为后续阶段, 本次不做。)

本次包含:
1. 后端: `/families`、`/families/{family}` 两个只读接口 + status 归一 helper
2. 前端: L0 库首页 / L1 族详情 / L2 成员详情 (splat 修 P0 + 标题兜底)
   + L1.5 合成详情 (仅 composite 型) + 路由改造
3. 磁盘规范 (已确认写盘): status 字段归一写回 + 全局 index.yaml 两级重建
   + 遗留 composite 归档到 `_archive/`

本次不做:
- wiki 沉淀; 文件夹大规模物理迁移 (仅归档遗留 composite)

## 8. 待决策 / 开放问题

- [x] 散因子展示: L0 双区 (族卡区 + 散因子区)
- [x] 族类型判定: 隐式 (有无 `_composite.yaml`)
- [x] 文件分工: `_meta.yaml`=介绍, `_composite.yaml`=结果
- [x] 101_alphas = collection 型, 不需要 `_composite.yaml`, 遗留文件归档
- [x] 成员表加 6 点缺层指示器
- [x] 磁盘规范: status 归一写回 + index.yaml 两级重建
- [x] 成员指标懒加载: 按可见行分批 (IntersectionObserver + 缓存 + 骨架; `/metrics?slugs=` 子集)
- [x] URL 区分: 保留 `fam/` 前缀 (族详情), splat 走成员详情, fam 路由排在 splat 前
- [x] 散因子识别: 后端返回 `kind`+`family`, 前端不猜
- [x] standalone 目录: 物理收口到 `standalone/`
- [ ] 介绍区方法论数字 (相关性/幂律): 后续优化项, 当前 0->1 阶段简化不做

## 9. 实施前置条件

服务器需从正确 cwd (`/home/ll/Public/strategy`) 重启, 并确认
`GET /api/factor/library/list` 能读到 99 个成员后, 再进入实现。
(当前线上服务器加载的是启动时的旧代码, 仅返回 2 个 composite。)

## 10. 交互与视觉细节 (讨论结论)

### 10.1 族卡视觉 (L0)

```
+------------------------------------------+
| [icon] 101 Formulaic Alphas      [alpha] |  <- 标题 + category 标签
| WorldQuant / 2015 / 论文(链接)           |  <- source 一行(灰字)
| -------------------------------------    |
| 99 成员                                  |  <- 成员数(大字)
| [########..] 已验证 99                   |  <- status 分布条(堆叠)
| 覆盖 94/99 (IC)                          |  <- 指标覆盖率(单独文字)
+------------------------------------------+
```

- **status 分布条**: 按 2.4 节 4 种规范状态堆叠 (stacked bar)
  - 已验证 = emerald(绿), 已注册 = slate/secondary, 草稿 = outline/灰, 已废弃 = destructive(红)
- **status 与覆盖率分开**: 分布条只表达 status; IC 覆盖率(94/99)用单独文字, 不混入条
- **多族网格**: 响应式 `grid-cols-1/2/3` (同现有卡片栅格), 族卡比散因子卡略大

### 10.2 L0 搜索交互 (下钻到成员)

搜索同时匹配 族 / 散因子 / 族内成员, 结果就地分区呈现 (不跳转)。

**成员数据来源 = 后端 `/search` 接口** (不在 L0 全量预加载成员):

```
GET /api/factor/search?q=alpha48
{
  families:   [{slug, display_name, matched_members:[{slug, display_name}]}],
  standalone: [{slug, display_name}]
}
```

- 理由: 与 3.3 "指标懒加载、按需取" 一致, 可扩展到上千成员
- 匹配范围: 族(display_name/description/source.paper) · 散因子(display_name/name/category) · 成员(display_name/name)

**下钻呈现**:

```
搜 "48" ->
  因子族区:
    +------------------------------------+
    | 101 Formulaic Alphas               |
    | 族内 1 个成员匹配:                 |
    |   - Alpha #48  ->                  |  <- 直接点进 L2
    +------------------------------------+
  散因子区: (无匹配则隐藏)
```

- 点匹配成员 -> 直接进 L2 成员详情
- 点族卡 -> 进 L1 且带搜索词 (成员表自动过滤)

### 10.3 未来 composite 型族 (schema 参考)

设想样例 `quant/factors/multi_score_v1/`:

```yaml
# _composite.yaml — composite 型特有字段
name: multi_score_v1_composite
display_name: "多因子打分合成"
weights:                       # 成员 -> 权重 (composite 核心)
  momentum_score: 0.4
  value_score: 0.3
  quality_score: 0.3
combine_method: weighted_sum   # weighted_sum / rank_ic_weighted / equal
l1: {definition, formula: "Sum(wi * rank(fi))", ...}   # 复用 6 层
l5: {...}                      # 族级回测 (schema 留位, 本次不实现)
```

结论:
- **composite vs collection 关键差异字段**: `weights` + `combine_method`
  (collection 型无合成关系, 故无此二字段)
- **族级回测 L5**: composite 型应支持独立的"合成因子整体"回测 (即 L1.5 价值);
  本次只在 schema 留位, 不实现逻辑 (无真实 composite 数据)
- **遗留文件归宿**: `stock/composite/factor-101-formulaic-alphas.yaml` 归档到
  `_archive/`, 加注释头标为 "composite 型 schema 参考样例" (其 `MegaAlpha = Sum(wi*ai)`
  是 composite 雏形, 留作将来参考); 归档不删, 但不被因子库扫描


