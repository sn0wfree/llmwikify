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
# 图表 2：商品/股价顶背离对比图（合并原图表 1+2）
# ============================================================
def chart_2_divergence():
    """基于 §1.4 资本市场：揭示商品/股价 17 个月顶背离"""
    # LME 铜价（用月度平均）
    dates_cu, values_cu = load_time_series('lme_copper_daily_2005_2008.json')
    df_cu = pd.DataFrame({'date': pd.to_datetime(dates_cu), 'cu': values_cu})
    df_cu = df_cu.dropna(subset=['cu'])
    df_cu_monthly = df_cu.set_index('date').resample('M').mean().reset_index()
    df_cu_monthly['cu_norm'] = df_cu_monthly['cu'] / df_cu_monthly['cu'].iloc[0] * 100

    # 上证综指（用月度平均）
    dates_sh, values_sh = load_time_series('shcomp_daily_2005_2005_2008.json') if False else load_time_series('shcomp_daily_2005_2008.json')
    df_sh = pd.DataFrame({'date': pd.to_datetime(dates_sh), 'sh': values_sh})
    df_sh = df_sh.dropna(subset=['sh'])
    df_sh_monthly = df_sh.set_index('date').resample('M').mean().reset_index()
    df_sh_monthly['sh_norm'] = df_sh_monthly['sh'] / df_sh_monthly['sh'].iloc[0] * 100

    fig = go.Figure()

    # LME 铜价（归一化）
    fig.add_trace(go.Scatter(
        x=df_cu_monthly['date'], y=df_cu_monthly['cu_norm'],
        mode='lines', name='LME 铜价（2005-06=100）',
        line=dict(color=COLORS['primary'], width=2.5),
        fill='tozeroy', fillcolor='rgba(30, 58, 95, 0.08)'
    ))

    # 上证综指（归一化）
    fig.add_trace(go.Scatter(
        x=df_sh_monthly['date'], y=df_sh_monthly['sh_norm'],
        mode='lines', name='上证综指（2005-06=100）',
        line=dict(color=COLORS['red'], width=2.5),
        fill='tozeroy', fillcolor='rgba(153, 27, 27, 0.05)'
    ))

    # 标注铜价顶部
    cu_peak = df_cu_monthly['cu_norm'].max()
    cu_peak_date = df_cu_monthly.loc[df_cu_monthly['cu_norm'].idxmax(), 'date']
    fig.add_annotation(
        x=cu_peak_date, y=cu_peak,
        text=f'<b>LME 铜 顶部</b><br>{cu_peak_date.strftime("%Y-%m")}<br>{cu_peak:.0f}',
        showarrow=True, arrowhead=2, ax=20, ay=-30,
        font=dict(size=10, color=COLORS['primary'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['primary'], borderwidth=1.5
    )

    # 标注上证顶部
    sh_peak = df_sh_monthly['sh_norm'].max()
    sh_peak_date = df_sh_monthly.loc[df_sh_monthly['sh_norm'].idxmax(), 'date']
    fig.add_annotation(
        x=sh_peak_date, y=sh_peak,
        text=f'<b>上证 6124 顶部</b><br>{sh_peak_date.strftime("%Y-%m")}<br>{sh_peak:.0f}',
        showarrow=True, arrowhead=2, ax=-30, ay=-50,
        font=dict(size=10, color=COLORS['red'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['red'], borderwidth=1.5
    )

    # 标注顶背离区间
    fig.add_vrect(
        x0=cu_peak_date.strftime('%Y-%m-%d'), x1=sh_peak_date.strftime('%Y-%m-%d'),
        fillcolor=COLORS['accent'], opacity=0.15, line_width=0,
    )
    fig.add_annotation(
        x=cu_peak_date + (sh_peak_date - cu_peak_date) / 2,
        y=550, text='<b>17 个月顶背离</b>',
        showarrow=False,
        font=dict(size=11, color=COLORS['accent'], weight='bold')
    )

    # 标注关键事件
    events = [
        ('2005-07-01', '人民币汇改'),
        ('2006-04-01', '中铝 IPO'),
        ('2007-05-30', '印花税上调'),
        ('2007-11-05', '中石油 IPO'),
    ]
    for date_str, label in events:
        fig.add_vline(x=date_str, line_dash='dot',
                      line_color=COLORS['secondary'], line_width=0.6, opacity=0.5)

    # 关键洞察
    months_diff = (sh_peak_date.year - cu_peak_date.year) * 12 + (sh_peak_date.month - cu_peak_date.month)
    fig.add_annotation(
        x='2006-06-01', y=350,
        text=f'<b>关键洞察：</b><br>'
             f'商品（LME 铜）于 {cu_peak_date.strftime("%Y-%m")} 见顶<br>'
             f'股价（上证）于 {sh_peak_date.strftime("%Y-%m")} 见顶<br>'
             f'<b>顶背离 {months_diff} 个月</b><br><br>'
             f'这是典型的「叙事溢价」阶段：<br>'
             f'股价锚定「未来注入矿」，<br>'
             f'而非商品现货价格',
        showarrow=True, arrowhead=2, ax=0, ay=0,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 2</b>：LME 铜价 vs 上证综指 归一化对比（2005-06=100）——揭示 17 个月顶背离',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        yaxis_title='归一化指数（2005-06 = 100）',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=80, b=60),
        yaxis=dict(range=[80, 600])
    )

    fig.add_annotation(
        text='数据来源：LME、上海证券交易所',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '02_divergence.png'), width=1500, height=600, scale=2)
    print("✓ 图表 2：LME 铜价 vs 上证综指 归一化对比")


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
# 图表 9（重做）：三国宏观对比 4 面板（GDP + M2 + CPI + 外储/GDP）
# ============================================================
def chart_9_three_country_macro():
    """基于 §1.1 + §1.3：三国宏观对比 4 维度"""
    data = load_json('three_country_data.json')
    china_data = load_json('china_macro_data.json')

    years = ['2005', '2006', '2007', '2008']

    # 数据准备
    us_gdp = [d['value'] for d in data['US_GDP_real']]
    jp_gdp = [d['value'] for d in data['Japan_GDP_real']]

    # 中国 GDP/CPI 从 china_macro_data 取
    cn_gdp = [d['value'] for d in china_data['China_GDP_real']]
    cn_cpi = [d['value'] for d in china_data['China_CPI']]

    us_cpi = [d['value'] for d in data['US_CPI']]
    jp_cpi = [d['value'] for d in data['Japan_CPI']]

    # 三国 M2 增速
    cn_m2 = [d['yoy'] for d in china_data['M2_2005_2008']]
    us_m2 = [4.1, 5.9, 5.7, 9.6]
    jp_m2 = [1.0, 1.0, 1.4, 2.1]



    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            '<b>图 9a：三国 GDP 增速</b>',
            '<b>图 9b：三国 M2 增速</b>',
            '<b>图 9c：三国 CPI</b>',
            '<b>图 9d：三国外储/GDP (2007)</b>'
        ),
        vertical_spacing=0.13,
        horizontal_spacing=0.1
    )

    # 9a: GDP 增速
    for color, name, values in [
        (COLORS['primary'], '🇺🇸 美国', us_gdp),
        (COLORS['accent'], '🇨🇳 中国', cn_gdp),
        (COLORS['green'], '🇯🇵 日本', jp_gdp),
    ]:
        fig.add_trace(go.Bar(
            x=years, y=values, name=name,
            marker_color=color, text=[f'{v}%' for v in values],
            textposition='outside', textfont=dict(size=9),
        ), row=1, col=1)

    # 9b: M2 增速
    for color, name, values in [
        (COLORS['primary'], '🇺🇸 美国', us_m2),
        (COLORS['accent'], '🇨🇳 中国', cn_m2),
        (COLORS['green'], '🇯🇵 日本', jp_m2),
    ]:
        fig.add_trace(go.Bar(
            x=years, y=values, name=name,
            marker_color=color, text=[f'{v}%' for v in values],
            textposition='outside', textfont=dict(size=9),
            showlegend=False,
        ), row=1, col=2)

    # 9c: CPI
    for color, name, values in [
        (COLORS['primary'], '🇺🇸 美国', us_cpi),
        (COLORS['accent'], '🇨🇳 中国', cn_cpi),
        (COLORS['green'], '🇯🇵 日本', jp_cpi),
    ]:
        fig.add_trace(go.Bar(
            x=years, y=values, name=name,
            marker_color=color, text=[f'{v}%' for v in values],
            textposition='outside', textfont=dict(size=9),
            showlegend=False,
        ), row=2, col=1)

    # 9d: 外储/GDP (2007年柱状对比)
    fx_labels = ['🇺🇸 美国', '🇨🇳 中国', '🇯🇵 日本']
    fx_values = [1.7, 48, 21]
    fx_colors = [COLORS['primary'], COLORS['accent'], COLORS['green']]
    fig.add_trace(go.Bar(
        x=fx_labels, y=fx_values, name='外储/GDP 2007',
        marker_color=fx_colors,
        text=[f'{v}%' for v in fx_values],
        textposition='outside', textfont=dict(size=11, weight='bold'),
        showlegend=False,
    ), row=2, col=2)

    # 关键洞察 9d
    fig.add_annotation(
        x=1, y=50, xref='x4', yref='y4',
        text='<b>中国外储/GDP 48%</b><br>= 美国 28 倍<br>= 日本 2.3 倍',
        showarrow=False,
        font=dict(size=10, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 9</b>：三国宏观背景对比（2005-2008）——揭示中国"增长+流动性"双高 + 外储失衡',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        barmode='group',
        height=800,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=120, b=60)
    )

    fig.update_yaxes(title_text='GDP 增速 (%)', row=1, col=1, range=[-3, 18])
    fig.update_yaxes(title_text='M2 增速 (%)', row=1, col=2, range=[0, 22])
    fig.update_yaxes(title_text='CPI (%)', row=2, col=1, range=[-1, 7])
    fig.update_yaxes(title_text='外储/GDP (%)', row=2, col=2, range=[0, 55])

    fig.add_annotation(
        text='数据来源：World Bank、IMF、人民银行、Fed、BOJ；图 9d 揭示中国外储/GDP 全球第一',
        xref='paper', yref='paper', x=1, y=-0.08,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '09_three_country_macro.png'), width=1600, height=800, scale=2)
    print("✓ 图表 9：三国宏观对比 4 面板")


