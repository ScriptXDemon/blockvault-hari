from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_SRC = REPO_ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from blockvault_api.zkpt_probe import run_zkpt_probe


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "output" / "zkpt" / f"runtime-probe-{timestamp}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live BlockVault ZKPT runtime probe.")
    parser.add_argument("--text", help="Optional probe text. Defaults to the built-in legal-text sample.")
    parser.add_argument(
        "--term",
        action="append",
        dest="terms",
        help="Search term to probe. Repeat the flag for multiple terms.",
    )
    parser.add_argument("--output", help="Optional JSON output path. Defaults to output/zkpt/runtime-probe-<timestamp>.json")
    parser.add_argument("--stdout-only", action="store_true", help="Print JSON only and do not write a file.")
    args = parser.parse_args()

    report = run_zkpt_probe(source_text=args.text, search_terms=args.terms)
    payload = json.dumps(report, indent=2)

    if args.stdout_only:
        print(payload)
        return 0

    output_path = Path(args.output).resolve() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote ZKPT runtime probe report to {output_path}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
