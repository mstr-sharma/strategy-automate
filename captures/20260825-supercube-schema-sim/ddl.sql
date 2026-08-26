-- SuperCube -> schema simulation tables (Neon PG, neondb.public)
-- Star topology:
--   fact SEMI_PARAMETRIC_MEASUREMENTS  grain: device x test insertion x test (raw measurement)
--   dim  SEMI_TEST_CATALOG             grain: test (spec limits live here)
--   ops  SEMI_LIMIT_OVERRIDES          grain: test (write-back target for the "choose your stat limit" transaction UX)
-- Identifiers quoted UPPERCASE to byte-match Studio column-name conventions.

DROP TABLE IF EXISTS "SEMI_PARAMETRIC_MEASUREMENTS";
DROP TABLE IF EXISTS "SEMI_LIMIT_OVERRIDES";
DROP TABLE IF EXISTS "SEMI_TEST_CATALOG";

CREATE TABLE "SEMI_TEST_CATALOG" (
    "TEST_NUM"      integer PRIMARY KEY,
    "TEST_NAME"     text NOT NULL UNIQUE,
    "TEST_CATEGORY" text NOT NULL,
    "UNITS"         text NOT NULL,
    "LSL"           numeric(14,6) NOT NULL,
    "USL"           numeric(14,6) NOT NULL,
    "TARGET_VALUE"  numeric(14,6) NOT NULL,
    "SPEC_REV"      text NOT NULL
);

CREATE TABLE "SEMI_PARAMETRIC_MEASUREMENTS" (
    "MEASUREMENT_ID" bigint PRIMARY KEY,
    "LOT_ID"         text NOT NULL,
    "WAFER_ID"       text NOT NULL,
    "DEVICE_ID"      text NOT NULL,
    "SITE_NUM"       smallint NOT NULL,
    "TESTER_ID"      text NOT NULL,
    "TEST_PROGRAM"   text NOT NULL,
    "TEST_STAGE"     text NOT NULL,
    "TEST_DATE"      date NOT NULL,
    "TEST_NUM"       integer NOT NULL REFERENCES "SEMI_TEST_CATALOG"("TEST_NUM"),
    "TEST_NAME"      text NOT NULL,
    "FLOAT_VALUE"    numeric(14,6) NOT NULL,
    "IS_PASS"        smallint NOT NULL
);

CREATE INDEX "IX_SEMI_MEAS_TEST" ON "SEMI_PARAMETRIC_MEASUREMENTS" ("TEST_NUM");
CREATE INDEX "IX_SEMI_MEAS_LOT"  ON "SEMI_PARAMETRIC_MEASUREMENTS" ("LOT_ID");
CREATE INDEX "IX_SEMI_MEAS_DATE" ON "SEMI_PARAMETRIC_MEASUREMENTS" ("TEST_DATE");

CREATE TABLE "SEMI_LIMIT_OVERRIDES" (
    "OVERRIDE_ID"  integer PRIMARY KEY,
    "TEST_NUM"     integer NOT NULL REFERENCES "SEMI_TEST_CATALOG"("TEST_NUM"),
    "LIMIT_METHOD" text NOT NULL,
    "MANUAL_LSL"   numeric(14,6),
    "MANUAL_USL"   numeric(14,6),
    "CHOSEN_BY"    text NOT NULL,
    "CHOSEN_AT"    timestamptz NOT NULL
);
