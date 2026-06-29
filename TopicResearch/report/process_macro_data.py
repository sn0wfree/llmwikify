"""
处理 ifind 拉取的 4 国宏观数据 → 年度化 → chart_data_extended.js
"""
import json
import os

DATA_DIR = os.path.expanduser("~/llmwikify/TopicResearch/data/raw")
OUT_JS = os.path.expanduser("~/llmwikify/TopicResearch/slides/chart_data_extended.js")
OUT_JSON = os.path.expanduser("~/llmwikify/TopicResearch/data/raw/macro_4country_2000_2026.json")

YEARS = list(range(2000, 2027))


def load_json(fname):
    with open(os.path.join(DATA_DIR, fname)) as f:
        return json.load(f)


def to_annual_avg(data, years=YEARS):
    """月度/日度数据 → 年度均值"""
    result = {}
    for d in data:
        yr = int(d["date"][:4])
        if yr in years:
            result.setdefault(yr, []).append(d["value"])
    return {yr: round(sum(vals) / len(vals), 2) if vals else None for yr, vals in result.items()}


def to_annual_yearend(data, years=YEARS):
    """日度数据 → 年末最后值"""
    result = {}
    for d in data:
        yr = int(d["date"][:4])
        if yr in years:
            result[yr] = d["value"]  # 覆盖，最后一条即年末
    return {yr: result.get(yr) for yr in years}


def to_annual_avg_quarterly(data, years=YEARS):
    """季度数据 → 年度均值"""
    return to_annual_avg(data, years)


def detect_frequency(data):
    """自动检测数据频率：annual / quarterly / monthly"""
    dates = [d["date"] for d in data if d.get("date")]
    if len(dates) < 2:
        return "annual"
    # 检查日期格式：YYYY-12-31 = 年度，YYYY-MM-30 = 季度，其他 = 月度
    d0 = dates[0]
    # 统计不同年份的数量 vs 总记录数
    years_seen = set()
    for d in data:
        yr = d["date"][:4]
        years_seen.add(yr)
    year_count = len(years_seen)
    total_count = len(data)
    if total_count <= year_count * 2:
        return "annual"  # 每年最多 2 条记录 = 年度
    elif total_count <= year_count * 5:
        return "quarterly"  # 每年 3-5 条 = 季度
    else:
        return "monthly"  # 每年 >12 条 = 月度


def to_annual_auto(data, years=YEARS):
    """自动检测频率并转换为年度值"""
    freq = detect_frequency(data)
    if freq == "annual":
        # 直接取，无需平均
        result = {}
        for d in data:
            yr = int(d["date"][:4])
            if yr in years:
                result[yr] = d["value"]
        return {yr: result.get(yr) for yr in years}
    elif freq == "quarterly":
        # 季度数据：先按年分组，再求均值
        return to_annual_avg(data, years)
    else:
        # 月度数据：直接求均值
        return to_annual_avg(data, years)


def merge_rate_with_lpr(old_rate_data, lpr_data, years=YEARS, lpr_start_year=2019):
    """合并旧贷款基准利率与LPR：2019年前用旧利率，2019年后用LPR"""
    old_annual = to_annual_yearend(old_rate_data, years)
    lpr_annual = to_annual_avg(lpr_data, years)
    result = {}
    for y in years:
        if y >= lpr_start_year and lpr_annual.get(y) is not None:
            result[y] = lpr_annual[y]
        else:
            result[y] = old_annual.get(y)
    return result


# === 加载数据 ===
# 名义GDP（from fetch_nominal_gdp.py）
us_gdp_nom = load_json("ifind_us_gdp_nominal.json")
cn_gdp_nom = load_json("ifind_cn_gdp_nominal.json")
jp_gdp_nom = load_json("ifind_jp_gdp_nominal.json")
eu_gdp_nom = load_json("ifind_eu_gdp_nominal.json")