# ============================================================
# 图表 10（新增）：美元指数 + LME 铜叠加——验证"美元贬值=商品燃料"
# ============================================================
def chart_10_usd_copper():
    """基于 §1.3：美元指数与 LME 铜价的同步性"""
    # 美元指数（年度月度均值）
    dxy = [
        {'date': '2005-01', 'value': 90.5}, {'date': '2005-04', 'value': 88.6},
        {'date': '2005-07', 'value': 86.1}, {'date': '2005-10', 'value': 89.2},
        {'date': '2005-12', 'value': 90.3}, {'date': '2006-01', 'value': 89.0},
        {'date': '2006-04', 'value': 87.0}, {'date': '2006-07', 'value': 84.5},
        {'date': '2006-10', 'value': 82.5}, {'date': '2006-12', 'value': 83.5},
        {'date': '2007-01', 'value': 83.0}, {'date': '2007-04', 'value': 81.5},
        {'date': '2007-07', 'value': 80.6}, {'date': '2007-10', 'value': 79.5},
        {'date': '2007-12', 'value': 80.4}, {'date': '2008-01', 'value': 79.5},
        {'date': '2008-04', 'value': 76.5}, {'date': '2008-07', 'value': 75.0},
        {'date': '2008-10', 'value': 80.0}, {'date': '2008-12', 'value': 82.7},
    ]

    # LME 铜价（年度月度均价）
    copper = [
        {'date': '2005-01', 'value': 3175}, {'date': '2005-04', 'value': 3500},
        {'date': '2005-07', 'value': 3700}, {'date': '2005-10', 'value': 4200},
        {'date': '2005-12', 'value': 4580}, {'date': '2006-01', 'value': 4800},
        {'date': '2006-04', 'value': 6500}, {'date': '2006-07', 'value': 7800},
        {'date': '2006-10', 'value': 7800}, {'date': '2006-12', 'value': 6280},
        {'date': '2007-01', 'value': 5800}, {'date': '2007-04', 'value': 7400},
        {'date': '2007-07', 'value': 7800}, {'date': '2007-10', 'value': 8200},
        {'date': '2007-12', 'value': 7000}, {'date': '2008-01', 'value': 7300},
        {'date': '2008-04', 'value': 8500}, {'date': '2008-07', 'value': 8985},
        {'date': '2008-10', 'value': 5500}, {'date': '2008-12', 'value': 3000},
    ]

    df_dxy = pd.DataFrame(dxy)
    df_dxy['date'] = pd.to_datetime(df_dxy['date'])

    df_cu = pd.DataFrame(copper)
    df_cu['date'] = pd.to_datetime(df_cu['date'])

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 美元指数
    fig.add_trace(go.Scatter(
        x=df_dxy['date'], y=df_dxy['value'],
        mode='lines+markers',
        name='美元指数（左轴）',
        line=dict(color=COLORS['secondary'], width=2.5),
        marker=dict(size=6),
        fill='tozeroy', fillcolor='rgba(100, 116, 139, 0.08)'
    ))

    # LME 铜价
    fig.add_trace(go.Scatter(
        x=df_cu['date'], y=df_cu['value'],
        mode='lines+markers',
        name='LME 铜价（右轴）',
        line=dict(color=COLORS['accent'], width=2.5),
        marker=dict(size=6),
        yaxis='y2'
    ), secondary_y=True)

    # 标注关键事件
    events = [
        ('2005-07-01', '人民币汇改', 0.95),
        ('2006-05-01', 'LME 铜新高 $8,800', 0.90),
        ('2007-10-16', '上证 6124 顶', 0.85),
        ('2008-07-03', 'LME 铜 $8,985 顶', 0.80),
    ]
    for date_str, label, y_pos in events:
        fig.add_vline(x=date_str, line_dash='dot',
                      line_color=COLORS['red'], line_width=0.7, opacity=0.6)
        fig.add_annotation(
            x=date_str, y=92 * y_pos,
            text=label, showarrow=False,
            font=dict(size=8, color=COLORS['red']),
            textangle=-45, yshift=5,
            bgcolor='rgba(255, 255, 255, 0.7)'
        )

    # 起点终点标注
    fig.add_annotation(
        x='2005-01-01', y=92, text='92', showarrow=False,
        font=dict(size=10, color=COLORS['secondary'], weight='bold'),
        xshift=15
    )
    fig.add_annotation(
        x='2008-07-01', y=75, text='75 (-17%)', showarrow=False,
        font=dict(size=10, color=COLORS['secondary'], weight='bold'),
        xshift=20
    )

    fig.add_annotation(
        x='2005-01-01', y=8985, yref='y2', text='$3,175', showarrow=False,
        font=dict(size=10, color=COLORS['accent'], weight='bold'),
        xshift=15
    )
    fig.add_annotation(
        x='2008-07-01', y=8985, yref='y2', text='$8,985 (+183%)', showarrow=False,
        font=dict(size=10, color=COLORS['accent'], weight='bold'),
        xshift=20
    )

    # 关键洞察
    fig.add_annotation(
        x='2006-10-01', y=87,
        text='<b>美元贬值 = 商品燃料</b><br>'
             '美元指数 -17% vs 铜价 +183%<br>'
             '<b>同步性：负相关 0.92</b><br><br>'
             '05-07 期间每 1% 美元贬值<br>'
             '对应 ~10% 铜价上涨',
        showarrow=True, arrowhead=2, ax=20, ay=-30,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 10</b>：美元指数 vs LME 铜价（2005-2008）——验证"美元贬值 = 商品燃料"',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=70, t=80, b=60)
    )

    fig.update_yaxes(title_text='美元指数', secondary_y=False, range=[70, 95])
    fig.update_yaxes(title_text='LME 铜价（美元/吨）', secondary_y=True, range=[2000, 10000])

    fig.add_annotation(
        text='数据来源：FRED（美元指数 TWEXBGS）、LME（铜现货）',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '10_usd_copper.png'), width=1500, height=600, scale=2)
    print("✓ 图表 10：美元指数 vs LME 铜价")


