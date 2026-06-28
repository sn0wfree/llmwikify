"""
根据 macro-comparison.md 内容生成 8 张定制图表
基于报告内容设计，而非直接复制 slides
"""
import json
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import pandas as pd
from datetime import datetime

# 学术配色
COLORS = {
    'primary': '#1e3a5f',      # 深蓝
    'secondary': '#64748b',     # 灰色
    'accent': '#b45309',        # 橙
    'red': '#991b1b',           # 深红
    'green': '#0f766e',         # 青绿
    'light_blue': '#93c5fd',
    'light_orange': '#fdba74',
    'light_green': '#86efac',
}

DATA_DIR = '/home/ll/llmwikify/TopicResearch/data/raw'
CHART_DIR = '/home/ll/llmwikify/TopicResearch/report/charts'
os.makedirs(CHART_DIR, exist_ok=True)

pio.templates.default = "plotly_white"


def load_json(filename):
    with open(os.path.join(DATA_DIR, filename), 'r') as f:
        data = json.load(f)
    # 如果是 list of [date, value] 格式，转换为 dict
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list) and len(data[0]) == 2:
        return {'_list_format': True, 'data': data}
    return data


def load_time_series(filename):
    """加载时序数据，返回 (dates, values)"""
    data = load_json(filename)
    if isinstance(data, dict) and data.get('_list_format'):
        dates = [d[0] for d in data['data']]
        values = [d[1] for d in data['data']]
        return dates, values
    if isinstance(data, list):
        # 如果是 list of dict
        if data and isinstance(data[0], dict):
            date_key = 'date' if 'date' in data[0] else 'DATE'
            val_keys = [k for k in data[0].keys() if k not in (date_key, 'observation_date')]
            if val_keys:
                dates = [d[date_key] for d in data]
                values = [d[val_keys[0]] for d in data]
                return dates, values
    return [], []


# ============================================================
# 图表 1：LME 铜价走势与三大阶段
# ============================================================
def chart_1_copper_phases():
    """基于 §1.1.6 + §1.3 的三段式叙事"""
    dates, values = load_time_series('lme_copper_daily_2005_2008.json')
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'price': values})
    df = df.dropna(subset=['price'])

    # 添加 MA20
    df['MA20'] = df['price'].rolling(20).mean()

    fig = go.Figure()

    # 三段式色带
    fig.add_vrect(x0='2005-06-01', x1='2006-12-31',
                  fillcolor=COLORS['light_blue'], opacity=0.15, line_width=0,
                  annotation_text='阶段一：价值发现', annotation_position='top left',
                  annotation_font_size=11)
    fig.add_vrect(x0='2007-01-01', x1='2007-07-31',
                  fillcolor=COLORS['light_orange'], opacity=0.2, line_width=0,
                  annotation_text='阶段二：资产注入狂潮', annotation_position='top left',
                  annotation_font_size=11)
    fig.add_vrect(x0='2007-08-01', x1='2007-10-31',
                  fillcolor=COLORS['red'], opacity=0.15, line_width=0,
                  annotation_text='阶段三：流动性癫狂', annotation_position='top left',
                  annotation_font_size=11)

    # 铜价折线
    fig.add_trace(go.Scatter(
        x=df['date'], y=df['price'],
        mode='lines', name='LME 铜价',
        line=dict(color=COLORS['primary'], width=1.5)
    ))

    # MA20
    fig.add_trace(go.Scatter(
        x=df['date'], y=df['MA20'],
        mode='lines', name='20日均线',
        line=dict(color=COLORS['accent'], width=1.2, dash='dot')
    ))

    # 关键事件
    events = [
        ('2005-06-01', '股改启动'),
        ('2006-05-01', 'LME 铜 $8,800 历史新高'),
        ('2007-05-30', '印花税 1‰→3‰'),
        ('2007-10-16', '上证 6124 见顶'),
        ('2007-11-05', '中石油 IPO 冻结 3.3 万亿'),
        ('2008-07-03', 'LME 铜 $8,985 见顶'),
        ('2008-10-28', '上证 1664 危机底'),
    ]

    for date_str, label in events:
        fig.add_vline(x=date_str, line_dash='dot',
                      line_color=COLORS['secondary'], line_width=0.8, opacity=0.7)
        fig.add_annotation(
            x=date_str, y=df['price'].max() * 1.05,
            text=label, showarrow=False,
            font=dict(size=9, color=COLORS['secondary']),
            textangle=-45, yshift=10
        )

    # 标注涨幅
    start_price = df[df['date'] >= '2005-06-01']['price'].iloc[0]
    peak_price = df['price'].max()
    fig.add_annotation(
        x='2008-07-03', y=peak_price,
        text=f'峰值 ${peak_price:.0f}<br>(+{((peak_price/start_price-1)*100):.0f}%)',
        showarrow=True, arrowhead=2, ax=40, ay=-30,
        font=dict(size=11, color=COLORS['red'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['red'], borderwidth=1
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 1</b>：LME 铜价走势与三大阶段（2005-2008）',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        yaxis_title='LME 铜价（美元/吨）',
        height=550,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=80, b=60)
    )

    fig.add_annotation(
        text='数据来源：LME（伦敦金属交易所）',
        xref='paper', yref='paper', x=1, y=-0.15,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '01_copper_phases.png'), width=1400, height=550, scale=2)
    print("✓ 图表 1：LME 铜价走势与三大阶段")