# 实际GDP（from fetch_real_gdp.py）
us_gdp_real = load_json("ifind_us_gdp_real.json")
cn_gdp_real = load_json("ifind_cn_gdp_real.json")
jp_gdp_real = load_json("ifind_jp_gdp_real.json")
eu_gdp_real = load_json("ifind_eu_gdp_real.json")

# 中国货币政策指标
cn_rrr = load_json("ifind_cn_rrr.json")
cn_m2 = load_json("ifind_cn_m2_yearly.json")
cn_trade = load_json("ifind_cn_trade_surplus.json")
cn_lpr = load_json("ifind_cn_lpr.json")

# 短端/长端市场利率
cn_short = load_json("ifind_cn_short_rate.json")
cn_long = load_json("ifind_cn_long_rate.json")
us_short = load_json("ifind_us_short_rate.json")
us_long = load_json("ifind_us_long_rate.json")
jp_short = load_json("ifind_jp_short_rate.json")
jp_long = load_json("ifind_jp_long_rate.json")

# 贸易数据
us_trade = load_json("ifind_us_trade.json")
eu_trade = load_json("ifind_eu_trade.json")
jp_trade = load_json("ifind_jp_trade.json")

# 美元指数和外汇储备
dxy = load_json("ifind_dxy.json")
cn_forex = load_json("ifind_cn_forex.json")
us_forex = load_json("ifind_us_forex.json")
jp_forex = load_json("ifind_jp_forex.json")
cn_gdp_usd = load_json("ifind_cn_gdp_usd.json")
us_gdp_usd = load_json("ifind_us_gdp_usd.json")
jp_gdp_usd = load_json("ifind_jp_gdp_usd.json")

us_cpi = load_json("ifind_us_cpi.json")
cn_cpi = load_json("ifind_cn_cpi.json")
jp_cpi = load_json("ifind_jp_cpi.json")
eu_cpi = load_json("ifind_eu_cpi.json")

us_rate = load_json("ifind_us_rate.json")
cn_rate = load_json("ifind_cn_loan_rate.json")
jp_rate = load_json("ifind_jp_rate.json")
eu_rate = load_json("ifind_eu_rate.json")

eurusd = load_json("ifind_eurusd.json")
usdjpy = load_json("ifind_usdjpy.json")
usdcny = load_json("ifind_usdcny.json")

