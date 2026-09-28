-- activation_events: the event behind LineUp Lab's activation metric.
--
-- NOT YET APPLIED. Schema lives in Supabase migrations (see engine/db.py
-- init_db), and this touches the live database, so it's applied deliberately,
-- not on deploy. The app already tolerates the table being absent:
-- /api/trade-finder treats a failed insert as non-fatal and just logs it.
--
-- Written to this database's real conventions, verified against the live
-- schema on 2026-09-28 rather than assumed:
--   * users.id is integer GENERATED ALWAYS AS IDENTITY -> user_id integer.
--   * every timestamp here is double precision epoch seconds (users.created_at,
--     sessions.expires_at, predictions.created_at...) -> occurred_at matches,
--     so the metric's 24h window is simple arithmetic against created_at.
--   * the app authenticates with its own users table, not Supabase Auth, so an
--     auth.uid() policy would never match anything. Same as every other public
--     table (migration enable_rls_on_public_tables): RLS on, no policies, so
--     the anon/authenticated roles see nothing and the app's own DATABASE_URL
--     connection is the only reader and writer.

CREATE TABLE public.activation_events (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    event_name  text    NOT NULL,
    league_id   text    NOT NULL,
    occurred_at double precision NOT NULL,
    -- First occurrence only per user/league/event: repeat Trade Finder views
    -- can't inflate the metric. The app inserts with ON CONFLICT DO NOTHING.
    CONSTRAINT activation_events_first_occurrence UNIQUE (user_id, league_id, event_name)
);

-- The activation query filters on user_id and event_name (equality) and
-- occurred_at (range). Equality columns first keeps it a narrow index scan.
CREATE INDEX activation_events_user_event_time
    ON public.activation_events (user_id, event_name, occurred_at);

ALTER TABLE public.activation_events ENABLE ROW LEVEL SECURITY;
