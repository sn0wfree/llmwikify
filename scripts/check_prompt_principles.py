#!/usr/bin/env python3
"""Check prompt templates for LLM Wiki Principle compliance.

Usage:
    python scripts/check_prompt_principles.py              # Human-readable report
    python scripts/check_prompt_principles.py --format json  # JSON output
    python scripts/check_prompt_principles.py --format ci    # CI-friendly (exit code based)
    python scripts/check_prompt_principles.py --threshold 0.90  # Fail below threshold
"""

import sys
import json
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llmwikify.core.principle_checker import PrincipleChecker


def main():
    parser = argparse.ArgumentParser(description="Check prompt templates for principle compliance")
    parser.add_argument(
        "--format",
        choices=["text", "json", "ci"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum overall score to pass (0.0-1.0). Fails if below threshold.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write output to file instead of stdout",
    )
    parser.add_argument(
        "--prompt-dir",
        type=str,
        default=None,
        help="Path to prompt templates directory",
    )

    args = parser.parse_args()

    defaults_dir = Path(args.prompt_dir) if args.prompt_dir else None
    checker = PrincipleChecker(defaults_dir=defaults_dir)
    results = checker.check_all_templates()

    if args.format == "json":
        output = json.dumps(checker.generate_json_report(results), indent=2)
    elif args.format == "ci":
        output = json.dumps(checker.generate_json_report(results), indent=2)
    else:
        output = checker.generate_report(results)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)

    # Determine exit code
    report = checker.generate_json_report(results)
    overall_score = report["overall_score"]

    if args.threshold > 0 and overall_score < args.threshold:
        print(f"\nFAILED: Score {overall_score:.2%} is below threshold {args.threshold:.2%}", file=sys.stderr)
        return 1

    if report["compliant_count"] < report["templates_checked"]:
        # Non-compliant templates exist, but only fail in CI mode
        if args.format == "ci":
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
