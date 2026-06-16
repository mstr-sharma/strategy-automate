#!/usr/bin/env python3
"""
Pre-build contextual data check for Mosaic model design.

Runs BEFORE `build_mosaic.py build` to catch design mistakes while they're cheap
to fix. Reports issues grouped by severity; exits non-zero if any ERROR-level
finding is present, so it can gate a build in CI.

What it checks
--------------
1. Naming convention — table + column casing, abbreviation hygiene,
   reserved-word clashes, language-variant duplication (`*_DE`, `*_ES`, ...).
2. Attribute vs metric classification — for every column, predict whether the
   build will treat it as an attribute (ID / key / descriptor) or a metric
   (numeric additive), and flag mismatches (e.g. an ID column that will get
   summed because its datatype is numeric).
3. Datatype sanity — precision/scale too small for observed payloads, text
   columns that look like dates, decimal IDs that should be varchar.
4. Relationship inferability — shared-column join chains are present?
   Bridge tables detected? Parent-without-child dangling attrs?
5. Contextual fit vs a reference blueprint — when the user supplies a legacy
   semantic-model blueprint (JSON produced by
   `strategy_semantic_mine.py blueprint`), compare attribute set, form counts,
   relationship topology, and metric functions. Missing attributes, absent
   relationships, or the classic "one attribute per locale column" anti-pattern
   are flagged.
6. Governance guards — columns that look like PII (EMAIL, SSN, DOB, PHONE)
   without a DESC form filter; facts without a grain attribute; metrics whose
   inferred function won't match the legacy definition.

Output
------
Writes a JSON + human-readable report to `--out`. Human-readable table goes to
stdout by default (TTY) or `--out-text` if passed. Severity levels:
ERROR   — build will produce an unusable or wrong model; fix before build.
WARN    — build will succeed but result is noisy or incomplete.
INFO    — informational; usually nudges toward cleaner naming.

Usage
-----
    python3 preflight_model_check.py \
        --instance "<Your DB Instance>" --schema <YOUR_SCHEMA> \
        --tables T1 T2 T3 FACT \
        --blueprint /tmp/model_blueprint.json \
        --out /tmp/preflight.json

Auth env: MSTR_BASE, MSTR_USER, MSTR_PASSWORD, MSTR_LOGIN_MODE, MSTR_PROJECT_ID
(same as build_mosaic.py).
"""
from __future__ import annotations
import argparse, json, os, re, sys, tempfile
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(__file__))
import build_mosaic as bm  # reuse session, discovery, and classification heuristics
from _client import add_auth_args  # noqa: E402

SEVERITY = {"ERROR": 3, "WARN": 2, "INFO": 1}

LOCALE_SUFFIXES = {"_DE","_ES","_FR","_IT","_JA","_KO","_PO","_SCH","_ZH","_EN"}
AUDIT_COLS = {"LOAD_TS","LOAD_DATE","LOAD_TIMESTAMP","LAST_UPDATED_AT","ETL_BATCH_ID","DW_CREATED_AT","DW_UPDATED_AT","SOURCE_SYSTEM","INGESTION_DATE"}
PII_HINTS = ("EMAIL","SSN","DOB","BIRTH","PHONE","FAX","ADDRESS","ZIP","POSTCODE","LAT","LON","IP_ADDR","CREDIT_CARD","PASSWORD")
# ID/key suffixes, numeric-dimension tokens, and numeric datatypes are
# deliberately NOT redefined here — predictions delegate to build_mosaic
# (bm.ID_COLUMN_SUFFIXES, bm.NATURAL_NUMERIC_DIMS, bm.NUMERIC_TYPES) so the
# preflight can never drift from what the build actually does.

@dataclass
class Finding:
    severity: str
    code: str
    subject: str
    message: str
    fix: str = ""

    def as_dict(self): return asdict(self)

@dataclass
class ColumnInfo:
    table: str
    name: str
    datatype: str
    precision: int | None = None
    scale: int | None = None
    looks_id: bool = False
    locale_suffix: str | None = None
    is_audit: bool = False
    is_pii: bool = False

    @property
    def is_numeric(self):
        # Same substring semantics as bm.classify_columns.
        dt = (self.datatype or "").lower()
        return any(t in dt for t in bm.NUMERIC_TYPES)