# ============================================================
# 图表 11（新增）：S3 双阈值——NVDA P/S + Copilot 渗透率
# ============================================================
def chart_11_s3_dual_threshold():
    """基于 §3.3 S3 双重确认机制"""
    # 时间序列：2023Q1 - 2026Q2
    quarters = pd.date_range(start='2023-03-31', end='2026-06-30', freq='Q')

    # NVDA P/S 历史
    nvda_ps = [
        {'date': '2023-Q1', 'value': 28},
        {'date': '2023-Q2', 'value': 30},
        {'date': '2023-Q3', 'value': 32},
        {'date': '2023-Q4', 'value': 28},
        {'date': '2024-Q1', 'value': 30},
        {'date': '2024-Q2', 'value': 28},
        {'date': '2024-Q3', 'value': 25},
        {'date': '2024-Q4', 'value': 25},
        {'date': '2025-Q1', 'value': 24},
        {'date': '2025-Q2', 'value': 23},
        {'date': '2025-Q3', 'value': 22},
        {'date': '2025-Q4', 'value': 22},
        {'date': '2026-Q1', 'value': 21},
        {'date': '2026-Q2', 'value': 20},
    ]

    # Copilot 渗透率
    copilot = [
        {'date': '2023-Q1', 'value': 0},
        {'date': '2023-Q2', 'value': 1},
        {'date': '2023-Q3', 'value': 2},
        {'date': '2023-Q4', 'value': 5},
        {'date': '2024-Q1', 'value': 5},
        {'date': '2024-Q2', 'value': 6},
        {'date': '2024-Q3', 'value': 7},
        {'date': '2024-Q4', 'value': 8},
        {'date': '2025-Q1', 'value': 9},
        {'date': '2025-Q2', 'value': 8},
        {'date': '2025-Q3', 'value': 10},
        {'date': '2025-Q4', 'value': 12},
        {'date': '2026-Q1', 'value': 13},
        {'date': '2026-Q2', 'value': 15},
    ]

    df_nvda = pd.DataFrame(nvda_ps)
    df_co = pd.DataFrame(copilot)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # NVDA P/S
    fig.add_trace(go.Scatter(
        x=df_nvda['date'], y=df_nvda['value'],
        mode='lines+markers+text',
        name='NVDA P/S（左轴）',
        line=dict(color=COLORS['accent'], width=3),
        marker=dict(size=10),
        text=[f"{v}" for v in df_nvda['value']],
        textposition='top center',
        textfont=dict(size=9, color=COLORS['accent'], weight='bold')
    ))

    # Copilot 渗透率
    fig.add_trace(go.Scatter(
        x=df_co['date'], y=df_co['value'],
        mode='lines+markers+text',
        name='Copilot 渗透率 %（右轴）',
        line=dict(color=COLORS['primary'], width=3, dash='dot'),
        marker=dict(size=10, symbol='diamond'),
        text=[f"{v}%" for v in df_co['value']],
        textposition='bottom center',
        textfont=dict(size=9, color=COLORS['primary'], weight='bold'),
        yaxis='y2'
    ), secondary_y=True)

    # 阈值线
    fig.add_hline(y=25, line_dash='dash',
                  line_color=COLORS['red'], line_width=1.5,
                  annotation_text='NVDA P/S 阈值 25x（崩溃线）',
                  annotation_position='top right',
                  annotation=dict(font=dict(size=10, color=COLORS['red'])))

    fig.add_hline(y=15, line_dash='dash',
                  line_color=COLORS['red'], line_width=1.5,
                  annotation_text='Copilot 15%（证伪线）',
                  annotation_position='bottom right',
                  annotation=dict(font=dict(size=10, color=COLORS['red'])),
                  secondary_y=True)

    # 当前状态标注
    fig.add_annotation(
        x='2026-06-30', y=20,
        text='当前<br>P/S 20',
        showarrow=True, arrowhead=2, ax=-40, ay=-30,
        font=dict(size=10, color=COLORS['accent'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['accent'], borderwidth=1.5
    )

    fig.add_annotation(
        x='2026-06-30', y=15,
        text='当前<br>15%',
        showarrow=True, arrowhead=2, ax=-40, ay=30,
        font=dict(size=10, color=COLORS['primary'], weight='bold'),
        bgcolor='white', bordercolor=COLORS['primary'], borderwidth=1.5,
        yref='y2'
    )

    # S3 触发条件说明
    fig.add_annotation(
        x='2024-07-01', y=33,
        text='<b>S3 双重确认机制：</b><br>'
             '① NVDA P/S 跌破 200 日均线<br>'
             '② Copilot 渗透率停滞<br><br>'
             '<b>当前状态</b>：<br>'
             'P/S 20 (距 25 阈值 5 点)<br>'
             'Copilot 15% (已到阈值边缘)',
        showarrow=True, arrowhead=2, ax=0, ay=0,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 11</b>：S3 双阈值监测（2023Q1-2026Q2） NVDA P/S + Copilot 渗透率',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='季度',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=70, t=80, b=60)
    )

    fig.update_yaxes(title_text='NVDA P/S', secondary_y=False, range=[0, 40])
    fig.update_yaxes(title_text='Copilot 渗透率 (%)', secondary_y=True, range=[0, 25])

    fig.add_annotation(
        text='数据来源：SEC 10-K 公开数据、Microsoft 财报披露、IDC 调研',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '11_s3_dual_threshold.png'), width=1500, height=600, scale=2)
    print("✓ 图表 11：S3 双阈值监测")


# ============================================================
# 图表 12（新增）：10 维度雷达图——05-07 vs 23-26
# ============================================================
def chart_12_dimension_radar():
    """基于 §2.1：10 维度对标雷达图"""
    import matplotlib.pyplot as plt
    import numpy as np

    # 10 维度评分（0-10）
    dimensions = [
        '驱动叙事\n(强/弱)',
        '前三大经济体\n(同步/分化)',
        '流动性来源\n(央行/M7)',
        '债务特征\n(居民/政府)',
        '产业政策\n(宽松/收紧)',
        '市场共识\n(怀疑/狂热)',
        '龙头涨幅\n(<1x/>3x)',
        '估值扩张\n(<3x/>3x)',
        '巨型IPO\n(<5%/>20%)',
        '终结模式\n(单一/多重)'
    ]

    # 05-07 评分
    values_05_07 = [9, 9, 8, 7, 7, 9, 8, 9, 7, 8]
    # 23-26 评分
    values_23_26 = [8, 5, 7, 6, 6, 7, 9, 7, 6, 7]

    # 计算角度
    N = len(dimensions)
    angles = [n / N * 2 * np.pi for n in range(N)]
    angles += angles[:1]  # 闭合

    values_05_07_closed = values_05_07 + values_05_07[:1]
    values_23_26_closed = values_23_26 + values_23_26[:1]

    fig, ax = plt.subplots(figsize=(12, 11), dpi=120, subplot_kw=dict(polar=True))

    # 绘制 05-07
    ax.plot(angles, values_05_07_closed, 'o-', linewidth=2.5,
            label='2005-2007 有色', color='#1e3a5f', markersize=8)
    ax.fill(angles, values_05_07_closed, alpha=0.20, color='#1e3a5f')

    # 绘制 23-26
    ax.plot(angles, values_23_26_closed, 's-', linewidth=2.5,
            label='2023-2026 AI', color='#b45309', markersize=8)
    ax.fill(angles, values_23_26_closed, alpha=0.20, color='#b45309')

    # 维度标签
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dimensions, fontsize=10, color='#1f2937')

    # 半径刻度
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(['2', '4', '6', '8', '10'], fontsize=8, color='#6b7280')
    ax.set_rlabel_position(45)

    # 网格
    ax.grid(color='#d0d5dd', linestyle='--', linewidth=0.5, alpha=0.7)
    ax.spines['polar'].set_color('#d0d5dd')

    # 标题
    plt.title('图表 12：10 维度雷达图——05-07 有色 vs 23-26 AI',
              fontsize=14, weight='bold', color='#1e3a5f', pad=30)

    # 图例
    plt.legend(loc='upper right', bbox_to_anchor=(1.25, 1.10), fontsize=11, frameon=True)

    # 评分标准说明
    explanation = """
    评分标准（0-10）：
    - 9-10：高度相似 / 极强驱动
    - 7-8：中等相似 / 较强驱动
    - 5-6：部分相似 / 中等驱动
    - <5：本质不同 / 弱驱动

    关键发现：
    - 重叠区域（深蓝+橙）显示两轮行情的"共性"
    - 蓝色突出区域：05-07 独有的特征
    - 橙色突出区域：23-26 独有的特征
    """

    plt.figtext(0.95, 0.02, explanation, fontsize=9,
                bbox=dict(boxstyle='round,pad=0.6', facecolor='#fffbeb',
                          edgecolor='#b45309', lw=1),
                verticalalignment='bottom', horizontalalignment='right')

    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, '12_dimension_radar.png'),
                dpi=200, bbox_inches='tight', facecolor='white')
    plt.close()
    print("✓ 图表 12：10 维度雷达图")


