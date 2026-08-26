-- Trim-proof override surface: one row per test, latest override attached
-- (LEFT JOIN), NULLs where no decision exists. The Manual LSL/USL facts and
-- the Limit Method attribute bind here instead of the sparse write-back table,
-- so cube SQL can never intersect the test list down.
CREATE OR REPLACE VIEW "SEMI_ACTIVE_LIMITS" AS
SELECT c."TEST_NUM",
       o."LIMIT_METHOD",
       o."MANUAL_LSL",
       o."MANUAL_USL",
       o."CHOSEN_BY",
       o."CHOSEN_AT"
FROM "SEMI_TEST_CATALOG" c
LEFT JOIN LATERAL (
    SELECT ov."LIMIT_METHOD", ov."MANUAL_LSL", ov."MANUAL_USL",
           ov."CHOSEN_BY", ov."CHOSEN_AT"
    FROM "SEMI_LIMIT_OVERRIDES" ov
    WHERE ov."TEST_NUM" = c."TEST_NUM"
    ORDER BY ov."CHOSEN_AT" DESC
    LIMIT 1
) o ON true;

SELECT count(*) AS view_rows,
       count("LIMIT_METHOD") AS with_override,
       count("MANUAL_USL") AS with_manual_usl
FROM "SEMI_ACTIVE_LIMITS";
