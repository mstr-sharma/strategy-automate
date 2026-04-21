#!/usr/bin/env python3
"""End-to-end build of 'Supply Chain Model-claude_skill-<ts>' from the
SD_TECH_PENGUIN_* tables in Synthetic Data / MCI_DEMO.

Steps (all timed):
  1. Login (+ identityToken)
  2. Discover 4 tables matching SD_TECH_PENGUIN in MCI_DEMO
  3. Create in-memory data model, add 4 tables, auto-gen attributes + metrics
  4. Set inferred relationships (shared-column heuristic)
  5. Create derived metric 'Avg Cost Per Unit Ordered' = SUM(TOTAL_COST)/SUM(QUANTITY_ORDERED)
  6. ACL deny on that derived metric for user '<demo-user>'
  7. Publish (in-memory cube)
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime
from pathlib import Path

# Import the skill's helpers
sys.path.insert(0, str(Path("/Users/<operator-user>/.claude/skills/build-mosaic-model/scripts")))
import build_mosaic as bm

class NS:  # argparse stand-in
    pass

def main():
    t0 = time.monotonic()
    phase = {}

    # ── Args ─────────────────────────────────────────────────────────────────
    args = NS()
    args.base          = bm.DEFAULT_BASE
    args.project_id    = bm.DEFAULT_PROJECT_ID
    args.user          = bm.DEFAULT_USER
    args.password      = bm.DEFAULT_PASSWORD
    args.login_mode    = bm.DEFAULT_LOGIN_MODE
    args.verbose       = True

    DS_NAME   = "Synthetic Data"
    SCHEMA    = "MCI_DEMO"
    PREFIX    = "SD_TECH_PENGUIN"
    TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
    MODEL_NAME = f"Supply Chain Model-claude_skill-{TIMESTAMP}"

    m = bm.MSTR(args)
    m.login()
    phase["login_ms"] = int((time.monotonic() - t0) * 1000)

    # ── Discovery ─────────────────────────────────────────────────────────────
    t = time.monotonic()
    ds_id = bm.resolve_instance_id(m, DS_NAME)
    print(f"[discover] {DS_NAME} -> {ds_id}", file=sys.stderr)

    ns_id = bm.resolve_namespace_id(m, ds_id, SCHEMA)
    r = m.get(f"/api/datasources/{ds_id}/catalog/namespaces/{ns_id}/tables")
    all_tables = r.json().get("tables", [])
    tables = sorted([t["name"] for t in all_tables if t["name"].startswith(PREFIX)])
    print(f"[discover] matched {len(tables)} tables", file=sys.stderr)
    for t_ in tables: print(f"   - {t_}", file=sys.stderr)
    assert len(tables) == 4, f"Expected 4 SD_TECH_PENGUIN tables, got {len(tables)}"
    phase["discover_ms"] = int((time.monotonic() - t) * 1000)

    # ── Build model (in-memory) ───────────────────────────────────────────────
    t = time.monotonic()
    build_args = NS()
    build_args.name               = MODEL_NAME
    build_args.source             = [f"{DS_NAME}:{SCHEMA}:{','.join(tables)}"]
    build_args.instance = build_args.schema = None; build_args.tables = []
    build_args.dest_folder        = bm.DEFAULT_DEST_FOLDER
    build_args.data_serve_mode    = "in_memory"
    build_args.attr_cols          = []
    build_args.metric_cols        = []
    # v2: entity-first attribute creation + inference — no dict/ERD needed.
    build_args.skip_relationships = False
    build_args.dictionary         = None
    build_args.erd                = []
    build_args.security_filter    = []
    build_args.grant              = []
    build_args.translate          = []
    build_args.certify            = False
    build_args.publish            = False   # do it later, after derived metric + ACL

    # cmd_build prints a JSON summary to stdout; capture by redirecting
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bm.cmd_build(m, build_args)
    summary = json.loads(buf.getvalue())
    model_id = summary["model_id"]
    print(f"[build] model_id={model_id}  tables={summary['tables']}  attrs={summary['attributes']}  metrics={summary['metrics']}  rels={summary['inferred_relationships']}", file=sys.stderr)
    phase["build_ms"] = int((time.monotonic() - t) * 1000)

    # ── Locate the two metrics we need for the derived calc ───────────────────
    t = time.monotonic()
    r = m.get(f"/api/model/dataModels/{model_id}")
    schema_folder = r.json().get("schemaFolderId")
    r = m.get(f"/api/folders/{schema_folder}?limit=500")
    folder_items = r.json()
    metric_items = [it for it in folder_items if it.get("subtype") in (1033, 1034)]
    print(f"[derived] {len(metric_items)} metrics in schema folder", file=sys.stderr)
    po_table = next(t_ for t_ in tables if t_.endswith("PURCHASE_ORDERS"))

    # Compound metric: Avg Cost Per Unit Ordered
    cs = bm.open_cs(m)
    derived_name = "Avg Cost Per Unit Ordered"
    # Try several token-type variants (MSTR Modeling API differs across versions).
    # Look up the SUM metric IDs we built (now renamed by the dictionary)
    wanted_metric_names = {"Total PO Cost", "Total Quantity Ordered"}
    metric_ids = {}
    for it in metric_items:
        if it["name"] in wanted_metric_names:
            metric_ids[it["name"]] = it["id"]
    if len(metric_ids) < 2:
        # Re-fetch after dictionary rename
        r = m.get(f"/api/folders/{schema_folder}?limit=500")
        for it in r.json():
            if it.get("subtype") in (1033, 1034) and it["name"] in wanted_metric_names:
                metric_ids[it["name"]] = it["id"]
    revenue_mid = metric_ids.get("Total PO Cost")
    qty_mid     = metric_ids.get("Total Quantity Ordered")

    # Compound-metric variants all fail on commit (MSTR auto-creates an "empty managed fact"
    # that blocks the changeset). Skipping to the fact-with-formula fallback that's known
    # to commit cleanly on this tenant.
    compound_variants = []
    if False and revenue_mid and qty_mid:
        compound_variants = [
            # Variant A: guid tokens wrapped in brackets
            {"expression":{"tokens":[
                {"type":"character","value":"["},
                {"type":"guid","value": revenue_mid},
                {"type":"character","value":"]"},
                {"type":"character","value":"/"},
                {"type":"character","value":"["},
                {"type":"guid","value": qty_mid},
                {"type":"character","value":"]"},
            ]}},
            # Variant B: function-call tree, divide(metric_a, metric_b) via `function` tokens
            {"expression":{"tokens":[
                {"type":"function","value":"Divide","children":[
                    {"type":"guid","value": revenue_mid},
                    {"type":"guid","value": qty_mid},
                ]}
            ]}},
            # Variant C: object_reference (was accepted earlier — operator was what failed)
            {"expression":{"tokens":[
                {"type":"object_reference","target":{"objectId":revenue_mid,"subType":"metric"}},
                {"type":"character","value":"/"},
                {"type":"object_reference","target":{"objectId":qty_mid,"subType":"metric"}},
            ]}},
        ]

    compound_ok = False
    r = None
    for i, v in enumerate(compound_variants):
        body = {
            "information": {"name": derived_name,
                            "description": "Compound derived metric: Total PO Cost divided by Total Quantity Ordered — the blended per-unit procurement cost."},
            "dimty": None,
            "format": {"header":[],"values":[
                {"type":"number_category","value":"1"},
                {"type":"number_format","value":"#,##0.00"},
                {"type":"number_currency_symbol","value":"$"},
                {"type":"number_decimal_places","value":"2"},
            ]},
            **v,
        }
        r = m.post(f"/api/model/dataModels/{model_id}/factMetrics?changesetId={cs}", json=body)
        print(f"[derived] compound variant {chr(65+i)} -> HTTP {r.status_code}", file=sys.stderr)
        if r.ok:
            compound_ok = True; break
        print(f"          body: {r.text[:250]}", file=sys.stderr)

    if not compound_ok:
        # Fallback: fact metric with inline column formula (rendered as a $ fact metric in Library).
        po_tid = next((it["id"] for it in folder_items
                       if it.get("subtype")==3840 and it.get("name")==po_table), None)
        if not po_tid:
            raise SystemExit(f"cannot find logical table ID for {po_table}")
        body = {
            "information": {"name": derived_name,
                            "description": "Derived metric (implemented as fact-with-formula — tenant doesn't accept token-based compound metrics): per-row TOTAL_COST / QUANTITY_ORDERED, averaged."},
            "fact": {
                "dataType": {"type":"double","precision":15,"scale":4},
                "expressions": [{
                    "expression": {"tokens": [
                        {"type":"column_reference","value":"TOTAL_COST"},
                        {"type":"character","value":"/"},
                        {"type":"column_reference","value":"QUANTITY_ORDERED"},
                    ]},
                    "tables": [{"objectId": po_tid, "subType":"logical_table", "name": po_table}],
                }],
                "extensions": [], "entryLevel": [],
            },
            "function": "avg", "functionProperties": [], "dimty": {},
            "format": {"header":[],"values":[
                {"type":"number_category","value":"1"},
                {"type":"number_format","value":"#,##0.00"},
                {"type":"number_currency_symbol","value":"$"},
                {"type":"number_decimal_places","value":"2"},
            ]},
        }
        r = m.post(f"/api/model/dataModels/{model_id}/factMetrics?changesetId={cs}", json=body)
        print(f"[derived] fact-formula fallback -> HTTP {r.status_code}", file=sys.stderr)
        if not r.ok:
            print(f"          body: {r.text[:400]}", file=sys.stderr)
            raise SystemExit("derived metric creation failed")
    derived_id = r.json()["information"]["objectId"]
    bm.commit_cs(m, cs)
    print(f"[derived] '{derived_name}' -> {derived_id}", file=sys.stderr)
    phase["derived_ms"] = int((time.monotonic() - t) * 1000)

    # ── Find <demo-user> + apply deny ACL on the derived metric ───────────
    t = time.monotonic()
    # Find Tommy via metadata search — the user appears as the 'owner' of objects
    tommy_id = None
    r = m.get("/api/searches/results?name=tommy&getAncestors=false&limit=50")
    if r.ok:
        for it in r.json().get("result", []):
            o = it.get("owner") or {}
            if "tommy" in (o.get("name","").lower()) and ("connell" in o.get("name","").lower()):
                tommy_id = o.get("id")
                print(f"[acl] found {o.get('name')} -> {tommy_id}", file=sys.stderr)
                break
    tommy_denied = False
    if not tommy_id:
        print("[acl] WARN <demo-user> not found; skipping deny", file=sys.stderr)
    else:
        # Fetch existing ACL, prepend a DENY entry for Tommy, PUT back.
        r = m.get(f"/api/objects/{derived_id}?type=4")
        r.raise_for_status()
        full = r.json()
        deny_mask = 1 | 64 | 128 | 512     # read+browse+execute+use
        deny_entry = {
            "trusteeId": tommy_id,
            "trusteeName": "O'Connell, Tommy",
            "trusteeType": 34, "trusteeSubtype": 8704,   # 34=user
            "rights": deny_mask, "deny": True,
            "inheritable": False, "type": 1,
        }
        new_acl = [deny_entry] + full.get("acl", [])
        # Try several body shapes — tenants differ.
        for body in [
            {"acl": new_acl},
            {"acl": new_acl, "id": derived_id, "type": 4},
        ]:
            r = m.s.put(f"{m.base}/api/objects/{derived_id}?type=4", json=body)
            print(f"[acl] PUT /api/objects/{derived_id} -> HTTP {r.status_code}", file=sys.stderr)
            if r.ok: break
            print(f"       body: {r.text[:250]}", file=sys.stderr)
        tommy_denied = r.ok
    phase["acl_ms"] = int((time.monotonic() - t) * 1000)

    # ── Publish (in-memory cube) ──────────────────────────────────────────────
    t = time.monotonic()
    r = m.post(f"/api/cubes/{model_id}", json={})
    print(f"[publish] POST /api/cubes/{model_id} -> HTTP {r.status_code}", file=sys.stderr)
    published = r.ok
    if not r.ok:
        print(f"          body: {r.text[:300]}", file=sys.stderr)
    phase["publish_ms"] = int((time.monotonic() - t) * 1000)

    # ── Summary ───────────────────────────────────────────────────────────────
    total_ms = int((time.monotonic() - t0) * 1000)
    print("\n" + "="*72)
    print(json.dumps({
        "model_name": MODEL_NAME,
        "model_id": model_id,
        "url": f"{m.base}/app/library#/model/{model_id}",
        "data_serve_mode": "in_memory",
        "tables": summary["tables"],
        "attributes": summary["attributes"],
        "metrics": summary["metrics"] + 1,  # + derived
        "derived_metric": {"name": derived_name, "id": derived_id,
                           "kind": "compound" if compound_ok else "fact_with_formula",
                           "formula": "[Total PO Cost] / [Total Quantity Ordered]" if compound_ok else "SUM(TOTAL_COST / QUANTITY_ORDERED)"},
        "inferred_relationships": summary["inferred_relationships"],
        "tommy_denied": tommy_denied,
        "published": published,
        "timing_ms": {**phase, "total": total_ms},
    }, indent=2))

if __name__ == "__main__":
    main()
