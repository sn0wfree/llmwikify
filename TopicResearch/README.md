# TopicResearch - 复盘 05-07 有色行情 vs 当前 AI 板块投资

> 3 个可量化、可监测的顶部信号

## 项目结构

```
TopicResearch/
├── README.md                   # 项目导航
├── 01-plan.md                  # 研究计划（MECE 拆解）
├── 02-data-sources.md          # 数据源清单 + 引用规范
├── 03-review-2007-nonferrous.md # 05-07 有色复盘正文
├── 04-current-ai-landscape.md  # 当前 AI 中美双线正文
├── 05-mega-ipo-analysis.md     # 巨型 IPO 专题正文
├── 06-signal-framework.md      # 3 信号框架正文
├── planning/
│   ├── 03-module-a-outline.md  # 05-07 有色复盘大纲
│   ├── 04-module-b-outline.md  # 当前 AI 中美双线大纲
│   ├── 05-module-c-outline.md  # 巨型 IPO 专题大纲
│   ├── 06-module-d-outline.md  # 3 信号框架大纲
│   └── 07-threshold-calibration-plan.md # 阈值校准计划
├── report/
│   ├── full-report.md          # 完整长文
│   └── executive-summary.md    # 执行摘要
├── slides/
│   ├── index.html              # reveal.js 幻灯片
│   ├── chart_data.js           # LME 铜铝日级数据
│   ├── shcomp_data.js          # 上证+有色日级数据
│   ├── plotly.min.js           # Plotly.js
│   ├── reveal.js               # Reveal.js
│   ├── reveal.css              # Reveal CSS
│   └── white.css               # Reveal white theme
└── data/raw/
    ├── lme_copper_daily_2005_2008.json    # LME 铜价日级
    ├── lme_aluminum_daily_2005_2008.json  # LME 铝价日级
    ├── shcomp_daily_2005_2008.json        # 上证指数日级
    └── nonferrous_daily_2005_2008.json    # 有色金属指数日级
```

## 信号速查

| 信号 | 定义 | 阈值 | 当前状态 |
|------|------|------|----------|
| **S1** | 巨型 AI IPO 上市即巅峰 | 30日跌幅 >20% + NDX走弱 | 未触发（OpenAI 未上市） |
| **S2** | Hyperscaler FCF 临界点 | FCF 转负 + capex/rev >35% | 预警区间（当前 30%） |
| **S3** | 私募估值倒挂瓦解 | 倒挂 >30% + 破发率 >40% | 接近预警（正溢价 15-25%） |

## 数据来源

- **ifind 金融数据终端**：LME 铜铝价格、上证指数、有色金属指数、M7 财务数据
- **SEC EDGAR**：M7 资本开支/营收数据
- **FRED**：M2、贸易顺差等宏观数据

## 快速访问

- 幻灯片服务：`http://10.67.10.50:37410/index.html`（端口 37410）
- 启动命令：`cd TopicResearch/slides && python3 -m http.server 37410 --bind 0.0.0.0`
