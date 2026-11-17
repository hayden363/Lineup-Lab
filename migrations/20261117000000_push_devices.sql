-- iOS app push notifications: one row per device (APNs token). Written only by POST /api/push/register for a
-- signed-in account; removed on sign-out, when APNs reports the token gone, or with the account (ON DELETE CASCADE).
-- Additive only. Same RLS stance as every other public table: RLS on, no policies, so only the app's own
-- DATABASE_URL connection can read or write it.

CREATE TABLE IF NOT EXISTS public.push_devices (
    token          text PRIMARY KEY CHECK (char_length(token) BETWEEN 32 AND 200),
    user_id        integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    platform       text    NOT NULL DEFAULT 'ios' CHECK (platform IN ('ios')),
    environment    text    NOT NULL DEFAULT 'production' CHECK (environment IN ('production', 'sandbox')),
    drive_reminder boolean NOT NULL DEFAULT TRUE,     -- "today's Daily Drive is live" once a day, if not played
    lineup_alerts  boolean NOT NULL DEFAULT TRUE,     -- a starter ruled out / questionable
    created_at     double precision NOT NULL,
    updated_at     double precision NOT NULL
);

CREATE INDEX IF NOT EXISTS push_devices_user_idx ON public.push_devices (user_id);

ALTER TABLE public.push_devices ENABLE ROW LEVEL SECURITY;
