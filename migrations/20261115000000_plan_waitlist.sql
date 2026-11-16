-- Waitlist for the paid plans (Manager: 3-4 leagues, Commissioner: 5+ leagues).
--
-- One row per (email, plan); a repeat sign-up is a no-op (ON CONFLICT DO NOTHING in
-- engine/db.py add_waitlist). No account is needed, so there is no user_id. Emails are only
-- used to tell people when a plan opens.
--
-- Additive only. Same RLS stance as every other public table: RLS on, no policies, so only the
-- app's own DATABASE_URL connection can read or write it.

CREATE TABLE IF NOT EXISTS public.plan_waitlist (
    email      text NOT NULL,
    plan       text NOT NULL CHECK (plan IN ('manager', 'commissioner')),
    created_at double precision NOT NULL,
    PRIMARY KEY (email, plan)
);
ALTER TABLE public.plan_waitlist ENABLE ROW LEVEL SECURITY;
