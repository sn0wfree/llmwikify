"""获取4国实际GDP数据并处理为年度YoY"""
import json, os, sys

os.chdir(os.path.expanduser('~/.agents/skills/ifind'))
sys.path.insert(0, '.')
from call import call

OUT_DIR = os.path.expanduser('~/llmwikify/TopicResearch/data/raw')

def get_level_and_calc_yoy(query):
    """获取level数据并计算YoY"""
    r = call('edb', 'get_edb_data', {'query': query})
    content = r['data']['result']['content'][0]['text']
    inner = json.loads(content)
    datas = inner['data']['datas'][0]['data']['data']
    datas.sort(key=lambda x: x[0])
    result = []
    for i, d in enumerate(datas):
        if i > 0 and datas[i-1][1] and datas[i-1][1] > 0:
            growth = (d[1] - datas[i-1][1]) / datas[i-1][1] * 100
            result.append({'date': d[0], 'value': round(growth, 2)})
        else:
            result.append({'date': d[0], 'value': None})
    return result

# US: 使用增长率数据（已经是年度YoY）
r = call('edb', 'get_edb_data', {'query': '美国GDP同比增速（200001-202612）'})
content = r['data']['result']['content'][0]['text']
inner = json.loads(content)
datas = inner['data']['datas'][0]['data']['data']
us_result = [{'date': d[0], 'value': d[1]} for d in datas]
with open(os.path.join(OUT_DIR, 'ifind_us_gdp_real.json'), 'w') as f:
    json.dump(us_result, f, indent=2)
print(f'✅ US: {len(us_result)} rows')

# CN: 使用level数据计算YoY
cn_result = get_level_and_calc_yoy('中国国内生产总值（200001-202612）')
with open(os.path.join(OUT_DIR, 'ifind_cn_gdp_real.json'), 'w') as f:
    json.dump(cn_result, f, indent=2)
print(f'✅ CN: {len(cn_result)} rows')

# JP: 使用level数据计算YoY
jp_result = get_level_and_calc_yoy('日本实际GDP（200001-202612）')
with open(os.path.join(OUT_DIR, 'ifind_jp_gdp_real.json'), 'w') as f:
    json.dump(jp_result, f, indent=2)
print(f'✅ JP: {len(jp_result)} rows')

# EU: 使用增长率数据（已经是年度YoY）
r = call('edb', 'get_edb_data', {'query': '欧元区GDP同比增速（200001-202612）'})
content = r['data']['result']['content'][0]['text']
inner = json.loads(content)
datas = inner['data']['datas'][0]['data']['data']
eu_result = [{'date': d[0], 'value': d[1]} for d in datas]
with open(os.path.join(OUT_DIR, 'ifind_eu_gdp_real.json'), 'w') as f:
    json.dump(eu_result, f, indent=2)
print(f'✅ EU: {len(eu_result)} rows')

print('Done')
