"""从 ifind EDB 拉取 4 国宏观数据（2000-2026）"""
import json, os, sys, time

# 必须在 ifind 目录下运行
os.chdir(os.path.expanduser('~/.agents/skills/ifind'))
sys.path.insert(0, '.')

from call import call

OUT_DIR = os.path.expanduser('~/llmwikify/TopicResearch/data/raw')
os.makedirs(OUT_DIR, exist_ok=True)

INDICATORS = [
    ("美国GDP同比增速（200001-202612）", "ifind_us_gdp.json"),
    ("中国GDP同比增速（200001-202612）", "ifind_cn_gdp.json"),
    ("日本GDP同比增速（200001-202612）", "ifind_jp_gdp.json"),
    ("欧元区GDP同比增速（200001-202612）", "ifind_eu_gdp.json"),
    ("美国CPI同比（200001-202612）", "ifind_us_cpi.json"),
    ("中国CPI同比（200001-202612）", "ifind_cn_cpi.json"),
    ("日本CPI同比（200001-202612）", "ifind_jp_cpi.json"),
    ("欧元区CPI同比（200001-202612）", "ifind_eu_cpi.json"),
    ("美国联邦基金利率（200001-202612）", "ifind_us_rate.json"),
    ("中国1年期贷款基准利率（200001-202612）", "ifind_cn_loan_rate.json"),
    ("日本央行政策利率（200001-202612）", "ifind_jp_rate.json"),
    ("欧洲央行主要再融资利率（200001-202612）", "ifind_eu_rate.json"),
    ("美元兑欧元汇率（200001-202612）", "ifind_eurusd.json"),
    ("美元兑日元汇率（200001-202612）", "ifind_usdjpy.json"),
    ("美元兑人民币汇率（200001-202612）", "ifind_usdcny.json"),
]

for query, fname in INDICATORS:
    print(f"  {fname}: ", end="", flush=True)
    r = call("edb", "get_edb_data", {"query": query})
    if not r["ok"]:
        print(f"FAIL {r.get('error','')}")
        continue
    try:
        content = r["data"]["result"]["content"][0]["text"]
        inner = json.loads(content)
        datas = inner["data"]["datas"][0]["data"]["data"]
        result = [{"date": d[0], "value": d[1]} for d in datas]
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            json.dump(result, f, indent=2)
        print(f"OK {len(result)} rows")
    except Exception as e:
        print(f"ERR {e}")
    time.sleep(1.5)

print("Done")
