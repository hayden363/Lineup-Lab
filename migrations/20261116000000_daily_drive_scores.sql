-- The Daily Drive: one saved score per finished daily game.
--
-- A row is written only by POST /api/play/score, and only after the server has verified the signed answer tokens
-- and recomputed the yards itself (engine/daily_drive_scores.py), so the browser can't post a made-up score.
--
-- A game is identified by who played it: a signed-in account (user_id) and/or an anonymous browser (device_hash =
-- sha256 of a random id the page keeps in localStorage). One score per (day, account) and one per (day, device);
-- a repeat submit is a no-op (INSERT ... ON CONFLICT DO NOTHING in engine/db.py save_drive_score).
--
-- Additive only. Same RLS stance as every other public table: RLS on, no policies, so only the app's own
-- DATABASE_URL connection can read or write it.

CREATE TABLE IF NOT EXISTS public.daily_drive_scores (
    id          bigserial PRIMARY KEY,
    game_date   date NOT NULL,                                       -- the US Eastern day that was played
    user_id     integer REFERENCES public.users (id) ON DELETE CASCADE,
    device_hash text,
    yards       integer NOT NULL CHECK (yards BETWEEN 0 AND 700),
    tiers       smallint[] NOT NULL CHECK (cardinality(tiers) BETWEEN 1 AND 12),   -- per prompt: 1-6, 0 = sacked
    created_at  double precision NOT NULL,
    CHECK (user_id IS NOT NULL OR device_hash IS NOT NULL)
);

-- one score per day per account, and one per day per browser
CREATE UNIQUE INDEX IF NOT EXISTS daily_drive_scores_day_user_uq
    ON public.daily_drive_scores (game_date, user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS daily_drive_scores_day_device_uq
    ON public.daily_drive_scores (game_date, device_hash) WHERE device_hash IS NOT NULL;
-- "my past scores" (newest first)
CREATE INDEX IF NOT EXISTS daily_drive_scores_user_idx
    ON public.daily_drive_scores (user_id, game_date DESC) WHERE user_id IS NOT NULL;

ALTER TABLE public.daily_drive_scores ENABLE ROW LEVEL SECURITY;
