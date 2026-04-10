# Wiki 引用追踪系统使用指南

## 📋 概述

基于 Karpathy LLM Wiki 原则构建的完整双向引用追踪系统，能够准确定位：
1. **这个页面引用了哪些页面？**（出站链接）
2. **哪些页面引用了这个页面？**（入站链接）
3. **引用发生在哪个章节？**（章节级粒度）

---

## 🛠️ 命令

### 1. `wiki build-index` - 构建引用索引

**功能**：扫描所有 wiki 页面，构建引用关系数据库

**用法**：
```bash
./llmwikify.py build-index
```

**输出**：
- `wiki/reference_index.json` - 引用关系数据库
- 包含所有页面的入站/出站链接
- 支持章节级引用（锚点）

**执行时机**：
- 首次使用时
- 批量修改页面后
- 定期维护（建议每周）

---

### 2. `wiki references <page>` - 查询页面引用

**功能**：显示指定页面的完整引用关系

**用法**：
```bash
./llmwikify.py references "Page Name"
```

**输出**：
- 📤 Outbound links：该页面引用了哪些页面
- 📥 Inbound links：哪些页面引用了该页面
- 📊 Summary：引用统计

**示例**：
```bash
# 查询公司页面
./llmwikify.py references "Agnico Eagle"

# 查询行业页面
./llmwikify.py references "Market Overview"

# 查询索引中的页面名
./llmwikify.py references "gold-industry-news"
```

---

## 📊 数据格式

### reference_index.json 结构

```json
{
  "built_at": "2026-04-09T18:00:00",
  "total_pages": 157,
  "outbound_links": {
    "page-name": [
      {
        "target": "target-page",
        "section": "#section-name",
        "display": "Display Text"
      }
    ]
  },
  "inbound_links": {
    "page-name": [
      {
        "source": "source-page",
        "section": "#section-name",
        "file": "path/to/file.md"
      }
    ]
  }
}
```

---

## 🎯 功能特性

### ✅ 已实现

1. **双向引用追踪**
   - 入站链接（谁引用了它）
   - 出站链接（它引用了谁）

2. **章节级粒度**
   - 支持 `[[page#section|text]]` 格式
   - 准确定位引用位置

3. **自动维护**
   - `build-index` 自动扫描所有页面
   - 无需手动更新引用关系

4. **CLI 查询**
   - 快速查询任意页面的引用
   - 支持模糊匹配

5. **用户可见**
   - 重定向页面显示"被引用自"
   - 公司页面显示"被以下页面引用"

---

## 📝 页面标注

### 重定向页面

```markdown
# Page Name.md

> **被引用自** (Top 5):
> - [[index|index]]
> - [[Industry News|Industry News]]

[Go to page →](actual-page.md)
```

### 公司页面

```markdown
# companies/company.md

## 📥 被以下页面引用

> *最后更新：2026-04-09*

### 行业
- [[Gold Industry News]]

### 分析
- [[Market Overview]]

*共 X 个页面引用了本页*
```

---

## 🔍 使用场景

### 场景 1：追踪公司新闻来源

```bash
# 查询哪些页面引用了某公司
./llmwikify.py references "First Quantum"

# 输出显示：
# - 行业页面引用
# - 分析页面引用
# - 索引页面引用
```

### 场景 2：分析引用网络

```bash
# 构建最新索引
./llmwikify.py build-index

# 查询热门页面（被引用最多）
python3 -c "
import json
data = json.load(open('wiki/reference_index.json'))
top = sorted(data['inbound_links'].items(), 
             key=lambda x: len(x[1]), 
             reverse=True)[:10]
for page, refs in top:
    print(f'{page}: {len(refs)} refs')
"
```

### 场景 3：维护引用健康

```bash
# 检查孤立页面
./llmwikify.py lint | grep orphan_page

# 检查断裂链接
./llmwikify.py lint | grep broken_link

# 查询特定页面的引用完整性
./llmwikify.py references "Page Name"
```

---

## 📊 统计数据

截至 2026-04-09：

| 指标 | 数值 |
|------|------|
| 总页面数 | 157 |
| 有出站链接的页面 | 126 |
| 有入站链接的页面 | 71 |
| 总引用数 | 636 |
| 被引用最多的页面 | Market Overview (97 次) |

---

## 🚀 未来改进

### Phase 6: 自动化维护

- [ ] ingest 新新闻时自动更新引用索引
- [ ] 检测并报告断裂的引用
- [ ] 建议新的交叉引用

### Phase 7: 可视化

- [ ] 生成引用关系图（graphviz）
- [ ] Obsidian Graph 视图集成
- [ ] 交互式引用网络图

### Phase 8: 智能推荐

- [ ] 基于内容推荐新链接
- [ ] 检测缺失的页面
- [ ] 建议合并相似页面

---

## 📚 参考

- [Karpathy LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md)
- [Wiki.py Usage Guide](wiki_quick_reference.md)
- [WIKI.md Configuration](../WIKI.md)
