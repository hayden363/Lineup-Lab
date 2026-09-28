-- LineUp Lab activation rate, by reporting week.
--
-- Canonical definition (locked 2026-09-21, resolving a 24h-vs-48h conflict
-- between two earlier drafts):
--   Activation is the percentage of users whose 24-hour post-registration
--   window closes in the reporting week who successfully sync a real Sleeper
--   or ESPN league and view a non-empty generated Trade Finder result for that
--   league within that window.
--
-- How the pieces map to that:
--   * registration time   = users.created_at (epoch seconds)
--   * the window          = [created_at, created_at + 86400)
--   * "sync + non-empty"  = a trade_finder_result_viewed row. The server only
--                           records it for the user's own connected league and
--                           only when suggestions came back non-empty (server.py
--                           api_trade_finder), so the row implies both.
--   * denominator         = users whose window has fully CLOSED. Someone who
--                           signed up 3 hours ago isn't counted as a failure yet
--                           — counting them would bias the rate downward.
--   * reporting week      = the week the window closes in, not the signup week.
--
-- CAVEAT: users who registered before activation_events existed have no events
-- and will read as not activated. Only cohorts whose window opened after the
-- migration and the server change were both live mean anything; set
-- instrumented_since in `params` below to that epoch to exclude the earlier
-- ones. (A CTE rather than a psql :variable, so this runs as-is in Supabase's
-- SQL editor, which doesn't support psql variables.)

WITH params AS (
    SELECT 0::double precision AS instrumented_since   -- <- set to go-live epoch
),
cohort AS (
    SELECT u.id                   AS user_id,
           u.created_at           AS registered_at,
           u.created_at + 86400   AS window_close
    FROM public.users u, params p
    WHERE u.created_at + 86400 <= EXTRACT(EPOCH FROM now())
      AND u.created_at >= p.instrumented_since
),
graded AS (
    SELECT c.user_id,
           date_trunc('week', to_timestamp(c.window_close)) AS reporting_week,
           EXISTS (
               SELECT 1
               FROM public.activation_events e
               WHERE e.user_id = c.user_id
                 AND e.event_name = 'trade_finder_result_viewed'
                 AND e.occurred_at >= c.registered_at
                 AND e.occurred_at <  c.window_close
           ) AS activated
    FROM cohort c
)
SELECT reporting_week,
       COUNT(*)                                   AS cohort_size,
       COUNT(*) FILTER (WHERE activated)          AS activated,
       ROUND(100.0 * COUNT(*) FILTER (WHERE activated) / COUNT(*), 1) AS activation_pct
FROM graded
GROUP BY reporting_week
ORDER BY reporting_week DESC;
