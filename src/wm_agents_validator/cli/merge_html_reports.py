from __future__ import annotations

import argparse
from pathlib import Path

from wm_agents_validator.controller.merge_html_reports import merge_html_reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge several already-rendered compare-traces HTML reports into one "
        "self-contained HTML report (e.g. one report per model, generated in separate runs) "
        "-- no re-fetching or re-verifying, just recombines the data each file already carries.",
        epilog=(
            "Example:\n"
            "  uv run merge-html-reports --in claude.html --in grok.html --out combined.html\n\n"
            "The merged report gets the same sortable table, Model/Contract filters, and "
            "per-plugin heatmap as a single compare-traces run -- e.g. toggle the heatmap to "
            '"group by Model" to compare claude vs grok side by side in one window.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--in",
        dest="inputs",
        action="append",
        required=True,
        metavar="REPORT_HTML",
        help="Path to a compare-traces HTML report. Repeatable -- pass one per file to merge.",
    )
    parser.add_argument("--out", required=True, help="Output merged HTML file path")
    args = parser.parse_args()

    html_texts = [Path(path).read_text(encoding="utf-8") for path in args.inputs]
    result = merge_html_reports(html_texts)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.html, encoding="utf-8")
    print(f"Merged {len(args.inputs)} report(s) into {out_path}")

    if result.warnings:
        print("\nReview before use:")
        for warning in result.warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
