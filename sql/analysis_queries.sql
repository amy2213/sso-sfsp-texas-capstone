-- SSO vs SFSP Texas Capstone
-- analysis_queries.sql
--
-- These queries run against the clean master tables produced by
-- scripts/01_ingest_clean_audit.py.
--
-- IMPORTANT: "meals" throughout this file means REPORTED MEALS SERVED
-- (i.e., meal counts as reported to TDA). They are NOT a count of
-- unique children served. A child receiving breakfast and lunch on the
-- same day counts as two meals.

-- ---------------------------------------------------------------
-- 1. Total reported meals by year and program
-- ---------------------------------------------------------------
SELECT
    program_year,
    program_type,
    COUNT(*)             AS records,
    SUM(total_meals)     AS total_reported_meals
FROM summer_meals_master
GROUP BY program_year, program_type
ORDER BY program_year, program_type;

-- ---------------------------------------------------------------
-- 2. Year-over-year SSO reported-meal growth
-- ---------------------------------------------------------------
WITH sso_by_year AS (
    SELECT
        program_year,
        SUM(total_meals) AS total_reported_meals
    FROM summer_meals_master
    WHERE program_type = 'SSO'
    GROUP BY program_year
)
SELECT
    program_year,
    total_reported_meals,
    LAG(total_reported_meals) OVER (ORDER BY program_year) AS prior_year_reported_meals,
    total_reported_meals
        - LAG(total_reported_meals) OVER (ORDER BY program_year) AS yoy_change,
    CASE
        WHEN LAG(total_reported_meals) OVER (ORDER BY program_year) IS NULL THEN NULL
        WHEN LAG(total_reported_meals) OVER (ORDER BY program_year) = 0   THEN NULL
        ELSE 1.0 * (total_reported_meals
                    - LAG(total_reported_meals) OVER (ORDER BY program_year))
            / LAG(total_reported_meals) OVER (ORDER BY program_year)
    END AS yoy_pct_change
FROM sso_by_year
ORDER BY program_year;

-- ---------------------------------------------------------------
-- 3. Reported meals per site by program and year
-- ---------------------------------------------------------------
SELECT
    program_year,
    program_type,
    COUNT(DISTINCT site_id)                                   AS distinct_sites,
    SUM(total_meals)                                          AS total_reported_meals,
    1.0 * SUM(total_meals) / NULLIF(COUNT(DISTINCT site_id), 0) AS meals_per_site
FROM summer_meals_master
WHERE site_id IS NOT NULL
GROUP BY program_year, program_type
ORDER BY program_year, program_type;

-- ---------------------------------------------------------------
-- 4. Reported meals per service day by program and year
-- ---------------------------------------------------------------
SELECT
    program_year,
    program_type,
    SUM(total_meals)                                AS total_reported_meals,
    SUM(service_days)                               AS total_service_days,
    1.0 * SUM(total_meals) / NULLIF(SUM(service_days), 0) AS meals_per_service_day
FROM summer_meals_master
WHERE service_days IS NOT NULL
GROUP BY program_year, program_type
ORDER BY program_year, program_type;

-- ---------------------------------------------------------------
-- 5. Meal-type mix by program (share of breakfast / lunch / snack / supper)
-- ---------------------------------------------------------------
SELECT
    program_type,
    SUM(breakfast_meals)                                              AS breakfast_meals,
    SUM(lunch_meals)                                                  AS lunch_meals,
    SUM(snack_meals)                                                  AS snack_meals,
    SUM(supper_meals)                                                 AS supper_meals,
    1.0 * SUM(breakfast_meals) / NULLIF(SUM(total_meals), 0)          AS breakfast_share,
    1.0 * SUM(lunch_meals)     / NULLIF(SUM(total_meals), 0)          AS lunch_share,
    1.0 * SUM(snack_meals)     / NULLIF(SUM(total_meals), 0)          AS snack_share,
    1.0 * SUM(supper_meals)    / NULLIF(SUM(total_meals), 0)          AS supper_share
FROM summer_meals_master
GROUP BY program_type
ORDER BY program_type;

-- ---------------------------------------------------------------
-- 6. Breakfast-to-lunch ratio by year and program
-- ---------------------------------------------------------------
SELECT
    program_year,
    program_type,
    SUM(breakfast_meals)                                       AS breakfast_meals,
    SUM(lunch_meals)                                           AS lunch_meals,
    1.0 * SUM(breakfast_meals) / NULLIF(SUM(lunch_meals), 0)   AS breakfast_to_lunch_ratio
FROM summer_meals_master
GROUP BY program_year, program_type
ORDER BY program_year, program_type;

-- ---------------------------------------------------------------
-- 7. Reimbursement per reported meal by year
-- ---------------------------------------------------------------
SELECT
    program_year,
    program_type,
    SUM(reimbursement_amount)                                            AS total_reimbursement,
    SUM(total_meals)                                                     AS total_reported_meals,
    1.0 * SUM(reimbursement_amount) / NULLIF(SUM(total_meals), 0)        AS reimbursement_per_reported_meal
FROM reimbursements_master
GROUP BY program_year, program_type
ORDER BY program_year, program_type;

-- ---------------------------------------------------------------
-- 8. Top 20 CEs by reported meals
-- ---------------------------------------------------------------
SELECT
    ce_id,
    ce_name,
    program_type,
    SUM(total_meals) AS total_reported_meals
FROM summer_meals_master
WHERE ce_name IS NOT NULL
GROUP BY ce_id, ce_name, program_type
ORDER BY total_reported_meals DESC
LIMIT 20;

-- ---------------------------------------------------------------
-- 9. Top 20 CEs by reimbursement amount
-- ---------------------------------------------------------------
SELECT
    ce_id,
    ce_name,
    program_type,
    SUM(reimbursement_amount) AS total_reimbursement
FROM reimbursements_master
WHERE ce_name IS NOT NULL
GROUP BY ce_id, ce_name, program_type
ORDER BY total_reimbursement DESC
LIMIT 20;

-- ---------------------------------------------------------------
-- 10. Data-quality flags summary across both master tables
-- ---------------------------------------------------------------
WITH meal_flags AS (
    SELECT 'summer_meals_master' AS table_name, data_quality_flags
    FROM summer_meals_master
),
reimb_flags AS (
    SELECT 'reimbursements_master' AS table_name, data_quality_flags
    FROM reimbursements_master
),
combined AS (
    SELECT * FROM meal_flags
    UNION ALL
    SELECT * FROM reimb_flags
)
SELECT
    table_name,
    data_quality_flags,
    COUNT(*) AS records
FROM combined
GROUP BY table_name, data_quality_flags
ORDER BY table_name, records DESC;
