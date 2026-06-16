# 因子反思优化功能设计文档

> 本文档记录因子反思优化功能的设计讨论和决策，包括 LLM 自我反思机制、建议类型、存储结构、UI 展示和应用流程。

---

## 1. 需求背景

### 1.1 问题

当前 L5 验证流程是单向的：

```
L4 提出假设 → L5 验证 → L4 回填 final_meaning → L6 风险诊断
```

**缺陷**：LLM 验证后不会主动反思因子设计本身（如参数选择、公式合理性、数据需求等），缺乏"从验证结果反馈到因子设计"的闭环。

### 1.2 目标

在 L5 验证后添加一个 LLM 自我反思步骤，让 LLM 根据验证结果主动提出因子优化建议（如参数调整、公式改进、新假设、数据需求），支持用户确认后应用到因子，形成迭代优化闭环。

### 1.3 核心原则

- **数据驱动**：反思必须基于 L5 验证数据，避免凭空臆断
- **渐进式**：每次验证都反思，但只提供建议，不自动修改因子
- **用户确认**：建议需用户确认后应用，确保安全
- **版本控制**：应用建议后创建 v2 因子，保留历史

---

## 2. 设计决策

### 2.1 反思在核心循环中的位置

**决策**：反思在 L5 验证后、L4 回填 final_meaning 前执行

```
L4 提出假设 + 沉淀逻辑
    ↓
L5 因子分析 + 假设检验
    ↓
[新增] L5.reflections：LLM 反思优化（每次自动）
    ↓
L4 回填 final_meaning
    ↓
L6 识别失效条件
    ↓
[可选] 用户应用建议 → 创建 v2 因子
    ↓
回到 L4 修正假设（带新版本）
```

**理由**：
1. 反思依赖 L5 验证结果，必须在验证后执行
2. 反思结果（suggestions）与 final_meaning 独立，可并行生成
3. 反思失败不应阻塞 L5 验证结果，try/except 包裹

### 2.2 反思结果存储位置

**决策**：存储在 `factor.l5.reflections` 数组（与 `hypothesis_testing`、`overall_assessment` 并列）

```yaml
factor:
  l5:
    factor_analysis: {...}
    hypothesis_testing: [...]
    overall_assessment: {...}
    validation_date: "2024-01-01~2024-07-19"
    reflections:           # 新增字段
      - iteration: 1
        date: 2024-01-15
        score_at_time: 45
        suggestions: [...]
        reflection_notes: "..."
        applied: false
        applied_date: null
```

**理由**：
- 反思是 L5 验证流程的直接产出，归档在 L5 下最自然
- 与 `hypothesis_testing` 并列，便于前端一次性获取所有 L5 数据
- 追加不覆盖，保留历史反思记录

### 2.3 反思触发机制

**决策**：每次验证都自动反思

| 触发场景 | 行为 | 说明 |
|---|---|---|
| 新因子首次验证 | 自动生成 initial reflection | 基线反思，即使 score=100 也生成 |
| 验证失败（score < 60） | 自动生成 reflection | 帮助理解失败原因 |
| 验证通过（score ≥ 60） | 自动生成 reflection | 即使通过也反思优化空间 |
| 用户手动触发 | 自动包含在验证流程中 | 无需额外操作 |

**理由**：
- 完整性：每次验证都生成反思，避免遗漏优化机会
- 一致性：触发逻辑简单，无需判断 score
- 安全性：反思只提供建议，不自动修改因子，成本可控

### 2.4 反思建议类型

**决策**：支持 4 种建议类型，按优先级排序

| 优先级 | 类型 | 说明 | 依据 |
|---|---|---|---|
| **P0** | `parameter_adjustment` | 调整 period、threshold 等参数 | L5 数据直接支持：IC 衰减可推断最优周期，分组收益可推断最优分组数 |
| **P1** | `formula_improvement` | 改进计算方式（标准化、去极值等） | L5 稳定性分析可判断是否需要，OOS 可判断过拟合 |
| **P2** | `new_hypothesis` | 基于验证发现提出新猜想 | L5 假设检验中"部分支持"的假设可引申 |
| **P3** | `data_requirement` | 需要更长历史、更高频率等 | L5 稳定性分析可判断 |

