"""真实 LLM 端到端验收 — 文档解析 → 知识库完善。

复跑 docs/designs/auto-doc-enrichment.md 的「真实场景验收（阶段 2）」。

与当时的模拟版本不同：LLM 环节**不做任何降级模拟**——key 无效或
provider 不可用时直接失败退出（exit 2），因为验收的意义就在于
验证真实 LLM 链路。

用法::

    python scripts/acceptance_real_llm.py                 # 临时 wiki，跑完即删
    python scripts/acceptance_real_llm.py --keep          # 保留 wiki 目录
    python scripts/acceptance_real_llm.py --wiki-root DIR  # 用已有 wiki

配置来源：``~/.llmwikify/llmwikify.json`` 的 ``llm`` 段
（provider / model / api_key），也可用 ``LLM_API_KEY`` /
``LLM_BASE_URL`` / ``LLM_PROVIDER`` 环境变量覆盖。

退出码：0 = 全部通过；2 = LLM 不可用；1 = 其它失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from llmwikify.foundation.config import config as global_config  # noqa: E402
from llmwikify.foundation.config import load_config  # noqa: E402

DEFAULT_FIXTURE = (
    REPO_ROOT
    / "examples"
    / "01_personal_reading_notes"
    / "fixtures"
    / "andrew-ng-ai-notes.md"
)


def _log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def _wiki_config(wiki_root: Path) -> dict[str, Any]:
    """Wiki config merged with the global ``llm`` section.

    ``llm.enabled`` is forced on: the acceptance explicitly exercises the
    LLM path, and the shipped default is ``False``.
    """
    cfg = load_config(wiki_root)
    llm_cfg = dict(global_config.get("llm") or {})
    if llm_cfg:
        merged = {**(cfg.get("llm") or {}), **llm_cfg}
        merged["enabled"] = True
        cfg["llm"] = merged
    return cfg


def _preflight() -> tuple[str, str]:
    """Verify the LLM is reachable. Returns (provider, model).

    Raises RuntimeError with an actionable message when the key or the
    endpoint is wrong — never silently degrade.
    """
    llm_cfg = global_config.get("llm") or {}
    provider = os.environ.get("LLM_PROVIDER") or llm_cfg.get("provider") or "openai"
    model = os.environ.get("LLM_MODEL") or llm_cfg.get("model") or ""
    api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("api_key") or ""
    if isinstance(api_key, str) and api_key.startswith("env:"):
        api_key = os.environ.get(api_key[4:], "")

    if not api_key:
        raise RuntimeError(
            "No LLM api_key configured. Set llm.api_key in "
            "~/.llmwikify/llmwikify.json or export LLM_API_KEY=..."
        )
    if len(api_key) < 20:
        raise RuntimeError(
            f"Configured api_key looks like a placeholder (len={len(api_key)}). "
            "Replace it with a real key before running the acceptance."
        )

    from llmwikify.foundation.llm_client import LLMClient

    client = LLMClient.from_config({"llm": {**llm_cfg, "enabled": True}})
    _log("0", f"provider={client.provider} model={model or '(default)'} base={client.base_url}")
    try:
        reply = client.chat(
            [{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=8,
        )
    except Exception as exc:
        raise RuntimeError(f"LLM preflight failed: {exc!r}") from exc
    _log("0", f"LLM reachable — reply: {str(reply)[:60]!r}")
    return provider, model


def _run(wiki_root: Path, fixture: Path) -> dict[str, Any]:
    from llmwikify.apps.agent.maintenance.config import EnricherConfig
    from llmwikify.apps.agent.maintenance.enricher import KnowledgeEnricher
    from llmwikify.kernel.wiki import Wiki

    cfg = _wiki_config(wiki_root)
    wiki = Wiki(wiki_root, config=cfg)

    report: dict[str, Any] = {"steps": []}

    # ── Step 1: parse + archive ─────────────────────────────────
    t0 = time.monotonic()
    source_data = wiki.ingest_source(str(fixture))
    if source_data.get("error"):
        raise RuntimeError(f"ingest_source failed: {source_data['error']}")
    elapsed = time.monotonic() - t0
    _log(
        "1",
        f"ingest_source → {source_data.get('source_path', '?')} "
        f"({len(source_data.get('content', ''))} chars, {elapsed:.1f}s)",
    )
    report["steps"].append({"step": "ingest", "seconds": round(elapsed, 2)})

    # ── Step 2: REAL LLM analysis (no simulation fallback) ──────
    t0 = time.monotonic()
    llm_result = wiki._llm_process_source(source_data)
    elapsed = time.monotonic() - t0
    analysis = llm_result.get("analysis") or {}
    operations = llm_result.get("operations") or []
    if not operations:
        raise RuntimeError(
            "LLM produced no wiki operations — analysis yielded nothing: "
            f"{json.dumps(analysis, ensure_ascii=False)[:400]}"
        )
    _log(
        "2",
        f"LLM analysis (real) {elapsed:.1f}s — entities={len(analysis.get('entities', []))} "
        f"relations={len(analysis.get('relations', []))} "
        f"claims={len(analysis.get('claims', []))} operations={len(operations)}",
    )
    for op in operations:
        _log("2", f"  {op.get('action')} → {op.get('page_name', '')}")
    report["steps"].append({"step": "llm", "seconds": round(elapsed, 2)})
    report["operations"] = len(operations)

    # ── Step 3: execute operations (real writes) ─────────────────
    t0 = time.monotonic()
    exec_result = wiki.execute_operations(operations)
    elapsed = time.monotonic() - t0
    pages = len(list(wiki._wiki_pages()))
    _log("3", f"executed {len(operations)} ops in {elapsed:.1f}s — wiki pages: {pages}")
    report["steps"].append({"step": "execute", "seconds": round(elapsed, 2)})
    report["pages"] = pages

    # ── Step 4: incremental enrichment (real) ───────────────────
    t0 = time.monotonic()
    enricher = KnowledgeEnricher(wiki, "acceptance", EnricherConfig())
    enrich_result = asyncio.run(enricher.enrich(llm_result, exec_result))
    elapsed = time.monotonic() - t0
    _log(
        "4",
        f"enrich {elapsed:.1f}s — concepts={enrich_result.concepts_checked} "
        f"sources={enrich_result.sources_checked} links={enrich_result.links_added} "
        f"proposals={enrich_result.proposals_created} "
        f"skipped={enrich_result.skipped_units} errors={enrich_result.errors}",
    )
    report["steps"].append({"step": "enrich", "seconds": round(elapsed, 2)})
    report["enrich"] = enrich_result.as_dict()

    # ── Step 5: index + lint residual ────────────────────────────
    wiki.build_index()
    index_file = wiki.wiki_dir / "index.md"
    index_body = index_file.read_text(encoding="utf-8") if index_file.exists() else ""
    _log("5", f"index.md ({len(index_body)} bytes)")
    for line in index_body.splitlines():
        if line.strip():
            _log("5", f"  {line}")

    from llmwikify.kernel.wiki.lint.rules.missing_cross_refs import (
        MissingCrossRefsRule,
    )

    pages_map = {
        wiki._page_display_name(p): p.read_text(encoding="utf-8")
        for p in wiki._wiki_pages()
    }
    residual: list[dict] = []
    MissingCrossRefsRule().detect_all(pages_map, wiki, residual)
    _log("5", f"missing_cross_ref residual: {residual}")
    report["residual"] = residual

    report["files"] = {
        str(p.relative_to(wiki.wiki_dir)): p.stat().st_size
        for p in sorted(wiki.wiki_dir.rglob("*.md"))
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, default=None)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--keep", action="store_true", help="keep the temp wiki")
    args = parser.parse_args()

    if not args.fixture.exists():
        print(f"fixture not found: {args.fixture}", file=sys.stderr)
        return 1

    try:
        _preflight()
    except RuntimeError as exc:
        print(f"[preflight] LLM unavailable: {exc}", file=sys.stderr)
        print(
            "[preflight] acceptance requires a working LLM — no simulation "
            "fallback (see docs/designs/auto-doc-enrichment.md).",
            file=sys.stderr,
        )
        return 2

    tmp_root: Path | None = None
    if args.wiki_root:
        wiki_root = args.wiki_root
        wiki_root.mkdir(parents=True, exist_ok=True)
    else:
        tmp_root = Path(tempfile.mkdtemp(prefix="llmwikify_acceptance_"))
        wiki_root = tmp_root / "wiki"

    try:
        from llmwikify.kernel.wiki import Wiki

        wiki = Wiki(wiki_root, config=_wiki_config(wiki_root))
        if not wiki.is_initialized():
            wiki.init()
        report = _run(wiki_root, args.fixture)
        print("\n=== 验收结论 ===")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        ok = bool(report.get("operations")) and not report.get("residual")
        print(f"\n结果: {'PASS' if ok else 'CHECK'}")
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        print(f"[fatal] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmp_root and not args.keep:
            shutil.rmtree(tmp_root, ignore_errors=True)
        elif tmp_root:
            print(f"\nwiki kept at: {tmp_root}")


if __name__ == "__main__":
    raise SystemExit(main())