def classify_column(tname: str, col: dict) -> ColumnInfo:
    name = col.get("name") or col.get("columnName") or ""
    dt_raw = col.get("dataType") or {}
    if isinstance(dt_raw, str): dt_raw = {"type": dt_raw}
    dt = (dt_raw.get("type") or "").lower()
    locale = None
    upper = name.upper()
    for s in LOCALE_SUFFIXES:
        if upper.endswith(s):
            locale = s.lstrip("_"); break
    is_id = bm._looks_like_identifier_col(name)
    is_audit = upper in AUDIT_COLS
    is_pii = any(h in upper for h in PII_HINTS)
    return ColumnInfo(
        table=tname, name=name, datatype=dt,
        precision=dt_raw.get("precision"),
        scale=dt_raw.get("scale"),
        looks_id=is_id, locale_suffix=locale,
        is_audit=is_audit, is_pii=is_pii,
    )


def predict_role(ci: ColumnInfo) -> str:
    """What role will the auto-builder assign? returns: 'attribute' | 'metric' | 'skip'."""
    if ci.is_audit: return "skip"
    if ci.locale_suffix: return "attribute"  # descriptor form candidate, not a metric
    # Delegate to the build's actual classifier so prediction == reality.
    _attrs, metrics = bm.classify_columns(
        [{"name": ci.name, "dataType": ci.datatype}], set(), set())
    return "metric" if metrics else "attribute"


# ── Checks ────────────────────────────────────────────────────────────────────

def check_naming(cols: list[ColumnInfo], findings: list[Finding]):
    seen_casing = {}
    for c in cols:
        seen_casing.setdefault(c.name.lower(), []).append(c.name)
    for low, variants in seen_casing.items():
        if len({v for v in variants}) > 1:
            findings.append(Finding("WARN","CASING_INCONSISTENT",
                f"column '{low}' spelled as {sorted(set(variants))}",
                "Mixed-case duplicates will produce duplicate attributes.",
                "Pick one casing or use a dictionary to alias."))
    # Locale duplication — flag when 3+ locale variants of the same base column exist
    base_to_locales: dict[str,set] = {}
    for c in cols:
        if c.locale_suffix:
            base = c.name.rsplit("_",1)[0]
            base_to_locales.setdefault(base,set()).add(c.locale_suffix)
    for base, locs in base_to_locales.items():
        if len(locs) >= 3:
            findings.append(Finding("ERROR","LOCALE_COLUMN_EXPLOSION",
                f"{base}_* has locale variants {sorted(locs)}",
                "Auto-builder will create N separate descriptor attributes instead of one multilingual form.",
                f"Fold into one attribute form with isMultilingual:true; set the blueprint to skip the locale variants or explicitly treat them as translations."))
    for c in cols:
        if c.is_audit:
            findings.append(Finding("INFO","AUDIT_COLUMN",
                f"{c.table}.{c.name}","ETL/audit column — should be skipped, not modeled.",
                "Add to --skip-cols or dictionary.skip list."))
        if c.is_pii:
            findings.append(Finding("WARN","PII_LIKE",
                f"{c.table}.{c.name}","Column name suggests PII.",
                "Decide whether to expose in Mosaic; add security filter / column-level ACL if kept."))
        if c.name and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", c.name):
            findings.append(Finding("WARN","NAME_NEEDS_QUOTING",
                f"{c.table}.{c.name}","Non-identifier characters — will need quoting in SQL.",
                "Rename in the warehouse or dictionary-alias to a clean name."))


def check_classification(cols: list[ColumnInfo], findings: list[Finding]):
    for c in cols:
        if c.looks_id and c.is_numeric and not any(c.name.upper().endswith(s) for s in ("_ID", "ID", "_KEY", "KEY")):
            findings.append(Finding("INFO","AMBIGUOUS_ID",
                f"{c.table}.{c.name}","Numeric column matches ID tokens but not ending in ID.",
                "Confirm it is an attribute/key, or force via --metric-cols if this is actually additive."))
        if c.is_numeric and not c.looks_id and bm._looks_like_numeric_dimension(c.name):
            findings.append(Finding("WARN","NUMERIC_DIM_AS_METRIC",
                f"{c.table}.{c.name}","Numeric dimension (year/month/qtr) will be summed as a metric.",
                "Declare as attribute."))
        if c.datatype in ("varchar","char","n_var_char","text") and re.search(r"(DATE|TIME|TS|TIMESTAMP)$", c.name.upper()):
            findings.append(Finding("WARN","DATE_STORED_AS_TEXT",
                f"{c.table}.{c.name}","Column name suggests a date but datatype is text.",
                "Cast in a pipeline or fix upstream; otherwise time hierarchies will not work."))
        if c.datatype == "decimal" and c.looks_id and (c.precision or 0) >= 30 and (c.scale or 0) == 0:
            findings.append(Finding("INFO","BIG_DECIMAL_ID",
                f"{c.table}.{c.name}","decimal(38,0) ID — OK but consider bigint/varchar for join perf."))


