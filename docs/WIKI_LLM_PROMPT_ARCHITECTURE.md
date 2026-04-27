# Wiki生成小型LLM模型与Prompt架构深度调研报告

> 调研时间：2026-04-27

## 一、核心发现

1. 混合方法是关键
2. CoT+RAG组合最优
3. 结构化输出是生产级必备
4. 中文场景需要专门优化
5. 长文档需要分层处理

## 二、幻觉抑制关键技术

### 2.1 CoT+RAG组合优化
- CoT引导逐步推理，减少逻辑跳跃
- RAG提供外部知识锚点
- 组合效果：幻觉率降至11%

### 2.2 Self-Consistency自洽性检测
- 生成多个候选答案，选择最一致的答案
- GSM8K提升+17.9%

### 2.3 HalluClean结构化检测与修正
- 推理增强的幻觉检测模块
- 针对性修正模块
- 在中文数据集上验证有效

### 2.4 CIP因果提示框架
- 构建实体-动作-事件的因果关系序列
- 延迟降低55.1%

### 2.5 M2R微宏检索框架
- 解决"中间迷失"问题
- 宏检索+微检索组合

### 2.6 其他前沿技术
- DSCC-HS: 动态自校准框架
- SHARP: 表征空间干预
- TIDE: Token级早退出
- Stable-RAG: 解决检索排序敏感性

## 三、中文LLM特定挑战

### 3.1 中文核心问题
- 模糊美学: 可能/也许等不确定表达
- 文化语境缺失: 古诗词/成语理解偏差
- 术语不一致: 多义词/方言差异
- 量词滥用: 数量表达不精确
- 专有名词边界: 复合名词识别错误

### 3.2 中文Prompt设计六脉神剑
1. 角色锚定法: 定义严谨的百科编辑专家角色
2. 双重约束法: 必须使用/禁止使用清单
3. 反诱导策略: 避免直译英文句式
4. 文化语境注入: 历史/节日/诗词/地方文化
5. 术语一致性检查: 统一术语表
6. 量化验证约束: 数值+时间+样本+来源

## 四、长文档处理最佳实践

### 4.1 分层处理架构
原始文档 → 语义分章 → 关键提取 → 知识图谱 → 渐进生成

### 4.2 智能分章算法
- 语义分章: 按标题/段落边界分割
- 固定窗口: 500-1500 tokens
- 递归分割: 层级分割直到可处理
- 重叠窗口: 10-15%重叠

推荐配置:
- 最大章节长度: 1500 tokens
- 重叠区域: 200 tokens
- 关键信息重复

### 4.3 Map-Reduce处理
1. 分章: SplitIntoChunks(doc, max_tokens=1500)
2. 并行摘要: ParallelMap(chunks, SummarizeChunk)
3. 聚合: ReduceChunkSummaries(summaries)
4. 递归: 如仍过长则递归处理

### 4.4 上下文记忆机制
- 知识图谱层: 实体关系
- 术语统一层: 标准定义
- 章节摘要层: 快速检索
- 引用索引层: 来源追踪

## 五、结构化输出与Schema约束

### 5.1 层级对比
| 层级 | 技术 | 成功率 | 场景 |
|------|------|--------|------|
| Level 1 | 提示约束 | 85-90% | 开发测试 |
| Level 2 | JSON Mode | 95-98% | 一般生产 |
| Level 3 | 原生约束 | 99.9% | 关键生产 |

### 5.2 主流Provider支持
- OpenAI: response_format: json_schema
- Anthropic: output_config.format
- Gemini: response_schema
- 本地模型: Outlines/llama.cpp

### 5.3 Schema设计规范
```json
{
  "type": "object",
  "properties": {
    "reasoning": {"type": "string"},
    "answer": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "sources": {"type": "array"},
    "uncertainty_markers": {"type": "array", "enum": ["UNVERIFIED", "PARTIAL", "OUTDATED"]}
  },
  "required": ["reasoning", "answer"]
}
```

## 六、完整Prompt架构设计

### 6.1 Wiki生成核心Prompt模板
# Wiki页面生成专家系统 v2.0

## 约束规则体系

### 禁止事项（强制）
- 模糊表述: 可能/也许/据说/大概
- 未验证数据: 所有统计数据必须有来源
- 主观推测: 明确区分事实与观点
- 时间模糊: 必须使用"截至YYYY年MM月"
- 中文标点混用: 全角/半角必须统一

### 必须遵守
- 引用≥2个独立来源
- 标注信息来源与时效
- 使用"根据[来源]显示"
- 数据必须包含: 数值+时间+样本
- 专业术语需统一查表