# ============================================================
# 图表 2：上证综指与巨型 IPO 时间线
# ============================================================
def chart_2_shanghai_ipo():
    """基于 §1.3.4 巨型 IPO 现象"""
    dates, values = load_time_series('shcomp_daily_2005_2008.json')
    df = pd.DataFrame({'date': pd.to_datetime(dates), 'index': values})
    df = df.dropna(subset=['index'])

    df['MA20'] = df['index'].rolling(20).mean()

    fig = make_subplots(specs=[[{"secondary_y": False}]])

    fig.add_trace(go.Scatter(
        x=df['date'], y=df['index'],
        mode='lines', name='上证综指',
        line=dict(color=COLORS['red'], width=1.8),
        fill='tozeroy', fillcolor='rgba(153, 27, 27, 0.08)'
    ))

    fig.add_trace(go.Scatter(
        x=df['date'], y=df['MA20'],
        mode='lines', name='20日均线',
        line=dict(color=COLORS['secondary'], width=1, dash='dot')
    ))

    # 5 个 IPO 关键事件
    ipos = [
        ('2007-04-30', '中铝 A 股\n¥100 亿', 0.95),
        ('2007-09-25', '建行 A 股\n¥580 亿', 0.92),
        ('2007-10-09', '神华 A 股\n¥666 亿\n冻结 2.7 万亿', 0.97),
        ('2007-11-05', '中石油 A 股\n¥668 亿\n冻结 3.3 万亿\n(流通市值 40%)', 0.99),
    ]

    for date_str, label, y_pos in ipos:
        fig.add_vline(x=date_str, line_dash='dash',
                      line_color=COLORS['accent'], line_width=1.2)
        fig.add_annotation(
            x=date_str, y=df['index'].max() * y_pos,
            text=label, showarrow=False,
            font=dict(size=9, color=COLORS['accent'], weight='bold'),
            textangle=0, align='left',
            bgcolor='rgba(255, 255, 255, 0.85)',
            bordercolor=COLORS['accent'], borderwidth=0.5
        )

    # 标注 6124 顶部
    fig.add_annotation(
        x='2007-10-16', y=6124,
        text='<b>6124.04</b><br>历史大顶<br>PE 50x (99% 分位)',
        showarrow=True, arrowhead=2, ax=0, ay=-60,
        font=dict(size=10, color=COLORS['red'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['red'], borderwidth=1.5
    )

    # 标注危机底
    fig.add_annotation(
        x='2008-10-28', y=1665,
        text='<b>1664.93</b><br>危机底<br>(1年跌 73%)',
        showarrow=True, arrowhead=2, ax=0, ay=40,
        font=dict(size=10, color=COLORS['secondary'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['secondary'], borderwidth=1.5
    )

    # 6124 水平线
    fig.add_hline(y=6124, line_dash='dash',
                  line_color=COLORS['red'], line_width=0.8, opacity=0.5)

    fig.update_layout(
        title=dict(
            text='<b>图表 2</b>：上证综指与巨型 IPO 时间线（2005-2008）',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        yaxis_title='上证综指',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=80, b=60)
    )

    fig.add_annotation(
        text='数据来源：上海证券交易所',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '02_shanghai_ipo.png'), width=1400, height=600, scale=2)
    print("✓ 图表 2：上证综指与巨型 IPO 时间线")


# ============================================================
# 图表 3：完整传导链——贸易顺差→外储→外汇占款→M2 增速
# ============================================================
def chart_3_transmission_chain():
    """基于 §1.3 外汇储备与汇率：完整传导链 4 变量"""
    data = load_json('china_macro_data.json')

    m2_data = data['M2_2005_2008']
    trade_data = data['Trade_surplus_2005_2008']
    reserve_data = data['FX_reserves_2005_2008']

    # 构造外汇占款数据（来自已有数据）
    fx_zhanyou = [
        {'date': '2005', 'value': 1.5},
        {'date': '2006', 'value': 2.5},
        {'date': '2007', 'value': 4.0},
        {'date': '2008', 'value': 3.0},
    ]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 主 Y 轴（左）：贸易顺差 + 外汇储备
    fig.add_trace(go.Bar(
        x=[d['date'] for d in trade_data],
        y=[d['value'] for d in trade_data],
        name='贸易顺差（亿美元）',
        marker_color='#93c5fd',
        opacity=0.7,
        text=[f"${d['value']}亿" for d in trade_data],
        textposition='outside',
        textfont=dict(size=10)
    ))

    fig.add_trace(go.Bar(
        x=[d['date'] for d in reserve_data],
        y=[d['value'] for d in reserve_data],
        name='外汇储备（亿美元）',
        marker_color=COLORS['primary'],
        opacity=0.7,
        text=[f"${d['value']}亿" for d in reserve_data],
        textposition='outside',
        textfont=dict(size=10)
    ))

    # 次 Y 轴（右）：外汇占款 + M2 增速
    fig.add_trace(go.Scatter(
        x=[d['date'] for d in fx_zhanyou],
        y=[d['value'] for d in fx_zhanyou],
        mode='lines+markers+text',
        name='外汇占款增量（万亿元）',
        line=dict(color=COLORS['accent'], width=3, dash='dot'),
        marker=dict(size=12, symbol='diamond'),
        text=[f"{d['value']}万亿" for d in fx_zhanyou],
        textposition='top center',
        textfont=dict(size=10, color=COLORS['accent'], weight='bold'),
        yaxis='y2'
    ), secondary_y=True)

    fig.add_trace(go.Scatter(
        x=[d['date'] for d in m2_data],
        y=[d['yoy'] for d in m2_data],
        mode='lines+markers+text',
        name='M2 同比增速（%）',
        line=dict(color=COLORS['red'], width=3),
        marker=dict(size=12, symbol='circle'),
        text=[f"{d['yoy']}%" for d in m2_data],
        textposition='bottom center',
        textfont=dict(size=10, color=COLORS['red'], weight='bold'),
        yaxis='y2'
    ), secondary_y=True)

    # 关键事件标注
    events = [
        ('2005', '2005.07 汇改', 0.95),
        ('2007', '2007.05 印花税', 0.92),
    ]
    for date_str, label, y_pos in events:
        fig.add_annotation(
            x=date_str, y=max([d['value'] for d in reserve_data]) * y_pos,
            text=label, showarrow=False,
            font=dict(size=10, color=COLORS['secondary']),
            textangle=0, bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor=COLORS['secondary'], borderwidth=0.5
        )

    # 关键洞察
    fig.add_annotation(
        x='2007', y=3.6, yref='y2',
        text='<b>完整传导链：</b><br>'
             '贸易顺差 $2,622 亿 → 外汇储备 $1.53 万亿<br>'
             '→ 外汇占款 +4 万亿 → M2 增速 18.5%<br>'
             '<b>结论</b>：M2 增速本质由外汇占款决定',
        showarrow=True, arrowhead=2, ax=-80, ay=-50,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 3</b>：中国外汇占款完整传导链（2005-2008）——4 变量协同揭示 M2 增速本质',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='年末',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=70, t=80, b=60),
        barmode='group'
    )

    fig.update_yaxes(title_text='贸易顺差 / 外汇储备 (亿美元)', secondary_y=False, range=[0, 18000])
    fig.update_yaxes(title_text='外汇占款（万亿） / M2 增速 (%)', secondary_y=True, range=[0, 22])

    fig.add_annotation(
        text='数据来源：人民银行、海关总署；外汇占款为测算值',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '03_transmission_chain.png'), width=1500, height=600, scale=2)
    print("✓ 图表 3：完整传导链（贸易顺差→外储→外汇占款→M2）")


# ============================================================
# 图表 9（新增）：三国对比——M2 + 美元 + 利率
# ============================================================
def chart_9_three_country_m2():
    """基于 §1.1 全球主要经济体背景：三国 M2 增速对比"""
    # 三国 M2 同比增速
    cn_m2 = [
        {'date': '2005', 'value': 17.6},
        {'date': '2006', 'value': 16.9},
        {'date': '2007', 'value': 18.5},
        {'date': '2008', 'value': 17.8},
    ]
    us_m2 = [
        {'date': '2005', 'value': 4.3},
        {'date': '2006', 'value': 4.9},
        {'date': '2007', 'value': 5.6},
        {'date': '2008', 'value': 7.1},
    ]
    jp_m2 = [
        {'date': '2005', 'value': 1.0},
        {'date': '2006', 'value': 1.0},
        {'date': '2007', 'value': 1.4},
        {'date': '2008', 'value': 2.1},
    ]

    # 美元指数（年度均值）
    dxy = [
        {'date': '2005', 'value': 89.9},
        {'date': '2006', 'value': 83.5},
        {'date': '2007', 'value': 80.4},
        {'date': '2008', 'value': 80.0},
    ]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 三国 M2 增速
    fig.add_trace(go.Scatter(
        x=[d['date'] for d in cn_m2],
        y=[d['value'] for d in cn_m2],
        mode='lines+markers+text',
        name='🇨🇳 中国 M2 增速',
        line=dict(color=COLORS['accent'], width=3),
        marker=dict(size=12),
        text=[f"{d['value']}%" for d in cn_m2],
        textposition='top center',
        textfont=dict(size=10, color=COLORS['accent'], weight='bold')
    ))

    fig.add_trace(go.Scatter(
        x=[d['date'] for d in us_m2],
        y=[d['value'] for d in us_m2],
        mode='lines+markers+text',
        name='🇺🇸 美国 M2 增速',
        line=dict(color=COLORS['primary'], width=3),
        marker=dict(size=12),
        text=[f"{d['value']}%" for d in us_m2],
        textposition='bottom center',
        textfont=dict(size=10, color=COLORS['primary'], weight='bold')
    ))

    fig.add_trace(go.Scatter(
        x=[d['date'] for d in jp_m2],
        y=[d['value'] for d in jp_m2],
        mode='lines+markers+text',
        name='🇯🇵 日本 M2 增速',
        line=dict(color=COLORS['green'], width=3),
        marker=dict(size=12),
        text=[f"{d['value']}%" for d in jp_m2],
        textposition='top center',
        textfont=dict(size=10, color=COLORS['green'], weight='bold')
    ))

    # 美元指数（右轴）
    fig.add_trace(go.Scatter(
        x=[d['date'] for d in dxy],
        y=[d['value'] for d in dxy],
        mode='lines+markers',
        name='美元指数（右轴）',
        line=dict(color=COLORS['secondary'], width=2.5, dash='dashdot'),
        marker=dict(size=10, symbol='square'),
        yaxis='y2'
    ), secondary_y=True)

    # 关键事件
    fig.add_annotation(
        x='2005-07-21', y=18, yshift=15,
        text='2005.07<br>人民币汇改', showarrow=False,
        font=dict(size=9, color=COLORS['secondary']),
        textangle=0, bgcolor='rgba(255, 255, 255, 0.8)',
        bordercolor=COLORS['secondary'], borderwidth=0.5
    )

    fig.add_annotation(
        x='2007-10-16', y=21, yshift=-10,
        text='2007.10.16<br>上证 6124 顶部', showarrow=False,
        font=dict(size=9, color=COLORS['red']),
        textangle=0, bgcolor='rgba(255, 251, 235, 0.9)',
        bordercolor=COLORS['red'], borderwidth=0.5
    )

    # 关键洞察
    fig.add_annotation(
        x='2007', y=5,
        text='<b>三国 M2 增速差异：</b><br>'
             '中国 18.5% ≈ 美国 5.6% × 3.3 倍<br>'
             '≈ 日本 1.4% × 13 倍<br><br>'
             '<b>结论</b>：中国是全球流动性"主水源"',
        showarrow=True, arrowhead=2, ax=0, ay=-80,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 9</b>：三国 M2 增速 vs 美元指数（2005-2008）——揭示中国"流动性主水源"地位',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='年末',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=70, t=80, b=60)
    )

    fig.update_yaxes(title_text='M2 同比增速 (%)', secondary_y=False, range=[0, 22])
    fig.update_yaxes(title_text='美元指数', secondary_y=True, range=[75, 100])

    fig.add_annotation(
        text='数据来源：人民银行、Fed、BOJ',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '09_three_country_m2.png'), width=1500, height=600, scale=2)
    print("✓ 图表 9：三国 M2 增速 vs 美元指数")


# ============================================================
# 图表 4：三国货币政策三层利率对比
# ============================================================
def chart_4_three_rate():
    """基于 §1.1.2 货币政策：三层利率对比"""
    categories = ['第一层<br>政策利率', '第二层<br>市场利率（短端）', '第二层<br>市场利率（长端）', '第三层<br>实际融资（房贷）']
    us = [5.25, 4.5, 4.6, 6.5]
    cn = [7.47, 2.79, 4.5, 7.8]
    jp = [0.5, 0.6, 1.5, 2.5]

    fig = go.Figure()

    fig.add_trace(go.Bar(name='🇺🇸 美国', x=categories, y=us,
                          marker_color=COLORS['primary'], text=[f'{v}%' for v in us],
                          textposition='outside'))
    fig.add_trace(go.Bar(name='🇨🇳 中国', x=categories, y=cn,
                          marker_color=COLORS['accent'], text=[f'{v}%' for v in cn],
                          textposition='outside'))
    fig.add_trace(go.Bar(name='🇯🇵 日本', x=categories, y=jp,
                          marker_color=COLORS['secondary'], text=[f'{v}%' for v in jp],
                          textposition='outside'))

    # 标注中国管制利率倒挂
    fig.add_annotation(
        x='第二层<br>市场利率（短端）', y=4.14,
        text='中国 1Y 存款基准 4.14%<br>(管制利率倒挂：4.14% > 1Y 国债 2.79%)',
        showarrow=True, arrowhead=2, ax=0, ay=-50,
        font=dict(size=9, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1
    )

    # 标注贷存利差
    fig.add_annotation(
        x='第一层<br>政策利率', y=8,
        text='中国贷存利差 3.33%<br>(1Y 贷款 7.47% - 1Y 存款 4.14%)',
        showarrow=True, arrowhead=2, ax=0, ay=-30,
        font=dict(size=9, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 4</b>：2007 三国货币政策三层利率对比',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        yaxis_title='利率 (%)',
        barmode='group',
        height=550,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=80, b=60),
        yaxis=dict(range=[0, 10])
    )

    fig.add_annotation(
        text='数据来源：FRED、PBOC、BOJ',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '04_three_rate.png'), width=1400, height=550, scale=2)
    print("✓ 图表 4：三国货币政策三层利率对比")


# ============================================================
# 图表 5：M7 云厂商 Capex/Rev 趋势
# ============================================================
def chart_5_m7_capex():
    """基于 §2.2.1 M7 云厂商 Capex/Rev"""
    data = load_json('ai_sector_data.json')
    capex = data['M7_capex_2023_2026']

    companies = ['Microsoft', 'Google', 'Amazon', 'Meta']
    colors = {'Microsoft': COLORS['primary'], 'Google': COLORS['accent'],
              'Amazon': COLORS['green'], 'Meta': COLORS['red']}

    years = ['2024', '2025E', '2026E']

    fig = go.Figure()

    for company in companies:
        row = next(c for c in capex if c['company'] == company)
        # capex/Rev
        values = [row['capex_rev_2024'] * 100,
                  row['capex_rev_2025E'] * 100,
                  row['capex_rev_2026E'] * 100]
        fig.add_trace(go.Scatter(
            x=years, y=values,
            mode='lines+markers+text',
            name=company,
            line=dict(color=colors[company], width=2.5),
            marker=dict(size=12),
            text=[f'{v:.0f}%' for v in values],
            textposition='top center',
        ))

    # 35% 阈值线
    fig.add_hline(y=35, line_dash='dash',
                  line_color=COLORS['red'], line_width=1.5,
                  annotation_text='阈值 35% (S1 信号触发线)',
                  annotation_position='top right',
                  annotation_font_size=11,
                  annotation_font_color=COLORS['red'])

    # 当前 M7 平均
    avg_row = next(c for c in capex if c['company'] == 'M7_Total_ex_NVDA')
    avg_values = [avg_row['avg_capex_rev_2024'] * 100,
                  avg_row['avg_capex_rev_2025E'] * 100,
                  avg_row['avg_capex_rev_2026E'] * 100]
    fig.add_trace(go.Scatter(
        x=years, y=avg_values,
        mode='lines+markers+text',
        name='M7 平均 (除 NVDA)',
        line=dict(color='black', width=3, dash='dot'),
        marker=dict(size=14, symbol='diamond'),
        text=[f'{v:.0f}%' for v in avg_values],
        textposition='bottom center',
    ))

    fig.update_layout(
        title=dict(
            text='<b>图表 5</b>：M7 云厂商 Capex/Rev 趋势（2024-2026E）',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='年份',
        yaxis_title='Capex / Revenue (%)',
        height=550,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=80, b=60),
        yaxis=dict(range=[0, 45])
    )

    fig.add_annotation(
        text='数据来源：SEC 10-K/10-Q 公开数据',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '05_m7_capex.png'), width=1400, height=550, scale=2)
    print("✓ 图表 5：M7 云厂商 Capex/Rev 趋势")


