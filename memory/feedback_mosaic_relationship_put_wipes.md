---
name: PUT /attributes/{id}/relationships REPLACES the full set in both directions
description: Strategy's relationship PUT is not append-only — it wipes incoming AND outgoing rels on the target attribute. Always go through the merge helper or set --replace explicitly.
type: feedback
---

## The trap

`PUT /api/model/dataModels/{model_id}/attributes/{attr_id}/relationships` is a
full-replace operation: whatever set of relationships you send becomes the
attribute's entire relationship inventory. Strategy does NOT diff against the
existing set, does NOT append, and does NOT respect direction. If you PUT
attribute A with only its outgoing relationships, every incoming relationship
that previously pointed AT A is silently deleted.

This burned hours on a TPC-DS Galaxy build: Level-B relationships wired
successfully; then Level-A wiring re-PUT to the same shared FK attributes
without the previously-written Level-B rels, and the entire Level-B set was
wiped with no error and no log line. The exit code was 0.

## The fix

Use the `put_relationships_merged()` helper in `skill/scripts/build_mosaic.py`
instead of raw PUT. It:

1. `GET`s the attribute's current relationships.
2. Dedupes by `(parent_objectId, child_objectId, relationship_table_objectId)`.
3. PUTs the union — both old + new.

`cmd_wire_relationships` now groups plan rows by child attribute and uses the
merge helper by default. The destructive mode is opt-in via `--replace`.

## When to use --replace

- Cleanup: you want to wipe a known-bad relationship graph and rebuild from a
  fresh hints file.
- Migration: you are intentionally replacing the legacy relationship set with
  a new conformed-dim layout and have already saved a `--before-out` snapshot.

Anywhere else, the merge default is correct.

## Detection / pre-flight

Before invoking the wire script, dump existing relationships if you might be
touching previously-wired attributes:

```bash
python3 skill/scripts/build_mosaic.py get-model-object \
  --kind attribute --model-id <id> --object-id <attr-id> \
  --out before/<attr-id>.json
```

After wiring, run topology validation to surface any silent wipes:

```bash
python3 skill/scripts/build_mosaic.py validate-topology \
  --model-id <id> --strict
```

Non-zero exit means there are isolated attributes — which is exactly what a
silent wipe produces.

## Related codes

- `8004ccdb` — relationship self-reference. The parent and child resolve to
  the same conformed attribute object id. Not caused by this wipe but often
  appears alongside it in cleanup scripts.

## See also

- `memory/feedback_mosaic_relationship_wiring.md` — six-step Kimball recipe.
- `memory/reference_strategy_error_codes.md` — error-code index.