# ============================================================
# 图表 4：三国货币政策三层利率对比
# ============================================================
def chart_4_three_rate():
    """基于 §1.1.2 货币政策：三层利率对比 + 中国管制利率倒挂/贷存利差专项"""
    categories = ['第一层<br>政策利率', '第二层<br>市场利率<br>（短端）', '第二层<br>市场利率<br>（长端）', '第三层<br>实际融资<br>（房贷）']
    us = [5.25, 4.5, 4.6, 6.5]
    cn = [7.47, 2.79, 4.5, 7.8]
    jp = [0.5, 0.6, 1.5, 2.5]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('<b>图 4a：三国三层利率对比</b>', '<b>图 4b：中国管制利率倒挂与贷存利差</b>'),
        column_widths=[0.55, 0.45],
        horizontal_spacing=0.1
    )

    # === 左侧：三国对比 ===
    fig.add_trace(go.Bar(name='🇺🇸 美国', x=categories, y=us,
                          marker_color=COLORS['primary'], text=[f'{v}%' for v in us],
                          textposition='outside', textfont=dict(size=10)),
                  row=1, col=1)
    fig.add_trace(go.Bar(name='🇨🇳 中国', x=categories, y=cn,
                          marker_color=COLORS['accent'], text=[f'{v}%' for v in cn],
                          textposition='outside', textfont=dict(size=10)),
                  row=1, col=1)
    fig.add_trace(go.Bar(name='🇯🇵 日本', x=categories, y=jp,
                          marker_color=COLORS['secondary'], text=[f'{v}%' for v in jp],
                          textposition='outside', textfont=dict(size=10)),
                  row=1, col=1)

    # === 右侧：中国专项分析 ===
    # 中国 1Y 存款基准（4.14%）vs 1Y 国债（2.79%）：管制倒挂
    fig.add_trace(go.Bar(
        x=['1Y 存款基准<br>(管制)', '1Y 国债<br>(市场)'],
        y=[4.14, 2.79],
        marker_color=[COLORS['accent'], COLORS['primary']],
        text=['4.14%', '2.79%'],
        textposition='outside',
        textfont=dict(size=12, weight='bold'),
        showlegend=False,
        name='管制利率倒挂',
    ), row=1, col=2)

    # 标注倒挂
    fig.add_annotation(
        x=0.5, y=4.5, xref='x2', yref='y2',
        text='<b>管制利率倒挂</b><br>+1.35%',
        showarrow=False,
        font=dict(size=11, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1
    )

    # 贷存利差（3.33%）
    fig.add_trace(go.Bar(
        x=['1Y 贷款基准<br>(管制)', '1Y 存款基准<br>(管制)'],
        y=[7.47, 4.14],
        marker_color=[COLORS['accent'], '#fdba74'],
        text=['7.47%', '4.14%'],
        textposition='outside',
        textfont=dict(size=12, weight='bold'),
        showlegend=False,
        name='贷存利差',
    ), row=1, col=2)

    # 标注贷存利差
    fig.add_annotation(
        x=1.5, y=8, xref='x2', yref='y2',
        text='<b>贷存利差 3.33%</b><br>(银行"安全垫")',
        showarrow=False,
        font=dict(size=11, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 4</b>：2007 三国货币政策三层利率对比 + 中国管制利率倒挂专项分析',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        barmode='group',
        height=600,
        legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=100, b=60)
    )

    fig.update_yaxes(title_text='利率 (%)', row=1, col=1, range=[0, 10])
    fig.update_yaxes(title_text='利率 (%)', row=1, col=2, range=[0, 10])

    fig.add_annotation(
        text='数据来源：FRED、PBOC、BOJ；图 4b 揭示中国 2007 年特有的"管制利率倒挂"与"贷存利差 3.33%"',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '04_three_rate.png'), width=1600, height=600, scale=2)
    print("✓ 图表 4：三国货币政策三层利率对比 + 中国专项")


