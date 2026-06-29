"""
生成宏观经济背景 8 张图表（matplotlib 学术风格）
对应 slides 1.1.1-1.2.5
"""
import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

# 学术配色
COLORS = {
    'us': '#2563eb',      # 蓝
    'cn': '#dc2626',      # 红
    'jp': '#16a34a',      # 绿
    'eu': '#d97706',      # 琥珀
    'gray': '#64748b',    # 灰
    'grid': '#e2e8f0',    # 网格
    'bg': '#ffffff',      # 背景
    'text': '#1e293b',    # 文字
    'accent': '#0f766e',  # 青绿
}

# 中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.facecolor'] = COLORS['bg']
plt.rcParams['axes.facecolor'] = COLORS['bg']
plt.rcParams['axes.edgecolor'] = COLORS['grid']
plt.rcParams['axes.grid'] = True
plt.rcParams['grid.alpha'] = 0.3
plt.rcParams['grid.color'] = COLORS['grid']

DATA_DIR = '/home/ll/llmwikify/TopicResearch/data/raw'
CHART_DIR = '/home/ll/llmwikify/TopicResearch/report/charts'
os.makedirs(CHART_DIR, exist_ok=True)

with open(os.path.join(DATA_DIR, 'macro_4country_2000_2026.json')) as f:
    data = json.load(f)

years = [int(y) for y in data['years']]
years_str = data['years']

