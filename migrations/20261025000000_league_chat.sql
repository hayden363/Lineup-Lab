-- League chat: verified members of the same Sleeper league talk to each other.
--
-- Design notes (docs/superpowers/specs/2026-10-25-league-chat-design.md):
--   * Membership is its own table. connected_teams accepts any roster_id for any
--     league, so "connected the same league" proves nothing about ownership.
--   * external_id is the Sleeper user_id proven through the team-name challenge;
--     UNIQUE (platform, league_id, external_id) stops two accounts claiming one
--     Sleeper user in the same league.
--   * Every table that references users cascades, so deleting an account removes
--     that person's memberships, messages, reports and challenges.
--   * Same RLS stance as every other public table: RLS on, no policies, so only
--     the app's own DATABASE_URL connection reads or writes.
--   * Timestamps are double precision epoch seconds, like the rest of the schema.

CREATE TABLE public.league_chat_members (
    user_id     integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    platform    text    NOT NULL,
    league_id   text    NOT NULL,
    external_id text    NOT NULL,
    role        text    NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'moderator')),
    muted_until double precision,
    joined_at   double precision NOT NULL,
    PRIMARY KEY (user_id, platform, league_id),
    UNIQUE (platform, league_id, external_id)
);

CREATE TABLE public.league_messages (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform   text    NOT NULL,
    league_id  text    NOT NULL,
    user_id    integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    body       text    NOT NULL CHECK (char_length(body) BETWEEN 1 AND 500),
    created_at double precision NOT NULL,
    deleted_at double precision
);

-- The poll reads one league's messages after the last id seen.
CREATE INDEX league_messages_league_id
    ON public.league_messages (platform, league_id, id);

CREATE TABLE public.league_message_reports (
    message_id  bigint  NOT NULL REFERENCES public.league_messages (id) ON DELETE CASCADE,
    reporter_id integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    created_at  double precision NOT NULL,
    PRIMARY KEY (message_id, reporter_id)
);

CREATE TABLE public.league_chat_challenges (
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
    platform   text    NOT NULL,
    league_id  text    NOT NULL,
    token      text    NOT NULL,
    created_at double precision NOT NULL,
    used_at    double precision
);

CREATE INDEX league_chat_challenges_lookup
    ON public.league_chat_challenges (user_id, platform, league_id, token);

ALTER TABLE public.league_chat_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.league_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.league_message_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.league_chat_challenges ENABLE ROW LEVEL SECURITY;
