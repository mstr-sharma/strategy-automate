# Mosaic builder rebuild: plan, apply, prove

Status: proposed 2026-10-22. Replaces `cmd_build` in `scripts/build_mosaic.py` once the live matrix (step 4) passes.

## Why

Builds fail on shapes nobody ran live, one at a time: a key spelled `SHIPMENT_ID` in Snowflake and `shipment_id` in
Postgres; one explicit relationship switching relationship inference off. Two causes sit underneath every one of them.

1. **Deciding and writing are the same step.** `cmd_build` (≈700 lines) infers the model while it posts to Strategy, so
   a wrong design is discovered by Strategy answering 400 halfway through, after a model already exists.
2. **The model is designed twice.** Ace drafts a full specification (attributes, forms, keys, relationships), then hands
   the builder a dictionary and the builder infers the model again from column names. The two disagree at the seams.

And the tests run against a fake tenant, so "the tests pass" has never meant "a real model answers questions".

## The shape

```
introspect ──► catalog ──► plan ──► check ──► apply ──► read back ──► publish ──► prove
 (REST)       (pure)     (pure)   (pure)    (REST)     (REST, diff)   (REST)    (SQL vs source)
```

- **Catalog** (pure data): every selected table with its datasource, store type, exact column names and types. Column
  identity is case-insensitive; each table keeps its own spelling. Any source the Strategy catalog API can describe
  works the same way: there is no per-store code above this layer.
- **Plan** (pure data, JSON, diffable): attributes with one form expression per table *in that table's spelling*,
  lookup tables, fact metrics with aggregation and format, relationships with their relationship table, derived and
  conditional metrics, serve mode. Ace's specification maps onto the plan one to one; when Ace sends a plan, the
  builder infers nothing. Inference (keys, conformance, descriptors) only fills a plan when no specification is given,
  and explicit relationships are added to inferred ones, never a switch between them.
- **Check** (pure, before anything is written). A plan that breaks one of these is refused, in words, with Strategy
  untouched:
  - every relationship's parent and child are both on its relationship table;
  - relationships form no cycle, and no pair is written in both directions;
  - every descriptor reaches its table's key;
  - **every dimension name reaches every fact table that carries its key** (the path check: "Amount by Customer Name"
    has a route);
  - conformed keys have joinable types across stores (integer vs decimal vs text is flagged);
  - names are unique per object type; aggregations fit the column (no SUM of an ID, no SUM of a rate);
  - in-memory vs live is allowed for the stores selected.
- **Apply**: write the plan through the REST API in one changeset per phase, each write idempotent by name, so a retry
  after a lost response converges instead of duplicating.
- **Read back**: fetch the model from Strategy and diff it against the plan. Any difference is a build failure, named
  object by object. "Built" means Strategy holds exactly the plan.
- **Publish**: wait on Strategy's own status with a deadline scaled to the data size, not a fixed 180 seconds.
- **Prove**: for every dimension × fact path, run a real query on the model's SQL surface (a metric by a name
  attribute), and run the same aggregate directly against the source tables. Totals and row counts must match. A model
  is "ready" only when every probe matches; the report says which ones did.

## The live matrix (the gate)

A runner that, on studio, takes table sets from every datasource the account can reach (Snowflake, Postgres,
BigQuery and whatever else the catalog lists): single-store sets, cross-store sets that share a key, keys in different
case, explicit hierarchies, live and in-memory. For each it runs plan → check → apply → read back → publish → prove,
records the result under `captures/`, and deletes the models it made. Random table subsets are drawn each run, so it
keeps finding shapes nobody wrote down. **No Ace kit ships unless the latest matrix run passes.**

## Steps

1. Live harness and sign-in: list datasources and tables, run one existing build end to end, capture it.
2. Catalog, plan and check as a pure library, with unit tests built from real captured catalogs (today's freight
   tables first). Both of this week's failures become check failures before any write.
3. Apply, read back and diff; publish wait; prove with source comparison.
4. The live matrix runner; run it until it passes; wire it as the release gate for Ace kits.
5. Ace sends its specification as the plan; the Model Designer shows the check result before Build, and the Terminal
   turns a failed check or probe into a proposed fix (a plan change, applied with one confirmation, then proven again).
   The plan is the editing surface, before and after a build:
   - every item says where it came from (the draft, a key found in the data, a relationship the person added), and
     any suggestion can be switched off; the check runs again on every change and says what it costs ("Region then
     reaches no metric");
   - a person edits it directly (rename, change an aggregation, move a form, add or remove a relationship) or tells
     the Terminal, which proposes the same edits as a plan change the person reviews before it is applied;
   - an existing model reads back into a plan, so editing a built model is the same flow: change the plan, check,
     apply only the difference, prove again.
6. Remove the old `cmd_build` path once Ace runs only on the new one.

New Ace features wait until step 4 passes.