# === 年度化处理 ===
macro = {
    "years": [str(y) for y in YEARS],
    "gdp_nom": {
        "us": [to_annual_auto(us_gdp_nom).get(y) for y in YEARS],
        "cn": [to_annual_auto(cn_gdp_nom).get(y) for y in YEARS],
        "jp": [to_annual_auto(jp_gdp_nom).get(y) for y in YEARS],
        "eu": [to_annual_auto(eu_gdp_nom).get(y) for y in YEARS],
    },
    "gdp_real": {
        "us": [to_annual_auto(us_gdp_real).get(y) for y in YEARS],
        "cn": [to_annual_auto(cn_gdp_real).get(y) for y in YEARS],
        "jp": [to_annual_auto(jp_gdp_real).get(y) for y in YEARS],
        "eu": [to_annual_auto(eu_gdp_real).get(y) for y in YEARS],
    },
    "cpi": {
        "us": [to_annual_avg(us_cpi).get(y) for y in YEARS],
        "cn": [to_annual_avg(cn_cpi).get(y) for y in YEARS],
        "jp": [to_annual_avg(jp_cpi).get(y) for y in YEARS],
        "eu": [to_annual_avg(eu_cpi).get(y) for y in YEARS],
    },
    "cn_monetary": {
        "rrr": [to_annual_yearend(cn_rrr).get(y) for y in YEARS],
        "m2": [to_annual_avg(cn_m2).get(y) for y in YEARS],
        "lpr": [to_annual_avg(cn_lpr).get(y) for y in YEARS],
    },
    "market_rate": {
        "cn_short": [to_annual_avg(cn_short).get(y) for y in YEARS],
        "cn_long": [to_annual_avg(cn_long).get(y) for y in YEARS],
        "us_short": [to_annual_avg(us_short).get(y) for y in YEARS],
        "us_long": [to_annual_avg(us_long).get(y) for y in YEARS],
        "jp_short": [to_annual_avg(jp_short).get(y) for y in YEARS],
        "jp_long": [to_annual_avg(jp_long).get(y) for y in YEARS],
    },
    "trade": {
        "cn": [to_annual_avg(cn_trade).get(y) for y in YEARS],
        "us": [to_annual_avg(us_trade).get(y) for y in YEARS],
        "eu": [to_annual_avg(eu_trade).get(y) for y in YEARS],
        "jp": [to_annual_avg(jp_trade).get(y) for y in YEARS],
    },
    "dxy": [to_annual_avg(dxy).get(y) for y in YEARS],
    "forex": {
        "cn": [to_annual_avg(cn_forex).get(y) for y in YEARS],
        "us": [to_annual_avg(us_forex).get(y) for y in YEARS],
        "jp": [to_annual_avg(jp_forex).get(y) for y in YEARS],
    },
    "gdp_usd": {
        "cn": [to_annual_avg(cn_gdp_usd).get(y) for y in YEARS],
        "us": [to_annual_avg(us_gdp_usd).get(y) for y in YEARS],
        "jp": [to_annual_avg(jp_gdp_usd).get(y) for y in YEARS],
    },
    "rate": {
        "us": [to_annual_yearend(us_rate).get(y) for y in YEARS],
        "cn": [merge_rate_with_lpr(cn_rate, cn_lpr).get(y) for y in YEARS],
        "jp": [to_annual_yearend(jp_rate).get(y) for y in YEARS],
        "eu": [to_annual_yearend(eu_rate).get(y) for y in YEARS],
    },
    "fx": {
        "eurusd": [to_annual_avg(eurusd).get(y) for y in YEARS],
        "usdjpy": [to_annual_avg(usdjpy).get(y) for y in YEARS],
        "usdcny": [to_annual_avg(usdcny).get(y) for y in YEARS],
    },
}

# === 保存 JSON ===
with open(OUT_JSON, "w") as f:
    json.dump(macro, f, indent=2, ensure_ascii=False)
print(f"✅ JSON: {OUT_JSON}")

