-- Monthly owner report + "last seen".
--
--   * users.last_seen_at: epoch seconds of the last time the account opened the app,
--     written at most once a day per person (engine/db.py touch_last_seen). Lets the
--     monthly report say how many people actually came back. NULL = not seen since
--     this column existed.
--   * report_log: one row per month already emailed to the owner. The row is inserted
--     BEFORE sending (ON CONFLICT DO NOTHING), so two app instances, a restart or a
--     deploy can never send the same month twice; it is deleted again if the send fails.
--
-- Additive only: nothing existing is changed. Same RLS stance as every other public
-- table: RLS on, no policies, so only the app's own DATABASE_URL connection can use it.

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS last_seen_at double precision;

CREATE TABLE IF NOT EXISTS public.report_log (
    period    text PRIMARY KEY,                 -- e.g. '2026-10'
    sent_at   double precision NOT NULL,
    recipient text NOT NULL
);
ALTER TABLE public.report_log ENABLE ROW LEVEL SECURITY;
