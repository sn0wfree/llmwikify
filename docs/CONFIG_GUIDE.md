# Wiki 配置指南

> llmwikify 是一个通用的 LLM-Wiki 工具，通过配置文件适配不同领域的使用场景。

**当前版本**: v0.12.6

---

## 📋 配置方式

### 方式 1：`.wiki-config.yaml`（推荐）

在项目根目录创建 `.wiki-config.yaml` 文件：

```yaml
# 孤立页面排除配置
orphan_detection:
  # 正则表达式匹配页面名
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # 日期格式：2025-07-31
    - '^meeting-.*'          # Meeting notes

  # Frontmatter 标记
  exclude_frontmatter:
    - 'redirect_to'          # 重定向页面
    - 'template: true'       # 模板页面

  # 归档目录
  archive_directories:
    - 'archive'              # 归档
    - 'logs'                 # 日志
```

### 方式 2：Python API 传入

```python
from llmwikify import Wiki

config = {
    'orphan_detection': {
        'exclude_patterns': [r'^\d{4}-\d{2}-\d{2}$'],
    }
}
wiki = Wiki('/path/to/wiki', config=config)
```

### 方式 3：`wiki init` 时生成的模板

运行 `llmwikify init` 会自动创建 `.wiki-config.yaml.example` 模板文件：

```bash
llmwikify init
cp .wiki-config.yaml.example .wiki-config.yaml
# 编辑 .wiki-config.yaml 定制配置
```

---

## ⚙️ 配置选项

### `orphan_detection` - 孤立页面排除

孤立页面是指**没有入站链接**的页面。某些页面类型天然独立，不应视为问题。

#### `exclude_patterns` - 页面名正则匹配

**零域假设原则**：默认不预设任何排除模式，用户必须显式配置。

**示例配置**：

```yaml
orphan_detection:
  exclude_patterns:
    # 每日/周/月总结
    - '^\d{4}-\d{2}-\d{2}$'      # 2025-07-31
    - '^week-\d+$'               # week-1, week-2
    - '^monthly-\d{4}-\d{2}$'    # monthly-2025-07

    # Meeting notes
    - '^meeting-.*'              # meeting-2025-07-31
    - '^standup-.*'              # standup-notes

    # 读书笔记
    - '^book-note-.*'            # book-note-atomic-habits

    # 发布说明
    - '^release-.*'              # release-1.0.0
```

#### `exclude_frontmatter` - Frontmatter 标记

**示例配置**：

```yaml
orphan_detection:
  exclude_frontmatter:
    - 'redirect_to'              # 重定向页面
    - 'template: true'           # 模板页面
    - 'deprecated: true'         # 已弃用文档
    - 'draft: true'              # 草稿页面
```

**页面示例**：
```markdown
---
redirect_to: actual-page.md
---

# Redirect Page

This page redirects to another.
```

#### `archive_directories` - 归档目录

**示例配置**：

```yaml
orphan_detection:
  archive_directories:
    - 'daily'                   # wiki/daily/2025-07/...
    - 'weekly'                  # wiki/weekly/...
    - 'journal'                 # wiki/journal/...
    - 'meetings'                # wiki/meetings/...
    - 'releases'                # wiki/releases/...
```

---

## 🎯 使用场景示例

### 场景 1：矿业新闻 Wiki

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'      # 每日总结
    - '^weekly-.*'               # 周度洞察
    - '^monthly-.*'              # 月度洞察

  exclude_frontmatter:
    - 'redirect_to'              # 公司重定向页面

  archive_directories:
    - 'daily'                    # wiki/daily/
    - 'analysis'                # wiki/analysis/
```

### 场景 2：个人知识库

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'      # 日记
    - '^book-note-.*'            # 读书笔记
    - '^course-.*'               # 课程笔记

  exclude_frontmatter:
    - 'template: true'           # 模板页面

  archive_directories:
    - 'journal'                  # wiki/journal/
    - 'notes'                    # wiki/notes/
```

### 场景 3：项目文档

```yaml
orphan_detection:
  exclude_patterns:
    - '^release-.*'              # 发布说明
    - '^meeting-.*'              # Meeting notes
    - '^rfc-.*'                  # RFC 文档

  exclude_frontmatter:
    - 'deprecated: true'         # 已弃用 API

  archive_directories:
    - 'releases'                 # wiki/releases/
    - 'meetings'                 # wiki/meetings/
```

### 场景 4：研究 Wiki

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'      # 实验日志
    - '^experiment-.*'           # 实验记录
    - '^paper-note-.*'           # 论文笔记

  exclude_frontmatter:
    - 'type: experiment'         # 实验页面

  archive_directories:
    - 'experiments'              # wiki/experiments/
    - 'papers'                   # wiki/papers/
```

---

## 🔍 验证配置

### 查看当前孤立页面

```bash
# 运行 lint 检查
llmwikify lint

# 查看智能推荐
llmwikify recommend
```

### 测试配置效果

```python
from llmwikify import Wiki
from pathlib import Path

wiki = Wiki(Path('/path/to/wiki'), config={
    'orphan_detection': {
        'exclude_patterns': [r'^test-.*']
    }
})

# 测试页面是否被排除
page_path = Path('/path/to/wiki/wiki/test-page.md')
should_exclude = wiki._should_exclude_orphan('test-page', page_path)
print(f"Should exclude: {should_exclude}")
```

---

## 📝 最佳实践

### 1. 最小化配置

从默认配置开始，仅添加必要的排除规则：

```yaml
# ❌ 过度配置
orphan_detection:
  exclude_patterns:
    - '.*'  # 排除所有页面（无意义）

# ✅ 最小配置
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # 仅排除日期格式
```

### 2. 逐步迭代

1. 运行 `llmwikify lint` 查看当前孤立页面
2. 识别哪些是"正常"的孤立（如日志、总结）
3. 添加对应的排除规则
4. 重新运行 `llmwikify lint` 验证

### 3. 文档化配置

在 `.wiki-config.yaml` 中添加注释说明原因：

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # 每日总结，独立记录
    - '^meeting-.*'          # Meeting notes，按日期组织
```

### 4. 版本控制

将 `.wiki-config.yaml` 纳入版本控制：

```bash
git add .wiki-config.yaml
git commit -m "Add wiki config for orphan page exclusion"
```

---

## ❓ 常见问题

### Q: 为什么我的页面还被报告为孤立？

**A**: 检查：
1. 页面名是否匹配 `exclude_patterns` 正则
2. Frontmatter 是否包含 `exclude_frontmatter` 中的键
3. 页面是否在 `archive_directories` 目录中

### Q: 如何调试配置？

**A**: 使用 Python 交互式测试：

```python
from llmwikify import Wiki
from pathlib import Path

wiki = Wiki(Path('.'))
print(wiki._should_exclude_orphan('page-name', Path('wiki/page-name.md')))
```

### Q: 配置不生效怎么办？

**A**: 检查：
1. `.wiki-config.yaml` 语法是否正确（YAML 格式）
2. 配置文件是否在正确的目录（wiki 根目录）
3. 是否使用了最新的 llmwikify 版本

---

## 📚 相关文档

- [LLM Wiki Principles](docs/LLM_WIKI_PRINCIPLES.md) - Karpathy 原则
- [Reference Tracking Guide](docs/REFERENCE_TRACKING_GUIDE.md) - 引用追踪
- [MCP Setup Guide](docs/MCP_SETUP.md) - MCP 服务器设置

---

*最后更新：2026-04-10 | llmwikify v0.12.6*
