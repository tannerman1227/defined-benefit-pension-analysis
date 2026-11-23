-- Census checks a PRT pricing analyst would run on the tape before
-- sending it to the pricing model. The table name is `census`.
-- These queries reconcile to pension.validation; they are not a second opinion
-- with different rules.

-- @@benefit_by_status
SELECT status,
       COUNT(*) AS participants,
       ROUND(SUM(CASE WHEN annual_benefit > 0 THEN annual_benefit ELSE 0 END), 2) AS positive_annual_benefit,
       ROUND(AVG(age), 2) AS average_age
FROM census
GROUP BY status
ORDER BY status;

-- @@formula_outliers
SELECT participant_id,
       age,
       service_years,
       final_average_pay,
       annual_benefit,
       ROUND(annual_benefit / (final_average_pay * service_years), 6) AS implied_accrual_rate
FROM census
WHERE status = 'active'
  AND COALESCE(service_years, 0) > 0
  AND COALESCE(final_average_pay, 0) > 0
  AND COALESCE(annual_benefit, 0) > 0
  AND ABS(annual_benefit / (final_average_pay * service_years) - 0.015) > 0.002
ORDER BY participant_id;

-- @@joint_life_missing_spouse
SELECT participant_id,
       status,
       payment_form,
       spouse_date_of_birth,
       spouse_sex
FROM census
WHERE payment_form IN ('JS50', 'JS100')
  AND (spouse_date_of_birth IS NULL OR TRIM(spouse_date_of_birth) = '')
ORDER BY participant_id;

-- @@duplicate_ids
SELECT participant_id,
       COUNT(*) AS rows_with_this_id
FROM census
GROUP BY participant_id
HAVING COUNT(*) > 1
ORDER BY participant_id;