**反思建议优先级评估矩阵**：

```
                可执行性
                高        低
影响  大  P0 参数调整  P1 公式改进
      小  P3 数据要求  P2 新假设
```

**核心原则**：反思必须基于 L5 数据，避免凭空臆断。Prompt 中要求每条建议必须有数据支撑。

### 2.5 应用方式

**决策**：建议 + 用户确认后应用

1. 反思只生成建议，存为 `applied: false`
2. 用户通过 UI 查看建议，点击"应用建议"按钮
3. 确认后创建 v2 因子（递增 version，保留原 v1）
4. 更新 `applied: true` + `applied_date`

**理由**：
- 安全性：用户确认后应用，避免 LLM 幻觉导致因子被错误修改
- 可追溯：v2 因子保留 v1 历史，可回滚
- 灵活性：用户可选择性应用部分建议（未来扩展）

### 2.6 反思 Prompt 设计

**决策**：使用 Jinja2 模板，接收 L5 全部 7 个模块数据

**Prompt 结构**：
1. **System message**：设定角色（量化因子优化专家）
2. **User message**：因子信息 + L5 验证结果 + L4 假设检验
3. **Output schema**：JSON 格式，包含 suggestions 数组和 reflection_notes

**关键设计**：
- 要求 reasoning 必须基于 L5 数据（50 字以内）
- 要求 confidence 反映建议确定性（high/medium/low）
- 要求每个建议必须有数据支撑

---

## 3. 数据结构

### 3.1 YAML 扩展

在 `factor.l5` 下新增 `reflections` 数组：

```yaml
factor:
  l5:
    factor_analysis: {...}
    hypothesis_testing: [...]
    overall_assessment: {...}
    validation_date: "2024-01-01~2024-07-19"
    reflections:
      - iteration: 1
        date: 2024-01-15
        score_at_time: 45
        suggestions:
          - type: parameter_adjustment
            path: l1.default_params.period
            current_value: 20
            proposed_value: 10
            reasoning: "IC 衰减快，缩短周期可能提升预测力"
            expected_impact: "IC 提升 ~30%"
            confidence: "medium"
          - type: formula_improvement
            path: l1.formula
            current_value: "f_t = close_t / close_{t-20} - 1"
            proposed_value: "f_t = (close_t - mean) / std"
            reasoning: "标准化消除市场整体波动影响"
            expected_impact: "稳定性提升"
            confidence: "high"
        reflection_notes: "基于 L5 验证，该因子主要问题是..."
        applied: false
        applied_date: null
```

### 3.2 建议类型定义

```typescript
interface ReflectionSuggestion {
  type: 'parameter_adjustment' | 'formula_improvement' | 'new_hypothesis' | 'data_requirement';
  path: string;                    // YAML 字段路径
  current_value: string | number;  // 当前值
  proposed_value: string | number; // 建议值
  reasoning: string;               // 改进理由（50 字以内）
  expected_impact: string;         // 预期影响
  confidence: 'high' | 'medium' | 'low'; // 建议确定性
}

interface Reflection {
  iteration: number;
  date: string;
  score_at_time: number;
  suggestions: ReflectionSuggestion[];
  reflection_notes: string;
  applied: boolean;
  applied_date: string | null;
}
```

---

## 4. 实施方案

### 4.1 Phase 1: 反思 Prompt（~30 分钟）

**文件**：`src/llmwikify/foundation/prompts/_defaults/repro_factor_reflect.yaml`

