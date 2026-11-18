-- The Daily Drive upgrade (2026-11-18): a stable puzzle per day, answer rarity, and the missed-guess log.
--
-- daily_drive_puzzles: the day's puzzle, frozen the first time it is built. Before this a redeploy rebuilt the day
--   from newer data and could swap prompts mid-day (seen on 2026-11-17). Written once per day (INSERT ... ON CONFLICT
--   DO NOTHING), read on every cold start.
-- daily_drive_picks: how many saved games named each answer, for "only 6% of players named him" on the end screen.
--   Counted only when a NEW score row is saved (one per account/device per day), from the server-verified answer
--   tokens, so nobody can inflate a count by replaying.
-- daily_drive_misses: rejected guesses, normalized (lowercase letters/digits/spaces, max 40 chars) and counted per
--   prompt. No account or device is stored. Read by tools/dd_misses.py to find missing answers and nicknames.
--
-- Additive only. RLS on, no policies: only the app's own DATABASE_URL connection can read or write.

CREATE TABLE IF NOT EXISTS public.daily_drive_puzzles (
    game_date  date PRIMARY KEY,
    puzzle     jsonb NOT NULL,
    created_at double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS public.daily_drive_picks (
    game_date date NOT NULL,
    prompt_id text NOT NULL,
    answer_id text NOT NULL,
    n         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (game_date, prompt_id, answer_id)
);

CREATE TABLE IF NOT EXISTS public.daily_drive_misses (
    game_date date NOT NULL,
    prompt_id text NOT NULL,
    guess     text NOT NULL CHECK (char_length(guess) BETWEEN 1 AND 40),
    n         integer NOT NULL DEFAULT 0,
    PRIMARY KEY (game_date, prompt_id, guess)
);

ALTER TABLE public.daily_drive_puzzles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_drive_picks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_drive_misses ENABLE ROW LEVEL SECURITY;
