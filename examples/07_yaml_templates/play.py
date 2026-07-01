"""
07 — 4 个 yaml 模板使用 demo

对应 docs/TUTORIAL.md §Part 3 — 9 个功能 playbook (07 yaml_templates)

演示 4 个开箱即用 yaml 配置模板 (CONFIGURATION_GUIDE.md §Use Case 1-4):

  personal-kb.yaml         # 个人 wiki, llm.enabled=false (本地 ollama)
  project-docs.yaml        # 项目文档 wiki, OpenAI + 2-step analyze
  research-wiki.yaml       # 研究 wiki, OpenAI + 长超时 (180s)
  mining-news-wiki.yaml    # 矿业新闻 wiki, OpenAI + 日期归档

模板结构 (CONFIGURATION_GUIDE.md §Key Sections):
  - orphan_detection.exclude_patterns:  regex 跳过孤立检测
  - orphan_detection.archive_directories: 历史目录
  - llm.{provider, model, api_key, timeout, enabled}

剧本规模：~100 行，可独立 `python play.py` 跑 (无 LLM 依赖, 仅解析 yaml)。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent / "yaml_templates"


def step(n: int, msg: str) -> None:
    print(f"\n=== Step {n}: {msg} ===")


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="llmwikify_yaml_demo_"))
    try:
        # ── Step 1: 列出 4 个模板
        step(1, "List 4 yaml templates")
        templates = sorted(TEMPLATES_DIR.glob("*.yaml"))
        for t in templates:
            print(f"   - {t.name} ({t.stat().st_size} bytes)")

        # ── Step 2: 解析每个模板, 展示关键字段
        step(2, "Parse each template and show llm + orphan_detection")
        for t in templates:
            data = yaml.safe_load(t.read_text(encoding="utf-8"))
            llm = data.get("llm", {})
            od = data.get("orphan_detection", {})
            print(f"\n   {t.name}:")
            print(f"      llm.enabled      = {llm.get('enabled')}")
            print(f"      llm.provider     = {llm.get('provider')}")
            print(f"      llm.model        = {llm.get('model')}")
            if "timeout" in llm:
                print(f"      llm.timeout      = {llm.get('timeout')}")
            excl = od.get("exclude_patterns", [])
            print(f"      exclude_patterns = {excl}")
            arch = od.get("archive_directories", [])
            print(f"      archive_dirs     = {arch}")

        # ── Step 3: 模板对比矩阵
        step(3, "Use case matrix")
        use_cases = {
            "personal-kb.yaml": "个人笔记 (offline, ollama/llama3)",
            "project-docs.yaml": "项目文档 (OpenAI, 2-step analyze)",
            "research-wiki.yaml": "学术研究 (OpenAI, 180s timeout)",
            "mining-news-wiki.yaml": "行业新闻 (OpenAI, 日期归档)",
        }
        for name, desc in use_cases.items():
            print(f"   {name:30s} → {desc}")

        # ── Step 4: 演示复制 + 自定义 + init
        step(4, "Demo: copy + customize + llmwikify init")
        base = TEMPLATES_DIR / "personal-kb.yaml"
        custom = work / "my-personal-kb.yaml"
        data = yaml.safe_load(base.read_text(encoding="utf-8"))
        # Simulate customization: change provider + add an exclude pattern
        data["llm"]["provider"] = "ollama"
        data["llm"]["model"] = "qwen2.5:7b"
        data["orphan_detection"]["exclude_patterns"].append("^draft-.*")
        custom.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        print(f"   Copied + customized to: {custom}")
        print(f"   llm.model = {data['llm']['model']}")
        print(f"   added exclude: {data['orphan_detection']['exclude_patterns'][-1]}")

        # ── Step 5: 演示 init 用 (CLI 不可用, 直接 import)
        step(5, "Demo: llmwikify.create_wiki + apply config")
        from llmwikify import create_wiki
        wiki_path = work / "my-notes"
        wiki = create_wiki(wiki_path)
        print(f"   Created wiki at: {wiki_path}")
        print(f"   Wiki config applied via create_wiki defaults")
        # Show wiki dirs
        print(f"   raw_dir  = {wiki.raw_dir}")
        print(f"   wiki_dir = {wiki.wiki_dir}")

        # ── Step 6: 总结 + 推荐选择
        step(6, "Summary — which template for your use case?")
        print("   个人 (offline)      → personal-kb.yaml + ollama")
        print("   项目文档 (中文/英文) → project-docs.yaml + OpenAI")
        print("   学术研究 (长 context) → research-wiki.yaml + OpenAI 180s")
        print("   行业新闻 (日更)      → mining-news-wiki.yaml + OpenAI")

        print(f"\nDone. Workdir: {work}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