```yaml
name: repro_factor_reflect
version: "1.0"
description: "基于 L5 验证结果反思因子设计并提出优化建议"
params:
  max_tokens: 1500
  temperature: 0.2

messages:
  - role: system
    content: |
      你是一个量化因子优化专家。基于 L5 验证结果，反思因子设计的不足，
      提出可执行的优化建议。反思要基于数据，避免凭空臆断。

  - role: user
    content: |
      基于以下 L5 验证结果，反思因子设计的不足并提出优化建议。

      ## 因子信息
      - 名称: {{ name }}
      - 定义: {{ definition }}
      - 公式: {{ formula }}
      - 类别: {{ category }}/{{ subcategory }}
      - 参数: {{ params }}

      ## L5 验证结果
      - 总分: {{ score }}/100
      - 状态: {{ status }}
      - IC Mean: {{ ic_mean }}, ICIR: {{ icir }}
      - 分组单调性: {{ monotonicity }}
      - 多空 Sharpe: {{ ls_sharpe }}
      - 换手率: {{ avg_turnover }}
      - 成本敏感: {{ cost_sensitivity }}
      - OOS RankIC: {{ oos_rank_ic }}

      ## L4 假设检验
      {{ hypothesis_testing }}

      ## 任务
      提出 1-3 条具体优化建议，每条包括：
      - type: parameter_adjustment | formula_improvement | new_hypothesis | data_requirement
      - path: YAML 字段路径
      - current_value + proposed_value: 当前值与建议值
      - reasoning: 改进理由（必须基于 L5 数据）
      - expected_impact: 预期影响
      - confidence: high | medium | low

      输出 JSON 格式：
      ```json
      {
        "suggestions": [
          {
            "type": "parameter_adjustment",
            "path": "l1.default_params.period",
            "current_value": 20,
            "proposed_value": 10,
            "reasoning": "IC 衰减快，缩短周期可能提升预测力",
            "expected_impact": "IC 提升 ~30%",
            "confidence": "medium"
          }
        ],
        "reflection_notes": "基于 L5 验证，该因子主要问题是..."
      }
      ```

      要求：
      1. reasoning 简洁（50字以内）
      2. 每条建议必须有数据支撑
      3. confidence 反映建议的确定性
```

### 4.2 Phase 2: 反思函数（~1 小时）

**文件**：`src/llmwikify/reproduction/l5_orchestrator.py`

新增函数：

1. `_build_reflection_prompt(factor, l5_data) -> str`：构建反思 prompt
2. `_parse_reflection(response) -> dict`：解析 LLM 输出

在 `run_l5_pipeline()` 中插入步骤 4b：

```python
# 4b. LLM reflection (every validation, after hypothesis testing)
if llm_client is not None:
    try:
        existing_reflections = l5_data.get("reflections", [])
        iteration = len(existing_reflections) + 1
        prompt = _build_reflection_prompt(factor_data, l5_data)
        response = llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500,
        )
        parsed = _parse_reflection(response)
        suggestions = parsed.get("suggestions", [])
        if suggestions:
            reflection = {
                "iteration": iteration,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "score_at_time": l5_data["overall_assessment"].get("score"),
                "suggestions": suggestions,
                "reflection_notes": parsed.get("reflection_notes", ""),
                "applied": False,
                "applied_date": None,
            }
            existing_reflections.append(reflection)
            l5_data["reflections"] = existing_reflections
    except Exception as exc:
        logger.warning("LLM reflection failed: %s", exc)
```

### 4.3 Phase 3: YAML 持久化（~15 分钟）

无需额外改动。`write_factor_yaml()` 使用 `yaml.dump()` 自动序列化 `l5_data["reflections"]`。

### 4.4 Phase 4: UI 展示 + 应用（~2 小时）

**文件**：`ui/webui/src/components/factor/FactorDetail.tsx`

在 `L5Content` 的假设检验结果和验证日期之间插入反思面板：

```tsx
{/* Reflections */}
{reflections && reflections.length > 0 && (
  <Section title="反思分析">
    <div className="space-y-4">
      {reflections.map((r: any, idx: number) => (
        <div key={idx} className="p-4 bg-muted rounded-md space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              反思 #{r.iteration} — {r.date}
            </span>
            <Badge variant={r.applied ? 'default' : 'secondary'}>
              {r.applied ? '已应用' : '待确认'}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{r.reflection_notes}</p>
          <div className="space-y-2">
            {r.suggestions?.map((s: any, sIdx: number) => (
              <div key={sIdx} className="p-3 bg-background rounded-md border">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="outline" className="text-xs">
                    {typeLabels[s.type] || s.type}
                  </Badge>
                  <Badge variant={confidenceColors[s.confidence] || 'secondary'}>
                    {s.confidence}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-muted-foreground">当前值:</span>{' '}
                    <span className="font-mono">{String(s.current_value)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">建议值:</span>{' '}
                    <span className="font-mono text-emerald-600">{String(s.proposed_value)}</span>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-2">{s.reasoning}</p>
                <p className="text-xs font-medium mt-1">预期影响: {s.expected_impact}</p>
                {!r.applied && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={() => applyReflection(factorName, r.iteration, sIdx)}
                  >
                    应用建议
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  </Section>
)}
```