def save_chart(fig, name):
    path = os.path.join(CHART_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  ✅ {name}')

# ========== 图表 1：名义 GDP 4 国柱状图 ==========
def chart_gdp_nominal():
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(years))
    width = 0.2
    
    us = [v if v else 0 for v in data['gdp_nom']['us']]
    cn = [v if v else 0 for v in data['gdp_nom']['cn']]
    jp = [v if v else 0 for v in data['gdp_nom']['jp']]
    eu = [v if v else 0 for v in data['gdp_nom']['eu']]
    
    ax.bar(x - 1.5*width, us, width, label='US', color=COLORS['us'], alpha=0.85)
    ax.bar(x - 0.5*width, cn, width, label='China', color=COLORS['cn'], alpha=0.85)
    ax.bar(x + 0.5*width, jp, width, label='Japan', color=COLORS['jp'], alpha=0.85)
    ax.bar(x + 1.5*width, eu, width, label='Euro Area', color=COLORS['eu'], alpha=0.85)
    
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax.set_ylabel('Nominal GDP Growth (%)', fontsize=12, fontweight='bold')
    ax.set_title('Nominal GDP Growth: US, China, Japan, Euro Area (2000-2026)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xticks(x[::2])
    ax.set_xticklabels(years_str[::2], rotation=45, ha='right')
    ax.legend(loc='upper right', framealpha=0.9)
    ax.axhline(y=0, color='black', linewidth=0.5)
    
    # 标注关键年份
    ax.axvspan(5.5, 7.5, alpha=0.1, color='red', label='2005-2007')
    ax.annotate('CN 23%', xy=(7, 23.18), xytext=(7, 25), fontsize=8, color=COLORS['cn'], fontweight='bold', ha='center')
    
    save_chart(fig, 'chart_gdp_nominal.png')

# ========== 图表 2：实际 GDP 4 国柱状图 ==========
def chart_gdp_real():
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(years))
    width = 0.2
    
    us = [v if v else 0 for v in data['gdp_real']['us']]
    cn = [v if v else 0 for v in data['gdp_real']['cn']]
    jp = [v if v else 0 for v in data['gdp_real']['jp']]
    eu = [v if v else 0 for v in data['gdp_real']['eu']]
    
    ax.bar(x - 1.5*width, us, width, label='US', color=COLORS['us'], alpha=0.85)
    ax.bar(x - 0.5*width, cn, width, label='China', color=COLORS['cn'], alpha=0.85)
    ax.bar(x + 0.5*width, jp, width, label='Japan', color=COLORS['jp'], alpha=0.85)
    ax.bar(x + 1.5*width, eu, width, label='Euro Area', color=COLORS['eu'], alpha=0.85)
    
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax.set_ylabel('Real GDP Growth (%)', fontsize=12, fontweight='bold')
    ax.set_title('Real GDP Growth: US, China, Japan, Euro Area (2000-2026)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xticks(x[::2])
    ax.set_xticklabels(years_str[::2], rotation=45, ha='right')
    ax.legend(loc='upper right', framealpha=0.9)
    ax.axhline(y=0, color='black', linewidth=0.5)
    
    ax.axvspan(5.5, 7.5, alpha=0.1, color='red')
    ax.annotate('CN 14%', xy=(7, 14.1), xytext=(7, 16), fontsize=8, color=COLORS['cn'], fontweight='bold', ha='center')
    ax.annotate('US -2.6%', xy=(9, -2.58), xytext=(9, -4), fontsize=8, color=COLORS['us'], fontweight='bold', ha='center')
    
    save_chart(fig, 'chart_gdp_real.png')

# ========== 图表 3：CPI 4 国柱状图 ==========
def chart_cpi():
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(years))
    width = 0.2
    
    us = [v if v else 0 for v in data['cpi']['us']]
    cn = [v if v else 0 for v in data['cpi']['cn']]
    jp = [v if v else 0 for v in data['cpi']['jp']]
    eu = [v if v else 0 for v in data['cpi']['eu']]
    
    ax.bar(x - 1.5*width, us, width, label='US', color=COLORS['us'], alpha=0.85)
    ax.bar(x - 0.5*width, cn, width, label='China', color=COLORS['cn'], alpha=0.85)
    ax.bar(x + 0.5*width, jp, width, label='Japan', color=COLORS['jp'], alpha=0.85)
    ax.bar(x + 1.5*width, eu, width, label='Euro Area', color=COLORS['eu'], alpha=0.85)
    
    ax.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax.set_ylabel('CPI Inflation (%)', fontsize=12, fontweight='bold')
    ax.set_title('CPI Inflation: US, China, Japan, Euro Area (2000-2026)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xticks(x[::2])
    ax.set_xticklabels(years_str[::2], rotation=45, ha='right')
    ax.legend(loc='upper right', framealpha=0.9)
    ax.axhline(y=0, color='black', linewidth=0.5)
    
    # 标注关键事件
    ax.axvspan(8.5, 9.5, alpha=0.1, color='red')
    ax.axvspan(20.5, 21.5, alpha=0.1, color='red')
    ax.axvspan(22.5, 23.5, alpha=0.1, color='red')
    ax.annotate('2008 Crisis', xy=(9, -0.35), xytext=(9, -2), fontsize=7, color='red', ha='center')
    ax.annotate('2020 COVID', xy=(20, 1.23), xytext=(20, 3), fontsize=7, color='red', ha='center')
    ax.annotate('2022 Peak', xy=(22, 8.02), xytext=(22, 9.5), fontsize=7, color='red', ha='center')
    
    save_chart(fig, 'chart_cpi.png')

# ========== 图表 4：货币政策双轴图 ==========
def chart_monetary():
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    cn_rate = [v if v else 0 for v in data['rate']['cn']]
    cn_rrr = [v if v else 0 for v in data['cn_monetary']['rrr']]
    cn_m2 = [v if v else 0 for v in data['cn_monetary']['m2']]
    cn_trade = [v if v else 0 for v in data['trade']['cn']]
    
    # 左轴：利率 + RRR
    l1, = ax1.plot(years, cn_rate, 'o-', color=COLORS['us'], linewidth=2, markersize=4, label='1Y Lending Rate')
    l2, = ax1.plot(years, cn_rrr, 's-', color=COLORS['cn'], linewidth=2, markersize=4, label='RRR')
    ax1.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Policy Rate / RRR (%)', fontsize=12, fontweight='bold', color=COLORS['text'])
    ax1.tick_params(axis='y', labelcolor=COLORS['text'])
    ax1.set_ylim(0, 22)
    
    # 右轴：M2
    ax2 = ax1.twinx()
    l3, = ax2.plot(years, cn_m2, 'D-', color=COLORS['eu'], linewidth=2, markersize=4, label='M2 Growth')
    ax2.set_ylabel('M2 Growth (%)', fontsize=12, fontweight='bold', color=COLORS['eu'])
    ax2.tick_params(axis='y', labelcolor=COLORS['eu'])
    ax2.set_ylim(0, 30)
    
    # 标注
    ax1.axvspan(6.5, 7.5, alpha=0.15, color='red')
    ax1.annotate('Tightening\n2006-2007', xy=(7, 18), fontsize=8, color='red', fontweight='bold', ha='center')
    ax1.annotate('RRR 14.5%', xy=(7, 14.5), xytext=(7.5, 16), fontsize=7, color=COLORS['cn'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['cn'], lw=1))
    ax1.annotate('Rate 7.47%', xy=(7, 7.47), xytext=(7.5, 9), fontsize=7, color=COLORS['us'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['us'], lw=1))
    ax2.annotate('M2 17.5%', xy=(7, 17.5), xytext=(6, 22), fontsize=7, color=COLORS['eu'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['eu'], lw=1))
    
    ax1.set_title('China Monetary Policy: Surface Tightening vs Actual Ease (2000-2026)', fontsize=14, fontweight='bold', pad=15)
    
    lines = [l1, l2, l3]
    ax1.legend(lines, [l.get_label() for l in lines], loc='upper left', framealpha=0.9)
    
    ax1.set_xticks(years[::2])
    ax1.set_xticklabels(years_str[::2], rotation=45, ha='right')
    
    save_chart(fig, 'chart_monetary.png')

# ========== 图表 5：市场利率三面板 ==========
def chart_term_spread():
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    
    countries = [
        ('China', 'cn', COLORS['cn']),
        ('US', 'us', COLORS['us']),
        ('Japan', 'jp', COLORS['jp']),
    ]
    
    for i, (name, code, color) in enumerate(countries):
        ax = axes[i]
        short = data['market_rate'][f'{code}_short']
        long = data['market_rate'][f'{code}_long']
        
        short_plot = [float(v) if v is not None else float('nan') for v in short]
        long_plot = [float(v) if v is not None else float('nan') for v in long]
        
        ax.plot(years, short_plot, '-', color=color, linewidth=2, label=f'{name} Short')
        ax.plot(years, long_plot, '--', color=color, linewidth=2, alpha=0.7, label=f'{name} Long')
        ax.fill_between(years, short_plot, long_plot, alpha=0.1, color=color)
        
        ax.set_ylabel('Rate (%)', fontsize=10, fontweight='bold')
        ax.set_title(f'{name} Market Rates', fontsize=11, fontweight='bold', loc='left')
        ax.legend(loc='upper right', fontsize=8, framealpha=0.9)
        ax.set_ylim(-1 if code == 'jp' else 0, 7)
    
    axes[2].set_xlabel('Year', fontsize=12, fontweight='bold')
    axes[2].set_xticks(years[::2])
    axes[2].set_xticklabels(years_str[::2], rotation=45, ha='right')
    
    # 标注
    for ax in axes:
        ax.axvline(x=2008, color='red', linewidth=1, linestyle='--', alpha=0.5)
        ax.axvline(x=2020, color='red', linewidth=1, linestyle='--', alpha=0.5)
    
    fig.suptitle('Short-term vs Long-term Market Rates (2000-2026)', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    
    save_chart(fig, 'chart_term_spread.png')

# ========== 图表 6：汇率与贸易 ==========
def chart_fx_trade():
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [1, 1.2]})
    
    # 上面板：汇率
    ax1 = axes[0]
    eurusd = data['fx']['eurusd']
    usdcny = data['fx']['usdcny']
    usdjpy = [v/100 if v else None for v in data['fx']['usdjpy']]
    
    ax1.plot(years, eurusd, '-', color=COLORS['us'], linewidth=2, label='EUR/USD')
    ax1.plot(years, usdcny, '-', color=COLORS['cn'], linewidth=2, label='USD/CNY')
    ax1.plot(years, usdjpy, '--', color=COLORS['jp'], linewidth=2, alpha=0.7, label='USD/JPY (÷100)')
    ax1.set_ylabel('Exchange Rate', fontsize=10, fontweight='bold')
    ax1.set_title('Exchange Rates', fontsize=11, fontweight='bold', loc='left')
    ax1.legend(loc='upper right', fontsize=8, framealpha=0.9)
    ax1.axvline(x=2005, color='red', linewidth=1, linestyle=':', alpha=0.7)
    ax1.annotate('2005\nReform', xy=(2005, 8.28), fontsize=7, color='red', ha='center', va='bottom')
    
    # 下面板：贸易差额
    ax2 = axes[1]
    cn_trade = [v if v else 0 for v in data['trade']['cn']]
    us_trade = [v if v else 0 for v in data['trade']['us']]
    
    ax2.bar(np.array(years) - 0.2, cn_trade, 0.4, label='China Surplus', color=COLORS['cn'], alpha=0.7)
    ax2.bar(np.array(years) + 0.2, us_trade, 0.4, label='US Deficit', color=COLORS['us'], alpha=0.7)
    ax2.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Trade Balance (100M USD)', fontsize=10, fontweight='bold')
    ax2.set_title('Trade Balance', fontsize=11, fontweight='bold', loc='left')
    ax2.legend(loc='upper right', fontsize=8, framealpha=0.9)
    ax2.axhline(y=0, color='black', linewidth=0.5)
    ax2.annotate('CN +2639', xy=(2007, 2639), xytext=(2009, 2800), fontsize=7, color=COLORS['cn'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['cn'], lw=1))
    ax2.annotate('US -592', xy=(2007, -592), xytext=(2009, -700), fontsize=7, color=COLORS['us'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['us'], lw=1))
    
    for ax in axes:
        ax.set_xticks(years[::2])
        ax.set_xticklabels(years_str[::2], rotation=45, ha='right')
    
    fig.suptitle('Exchange Rates & Trade Balance (2000-2026)', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    
    save_chart(fig, 'chart_fx_trade.png')

# ========== 图表 7：外汇储备/GDP ==========
def chart_forex_reserve():
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    # 计算外储/GDP比率
    def calc_ratio(forex_arr, gdp_arr):
        result = []
        last_gdp = None
        for f, g in zip(forex_arr, gdp_arr):
            if g: last_gdp = g
            if f and last_gdp and last_gdp > 0:
                result.append(f / last_gdp * 100)
            else:
                result.append(None)
        return result
    
    cn_ratio = calc_ratio(data['forex']['cn'], data['gdp_usd']['cn'])
    us_ratio = calc_ratio(data['forex']['us'], data['gdp_usd']['us'])
    jp_ratio = calc_ratio(data['forex']['jp'], data['gdp_usd']['jp'])
    
    l1, = ax1.plot(years, cn_ratio, 'o-', color=COLORS['cn'], linewidth=2.5, markersize=5, label='China')
    l2, = ax1.plot(years, us_ratio, 's--', color=COLORS['us'], linewidth=2, markersize=4, label='US')
    l3, = ax1.plot(years, jp_ratio, '^-.', color=COLORS['jp'], linewidth=2, markersize=4, label='Japan')
    
    ax1.set_xlabel('Year', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Forex Reserves / GDP (%)', fontsize=12, fontweight='bold')
    ax1.set_title('Foreign Exchange Reserves as % of GDP (2000-2026)', fontsize=14, fontweight='bold', pad=15)
    ax1.legend(loc='upper left', framealpha=0.9)
    ax1.set_ylim(0, 55)
    
    # 标注
    ax1.annotate('Peak 49%', xy=(2014, 49), xytext=(2016, 52), fontsize=9, color=COLORS['cn'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['cn'], lw=1.5))
    ax1.annotate('Trough 28%', xy=(2016, 28), xytext=(2018, 25), fontsize=9, color=COLORS['cn'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=COLORS['cn'], lw=1.5))
    ax1.annotate('CN 37%', xy=(2007, 37), xytext=(2003, 40), fontsize=8, color=COLORS['cn'], fontweight='bold')
    ax1.annotate('JP 20%', xy=(2007, 19.8), xytext=(2003, 22), fontsize=8, color=COLORS['jp'], fontweight='bold')
    ax1.annotate('US 0.3%', xy=(2007, 0.3), xytext=(2003, 5), fontsize=8, color=COLORS['us'], fontweight='bold')
    
    ax1.axvline(x=2005, color='red', linewidth=1, linestyle=':', alpha=0.5)
    ax1.axvline(x=2014, color='red', linewidth=1, linestyle='--', alpha=0.5)
    ax1.axvline(x=2015, color='red', linewidth=1, linestyle=':', alpha=0.5)
    
    ax1.set_xticks(years[::2])
    ax1.set_xticklabels(years_str[::2], rotation=45, ha='right')
    
    save_chart(fig, 'chart_forex_reserve.png')

# ========== 图表 8：不可能三角 ==========
def chart_impossible_trinity():
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')
    
    # 三角形
    triangle = plt.Polygon([(50, 90), (10, 15), (90, 15)], fill=False, 
                           edgecolor=COLORS['gray'], linewidth=3, linestyle='-')
    ax.add_patch(triangle)
    
    # 填充
    triangle_fill = plt.Polygon([(50, 90), (10, 15), (90, 15)], 
                                facecolor=COLORS['grid'], alpha=0.2, edgecolor='none')
    ax.add_patch(triangle_fill)
    
    # 三个顶点
    ax.plot(50, 90, 'o', color=COLORS['cn'], markersize=25, markeredgecolor='white', markeredgewidth=2, zorder=5)
    ax.text(50, 93, 'Fixed\nExchange Rate', ha='center', fontsize=12, fontweight='bold', color=COLORS['text'])
    
    ax.plot(10, 15, 'o', color=COLORS['us'], markersize=25, markeredgecolor='white', markeredgewidth=2, zorder=5)
    ax.text(10, 8, 'Free Capital\nFlow', ha='center', fontsize=12, fontweight='bold', color=COLORS['text'])
    
    ax.plot(90, 15, 'o', color=COLORS['jp'], markersize=25, markeredgecolor='white', markeredgewidth=2, zorder=5)
    ax.text(90, 8, 'Independent\nMonetary Policy', ha='center', fontsize=12, fontweight='bold', color=COLORS['text'])
    
    # 三种组合
    ax.text(25, 50, 'B: Fixed +管制\nSacrifice\nMonetary Policy', ha='center', fontsize=9, 
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=COLORS['gray'], alpha=0.9))
    ax.text(75, 50, 'C: Float + Free\nSacrifice\nFixed Rate', ha='center', fontsize=9,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=COLORS['gray'], alpha=0.9))
    ax.text(50, 25, 'A: Fixed + Free\nSacrifice\nMonetary Policy', ha='center', fontsize=9,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=COLORS['gray'], alpha=0.9))
    
    # 中国 05-07 位置
    ax.plot(28, 55, 'o', color=COLORS['cn'], markersize=18, markeredgecolor='white', markeredgewidth=2, zorder=6)
    ax.text(28, 55, 'CN\n05-07', ha='center', va='center', fontsize=8, fontweight='bold', color='white', zorder=7)
    
    # 中国现在位置
    ax.plot(45, 45, 'o', color='#f97316', markersize=18, markeredgecolor='white', markeredgewidth=2, zorder=6)
    ax.text(45, 45, 'CN\nNow', ha='center', va='center', fontsize=8, fontweight='bold', color='white', zorder=7)
    
    # 美国位置
    ax.plot(75, 25, 'o', color=COLORS['us'], markersize=18, markeredgecolor='white', markeredgewidth=2, zorder=6)
    ax.text(75, 25, 'US', ha='center', va='center', fontsize=8, fontweight='bold', color='white', zorder=7)
    
    # 移动箭头
    ax.annotate('', xy=(42, 47), xytext=(31, 53),
               arrowprops=dict(arrowstyle='->', color=COLORS['cn'], lw=2, linestyle='dashed'))
    ax.text(35, 52, 'Move', fontsize=8, color=COLORS['cn'], fontweight='bold', rotation=-30)
    
    # 图例
    ax.plot(5, 95, 'o', color=COLORS['cn'], markersize=8)
    ax.text(8, 95, 'China 05-07 (B)', fontsize=9, va='center')
    ax.plot(5, 90, 'o', color='#f97316', markersize=8)
    ax.text(8, 90, 'China Now (→C)', fontsize=9, va='center')
    ax.plot(5, 85, 'o', color=COLORS['us'], markersize=8)
    ax.text(8, 85, 'US (C)', fontsize=9, va='center')
    
    ax.set_title('Mundell-Fleming Impossible Trinity', fontsize=16, fontweight='bold', pad=20)
    
    save_chart(fig, 'chart_impossible_trinity.png')

# ========== 主函数 ==========
if __name__ == '__main__':
    print('Generating macro charts...')
    chart_gdp_nominal()
    chart_gdp_real()
    chart_cpi()
    chart_monetary()
    chart_term_spread()
    chart_fx_trade()
    chart_forex_reserve()
    chart_impossible_trinity()
    print('\nDone! All charts saved to charts/')
