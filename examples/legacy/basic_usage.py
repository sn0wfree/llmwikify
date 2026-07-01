"""
DEPRECATED — 保留作为 v0.13 风格 API 演示。
推荐端到端剧本：
  ../01_personal_reading_notes/    init + ingest + search + write
  ../02_company_research_kb/       batch ingest + analyze + synthesize

llmwikify 基础使用示例

演示：
1. 创建/打开知识库
2. 写入和读取页面
3. 全文搜索
4. 获取引用关系
5. 知识库健康检查
"""

import os
import tempfile
from pathlib import Path

from llmwikify import Wiki, create_wiki


def example_1_create_and_open():
    """示例 1：创建和打开知识库"""
    print("=" * 60)
    print("示例 1：创建和打开知识库")
    print("=" * 60)

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki_path = Path(tmpdir) / "my-wiki"

        # 使用便捷函数创建
        wiki = create_wiki(wiki_path)

        # 初始化目录结构
        wiki.init()
        print(f"✓ 知识库创建于: {wiki_path}")
        print(f"  Wiki 根目录: {wiki.root}")
        print(f"  Pages 目录: {wiki.wiki_dir}")
        print(f"  Raw 目录: {wiki.raw_dir}")


def example_2_page_operations():
    """示例 2：页面读写操作"""
    print("\n" + "=" * 60)
    print("示例 2：页面读写操作")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 写入页面
        wiki.write_page(
            "Python/设计模式/单例模式",
            """# 单例模式

单例模式确保一个类只有一个实例，并提供全局访问点。

## 实现方式

```python
class Singleton:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

## 适用场景

- 日志记录器
- 数据库连接池
- 配置管理器

## 参见

- [[工厂模式]]
- [[依赖注入]]
"""
        )
        print("✓ 页面已写入")

        # 读取页面
        content = wiki.read_page("Python/设计模式/单例模式")
        print(f"✓ 读取页面，内容长度: {len(content)} 字符")

        # 搜索页面
        results = wiki.search("单例模式")
        print(f"✓ 搜索结果数: {len(results)}")


def example_3_search():
    """示例 3：全文搜索"""
    print("\n" + "=" * 60)
    print("示例 3：全文搜索")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 创建多个测试页面
        pages = [
            ("机器学习/监督学习", "监督学习使用标记数据训练模型，包括分类和回归。"),
            ("机器学习/无监督学习", "无监督学习使用未标记数据，包括聚类和降维。"),
            ("机器学习/强化学习", "强化学习通过与环境交互来学习策略。"),
        ]

        for name, content in pages:
            wiki.write_page(name, f"# {name}\n\n{content}")

        print(f"✓ 创建了 {len(pages)} 个测试页面")

        # 搜索
        keyword = "学习"
        results = wiki.search(keyword, limit=10)
        print(f"\n搜索关键词: '{keyword}'")
        print(f"找到 {len(results)} 个结果:\n")

        for i, result in enumerate(results, 1):
            print(f"{i}. {result['page_name']}")
            print(f"   Score: {result['score']:.4f}")


def example_4_links():
    """示例 4：引用关系"""
    print("\n" + "=" * 60)
    print("示例 4：引用关系")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        # 创建相互引用的页面
        wiki.write_page("A", "# Page A\n\n链接到 [[B]] 和 [[C]]")
        wiki.write_page("B", "# Page B\n\n链接到 [[A]]")
        wiki.write_page("C", "# Page C")

        # 重建索引
        wiki.build_index()

        # 获取入链
        inbound = wiki.get_inbound_links("A")
        print(f"页面 A 的入链数: {len(inbound)}")
        for link in inbound:
            print(f"  ← {link['source']}")

        # 获取出链
        outbound = wiki.get_outbound_links("A")
        print(f"\n页面 A 的出链数: {len(outbound)}")
        for link in outbound:
            print(f"  → {link['target']}")


def example_5_health_check():
    """示例 5：健康检查"""
    print("\n" + "=" * 60)
    print("示例 5：健康检查")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        wiki = create_wiki(tmpdir)
        wiki.init()

        wiki.write_page("孤页面", "# 孤页面\n\n没有链接到其他页面")
        wiki.write_page("首页", "# 首页\n\n[[存在的页面]]")

        # 运行 lint
        lint_result = wiki.lint(mode="check")
        print("健康检查结果:")
        print(f"  问题数量: {lint_result.get('issue_count', 0)}")
        print(f"  孤儿页面: {len(lint_result.get('orphan_pages', []))}")
        print(f"  死链: {len(lint_result.get('broken_links', []))}")


if __name__ == "__main__":
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " llmwikify 基础使用示例".center(58) + "║")
    print("╚" + "═" * 58 + "╝\n")

    example_1_create_and_open()
    example_2_page_operations()
    example_3_search()
    example_4_links()
    example_5_health_check()

    print("\n" + "=" * 60)
    print("✓ 所有示例运行完成！")
    print("=" * 60)
