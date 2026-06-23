# LLM 量化因子代码生成经验库

本目录记录 LLM 生成量化因子代码的经验教训，用于优化 prompt 和 ReAct 流程。

## 文件结构

```
llm_code_generation/
├── README.md                          # 本文件
├── PARSING_FAILURE_MODES.md            # 五大失败模式与修复方案
├── PROMPT_ENGINEERING.md              # Prompt 设计原则
├── REACT_FLOW_OPTIMIZATION.md         # ReAct 流程优化
└── LESSONS_LEARNED.md                 # 经验教训总结
```

## 项目背景

- **项目**: 101 Formulaic Alphas 论文复现
- **路径**: LLM Code → QuantNodes PipelineRunner → IC/ICIR 回测
- **成果**: 94/96 成功率 (97.9%), 23 个 alpha 通过阈值 (ICIR>0.10)

## 快速导航

- 想了解失败模式 → `PARSING_FAILURE_MODES.md`
- 想优化 prompt → `PROMPT_ENGINEERING.md`
- 想优化 ReAct → `REACT_FLOW_OPTIMIZATION.md`
- 想快速参考 → `LESSONS_LEARNED.md`
