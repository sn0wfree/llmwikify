"""从 ifind EDB 拉取 4 国名义GDP level数据，计算 YoY 增长率"""
import json, os, sys, time

os.chdir(os.path.expanduser('~/.agents/skills/ifind'))
sys.path.insert(0, '.')
from call import call

OUT_DIR = os.path.expanduser('~/llmwikify/TopicResearch/data/raw')
os.makedirs(OUT_DIR, exist_ok=True)

# 查询语句（level数据）
LEVEL_QUERIES = [
    ("美国名义GDP（200001-202612）", "ifind_us_gdp_nominal.json"),
    ("中国名义GDP（200001-202612）", "ifind_cn_gdp_nominal.json"),
    ("日本GDP（200001-202612）", "ifind_jp_gdp_nominal.json"),
    ("欧元区国内生产总值（200001-202612）", "ifind_eu_gdp_nominal.json"),
]

def calc_yoy_growth(datas):
    """从level数据计算YoY增长率"""
    datas.sort(key=lambda x: x[0])
    result = []
    for i, d in enumerate(datas):
        yr = int(d[0][:4])
        if i > 0 and datas[i-1][1] and datas[i-1][1] > 0:
            growth = (d[1] - datas[i-1][1]) / datas[i-1][1] * 100
            result.append({'date': d[0], 'value': round(growth, 2)})
        else:
            result.append({'date': d[0], 'value': None})
    return result

for query, fname in LEVEL_QUERIES:
    print(f"  {fname}: ", end="", flush=True)
    r = call("edb", "get_edb_data", {"query": query})
    if not r["ok"]:
        print(f"FAIL {r.get('error','')}")
        continue
    try:
        content = r["data"]["result"]["content"][0]["text"]
        inner = json.loads(content)
        datas = inner["data"]["datas"][0]["data"]["data"]
        # 计算YoY增长率
        result = calc_yoy_growth(datas)
        with open(os.path.join(OUT_DIR, fname), "w") as f:
            json.dump(result, f, indent=2)
        print(f"OK {len(result)} rows")
    except Exception as e:
        print(f"ERR {e}")
    time.sleep(1.5)

print("Done")