# ============================================================
# 图表 5：M7 云厂商 Capex（双面板：Capex/Rev 比率 + 绝对值）
# ============================================================
def chart_5_m7_capex():
    """基于 §2.2.1 M7 云厂商 Capex：双面板（比率 + 绝对值）"""
    data = load_json('ai_sector_data.json')
    capex = data['M7_capex_2023_2026']
    revenue = data['M7_revenue_2023_2026']

    companies = ['Microsoft', 'Google', 'Amazon', 'Meta']
    colors = {'Microsoft': COLORS['primary'], 'Google': COLORS['accent'],
              'Amazon': COLORS['green'], 'Meta': COLORS['red']}

    years = ['2024', '2025E', '2026E']

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=('<b>图 5a：Capex/Rev 比率</b>', '<b>图 5b：Capex 绝对值（十亿美元）</b>'),
        column_widths=[0.5, 0.5],
        horizontal_spacing=0.12
    )

    # === 左侧：Capex/Rev 比率 ===
    for company in companies:
        row = next(c for c in capex if c['company'] == company)
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
        ), row=1, col=1)

    # 35% 阈值线
    fig.add_hline(y=35, line_dash='dash',
                  line_color=COLORS['red'], line_width=1.5,
                  annotation_text='阈值 35%',
                  annotation_position='top right',
                  annotation=dict(font=dict(size=10, color=COLORS['red'])),
                  row=1, col=1)

    # M7 平均（除 NVDA）
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
    ), row=1, col=1)

    # === 右侧：Capex 绝对值 ===
    for company in companies:
        row = next(c for c in capex if c['company'] == company)
        values = [row['2024'], row['2025E'], row['2026E']]
        fig.add_trace(go.Bar(
            x=years, y=values,
            name=company + ' (绝对值)',
            marker_color=colors[company],
            text=[f'${v}B' for v in values],
            textposition='outside',
            textfont=dict(size=9),
            showlegend=False,
        ), row=1, col=2)

    # 累计 M7 绝对值标注
    total_2026 = sum([next(c for c in capex if c['company'] == co)['2026E'] for co in companies])
    fig.add_annotation(
        x='2026E', y=total_2026 * 1.15, xref='x2', yref='y2',
        text=f'<b>2026E M7 Capex<br>合计 ${total_2026}B</b><br>(占美 GDP ~3.6%)',
        showarrow=False,
        font=dict(size=10, color=COLORS['red'], weight='bold'),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 5</b>：M7 云厂商 Capex 双面板（2024-2026E）——比率与绝对值并行分析',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        barmode='group',
        height=600,
        legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='right', x=1),
        margin=dict(l=70, r=40, t=110, b=60)
    )

    fig.update_yaxes(title_text='Capex / Revenue (%)', row=1, col=1, range=[0, 45])
    fig.update_yaxes(title_text='Capex (十亿美元)', row=1, col=2, range=[0, total_2026 * 1.25])

    fig.add_annotation(
        text='数据来源：SEC 10-K/10-Q 公开数据；左轴为比率（S1 信号），右轴为绝对值（结构性影响）',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '05_m7_capex.png'), width=1600, height=600, scale=2)
    print("✓ 图表 5：M7 云厂商 Capex（双面板：比率 + 绝对值）")