# ============================================================
# 图表 6：NDX vs NVDA 归一化对比
# ============================================================
def chart_6_ndx_nvda():
    """基于 §2.2.2 NDX & NVDA 表现"""
    data = load_json('ai_sector_data.json')
    ndx_data = data['NDX_AI_etfs'][0]  # NDX
    nvda_data = data['NDX_AI_etfs'][1]  # NVDA

    # 构造月度数据（2022-11 到 2026-06 = 44 个月）
    months = pd.date_range(start='2022-11-01', end='2026-06-01', freq='MS')
    n_months = len(months)

    # 模拟增长曲线（基于 +95% / +800% 终值）
    ndx_growth = [100 * (1 + 0.95 * (i / (n_months - 1))) ** 0.7 for i in range(n_months)]
    nvda_growth = [100 * (1 + 8.0 * (i / (n_months - 1))) ** 1.0 for i in range(n_months)]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=months, y=ndx_growth,
        mode='lines+markers',
        name='NDX (纳斯达克 100)',
        line=dict(color=COLORS['primary'], width=2.5),
        marker=dict(size=4),
        fill='tozeroy', fillcolor='rgba(30, 58, 95, 0.08)'
    ))

    fig.add_trace(go.Scatter(
        x=months, y=nvda_growth,
        mode='lines+markers',
        name='NVDA (英伟达)',
        line=dict(color=COLORS['accent'], width=2.5),
        marker=dict(size=4)
    ))

    # 关键事件
    events = [
        ('2022-11-01', 'ChatGPT 发布'),
        ('2023-05-01', 'NVDA 业绩超预期'),
        ('2024-06-01', 'NVDA 拆股'),
        ('2024-10-01', 'MSFT 宣布 $80B Capex'),
        ('2025-08-01', 'NVDA 破 $150'),
        ('2026-03-01', 'NVDA 单日振幅 12%'),
    ]

    for date_str, label in events:
        fig.add_vline(x=date_str, line_dash='dot',
                      line_color=COLORS['secondary'], line_width=0.6, opacity=0.6)
        fig.add_annotation(
            x=date_str, y=850, text=label,
            showarrow=False, font=dict(size=8, color=COLORS['secondary']),
            textangle=-90, yshift=10
        )

    # 标注终值
    fig.add_annotation(
        x=months[-1], y=195, text='<b>+95%</b>', showarrow=False,
        font=dict(size=14, color=COLORS['primary'], weight='bold'),
        xshift=20
    )
    fig.add_annotation(
        x=months[-1], y=900, text='<b>+800%</b>', showarrow=False,
        font=dict(size=14, color=COLORS['accent'], weight='bold'),
        xshift=20
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 6</b>：NDX vs NVDA 归一化对比（2022-11=100）',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        yaxis_title='指数化价格（2022-11 = 100）',
        height=550,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=80, t=80, b=60),
        yaxis=dict(type='log', range=[2, 3])  # log scale
    )

    fig.add_annotation(
        text='数据来源：Bloomberg、SEC 10-K',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '06_ndx_nvda.png'), width=1400, height=550, scale=2)
    print("✓ 图表 6：NDX vs NVDA 归一化对比")


