# llmwikify 项目结构

标准 Python 包结构的项目布局

## 📁 目录结构

```
llmwikify/
├── 📄 pyproject.toml              # 项目配置和依赖 (PEP 517/518)
├── 📄 MANIFEST.in                 # 打包文件清单
├── 📄 README.md                   # 项目说明和使用指南
├── 📄 CHANGELOG.md                # 版本变更记录
├── 📄 LICENSE                     # MIT 许可证
├── 📄 .gitignore                  # Git 忽略规则
├── 📄 .wiki-config.yaml.example   # 配置文件模板
│
├── 📂 src/llmwikify/              # 源代码目录
│   ├── __init__.py                # 包入口和版本定义
│   ├── llmwikify.py               # 核心实现 (1,965 行)
│   └── py.typed                   # PEP 561 类型标记
│
├── 📂 tests/                      # 测试目录
│   ├── conftest.py                # pytest 配置和 fixtures
│   ├── test_cli.py                # CLI 命令测试
│   ├── test_extractors.py         # 提取器测试
│   ├── test_index.py              # 索引功能测试
│   ├── test_recommend.py          # 推荐引擎测试
│   └── test_wiki_core.py          # Wiki 核心测试
│
├── 📂 docs/                       # 文档目录
│   ├── CONFIG_GUIDE.md            # 配置指南
│   ├── LLM_WIKI_PRINCIPLES.md     # Karpathy LLM Wiki 原则
│   └── REFERENCE_TRACKING_GUIDE.md # 引用追踪指南
│
└── 📂 examples/                   # 示例目录 (待填充)
```

## 📊 文件统计

| 类别 | 文件数 | 代码行数 |
|------|--------|----------|
| 核心代码 | 2 | ~2,020 |
| 测试代码 | 6 | ~800 |
| 文档 | 7 | ~2,500 |
| 配置 | 4 | ~250 |
| **总计** | **19** | **~5,570** |

## 🎯 核心组件

### src/llmwikify/

| 文件 | 行数 | 说明 |
|------|------|------|
| `__init__.py` | 55 | 包入口、版本、导出 |
| `llmwikify.py` | 1,965 | 核心实现 |
| `py.typed` | - | 类型标记 |

### llmwikify.py 模块结构

```
llmwikify.py (1,965 行)
├── 1. 导入和常量 (30 行)
├── 2. 数据类 (95 行)
│   ├── ExtractedContent
│   ├── Link
│   ├── Issue
│   └── PageMeta
├── 3. 提取器 (296 行)
│   ├── detect_source_type()
│   ├── extract()
│   ├── _extract_text_file()
│   ├── _extract_html_file()
│   ├── _extract_pdf()
│   ├── _extract_url()
│   └── _extract_youtube()
├── 4. WikiIndex 类 (401 行)
│   ├── 数据库管理
│   ├── FTS5 全文搜索
│   └── 引用追踪
├── 5. Wiki 类 (565 行)
│   ├── 配置系统
│   ├── 页面管理
│   ├── 搜索和推荐
│   └── 孤立页检测
├── 6. MCPServer 类 (71 行)
│   └── 8 个 MCP 工具
├── 7. WikiCLI 类 (376 行)
│   └── 15 个 CLI 命令
└── 8. 主入口 (main)
```

## 🧪 测试套件

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| `test_cli.py` | 8 | CLI 命令 |
| `test_extractors.py` | 12 | 内容提取器 |
| `test_index.py` | 8 | WikiIndex |
| `test_recommend.py` | 5 | 推荐引擎 |
| `test_wiki_core.py` | 16 | Wiki 核心 |
| **总计** | **49** | **100%** |

## 📦 安装和开发

### 基础安装
```bash
pip install -e .
```

### 开发安装
```bash
pip install -e ".[dev]"
```

### 运行测试
```bash
pytest
```

### 代码检查
```bash
# 格式化
black src/llmwikify

# Linting
ruff check src/llmwikify

# 类型检查
mypy src/llmwikify
```

## 🚀 打包发布

### 构建
```bash
python -m build
```

### 发布到 PyPI
```bash
twine upload dist/*
```

## 📝 版本管理

版本号格式：`v0.MAJOR.MINOR`

- `0.10.0` - 初始发布版本
- `0.10.x` - Bug 修复和小改进
- `0.11.0` - 功能迭代

## 📋 文档体系

| 文档 | 目标读者 | 内容 |
|------|----------|------|
| README.md | 用户 | 快速开始、功能介绍 |
| CHANGELOG.md | 用户/开发者 | 版本变更历史 |
| ARCHITECTURE.md | 开发者 | 技术架构、设计决策 |
| CONFIG_GUIDE.md | 用户 | 配置选项详解 |
| LLM_WIKI_PRINCIPLES.md | 所有 | 设计理念 |
| REFERENCE_TRACKING_GUIDE.md | 用户 | 引用追踪功能 |

---

*最后更新：2026-04-10 | 版本：0.10.0*