### 4.5 Phase 5: 测试（~1 小时）

**新增文件**：`tests/reproduction/test_l5_reflection.py`

测试覆盖：
1. `_build_reflection_prompt()`：验证 prompt 包含所有 L5 字段
2. `_parse_reflection()`：验证 JSON 解析、think block 剥离、无效输入处理
3. `run_l5_pipeline()`：验证反思结果写入 YAML

---

## 5. 关键文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `src/llmwikify/foundation/prompts/_defaults/repro_factor_reflect.yaml` | 新建 | 反思 prompt |
| `src/llmwikify/reproduction/l5_orchestrator.py` | 修改 | 新增 `_build_reflection_prompt()`、`_parse_reflection()`，在 `run_l5_pipeline()` 中调用 |
| `ui/webui/src/components/factor/FactorDetail.tsx` | 修改 | L5Content 新增反思面板 |
| `tests/reproduction/test_l5_reflection.py` | 新建 | 单元测试 |

---

## 6. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| LLM 凭空臆断建议 | prompt 强调"必须基于 L5 数据"，提供具体数据点 |
| 反思增加 token 成本 | reflection prompt 限制 max_tokens=1500，temperature=0.2 |
| 用户误应用建议 | UI 需确认对话框 + 显示 diff（before/after YAML） |
| 应用后因子版本混乱 | 严格递增 version，记录 applied_date 链路 |
| LLM 输出格式不稳定 | 同 hypothesis_testing：先 code block 提取 + fallback {} |
| 反思失败阻塞验证 | try/except 包裹，反思失败只 warning，不影响 L5 结果 |

---

## 7. 工作量估算

| Phase | 工作量 |
|---|---|
| Phase 1: 反思 prompt | 30 分钟 |
| Phase 2: 反思函数 | 1 小时 |
| Phase 3: YAML 持久化 | 15 分钟 |
| Phase 4: UI 展示 + 应用 | 2 小时 |
| Phase 5: 测试 | 1 小时 |
| **总计** | **~5 小时** |

---

## 8. 核心循环（更新后）

```
L4 提出假设 + 沉淀逻辑
    ↓
L5 因子分析 + 假设检验
    ↓
[新增] L5.reflections：LLM 反思优化（每次自动）
    ↓
L4 回填 final_meaning
    ↓
L6 识别失效条件
    ↓
[可选] 用户应用建议 → 创建 v2 因子
    ↓
回到 L4 修正假设（带新版本）
```

---

## 9. 待讨论

### 9.1 反思建议的应用粒度

**当前设计**：每条建议单独应用（用户点击"应用建议"按钮）

**备选方案**：整批应用（用户点击"应用全部建议"按钮）

**问题**：是否需要支持"选择性应用"（勾选部分建议后应用）？

### 9.2 反思与版本的关系

**当前设计**：应用建议后创建 v2 因子，保留 v1

**备选方案**：原地修改（覆盖 v1，但记录 git diff）

**问题**：是否需要保留 v1 因子文件？

### 9.3 反思的最大迭代次数

**当前设计**：无限制（每次验证都生成新反思）

**问题**：是否需要设置上限（如最多 5 次反思）？避免无限循环。

### 9.4 反思 Prompt 的模板化程度

**当前设计**：硬编码在 `_build_reflection_prompt()` 中

**备选方案**：使用 `_defaults/repro_factor_reflect.yaml` 模板（与其他 prompt 一致）

**问题**：是否需要支持自定义反思 prompt？