# === 生成 JS ===
js_lines = [
    "// 4 国宏观数据 2000-2026（ifind EDB）",
    "// 用途：图表1 GDP/CPI/利率/汇率 4面板",
    f"var macroYears = {json.dumps(macro['years'])};",
    "",
    "// 名义GDP 增速 (%)",
    f"var macroGDP_US = {json.dumps(macro['gdp_nom']['us'])};",
    f"var macroGDP_CN = {json.dumps(macro['gdp_nom']['cn'])};",
    f"var macroGDP_JP = {json.dumps(macro['gdp_nom']['jp'])};",
    f"var macroGDP_EU = {json.dumps(macro['gdp_nom']['eu'])};",
    "",
    "// 实际GDP 增速 (%)",
    f"var macroGDPReal_US = {json.dumps(macro['gdp_real']['us'])};",
    f"var macroGDPReal_CN = {json.dumps(macro['gdp_real']['cn'])};",
    f"var macroGDPReal_JP = {json.dumps(macro['gdp_real']['jp'])};",
    f"var macroGDPReal_EU = {json.dumps(macro['gdp_real']['eu'])};",
    "",
    "// CPI 通胀 (%)",
    f"var macroCPI_US = {json.dumps(macro['cpi']['us'])};",
    f"var macroCPI_CN = {json.dumps(macro['cpi']['cn'])};",
    f"var macroCPI_JP = {json.dumps(macro['cpi']['jp'])};",
    f"var macroCPI_EU = {json.dumps(macro['cpi']['eu'])};",
    "",
    "// 政策利率 (%)",
    f"var macroRate_US = {json.dumps(macro['rate']['us'])};",
    f"var macroRate_CN = {json.dumps(macro['rate']['cn'])};",
    f"var macroRate_JP = {json.dumps(macro['rate']['jp'])};",
    f"var macroRate_EU = {json.dumps(macro['rate']['eu'])};",
    "",
    "// 汇率",
    f"var macroFX_EURUSD = {json.dumps(macro['fx']['eurusd'])};",
    f"var macroFX_USDJPY = {json.dumps(macro['fx']['usdjpy'])};",
    f"var macroFX_USDCNY = {json.dumps(macro['fx']['usdcny'])};",
    "",
    "// 中国货币政策指标",
    f"var macroRRR_CN = {json.dumps(macro['cn_monetary']['rrr'])};",
    f"var macroM2_CN = {json.dumps(macro['cn_monetary']['m2'])};",
    f"var macroLPR_CN = {json.dumps(macro['cn_monetary']['lpr'])};",
    "",
    "// 短端/长端市场利率 (%)",
    f"var macroShort_CN = {json.dumps(macro['market_rate']['cn_short'])};",
    f"var macroLong_CN = {json.dumps(macro['market_rate']['cn_long'])};",
    f"var macroShort_US = {json.dumps(macro['market_rate']['us_short'])};",
    f"var macroLong_US = {json.dumps(macro['market_rate']['us_long'])};",
    f"var macroShort_JP = {json.dumps(macro['market_rate']['jp_short'])};",
    f"var macroLong_JP = {json.dumps(macro['market_rate']['jp_long'])};",
    "",
    "// 贸易差额 (亿美元)",
    f"var macroTrade_CN = {json.dumps(macro['trade']['cn'])};",
    f"var macroTrade_US = {json.dumps(macro['trade']['us'])};",
    f"var macroTrade_EU = {json.dumps(macro['trade']['eu'])};",
    f"var macroTrade_JP = {json.dumps(macro['trade']['jp'])};",
    "",
    "// 美元指数与外汇储备",
    f"var macroDXY = {json.dumps(macro['dxy'])};",
    f"var macroForex_CN = {json.dumps(macro['forex']['cn'])};",
    f"var macroForex_US = {json.dumps(macro['forex']['us'])};",
    f"var macroForex_JP = {json.dumps(macro['forex']['jp'])};",
    f"var macroGDP_USD_CN = {json.dumps(macro['gdp_usd']['cn'])};",
    f"var macroGDP_USD_US = {json.dumps(macro['gdp_usd']['us'])};",
    f"var macroGDP_USD_JP = {json.dumps(macro['gdp_usd']['jp'])};",
]

with open(OUT_JS, "w") as f:
    f.write("\n".join(js_lines) + "\n")
print(f"✅ JS: {OUT_JS}")

# === 打印摘要 ===
print("\n=== 数据摘要 ===")
for panel, labels in [
    ("gdp_nom", ["us", "cn", "jp", "eu"]),
    ("gdp_real", ["us", "cn", "jp", "eu"]),
    ("cpi", ["us", "cn", "jp", "eu"]),
    ("rate", ["us", "cn", "jp", "eu"]),
]:
    print(f"\n{panel}:")
    for label in labels:
        vals = macro[panel][label]
        valid = [v for v in vals if v is not None]
        if valid:
            print(f"  {label.upper()}: {min(valid):.1f} ~ {max(valid):.1f} ({len(valid)} years)")
        else:
            print(f"  {label.upper()}: no data")

print(f"\nFX:")
for pair in ["eurusd", "usdjpy", "usdcny"]:
    vals = macro["fx"][pair]
    valid = [v for v in vals if v is not None]
    if valid:
        print(f"  {pair.upper()}: {min(valid):.2f} ~ {max(valid):.2f} ({len(valid)} years)")