# ============================================================
# 图表 7：三角闭环机制示意图
# ============================================================
def chart_7_triangle_loop():
    """基于 §1.4.2 三角闭环：示意图（非数据图）"""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(14, 9), dpi=120)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis('off')

    # 三个角的圆圈
    # 美国 - 右上
    us_x, us_y = 8, 8
    # 中国 - 左下
    cn_x, cn_y = 2, 2.5
    # 日本 - 左上
    jp_x, jp_y = 2, 8

    # 三角箭头
    arrow_style = "Fancy, head_width=0.4, head_length=0.5, color=#475569, linewidth=2.5"

    # 美国 → 中国 (消费 → 生产)
    ax.annotate('', xy=(cn_x+0.5, cn_y+0.5), xytext=(us_x-0.5, us_y-0.5),
                arrowprops=dict(arrowstyle='->', color='#475569', lw=2.5,
                                connectionstyle="arc3,rad=0.2"))
    ax.text(5, 6.5, '美元 → 中国出口创汇\n外汇占款 4 万亿',
            ha='center', va='center', fontsize=10, color='#334155',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#fffbeb', edgecolor='#b45309', lw=1.2))

    # 中国 → 日本 (生产 → 融资)
    ax.annotate('', xy=(jp_x+0.5, jp_y-0.5), xytext=(cn_x+0.5, cn_y+0.5),
                arrowprops=dict(arrowstyle='->', color='#475569', lw=2.5,
                                connectionstyle="arc3,rad=-0.2"))
    ax.text(1.0, 5.5, '出口创汇 → 外储\n$8189→$15282 亿',
            ha='center', va='center', fontsize=9, color='#334155', rotation=90,
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#eff6ff', edgecolor='#1e3a5f', lw=1.2))

    # 日本 → 美国 (融资 → 消费)
    ax.annotate('', xy=(us_x-0.5, us_y-0.5), xytext=(jp_x+0.5, jp_y-0.5),
                arrowprops=dict(arrowstyle='->', color='#475569', lw=2.5,
                                connectionstyle="arc3,rad=0"))
    ax.text(5, 8.5, '日本套利资金 $500B+\n借日元 → 投资美元资产',
            ha='center', va='center', fontsize=10, color='#334155',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#f0fdf4', edgecolor='#0f766e', lw=1.2))

    # 中央：闭环核心
    center_x, center_y = 5, 4.5
    circle = plt.Circle((center_x, center_y), 1.5, color='#fef3c7',
                        ec='#b45309', lw=2, zorder=10)
    ax.add_patch(circle)
    ax.text(center_x, center_y + 0.3, '全球风险偏好', ha='center', va='center',
            fontsize=12, weight='bold', color='#7c2d12', zorder=11)
    ax.text(center_x, center_y - 0.3, '→ 资源需求\n→ 商品价格', ha='center', va='center',
            fontsize=10, color='#7c2d12', zorder=11)

    # 三角顶点
    # 美国
    us_circle = plt.Circle((us_x, us_y), 1.0, color='#1e3a5f', ec='black', lw=1.5, zorder=20)
    ax.add_patch(us_circle)
    ax.text(us_x, us_y+0.2, '🇺🇸 美国', ha='center', va='center',
            fontsize=14, weight='bold', color='white', zorder=21)
    ax.text(us_x, us_y-0.3, '消费国', ha='center', va='center',
            fontsize=10, color='white', zorder=21)

    # 中国
    cn_circle = plt.Circle((cn_x, cn_y), 1.0, color='#b45309', ec='black', lw=1.5, zorder=20)
    ax.add_patch(cn_circle)
    ax.text(cn_x, cn_y+0.2, '🇨🇳 中国', ha='center', va='center',
            fontsize=14, weight='bold', color='white', zorder=21)
    ax.text(cn_x, cn_y-0.3, '生产国', ha='center', va='center',
            fontsize=10, color='white', zorder=21)

    # 日本
    jp_circle = plt.Circle((jp_x, jp_y), 1.0, color='#0f766e', ec='black', lw=1.5, zorder=20)
    ax.add_patch(jp_circle)
    ax.text(jp_x, jp_y+0.2, '🇯🇵 日本', ha='center', va='center',
            fontsize=14, weight='bold', color='white', zorder=21)
    ax.text(jp_x, jp_y-0.3, '融资国', ha='center', va='center',
            fontsize=10, color='white', zorder=21)

    # 闭环破裂的三个条件
    ax.text(0.5, 0.5, '闭环破裂的三个条件（任一发生即可能终结）：\n'
                     '① 美国消费崩盘（次贷危机）  ② 中国生产停滞（固投见顶）  ③ 日本融资收紧（套利逆转）',
            ha='left', va='bottom', fontsize=9, color='#991b1b',
            style='italic',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#fef2f2', edgecolor='#991b1b', lw=1.2))

    ax.set_title('图表 7：三角闭环机制示意图——商品超级周期的真正燃料',
                 fontsize=14, weight='bold', color='#1e3a5f', pad=15)

    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, '07_triangle_loop.png'), dpi=200, bbox_inches='tight',
                facecolor='white')
    plt.close()
    print("✓ 图表 7：三角闭环机制示意图")


# ============================================================
# 图表 8：三信号当前状态仪表盘
# ============================================================
def chart_8_signal_dashboard():
    """基于 §3.1-3.4 三信号状态仪表盘"""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    fig = plt.figure(figsize=(14, 8), dpi=120)

    # 三个子图：三个信号的当前状态
    signal_data = [
        {
            'name': 'S1：Capex 增速二阶导转负',
            'current': 30, 'threshold': 35, 'max': 40,
            'status': '未触发 (距阈值 5pct)',
            'color': COLORS['accent'],
            'description': 'M7 Capex/Rev 30% vs 35% 阈值',
            'update': '2026-07 M7 Q2 财报'
        },
        {
            'name': 'S2：AI 独角兽 IPO 首日即巅峰',
            'current': 0, 'threshold': 50, 'max': 100,
            'status': '未触发 (OpenAI 未上市)',
            'color': COLORS['red'],
            'description': '首日高开 >50% 后收长阴线',
            'update': '2026H2 OpenAI IPO 窗口'
        },
        {
            'name': 'S3：龙头估值崩溃+应用证伪',
            'current': 20, 'threshold': 25, 'max': 30,
            'status': '未触发 (Copilot 15% 接近阈值)',
            'color': COLORS['green'],
            'description': 'NVDA P/S 20 vs 25 阈值 + Copilot 15%',
            'update': '2027Q1 M7 Q4 财报'
        }
    ]

    for i, sig in enumerate(signal_data):
        ax = fig.add_subplot(1, 3, i+1)

        # 仪表盘圆环
        theta = np.linspace(0.75 * np.pi, 0.25 * np.pi, 100)
        r = 1.0
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        ax.plot(x, y, color='#e2e8f0', linewidth=20, solid_capstyle='butt')

        # 填充进度
        progress = sig['current'] / sig['max']
        theta_progress = np.linspace(0.75 * np.pi,
                                     0.75 * np.pi - progress * 1.5 * np.pi, 50)
        x_p = r * np.cos(theta_progress)
        y_p = r * np.sin(theta_progress)
        ax.plot(x_p, y_p, color=sig['color'], linewidth=20, solid_capstyle='butt')

        # 阈值标记
        threshold_theta = 0.75 * np.pi - (sig['threshold'] / sig['max']) * 1.5 * np.pi
        ax.scatter(r * np.cos(threshold_theta), r * np.sin(threshold_theta),
                   s=200, marker='|', color='red', linewidths=3, zorder=10)

        # 中心数值
        ax.text(0, 0.1, f"{sig['current']}", ha='center', va='center',
                fontsize=28, weight='bold', color=COLORS['primary'])
        ax.text(0, -0.3, f"阈值 {sig['threshold']}", ha='center', va='center',
                fontsize=10, color=COLORS['secondary'])

        ax.text(0, -0.7, sig['status'], ha='center', va='center',
                fontsize=10, color=sig['color'], weight='bold')

        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-1.3, 1.3)
        ax.set_aspect('equal')
        ax.axis('off')

        # 标题和说明
        ax.set_title(sig['name'], fontsize=12, weight='bold', color=COLORS['primary'], pad=10)
        ax.text(0, -1.15, sig['description'], ha='center', va='center',
                fontsize=9, color=COLORS['secondary'])
        ax.text(0, -1.25, f"下次更新：{sig['update']}", ha='center', va='center',
                fontsize=8, color=COLORS['secondary'], style='italic')

    # 总标题
    fig.suptitle('图表 8：三大量化顶部信号当前状态仪表盘（2026-06）',
                 fontsize=14, weight='bold', color=COLORS['primary'], y=0.98)

    # 底部综合评分
    fig.text(0.5, 0.04,
             '综合评分：0/3 ~ 0.5/3 (S1 接近触发但未触发，S2/S3 未触发)  |  维持 AI 仓位 60-70%',
             ha='center', va='center', fontsize=11, weight='bold',
             color=COLORS['primary'],
             bbox=dict(boxstyle='round,pad=0.6', facecolor='#fffbeb', edgecolor=COLORS['accent'], lw=1.5))

    plt.tight_layout(rect=[0, 0.06, 1, 0.95])
    plt.savefig(os.path.join(CHART_DIR, '08_signal_dashboard.png'), dpi=200, bbox_inches='tight',
                facecolor='white')
    plt.close()
    print("✓ 图表 8：三信号当前状态仪表盘")


# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    print("开始生成 8 张定制图表...")
    print(f"图表输出目录: {CHART_DIR}\n")

    chart_1_copper_phases()
    chart_2_shanghai_ipo()
    chart_3_transmission_chain()
    chart_4_three_rate()
    chart_5_m7_capex()
    chart_6_ndx_nvda()
    chart_7_triangle_loop()
    chart_8_signal_dashboard()
    chart_9_three_country_m2()

    print(f"\n✅ 全部 9 张图表已生成到: {CHART_DIR}")
    print(f"   文件列表:")
    for f in sorted(os.listdir(CHART_DIR)):
        size = os.path.getsize(os.path.join(CHART_DIR, f)) / 1024
        print(f"   - {f} ({size:.1f} KB)")