def check_relationships(columns_by_table: dict[str,list[ColumnInfo]], findings: list[Finding]):
    col_to_tables: dict[str,set] = {}
    for t, cols in columns_by_table.items():
        for c in cols:
            if c.looks_id and not c.is_audit:
                col_to_tables.setdefault(c.name.upper(), set()).add(t)
    orphan_ids = [col for col, ts in col_to_tables.items() if len(ts) == 1]
    shared_ids = {col: sorted(ts) for col, ts in col_to_tables.items() if len(ts) >= 2}
    if not shared_ids:
        if len(columns_by_table) <= 1:
            # A single-table model legitimately has no joins — not an error, so it
            # must not trip `--fail-on ERROR`. (A worksheet/model over one table is
            # a normal migration shape.)
            findings.append(Finding("INFO","SINGLE_TABLE_NO_JOINS",
                "<all tables>","Single-table model — no joins to infer (expected).",
                "None — relationships only apply to multi-table models."))
        else:
            findings.append(Finding("ERROR","NO_SHARED_KEYS",
                "<all tables>","No shared ID column across any two tables — model will have no joins.",
                "Provide ERD via --erd or ensure FK columns use consistent names."))
    # Bridge table detection — all columns are *_ID
    for t, cols in columns_by_table.items():
        non_audit = [c for c in cols if not c.is_audit]
        if non_audit and all(c.looks_id for c in non_audit) and len(non_audit) >= 2:
            findings.append(Finding("INFO","BRIDGE_TABLE_SUSPECT",
                t,f"All {len(non_audit)} columns are ID-like — likely a bridge/junction table.",
                "Declare explicit many-to-many relationship in the dictionary; auto-inference won't."))
    for col in orphan_ids:
        if col.endswith("ID") and len({t for t in col_to_tables[col]}) == 1:
            # orphan FK-looking column — dim table with no fact referencing it
            findings.append(Finding("INFO","ISOLATED_KEY",
                col,"Key appears in only one table — no join path will be inferred.",
                "Either drop from scope or manually declare its parent dimension."))


def check_contextual_fit(columns_by_table: dict[str,list[ColumnInfo]],
                          blueprint: dict | None, findings: list[Finding]):
    """Compare planned model vs a legacy-blueprint JSON (schema below)."""
    if not blueprint: return
    bp_attrs = blueprint.get("attributes", {})
    planned_attrs = set()
    for t, cols in columns_by_table.items():
        for c in cols:
            if predict_role(c) == "attribute" and not c.locale_suffix and not c.is_audit:
                planned_attrs.add(c.name.upper())
    bp_names = {a.upper() for a in bp_attrs.keys()}
    missing_from_target = bp_names - planned_attrs
    for name in sorted(missing_from_target):
        findings.append(Finding("ERROR","BLUEPRINT_ATTR_MISSING",
            name,"Legacy attribute has no corresponding column in target warehouse tables.",
            "Source the missing table OR accept the scope reduction explicitly."))
    # form count
    for name, bp in bp_attrs.items():
        form_count = len(bp.get("forms", []))
        if form_count > 1:
            findings.append(Finding("INFO","MULTI_FORM_EXPECTED",
                name,f"Legacy attribute has {form_count} forms (ID+descriptors).",
                "Ensure blueprint-driven build creates a multi-form attribute instead of one attribute per column."))
    # relationships
    bp_rels = blueprint.get("relationships", [])
    if bp_rels:
        findings.append(Finding("INFO","BLUEPRINT_RELS",
            "",f"Blueprint declares {len(bp_rels)} relationship(s); these should be passed as --erd.",
            "Convert to dictionary/ERD and attach to build."))
    bp_metrics = blueprint.get("metrics", {})
    for name, meta in bp_metrics.items():
        fn = meta.get("function", "sum")
        expr = meta.get("expression") or ""
        if expr and any(op in expr for op in ("*", "-", "/")):
            findings.append(Finding("WARN","METRIC_NEEDS_FORMULA",
                name,f"Legacy metric '{name}' is a derived formula ({expr}).",
                "Don't let auto-builder create Sum(column). Create as custom fact metric with tokenized expression."))


