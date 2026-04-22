#!/usr/bin/env python3
"""Compare Strategy model results against a trusted reference result set.

This is the first pluggable data-correctness runner for the strategy-validation
skill. It intentionally starts with file/result-set adapters so Mosaic, classic
reports, warehouse SQL, and external systems can all feed the same diff engine.
Live source adapters should reduce to the same row-list shape.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from typing import Any


NULL_SENTINEL = "<NULL>"


def load_rows(path: str) -> list[dict[str, Any]]:
    if path.lower().endswith(".csv"):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except OSError as exc:
            raise SystemExit(f"{path}: {exc}") from exc
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except OSError as exc:
        raise SystemExit(f"{path}: {exc}") from exc
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "items", "result", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise SystemExit(f"{path}: expected CSV, JSON list, or JSON object with rows/data/items/results")


def split_cols(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def key_for(row: dict[str, Any], key_cols: list[str]) -> tuple:
    if not key_cols:
        return ()
    return tuple(NULL_SENTINEL if row.get(col) in (None, "") else str(row.get(col)) for col in key_cols)


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def infer_measures(model_rows: list[dict[str, Any]], reference_rows: list[dict[str, Any]], key_cols: list[str]) -> list[str]:
    names = sorted((set().union(*(r.keys() for r in model_rows or [{}])) &
                    set().union(*(r.keys() for r in reference_rows or [{}]))) - set(key_cols))
    measures = []
    for name in names:
        values = [number(row.get(name)) for row in (model_rows[:20] + reference_rows[:20])]
        if any(value is not None for value in values):
            measures.append(name)
    return measures


def index_rows(rows: list[dict[str, Any]], key_cols: list[str], label: str) -> tuple[dict[tuple, dict], list[tuple]]:
    indexed: dict[tuple, dict] = {}
    duplicates: list[tuple] = []
    for idx, row in enumerate(rows):
        key = key_for(row, key_cols) if key_cols else (idx if len(rows) > 1 else 0,)
        if key in indexed:
            duplicates.append(key)
            continue
        indexed[key] = row
    if duplicates:
        sample = ", ".join(str(k) for k in duplicates[:5])
        raise SystemExit(f"{label}: duplicate keys found: {sample}")
    return indexed, duplicates


def compare_rows(model_rows: list[dict[str, Any]], reference_rows: list[dict[str, Any]],
                 key_cols: list[str], measure_cols: list[str], tolerance: float,
                 query_name: str) -> dict[str, Any]:
    started = time.monotonic()
    if not measure_cols:
        measure_cols = infer_measures(model_rows, reference_rows, key_cols)
    if not measure_cols:
        raise SystemExit("No measure columns supplied or inferred")

    model_idx, _ = index_rows(model_rows, key_cols, "model")
    ref_idx, _ = index_rows(reference_rows, key_cols, "reference")
    model_keys = set(model_idx)
    ref_keys = set(ref_idx)
    common = sorted(model_keys & ref_keys)

    deltas = []
    worst = 0.0
    for key in common:
        mrow = model_idx[key]
        rrow = ref_idx[key]
        for col in measure_cols:
            mv = number(mrow.get(col))
            rv = number(rrow.get(col))
            if mv is None and rv is None:
                continue
            if mv is None or rv is None:
                rel = 1.0
            else:
                rel = abs(mv - rv) / max(abs(mv), abs(rv), 1.0)
            worst = max(worst, rel)
            if rel > tolerance:
                deltas.append({
                    "key": list(key) if isinstance(key, tuple) else key,
                    "metric": col,
                    "model": mv,
                    "reference": rv,
                    "delta_pct": rel,
                })

    reference_only = sorted(ref_keys - model_keys)
    model_only = sorted(model_keys - ref_keys)
    status = "ok" if not (reference_only or model_only or deltas) else "mismatch"
    return {
        "query_name": query_name,
        "status": status,
        "row_count_model": len(model_rows),
        "row_count_reference": len(reference_rows),
        "matched_rows": len(common) - len({tuple(d["key"]) if isinstance(d["key"], list) else d["key"] for d in deltas}),
        "reference_only_rows": [list(k) if isinstance(k, tuple) else k for k in reference_only[:50]],
        "model_only_rows": [list(k) if isinstance(k, tuple) else k for k in model_only[:50]],
        "delta_rows": deltas[:100],
        "worst_delta_pct": worst,
        "metric_columns": measure_cols,
        "elapsed_model_ms": None,
        "elapsed_reference_ms": None,
        "elapsed_compare_ms": int((time.monotonic() - started) * 1000),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-file", "--model-result-file", dest="model_file",
                        help="CSV/JSON rows produced from the model under test")
    parser.add_argument("--reference-file", "--reference-result-file", dest="reference_file",
                        help="CSV/JSON rows from the trusted comparator")
    parser.add_argument("--key", default="", help="comma-separated key/dimension columns; omit only for a single-row total")
    parser.add_argument("--measures", default="", help="comma-separated numeric measure columns; inferred when omitted")
    parser.add_argument("--query-name", default="file_result_comparison")
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--out", help="write structured JSON result")

    # Planned live adapters. Accepted so callers get an honest message instead of
    # an unknown-argument failure while the adapters are being implemented.
    parser.add_argument("--model")
    parser.add_argument("--reference-mosaic")
    parser.add_argument("--reference-sql-file")
    parser.add_argument("--reference-conn")
    parser.add_argument("--reference-classic-report")
    parser.add_argument("--reference-rest-file")
    parser.add_argument("--query-suite")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.model_file and args.reference_file):
        raise SystemExit(
            "Provide --model-file and --reference-file for the implemented file adapter. "
            "Live Mosaic/classic/warehouse adapters are intentionally pending and should feed this diff engine."
        )

    result = compare_rows(
        load_rows(args.model_file),
        load_rows(args.reference_file),
        split_cols(args.key),
        split_cols(args.measures),
        args.tolerance,
        args.query_name,
    )
    text = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
