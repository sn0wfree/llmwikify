# ReAct 流程优化

## 流程概览

```
REASON → ACT → OBSERVE → DECIDE → (循环或结束)
  ↑        ↓       ↓        ↓
  LLM    提取代码  注入反馈  判断是否重试
  生成    验证语法  给LLM    (最多3轮)
  代码    执行代码
```

## 状态机

| 状态 | 动作 | 输出 |
|------|------|------|
| REASON | LLM 调用生成代码 | response (含 python 代码块) |
| ACT | 提取代码 → 验证语法 → 安全检查 → 执行 | factor_series 或 error |
| OBSERVE | 记录结果 → 注入反馈到 message history | feedback message |
| DECIDE | 判断是否继续重试 | continue 或 break |

## 错误分类 (ReactErrorKind)

| ErrorKind | 含义 | 触发条件 |
|-----------|------|---------|
| EXTRACT_FAILED | 无法提取代码 | 响应中无 ```python``` 代码块 |
| SYNTAX_ERROR | 语法错误 | ast.parse 失败 |
| SAFETY_ERROR | 安全检查失败 | CodeSandbox 拒绝 或 if-on-polars 检测 |
| EXECUTE_ERROR | 执行异常 | 代码运行时错误 或 timeout |
| OUTPUT_INVALID | 返回类型错误 | 返回值不是 pl.Series |

---

## 关键组件

### 1. _validate_safety() — 安全检查

```python
def _validate_safety(code: str) -> tuple[bool, str]:
    # 1. 正则检测 if-on-polars (提前拦截)
    if_patterns = [
        r'if\s+rank\s*\(',
        r'if\s+pl\.col\s*\(',
        r'if\s+rolling_\w+\s*\(',
        r'if\s+ts_\w+\s*\(',
        r'if\s+correlation\s*\(',
        r'if\s+scale\s*\(',
        r'if\s+zscore\s*\(',
    ]
    # 2. CodeSandbox 安全检查
    # 返回 (is_safe, error_message)
```

**优化点**:
- 增加 `elif` 模式检测
- 增加 `and`/`or`/`not` 关键字检测
- 提供具体的修复示例

### 2. _sanitize_code() — 自动修复

```python
def _sanitize_code(code: str) -> str:
    # and → &
    # or → |
    # not → ~
    # (只处理关键字，不处理字符串中的)
```

**优化点**:
- 当前 regex 不处理 `if` 模式
- 可以增加更复杂的模式匹配

### 3. OBSERVE_FEEDBACK_TEMPLATE — 反馈模板

```
[ReAct OBSERVE] Your previous code failed at stage: {stage}

Error:
{error}

{context}

## FIX GUIDE
### If "truth value of an Expr is ambiguous":
[具体修复示例]

### If "TimeoutError":
[优化建议]

### General:
[通用规则]

Output ONLY corrected code block, no prose.
```

**优化点**:
- 按错误类型分类反馈
- 给出具体的 WRONG/RIGHT 代码示例
- 包含上次代码上下文

### 4. _execute_code() — 执行引擎

```python
def _execute_code(code: str, df: pl.DataFrame, timeout_sec: float = 120.0) -> pl.Series:
    # 1. 构建命名空间 (QuantNodes 算子 + polars)
    # 2. 线程安全执行 (threading.Thread + join timeout)
    # 3. 处理 pl.Expr → pl.Series 转换
```

**优化点**:
- timeout 从 60s 提升到 120s
- 可以增加执行日志

---

## ReAct 循环优化

### 循环次数

| 次数 | 成功率 | 说明 |
|------|--------|------|
| 1 次 (1-shot) | 37% | 无法修复拼写错误 |
| 2 次 | 60% | 能修复简单错误 |
| 3 次 | 80% | 能修复大部分错误 |
| 4 次 | 97.9% | 接近最优 |

**建议**: max_repair_rounds=3 (共 4 次 LLM 调用)

### 反馈质量

| 反馈类型 | 效果 |
|---------|------|
| 通用错误信息 | 差 — LLM 不知道如何修复 |
| 具体错误信息 + 代码上下文 | 中 — LLM 能理解问题 |
| 具体错误信息 + 代码上下文 + WRONG/RIGHT 示例 | 好 — LLM 能正确修复 |

### 错误分类细化

当前 5 种错误可以进一步细化:

| 当前分类 | 细化分类 | 修复策略 |
|---------|---------|---------|
| EXECUTE_ERROR | DangerousCodeError | 提供 pl.when() 示例 |
| EXECUTE_ERROR | TimeoutError | 建议 materialization |
| EXECUTE_ERROR | NameError | 提供可用算子列表 |
| EXECUTE_ERROR | 其他运行时错误 | 保持通用反馈 |

---

## 性能基准

| 指标 | 基线 (1-shot) | ReAct 优化后 |
|------|--------------|-------------|
| 成功率 | 37% | 97.9% |
| 平均 LLM 调用次数 | 1 | 2.5 |
| 平均执行时间 | 15s | 30s |
| NaN IC 比例 | 高 | 0% |

---

## 优化清单

### Prompt 层
- [ ] 开头 "DO NOT" 列表
- [ ] 3 条核心规则 + 示例
- [ ] WRONG/RIGHT 代码对比

### ReAct 层
- [ ] 错误分类细化 (5 → 8 种)
- [ ] OBSERVE 反馈模板 (按错误类型分类)
- [ ] _validate_safety 正则增强 (11 if 模式 + 3 bool 模式)
- [ ] _sanitize_code 增强

### 数据层
- [ ] 二值因子检测 + noise
- [ ] NaN IC 处理
- [ ] industry 列支持
- [ ] timeout 配置 (120s)