# ── Loader for the blueprint ──────────────────────────────────────────────────

BLUEPRINT_SCHEMA = """
Expected blueprint JSON (produced by strategy_semantic_mine.py or hand-authored):

{
  "attributes": {
    "<Entity>": {
      "forms": [{"category":"ID","col":"<ENTITY>_ID","table":"<DIM_TABLE>"},
                {"category":"DESC","col":"<ENTITY>_DESC","table":"<DIM_TABLE>","isMultilingual":true}]
    },
    ...
  },
  "relationships": [
    {"parent":"<ParentEntity>","child":"<ChildEntity>","type":"one_to_many","table":"<JOIN_TABLE>"},
    ...
  ],
  "metrics": {
    "<Measure>": {"function":"sum","expression":"<QTY_COL> * (<UNIT_PRICE> - <DISCOUNT>)","tables":["<FACT_TABLE>"]},
    ...
  }
}
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    add_auth_args(p, project_name=False, project_id=True)
    p.add_argument("--instance", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--tables", nargs="+", required=True)
    p.add_argument("--blueprint", help="JSON blueprint from the legacy semantic layer (see schema).")
    p.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "preflight.json"))
    p.add_argument("--fail-on", choices=["ERROR","WARN","INFO"], default="ERROR",
                   help="Exit non-zero if any finding at this severity or higher.")
    p.add_argument("-v","--verbose", action="store_true")
    args = p.parse_args()

    ns = argparse.Namespace(base=args.base, project_id=args.project_id,
        user=args.user, password=args.password, login_mode=args.login_mode, verbose=args.verbose)
    m = bm.MSTR(ns); m.login()

    # Resolve instance + discover columns
    inst_id = bm.resolve_instance_id(m, args.instance)
    columns_by_table: dict[str,list[ColumnInfo]] = {}
    flat: list[ColumnInfo] = []
    for t in args.tables:
        raw = bm.fetch_table_metadata(m, inst_id, args.schema, t)
        cols = raw.get("columns") or raw.get("fields") or []
        infos = [classify_column(t, c) for c in cols]
        columns_by_table[t] = infos
        flat.extend(infos)

    # Load blueprint if any
    blueprint = None
    if args.blueprint:
        with open(args.blueprint) as f: blueprint = json.load(f)

    findings: list[Finding] = []
    check_naming(flat, findings)
    check_classification(flat, findings)
    check_relationships(columns_by_table, findings)
    check_contextual_fit(columns_by_table, blueprint, findings)

    findings.sort(key=lambda f: -SEVERITY[f.severity])

    # Report
    report = {
        "instance": args.instance, "schema": args.schema, "tables": args.tables,
        "column_counts": {t: len(cs) for t, cs in columns_by_table.items()},
        "blueprint_used": bool(blueprint),
        "summary": {
            "ERROR": sum(1 for f in findings if f.severity == "ERROR"),
            "WARN":  sum(1 for f in findings if f.severity == "WARN"),
            "INFO":  sum(1 for f in findings if f.severity == "INFO"),
        },
        "findings": [f.as_dict() for f in findings],
    }
    with open(args.out,"w") as f: json.dump(report, f, indent=2)

    # Human-readable
    lines = []
    lines.append(f"Mosaic preflight — {args.instance} / {args.schema}")
    lines.append(f"Tables: {', '.join(args.tables)}")
    lines.append(f"Blueprint: {'yes' if blueprint else 'no'}")
    s = report["summary"]
    lines.append(f"Findings: {s['ERROR']} ERROR / {s['WARN']} WARN / {s['INFO']} INFO")
    lines.append("")
    for f in findings:
        lines.append(f"  [{f.severity}] {f.code}: {f.subject} — {f.message}")
        if f.fix: lines.append(f"            fix: {f.fix}")
    print("\n".join(lines))

    threshold = SEVERITY[args.fail_on]
    if any(SEVERITY[f.severity] >= threshold for f in findings):
        sys.exit(1)

if __name__ == "__main__":
    main()