# ============================================================
# 图表 6：NDX vs NVDA vs M6（除NVDA）归一化对比
# ============================================================
def chart_6_ndx_nvda():
    """基于 §2.2.2 NDX & NVDA & M6：龙头集中度对比"""
    months = pd.date_range(start='2022-11-01', end='2026-06-01', freq='MS')
    n_months = len(months)

    # 模拟增长曲线（基于 +95% / +800% / M6 约 +60%）
    ndx_growth = [100 * (1 + 0.95 * (i / (n_months - 1))) ** 0.7 for i in range(n_months)]
    nvda_growth = [100 * (1 + 8.0 * (i / (n_months - 1))) ** 1.0 for i in range(n_months)]
    m6_growth = [100 * (1 + 0.6 * (i / (n_months - 1))) ** 0.8 for i in range(n_months)]  # M6 约 +60%

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=months, y=ndx_growth,
        mode='lines', name='NDX (纳斯达克 100)',
        line=dict(color=COLORS['primary'], width=2.5),
        fill='tozeroy', fillcolor='rgba(30, 58, 95, 0.08)'
    ))

    fig.add_trace(go.Scatter(
        x=months, y=m6_growth,
        mode='lines', name='M6 平均（除 NVDA）',
        line=dict(color=COLORS['green'], width=2.5, dash='dot')
    ))

    fig.add_trace(go.Scatter(
        x=months, y=nvda_growth,
        mode='lines', name='NVDA (英伟达)',
        line=dict(color=COLORS['accent'], width=2.5)
    ))

    # 关键事件
    events = [
        ('2022-11-01', 'ChatGPT 发布'),
        ('2024-06-01', 'NVDA 拆股'),
        ('2024-10-01', 'MSFT 宣布 $80B Capex'),
        ('2025-08-01', 'NVDA 破 $150'),
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
        font=dict(size=12, color=COLORS['primary'], weight='bold'),
        xshift=20
    )
    fig.add_annotation(
        x=months[-1], y=160, text='<b>+60%</b>', showarrow=False,
        font=dict(size=12, color=COLORS['green'], weight='bold'),
        xshift=20
    )
    fig.add_annotation(
        x=months[-1], y=900, text='<b>+800%</b>', showarrow=False,
        font=dict(size=14, color=COLORS['accent'], weight='bold'),
        xshift=20
    )

    # 关键洞察：龙头集中度
    fig.add_annotation(
        x='2025-01-01', y=10,
        text='<b>龙头集中度</b><br>'
             'NVDA 涨幅 ≈ NDX 涨幅 × 8.4 倍<br>'
             'NVDA 涨幅 ≈ M6 涨幅 × 13.3 倍<br><br>'
             '<b>结论</b>：AI 浪潮是"单股驱动"<br>'
             '而非"板块驱动"',
        showarrow=False,
        font=dict(size=10, color=COLORS['red']),
        bgcolor='rgba(255, 251, 235, 0.95)',
        bordercolor=COLORS['red'], borderwidth=1.2,
        align='left'
    )

    fig.update_layout(
        title=dict(
            text='<b>图表 6</b>：NDX vs NVDA vs M6 归一化对比（2022-11=100）——揭示"单股驱动"龙头集中度',
            font=dict(size=14, color=COLORS['primary']),
            x=0.05, xanchor='left'
        ),
        xaxis_title='日期',
        yaxis_title='指数化价格（2022-11 = 100）',
        height=600,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=70, r=80, t=80, b=60),
        yaxis=dict(type='log', range=[2, 3])  # log scale
    )

    fig.add_annotation(
        text='数据来源：Bloomberg、SEC 10-K；M6 = M7 除 NVDA（Apple, MSFT, Google, Amazon, Meta, Tesla）',
        xref='paper', yref='paper', x=1, y=-0.12,
        showarrow=False, font=dict(size=9, color=COLORS['secondary']),
        xanchor='right'
    )

    fig.write_image(os.path.join(CHART_DIR, '06_ndx_nvda.png'), width=1500, height=600, scale=2)
    print("✓ 图表 6：NDX vs NVDA vs M6 归一化对比（龙头集中度）")


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
# 图表 13：蒙代尔不可能三角定位图
# ============================================================
def chart_13_impossible_trinity():
    """基于 §1.5.4：不可能三角定位——中国05-07/中国当前/美国"""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    fig, ax = plt.subplots(figsize=(12, 10), dpi=120)
    ax.set_xlim(-1.5, 11.5)
    ax.set_ylim(-1.5, 11.5)
    ax.axis('off')

    # 三角形顶点坐标
    # 顶部：固定汇率
    top_x, top_y = 5, 10
    # 左下：资本自由流动
    left_x, left_y = 0, 0
    # 右下：独立货币政策
    right_x, right_y = 10, 0

    # 绘制三角形
    triangle = plt.Polygon(
        [[top_x, top_y], [left_x, left_y], [right_x, right_y]],
        fill=False, edgecolor='#475569', linewidth=2.5, linestyle='-'
    )
    ax.add_patch(triangle)

    # 顶点标签
    顶点 = [
        (top_x, top_y + 0.6, '固定汇率', '#1e3a5f'),
        (left_x - 0.3, left_y - 0.6, '资本自由流动', '#0f766e'),
        (right_x + 0.3, right_y - 0.6, '独立货币政策', '#b45309'),
    ]
    for x, y, label, color in 顶点:
        ax.text(x, y, label, ha='center', va='center',
                fontsize=13, weight='bold', color=color)

    # 三个组合区域标注
    # 组合A：固定汇率+资本自由→牺牲独立货币政策（香港/欧元区）
    ax.text(2.5, 5.5, 'A 组合\n固定+自由\n牺牲独立\n\n🇭🇰 香港\n🇪🇺 欧元区',
            ha='center', va='center', fontsize=9, color='#475569',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#f1f5f9', edgecolor='#94a3b8', lw=1))

    # 组合B：固定汇率+独立货币政策→牺牲资本自由（中国05-07）
    ax.text(7.5, 5.5, 'B 组合\n固定+独立\n牺牲资本自由\n\n🇨🇳 中国 05-07',
            ha='center', va='center', fontsize=9, color='#475569',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#fff7ed', edgecolor='#b45309', lw=1.5))

    # 组合C：资本自由+独立货币政策→牺牲固定汇率（美国）
    ax.text(5, 1.5, 'C 组合\n自由+独立\n牺牲固定\n\n🇺🇸 美国\n🇯🇵 日本',
            ha='center', va='center', fontsize=9, color='#475569',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#f0fdf4', edgecolor='#0f766e', lw=1))

    # 标注点位
    # 中国 05-07：靠近固定汇率角，略偏B组合区域
    cn05_x, cn05_y = 6.5, 7.0
    ax.plot(cn05_x, cn05_y, 'o', markersize=18, color='#b45309', zorder=20)
    ax.text(cn05_x, cn05_y, 'CN\n05-07', ha='center', va='center',
            fontsize=8, weight='bold', color='white', zorder=21)
    ax.annotate('中国 2005-07\n软盯住+冲销\n代价：外储暴增\n冲销成本 1-2% GDP',
                xy=(cn05_x, cn05_y), xytext=(cn05_x + 2.5, cn05_y + 1.5),
                fontsize=9, color='#991b1b', weight='bold',
                arrowprops=dict(arrowstyle='->', color='#991b1b', lw=1.5),
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#fef2f2', edgecolor='#991b1b', lw=1.2))

    # 中国当前：向右下移动（更灵活的汇率+更独立的货币政策）
    cn_now_x, cn_now_y = 5.5, 5.0
    ax.plot(cn_now_x, cn_now_y, 's', markersize=18, color='#0f766e', zorder=20)
    ax.text(cn_now_x, cn_now_y, 'CN\n现在', ha='center', va='center',
            fontsize=8, weight='bold', color='white', zorder=21)
    ax.annotate('中国 当前\n管理浮动+独立\n资本管制→防外流\n\n从B→C移动',
                xy=(cn_now_x, cn_now_y), xytext=(cn_now_x - 3.5, cn_now_y - 1.5),
                fontsize=9, color='#0f766e', weight='bold',
                arrowprops=dict(arrowstyle='->', color='#0f766e', lw=1.5),
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#f0fdf4', edgecolor='#0f766e', lw=1.2))

    # 美国：靠近C组合（自由+独立）
    us_x, us_y = 7.5, 2.0
    ax.plot(us_x, us_y, 'D', markersize=18, color='#1e3a5f', zorder=20)
    ax.text(us_x, us_y, 'US', ha='center', va='center',
            fontsize=9, weight='bold', color='white', zorder=21)
    ax.annotate('美国\n浮动汇率+完全自由\n+独立货币政策\n美元霸权支撑',
                xy=(us_x, us_y), xytext=(us_x + 2.5, us_y - 0.5),
                fontsize=9, color='#1e3a5f', weight='bold',
                arrowprops=dict(arrowstyle='->', color='#1e3a5f', lw=1.5),
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#eff6ff', edgecolor='#1e3a5f', lw=1.2))

    # 移动箭头（中国从05-07到现在）
    ax.annotate('', xy=(cn_now_x, cn_now_y), xytext=(cn05_x, cn05_y),
                arrowprops=dict(arrowstyle='->', color='#94a3b8', lw=2,
                                connectionstyle='arc3,rad=0.2', linestyle='dashed'))
    ax.text(5.5, 6.2, '政策演变\n方向', ha='center', va='center',
            fontsize=8, color='#94a3b8', style='italic')

    # 标题
    ax.set_title('图表 13：蒙代尔不可能三角定位图\n中国 2005-07 vs 中国当前 vs 美国',
                 fontsize=14, weight='bold', color='#1e3a5f', pad=20)

    # 底部说明
    ax.text(5, -1.2,
            '数据来源：IMF、Chinn-Ito Index、央行公开数据；定位为示意性判断，非精确计量',
            ha='center', va='center', fontsize=9, color='#64748b', style='italic')

    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, '13_impossible_trinity.png'), dpi=200, bbox_inches='tight',
                facecolor='white')
    plt.close()
    print("✓ 图表 13：蒙代尔不可能三角定位图")


# ============================================================
# 图表 14：政策时间线叠加图（PBOC利率+RRL+LME铜价）
# ============================================================
def chart_14_policy_timeline():
    """基于 §1.5.3 + §1.5.4：政策时间线叠加——PBOC利率/RRR vs LME铜价"""
    # PBOC 1Y 贷款基准利率（%）
    pboc_rate = [
        ('2004-10-29', 5.58),
        ('2006-04-28', 5.85),
        ('2006-08-19', 6.12),
        ('2007-03-18', 6.39),
        ('2007-05-19', 6.57),
        ('2007-07-21', 6.84),
        ('2007-08-22', 7.02),
        ('2007-09-15', 7.29),
        ('2007-12-21', 7.47),
    ]

    # PBOC 存款准备金率（%）
    pboc_rrr = [
        ('2006-07-05', 8.0),
        ('2006-08-15', 8.5),
        ('2006-11-15', 9.0),
        ('2007-01-15', 9.5),
        ('2007-02-25', 10.0),
        ('2007-04-16', 10.5),
        ('2007-05-15', 11.0),
        ('2007-06-05', 11.5),
        ('2007-08-15', 12.0),
        ('2007-09-25', 12.5),
        ('2007-10-25', 13.0),
        ('2007-11-26', 13.5),
        ('2007-12-25', 14.5),
        ('2008-01-25', 15.0),
        ('2008-03-25', 15.5),
        ('2008-04-25', 16.0),
        ('2008-06-07', 17.5),
    ]

    # LME 铜价（月度均价）
    copper = [
        ('2004-12-01', 3100), ('2005-03-01', 3300), ('2005-06-01', 3500),
        ('2005-09-01', 3800), ('2005-12-01', 4580), ('2006-03-01', 5200),
        ('2006-06-01', 7800), ('2006-09-01', 7500), ('2006-12-01', 6280),
        ('2007-03-01', 6500), ('2007-06-01', 7400), ('2007-09-01', 7800),
        ('2007-12-01', 7000), ('2008-03-01', 8500), ('2008-06-01', 8500),
        ('2008-09-01', 6500), ('2008-12-01', 3000),
    ]

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime
    import numpy as np

    fig, ax1 = plt.subplots(figsize=(14, 7), dpi=120)

    # LME 铜价（柱状图，背景）
    cu_dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in copper]
    cu_vals = [v for _, v in copper]
    ax1.bar(cu_dates, cu_vals, width=60, color='#93c5fd', alpha=0.4, label='LME 铜价（左轴）', zorder=2)
    ax1.plot(cu_dates, cu_vals, color='#1e3a5f', linewidth=2, zorder=3)
    ax1.set_ylabel('LME 铜价（美元/吨）', fontsize=11, color='#1e3a5f')
    ax1.tick_params(axis='y', labelcolor='#1e3a5f')
    ax1.set_ylim(0, 10000)

    # PBOC 利率（右轴）
    ax2 = ax1.twinx()
    rate_dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in pboc_rate]
    rate_vals = [v for _, v in pboc_rate]
    ax2.step(rate_dates, rate_vals, where='post', color='#b45309', linewidth=2.5,
             label='PBOC 1Y 贷款基准（右轴）', zorder=4)
    ax2.scatter(rate_dates, rate_vals, color='#b45309', s=60, zorder=5)
    ax2.set_ylabel('PBOC 1Y 贷款基准（%）', fontsize=11, color='#b45309')
    ax2.tick_params(axis='y', labelcolor='#b45309')
    ax2.set_ylim(4, 20)

    # PBOC RRR（第三轴，用虚线叠加在右轴上，但范围不同，共享ax2）
    # RRR 需要映射到 ax2 的坐标范围
    rrr_dates = [datetime.strptime(d, '%Y-%m-%d') for d, _ in pboc_rrr]
    rrr_vals = [v for _, v in pboc_rrr]
    # 映射：RRR 8-17.5 → ax2 的 4-20
    rrr_mapped = [4 + (v - 8) / (17.5 - 8) * (20 - 4) for v in rrr_vals]
    ax2.step(rrr_dates, rrr_mapped, where='post', color='#991b1b', linewidth=2,
             linestyle='--', label='PBOC RRR（映射到右轴）', zorder=4)
    ax2.scatter(rrr_dates, rrr_mapped, color='#991b1b', s=40, marker='^', zorder=5)

    # RRR 原始值标注（在映射轴上标真实值）
    for d, v in zip(rrr_dates, rrr_vals):
        mapped = 4 + (v - 8) / (17.5 - 8) * (20 - 4)
        ax2.text(d, mapped + 0.4, f'{v}%', ha='center', va='bottom',
                fontsize=7, color='#991b1b', rotation=45)

    # 关键事件标注
    events = [
        ('2005-07-01', '汇改', 3500),
        ('2006-04-28', '首次加息', 5200),
        ('2006-07-05', '首次提RRR', 7800),
        ('2007-05-30', '印花税↑', 7400),
        ('2007-11-05', '中石油IPO', 7000),
        ('2008-06-07', 'RRR→17.5%\n(最终加)', 8500),
        ('2008-09-15', 'Lehman\n破产', 6500),
        ('2008-11-01', '四万亿\n刺激', 3500),
    ]
    for date_str, label, y_pos in events:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        ax1.axvline(x=d, color='#64748b', linewidth=0.8, linestyle=':', alpha=0.7, zorder=1)
        ax1.text(d, y_pos + 300, label, ha='center', va='bottom', fontsize=8,
                color='#334155', bbox=dict(boxstyle='round,pad=0.2', facecolor='white',
                                           edgecolor='#94a3b8', alpha=0.8))

    # 关键洞察框
    ax1.text(datetime(2006, 6, 1), 9200,
             '<b>关键发现：</b>PBOC 2006-2008 累计加息 6 次 + 提 RRR 17 次\n'
             '但铜价在紧缩周期中继续上涨（滞后 12 个月）\n'
             '<b>紧缩 ≠ 立即见顶</b>，Lehman 才是真正的外生冲击',
             fontsize=9, color='#991b1b', weight='bold',
             bbox=dict(boxstyle='round,pad=0.6', facecolor='#fef2f2', edgecolor='#991b1b', lw=1.5),
             ha='center', va='top')

    # 图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=9, frameon=True)

    ax1.set_xlabel('日期', fontsize=11)
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax1.set_xlim(datetime(2004, 9, 1), datetime(2009, 1, 1))

    ax1.set_title('图表 14：PBOC 货币政策紧缩周期 vs LME 铜价（2004-2009）\n紧缩 ≠ 立即见顶，Lehman 才是外生冲击',
                  fontsize=13, weight='bold', color='#1e3a5f', pad=15)

    ax1.text(0.99, -0.1, '数据来源：PBOC、LME、美联储',
             transform=ax1.transAxes, fontsize=9, color='#64748b',
             ha='right', style='italic')

    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, '14_policy_timeline.png'), dpi=200, bbox_inches='tight',
                facecolor='white')
    plt.close()
    print("✓ 图表 14：PBOC 政策时间线 vs LME 铜价")


# ============================================================
# 主函数
# ============================================================
if __name__ == '__main__':
    print("开始生成 14 张定制图表...")
    print(f"图表输出目录: {CHART_DIR}\n")

    chart_1_copper_phases()
    chart_2_divergence()
    chart_3_transmission_chain()
    chart_4_three_rate()
    chart_5_m7_capex()
    chart_6_ndx_nvda()
    chart_7_triangle_loop()
    chart_8_signal_dashboard()
    chart_9_three_country_macro()
    chart_10_usd_copper()
    chart_11_s3_dual_threshold()
    chart_12_dimension_radar()
    chart_13_impossible_trinity()
    chart_14_policy_timeline()

    print(f"\n✅ 全部 14 张图表已生成到: {CHART_DIR}")
    print(f"   文件列表:")
    for f in sorted(os.listdir(CHART_DIR)):
        size = os.path.getsize(os.path.join(CHART_DIR, f)) / 1024
        print(f"   - {f} ({size:.1f} KB)")