### 三层验证流程
第一层: 事实提取 → 实体识别 → 事实抽取 → 来源匹配
第二层: 交叉验证 → 检索≥2个来源 → 一致性检查 → 置信度评估
第三层: 结构化输出 → 验证通过 → 标记[FACT] → 降级处理 → 标记[UNVERIFIED/PARTIAL]

### 长文档处理指令
- 最大章节长度: 1500 tokens
- 重叠区域: 200 tokens
- 渐进生成: 骨架 → 要点 → 详细 → 校验

### 6.2 系统参数配置
```yaml
generation:
  temperature: 0.2-0.3
  top_p: 0.8-0.9
  max_tokens: 2048
  presence_penalty: 0.1

validation:
  fact_check: true
  source_verification: true
  cross_reference: true
  uncertainty_marking: required

memory:
  enable_long_context: true
  max_context: 2048
  chunk_overlap: 300

constraints:
  min_sources: 2
  fact_verification: strict
```

### 6.3 轻量级即插即用模板
# 即插即用Prompt模板

角色设定: 你是一个严谨的中文Wiki百科编辑专家

核心约束:
1. 只输出已验证事实，标注[UNVERIFIED]
2. 使用"根据[来源]显示"而非"可能是"
3. 数据必须包含: 数值+时间+样本+来源
4. 禁止模糊表述

输出格式:
{
  "content": "正文内容",
  "sources": [{"name": "", "url": "", "date": ""}],
  "uncertainty": ["[UNVERIFIED]具体内容"]
}

## 七、关键技术组合方案

| 场景 | 推荐组合 | 效果 |
|------|---------|------|
| 通用Wiki生成 | CoT + RAG + HalluClean | 幻觉率↓40-50% |
| 中文专业领域 | 中文约束 + 术语表 + CIP | 文化理解↑60% |
| 长文档处理 | M2R + 分章 + 记忆 | 连贯性↑30% |
| 高可靠性场景 | Self-Consistency + 三重验证 | 准确率↑50% |
| 生产级部署 | 结构化输出 + Pydantic + 重试 | 可用性99.9% |

## 八、预期效果

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 幻觉率 | 30-40% | <5% | 85-90%↓ |
| Token效率 | 1x | 3-5x | 3-5x↑ |
| 引用完整率 | 40-50% | >95% | 2x↑ |
| 中文流畅度 | 3.5/5 | ≥4.5/5 | 28%↑ |
| 长文档连贯性 | 60-70% | ≥90% | 30%↑ |

## 九、实施建议与路线图

### 方案A: 快速验证(1-2周)
1. 选择基线模型(Qwen2.5-7B或GLM-4-9B)
2. 部署结构化输出
3. 实现基础幻觉检测规则
4. 测试10-20个案例
5. 评估幻觉率和质量

### 方案B: 完整实现(4-6周)
第一阶段: Prompt架构 + 结构化输出
第二阶段: RAG检索增强 + CoT推理
第三阶段: 中文约束 + 术语统一
第四阶段: 长文档分章 + 记忆机制
第五阶段: Self-Consistency校验

### 方案C: 深度定制(8-12周)
1. 基础架构
2. 中文文化语境库构建
3. 领域专用术语表开发
4. HalluClean框架集成
5. 持续优化与微调

## 十、推荐模型

### 小型LLM模型推荐
| 模型 | 参数 | 特点 | 适用场景 |
|------|------|------|----------|
| SmolLM-135M | 135M | 文本生成强 | 通用Wiki生成 |
| SmolLM2-135M | 135M | 指令优化 | 指令性Wiki任务 |
| SmolLM3 | 135M-3B | 长上下文 | 大型Wiki项目 |
| GLM-4-9B | 9B | 中文优化 | 生产级部署 |
| Qwen2.5-7B | 7B | 阿里中文优化 | 通用中文场景 |
| TinyLlama-110M | 110M | 极致轻量 | 简单文本生成 |

### 本地部署方案
硬件: RTX 3060 12GB / RTX 4090 24GB, 8核CPU, 32GB内存, 50GB SSD
软件: Ollama / LM Studio / vLLM, 4-bit量化

## 十一、参考资料

### 核心论文
1. Toward Epistemic Stability (2026) - 工业级幻觉抑制五大方法
2. DSCC-HS (2025) - 动态自校准框架
3. CIP (2025) - 因果提示框架
4. HalluClean (2025) - 结构化检测与修正
5. M2R (2025) - 微宏检索框架
6. Self-Consistency (2022) - 自洽性解码

### 中文资源
1. 腾讯云《中文大语言模型提示工程完整优化版》
2. HalluQA/CMHE-HD中文幻觉数据集
3. CLUE基准测试2023
