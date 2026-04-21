#!/usr/bin/env python3
"""Fix relationships on an already-built Mosaic model using the shared-key merge pattern.

Problem: MSTR requires the parent attribute to have an expression on the relationship's
join table. When we created separate FK-side attributes (e.g. "Product ID (Opportunities)"
on OPPORTUNITIES), the dimension attribute "Product ID" only had an expression on PRODUCTS,
so parent→child relationships with join_table=OPPORTUNITIES failed.

Fix:
  1. For each shared-key column, identify the "parent" attribute (dim side) and the
     FK-side attributes (on fact tables).
  2. PATCH the parent attribute to append expressions on each fact table (using the
     same column name).
  3. DELETE the FK-side attributes (now redundant).
  4. Create relationships parent → fact-table-PK, join_table=fact-table.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/Users/<operator-user>/.claude/skills/build-mosaic-model/scripts")
import build_mosaic as bm

MODEL_ID = "A860AD1615F445ECB65E10DABCCE05D7"

class NS: pass
args = NS()
args.base=bm.DEFAULT_BASE; args.project_id=bm.DEFAULT_PROJECT_ID
args.user=bm.DEFAULT_USER; args.password=bm.DEFAULT_PASSWORD
args.login_mode=1; args.verbose=False

m = bm.MSTR(args); m.login()
print(f"[auth] ok; model_id={MODEL_ID}", file=sys.stderr)

# ── Load the dictionary so we know explicit rels + which side is parent ───────
dict_path = Path(__file__).parent / "supply_chain_dict.json"
spec = json.loads(dict_path.read_text())
explicit_rels = spec.get("relationships", [])

# ── Fetch the model's schema folder & enumerate attributes ────────────────────
r = m.get(f"/api/model/dataModels/{MODEL_ID}")
schema_folder = r.json()["schemaFolderId"]
r = m.get(f"/api/folders/{schema_folder}?limit=500")
folder_items = r.json()
attrs  = [it for it in folder_items if it.get("subtype") == 3072]
tables = [it for it in folder_items if it.get("subtype") == 3840]
tables_by_name = {t["name"]: t["id"] for t in tables}
attrs_by_name  = {a["name"]: a["id"] for a in attrs}

# Map explicit rel "TABLE.COL" → attribute id we'd created for it
def attr_for(table_col: str) -> tuple[str, str]:
    """Return (attr_id, attr_name) for a TABLE.COLUMN reference."""
    t, _, col = table_col.partition(".")
    # Our naming convention: dim side = "<Friendly Col>", fk side = "<Friendly Col> (<Short Table>)"
    base = bm.friendly_col(col)
    short = bm.friendly_table(t)
    if f"{base} ({short})" in attrs_by_name:
        return attrs_by_name[f"{base} ({short})"], f"{base} ({short})"
    if base in attrs_by_name:
        return attrs_by_name[base], base
    raise RuntimeError(f"cannot find attribute for {table_col} (tried '{base}' and '{base} ({short})')")

# ── Fetch parent attribute JSON, add expressions for each child table ─────────
def merge_parent_to_fact(parent_tc: str, fact_tc: str):
    p_id, p_name = attr_for(parent_tc)
    f_table, _, f_col = fact_tc.partition(".")
    f_table_id = tables_by_name.get(f_table)
    if not f_table_id: raise RuntimeError(f"no table id for {f_table}")

    # GET parent
    r = m.get(f"/api/model/dataModels/{MODEL_ID}/attributes/{p_id}")
    if not r.ok: raise RuntimeError(f"GET parent attr: {r.status_code} {r.text[:300]}")
    parent = r.json()

    # Add new expression on fact table to the key form. First normalize ALL
    # existing expressions from text-form to token-form (MSTR PATCH rejects text-only).
    for form in parent.get("forms", []):
        for e in form.get("expressions", []):
            ex = e.get("expression", {})
            if "text" in ex and "tokens" not in ex and "tree" not in ex:
                e["expression"] = {"tokens":[{"type":"column_reference","value": ex["text"]}]}
    for form in parent.get("forms", []):
        if form.get("category","").upper() == "ID" or form.get("type") == "system":
            new_expr = {
                "expression": {"tokens":[{"type":"column_reference","value": f_col}]},
                "tables": [{"objectId": f_table_id, "subType":"logical_table", "name": f_table}],
            }
            exists = any(t.get("objectId")==f_table_id for e in form.get("expressions",[]) for t in e.get("tables",[]))
            if not exists:
                form.setdefault("expressions", []).append(new_expr)
            break

    # Ensure every form has a non-empty name
    for i, form in enumerate(parent.get("forms", [])):
        if not form.get("name"):
            form["name"] = form.get("alias") or form.get("category") or f"Form{i+1}"

    # PATCH with full attribute body (forms + keyForm + lookupTable + displays)
    patch_body = {
        "forms":    parent["forms"],
        "keyForm":  parent.get("keyForm"),
        "attributeLookupTable": parent.get("attributeLookupTable"),
    }
    if parent.get("displays"): patch_body["displays"] = parent["displays"]
    cs = bm.open_cs(m)
    r = m.s.patch(f"{m.base}/api/model/dataModels/{MODEL_ID}/attributes/{p_id}?changesetId={cs}",
                  json=patch_body)
    if not r.ok:
        m.delete(f"/api/model/changesets/{cs}")
        raise RuntimeError(f"PATCH parent: {r.status_code} {r.text[:400]}")
    bm.commit_cs(m, cs)
    print(f"  [merge] {p_name}: +expr on {f_table} (col {f_col})", file=sys.stderr)
    return p_id

# ── Delete the FK-side duplicate attributes ──────────────────────────────────
def delete_attr(attr_id: str, name: str):
    r = m.delete(f"/api/objects/{attr_id}?type=12")
    if r.ok:  print(f"  [del] attribute {name} ({attr_id})", file=sys.stderr)
    else:     print(f"  [del] WARN {name} {attr_id}: {r.status_code} {r.text[:200]}", file=sys.stderr)

# ── Phase 1: for each parent, merge ALL child-table expressions in one PATCH ─
print("\n── Phase 1: merging parent attributes onto fact tables ──", file=sys.stderr)
fk_to_delete = set()
parent_ids = {}
# Group: parent_tc -> [child_tc, child_tc, ...]
from collections import defaultdict
by_parent = defaultdict(list)
for rel in explicit_rels:
    by_parent[rel["parent"]].append(rel["child"])
    fk_to_delete.add(rel["child"])

def merge_parent_to_facts_bulk(parent_tc: str, child_tcs: list[str]):
    """DELETE the existing parent attribute, then POST a replacement with expressions on all fact tables."""
    p_id, p_name = attr_for(parent_tc)
    r = m.get(f"/api/model/dataModels/{MODEL_ID}/attributes/{p_id}")
    if not r.ok: raise RuntimeError(f"GET parent attr: {r.status_code} {r.text[:300]}")
    parent = r.json()

    p_table, _, p_col = parent_tc.partition(".")
    p_table_id = tables_by_name[p_table]

    # Build new attribute body: key form with expression on parent table + all child tables.
    all_table_exprs = [(p_table_id, p_table, p_col)]
    for fact_tc in child_tcs:
        ft, _, fc = fact_tc.partition(".")
        all_table_exprs.append((tables_by_name[ft], ft, fc))

    # Pull display-form data from the GET response (non-key forms), so we preserve descriptions etc.
    # For simplicity, rebuild with just the key form referencing all tables.
    FORM_ID = bm.FORM_ID
    new_body = {
        "information": {"name": p_name, "description": parent.get("information",{}).get("description","")},
        "forms": [{
            "id": FORM_ID,
            "category": "ID",
            "type": "system",
            "displayFormat": "text",
            "expressions": [
                {"expression": {"tokens":[{"type":"column_reference","value": col}]},
                 "tables": [{"objectId": tid, "subType":"logical_table", "name": tn}]}
                for tid, tn, col in all_table_exprs
            ],
            "lookupTable": {"objectId": p_table_id, "subType":"logical_table", "name": p_table},
        }],
        "keyForm": {"id": FORM_ID},
        "attributeLookupTable": {"objectId": p_table_id, "subType":"logical_table", "name": p_table},
    }

    # DELETE existing (outside changeset), then POST replacement in a new changeset
    r = m.delete(f"/api/objects/{p_id}?type=12")
    if r.status_code not in (200, 204):
        print(f"    WARN delete {p_name}: {r.status_code} {r.text[:200]}", file=sys.stderr)
    import time as _t; _t.sleep(0.5)
    cs = bm.open_cs(m)
    r = m.post(f"/api/model/dataModels/{MODEL_ID}/attributes?changesetId={cs}", json=new_body)
    if not r.ok:
        m.delete(f"/api/model/changesets/{cs}")
        raise RuntimeError(f"POST replacement {p_name}: {r.status_code} {r.text[:400]}")
    new_id = r.json()["information"]["objectId"]
    resp = r.json()
    fids = [f["id"] for f in resp.get("forms",[]) if f.get("id")]
    if fids:
        m.s.patch(f"{m.base}/api/model/dataModels/{MODEL_ID}/attributes/{new_id}?changesetId={cs}",
                  json={"displays":{"reportDisplays":[{"id":fid} for fid in fids],
                                    "browseDisplays": [{"id":fid} for fid in fids]}})
    bm.commit_cs(m, cs)
    print(f"  [merge] {p_name} replaced with expressions on {len(all_table_exprs)} tables -> {new_id}", file=sys.stderr)
    return new_id

for parent_tc, child_tcs in by_parent.items():
    parent_ids[parent_tc] = merge_parent_to_facts_bulk(parent_tc, child_tcs)

# ── Phase 2: delete the FK-side attributes we merged away ─────────────────────
print("\n── Phase 2: deleting FK-side duplicate attributes ──", file=sys.stderr)
for fk in fk_to_delete:
    aid, name = attr_for(fk)
    delete_attr(aid, name)

# ── Phase 3: pick a PK attribute per fact table for the child side of rels ───
# Map fact table -> primary key attribute name from the dictionary
# (We consider the <Friendly Col> without table suffix as canonical PK candidates.)
FACT_PK = {
    "SD_TECH_PENGUIN_20260413_2145_OPPORTUNITIES":   "Opportunity ID",
    "SD_TECH_PENGUIN_20260413_2145_PURCHASE_ORDERS": "PO Number",
}
# Re-fetch attrs_by_name after deletions
r = m.get(f"/api/folders/{schema_folder}?limit=500")
folder_items = r.json()
attrs_by_name = {it["name"]: it["id"] for it in folder_items if it.get("subtype") == 3072}

print("\n── Phase 3: creating relationships ──", file=sys.stderr)
cs = bm.open_cs(m)
rels_ok = 0
for rel in explicit_rels:
    p_id   = parent_ids[rel["parent"]]
    fact_t = rel["child"].split(".")[0]
    pk_name = FACT_PK.get(fact_t)
    if not pk_name:
        print(f"  SKIP {rel['parent']}→{rel['child']}: no PK known for {fact_t}", file=sys.stderr)
        continue
    c_id = attrs_by_name.get(pk_name)
    if not c_id:
        print(f"  SKIP: child PK attr '{pk_name}' not found", file=sys.stderr)
        continue
    join_tid = tables_by_name[rel["relationship_table"]]
    body = {"relationships":[{
        "parent":{"objectId": p_id, "subType":"attribute"},
        "child": {"objectId": c_id, "subType":"attribute"},
        "relationshipType": rel.get("type","one_to_many"),
        "relationshipTable":{"objectId": join_tid, "subType":"logical_table"},
    }]}
    r = m.put(f"/api/model/dataModels/{MODEL_ID}/attributes/{c_id}/relationships?changesetId={cs}", json=body)
    if r.ok:
        rels_ok += 1
        print(f"  [rel] {rel['parent']} → {pk_name} (via {rel['relationship_table']})", file=sys.stderr)
    else:
        print(f"  [rel] WARN: {r.status_code} {r.text[:300]}", file=sys.stderr)
bm.commit_cs(m, cs)

# ── Republish ─────────────────────────────────────────────────────────────────
r = m.post(f"/api/cubes/{MODEL_ID}", json={})
print(f"\n[republish] HTTP {r.status_code}", file=sys.stderr)

print(f"\n{'='*60}\nRelationships created: {rels_ok}/{len(explicit_rels)}\n{'='*60}")
