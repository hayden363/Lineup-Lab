"""
FANTASY APP — API SERVER
=========================
FastAPI wrapper around the engine/ package. Serves JSON to the frontend
in static/ and hosts that frontend itself (single-process, single-command
local app).

RUN:
    source .venv/bin/activate
    uvicorn server:app --reload --port 8420

Then open http://localhost:8420

SECURITY POSTURE (see README for the full writeup):
  - bcrypt password hashing, cryptographically random session tokens
  - httponly + SameSite=Lax session cookies, auto-`Secure` when served over https
  - ESPN cookies encrypted at rest (engine/crypto.py), never echoed back to the client
  - rate limiting on auth endpoints (login/signup/resend/forgot-password/
    reset-password) and on unauthenticated-but-expensive ones (refresh,
    per-player news) so a public launch isn't wide open to abuse
  - standard hardening response headers (nosniff, frame-deny, referrer policy)
  - no wildcard CORS — this process serves its own frontend, same-origin only
  - parameterized SQL everywhere (see engine/db.py); no string-built queries
  - this is a LAN-local dev app, not TLS-terminated — see README before
    exposing it beyond your own network
"""

import hashlib
import math
import os
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from engine import chat as chat_layer
from engine import correlation
from engine import data as data_layer
from engine import db
from engine import espn as espn_layer
from engine import external_projections as external_projections_layer
from engine import league_trades as league_trades_layer
from engine import boxscore as boxscore_layer
from engine import schemas
from engine import live_scores as live_scores_layer
from engine import locks
from engine import waivers as waivers_layer
from engine import lineup_advisor
from engine import ros_projection
from engine import startsit_ai
from engine import mail as mail_layer
from engine import news as news_layer
from engine import oauth as oauth_layer
from engine import projection_blend
from engine import refresh_scheduler
from engine import sleeper as sleeper_layer
from engine import tools
from engine.advanced import ADVANCED_COLS
from engine.profile import upcoming_week
from engine.board import (POSITIONS, build_board, overall_board, load_bundle, matchup_multiplier,
                           player_detail, project_vs, search_players)
from engine.metrics import WEIGHTS
from engine.scoring import PRESETS


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Weekly-refresh automation (see engine/refresh_scheduler.py) — starts
    # a background task that periodically force-refreshes the board data
    # so it's never more than REFRESH_INTERVAL_HOURS stale, without
    # needing a separate cron job/launchd plist. Cancelled cleanly on
    # shutdown rather than left to die mid-fetch.
    task = refresh_scheduler.start()
    news_layer.warm()   # fill the news cache in the background so the first visitor isn't the one waiting
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Lineup Lab API", lifespan=lifespan)
# Nothing here was being compressed before — app.js/style.css (~190KB
# combined) and every JSON board response went over the wire raw. gzip
# shrinks text/JSON/JS/CSS by roughly 70-80%; skips anything already
# under 500 bytes (not worth the CPU) and doesn't touch images (already
# compressed formats, gzipping them again just wastes CPU for ~0 gain).
app.add_middleware(GZipMiddleware, minimum_size=500)

SESSION_COOKIE = "eb_session"


# ------------------------------------------------------------- security ----
# Read-only endpoints whose answer is the same for every signed-out visitor
# (the Big Board, a player card, the app's config). Letting a CDN or the
# browser hold them for a few minutes takes most read traffic off the app.
_PUBLIC_CACHE_PATHS = ("/api/meta", "/api/board")
_PUBLIC_CACHE_PLAYER = re.compile(r"^/api/player/[^/]+$")
PUBLIC_CACHE_CONTROL = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"


def _public_cache_headers(request: Request, response: Response) -> None:
    """Cache-Control for the endpoints above, only for a signed-out GET that
    succeeded. Anyone with a session cookie gets no caching header at all: their
    answer depends on their saved scoring and must never be stored or shared.
    Vary: Cookie keeps a shared cache from handing one kind of answer to the other."""
    path = request.url.path
    if request.method != "GET" or response.status_code != 200:
        return
    if path not in _PUBLIC_CACHE_PATHS and not _PUBLIC_CACHE_PLAYER.match(path):
        return
    response.headers.append("Vary", "Cookie")
    if SESSION_COOKIE not in request.cookies and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL


@app.middleware("http")
async def security_headers(request: Request, call_next):
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # log the failed /api/ request too, then re-raise — never swallow
        if request.url.path.startswith("/api/"):
            print(f"[req] method={request.method} path={request.url.path} "
                  f"status=500 ms={int((time.perf_counter() - t0) * 1000)}")
        raise
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    # this app has no external script/style/image dependencies — a strict
    # CSP costs nothing here and blocks injected-script XSS even if a data
    # value somehow slipped past escaping
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    )
    # Real gap found in a security pass: this was missing entirely. Only
    # meaningful (and only sent) once actually served over https — same
    # scheme check the session/OAuth-state cookies already use to decide
    # `Secure` — so plain local dev over http is unaffected. No `preload`:
    # that's a real, harder-to-reverse commitment (submission to browsers'
    # baked-in preload list) worth a deliberate decision, not a default.
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    _public_cache_headers(request, response)
    # request timing: path only (never the query string — league ids must
    # not reach logs); /api/ only so /healthz and static files stay quiet
    if request.url.path.startswith("/api/"):
        print(f"[req] method={request.method} path={request.url.path} "
              f"status={response.status_code} ms={int((time.perf_counter() - t0) * 1000)}")
    return response


# simple in-memory sliding-window rate limiter for the sensitive auth
# endpoints (login/signup/resend/forgot-password) — a single process, local
# app doesn't need a distributed limiter; this is enough to blunt brute
# forcing without adding a dependency
_RATE_BUCKETS: Dict[str, deque] = defaultdict(deque)


def rate_limit(key_prefix: str, limit: int, window_seconds: int):
    def dep(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{key_prefix}:{client_ip}"
        now = time.time()
        bucket = _RATE_BUCKETS[key]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(429, "Too many attempts — wait a bit and try again.")
        bucket.append(now)
    return dep


login_rate_limit = rate_limit("login", limit=10, window_seconds=5 * 60)
signup_rate_limit = rate_limit("signup", limit=5, window_seconds=15 * 60)
mail_rate_limit = rate_limit("mail", limit=3, window_seconds=10 * 60)
oauth_rate_limit = rate_limit("oauth", limit=15, window_seconds=5 * 60)
# reset_password's token is a cryptographically random 256-bit
# secrets.token_urlsafe(32) (see engine/db.py) — not brute-forceable
# regardless — this is defense-in-depth, same reasoning as the other
# auth endpoints above.
reset_rate_limit = rate_limit("reset", limit=10, window_seconds=15 * 60)
# /api/refresh force-refetches everything (nflverse weekly stats, full
# play-by-play, NGS, schedule, snap counts — real network I/O, several
# seconds of work) and had NO auth or limit at all before a public
# launch made that a real concern: unauthenticated + unlimited meant
# anyone could hammer it into a self-inflicted DoS / upstream-rate-limit
# problem. POST /api/refresh still works for anyone within this budget —
# it was never meant to be a privileged endpoint, just a bounded one.
refresh_rate_limit = rate_limit("refresh", limit=3, window_seconds=10 * 60)
# Player news can trigger a real Anthropic API call per distinct player
# (see engine/news.py's ai_summary_for_player — cached per player, but
# the cache doesn't stop someone from cycling through many different
# players). Only matters once ANTHROPIC_API_KEY is actually set; harmless
# either way.
news_rate_limit = rate_limit("news", limit=30, window_seconds=60)
# Same shape as news_rate_limit — one real outbound call to FantasyPros
# per distinct position/week combo (cached an hour, see
# engine/external_projections.py), harmless either way, but only matters
# once FANTASYPROS_API_KEY is actually set.
projcompare_rate_limit = rate_limit("projcompare", limit=30, window_seconds=60)

OAUTH_STATE_COOKIE = "eb_oauth_state"


def _clean(obj: Any) -> Any:
    """Recursively replace NaN/inf with None so the JSON encoder doesn't choke.
    Deliberately untyped input/output (Any) — it walks arbitrary JSON-shaped
    data (dict/list/float/anything else) and preserves whatever shape it's
    given; a precise type here would just be self-referential noise."""
    if hasattr(obj, "item") and type(obj).__module__ == "numpy":
        # A numpy scalar (int64/float64/bool_) from a DataFrame cell: the
        # JSON encoder can't serialize numpy.int64, so one injured player's
        # injury_sample_n used to 500 the whole roster response.
        obj = obj.item()
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


# ------------------------------------------------------------------ auth ----
def current_user(request: Request):
    """Optional auth: returns the signed-in user's public record, or None."""
    return db.get_user_by_session(request.cookies.get(SESSION_COOKIE))


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "sign in required")
    return user


def _set_session_cookie(request: Request, response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=(request.url.scheme == "https"),  # auto-upgrades if this ever sits behind TLS
        max_age=db.SESSION_TTL_SECONDS,
    )


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    identifier: str
    password: str


class DeleteAccountRequest(BaseModel):
    password: str = ""
    confirm: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _send_verification(request: Request, user) -> str:
    """Best-effort: signup never fails because mail isn't set up — the account
    just stays unverified until it is. Returns "sent", "failed" or
    "not_configured" so callers can tell the user the truth."""
    if not mail_layer.configured():
        print("[mail] GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set — skipping verification email "
              "(see .env.example)")
        return "not_configured"
    token = db.create_verification_token(user["id"])
    verify_url = f"{str(request.base_url).rstrip('/')}/api/auth/verify?token={token}"
    try:
        mail_layer.send_verification_email(user["email"], user["username"], verify_url)
    except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
        print(f"[mail] couldn't send verification email: {e}")
        return "failed"
    return "sent"


def _notify_welcome(base_url: str, user) -> None:
    """Welcome email, best-effort and after the response: a mail problem must never
    break a verify or sign-in."""
    if not mail_layer.configured():
        return
    try:
        mail_layer.send_welcome_email(user["email"], user["username"], base_url)
    except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
        print(f"[mail] couldn't send welcome email: {e}")


def _notify_password_changed(base_url: str, user) -> None:
    if not mail_layer.configured():
        return
    try:
        mail_layer.send_password_changed_email(user["email"], user["username"], base_url)
    except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
        print(f"[mail] couldn't send password-changed email: {e}")


@app.post("/api/auth/signup", dependencies=[Depends(signup_rate_limit)])
def signup(req: SignupRequest, request: Request, response: Response):
    try:
        user = db.create_user(req.username, req.email, req.password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    _set_session_cookie(request, response, db.create_session(user["id"]))
    return {**user, "verification_email": _send_verification(request, user)}


@app.get("/api/auth/verify", include_in_schema=False)
def verify_email(token: str, request: Request, background: BackgroundTasks):
    try:
        user = db.consume_verification_token(token)
        background.add_task(_notify_welcome, str(request.base_url), user)
        return RedirectResponse(url="/?verified=1")
    except db.AuthError:
        return RedirectResponse(url="/?verified=0")


@app.post("/api/auth/resend-verification", dependencies=[Depends(mail_rate_limit)])
def resend_verification(request: Request, user=Depends(require_user)):
    if user["email_verified"]:
        return {"status": "already_verified"}
    if not mail_layer.configured():
        raise HTTPException(400, "Email isn't set up on this server yet — see .env.example.")
    if _send_verification(request, user) != "sent":
        raise HTTPException(503, "We couldn't send the email just now. Please try again in a few minutes.")
    return {"status": "sent"}


@app.post("/api/auth/login", dependencies=[Depends(login_rate_limit)])
def login(req: LoginRequest, request: Request, response: Response):
    try:
        user = db.authenticate(req.identifier, req.password)
    except db.AuthError as e:
        raise HTTPException(401, str(e))
    _set_session_cookie(request, response, db.create_session(user["id"]))
    return user


def _oauth_redirect_uri(request: Request, provider: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/api/auth/{provider}/callback"


@app.get("/api/auth/google/start")
def oauth_google_start(request: Request):
    state = secrets.token_urlsafe(24)
    try:
        url = oauth_layer.google_authorize_url(_oauth_redirect_uri(request, "google"), state)
    except oauth_layer.OAuthError as e:
        raise HTTPException(400, str(e))
    resp = RedirectResponse(url=url)
    # short-lived, httponly — just enough to round-trip the CSRF state
    # through the provider and back; not a real session
    resp.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax",
                     secure=(request.url.scheme == "https"), max_age=600)
    return resp


@app.get("/api/auth/google/callback", dependencies=[Depends(oauth_rate_limit)])
def oauth_google_callback(request: Request, response: Response, background: BackgroundTasks,
                           code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if error or not code or not state or not expected_state or state != expected_state:
        return RedirectResponse(url="/?oauth_error=1")
    try:
        claims = oauth_layer.google_exchange_code(code, _oauth_redirect_uri(request, "google"))
        user = db.find_or_create_oauth_user("google", claims["provider_id"], claims["email"], claims.get("name"))
    except (oauth_layer.OAuthError, db.AuthError) as e:
        print(f"[oauth] google sign-in failed: {e}")
        return RedirectResponse(url="/?oauth_error=1")
    resp = RedirectResponse(url="/?oauth=1")
    resp.delete_cookie(OAUTH_STATE_COOKIE)
    _set_session_cookie(request, resp, db.create_session(user["id"]))
    if user.get("just_created"):
        background.add_task(_notify_welcome, str(request.base_url), user)
    return resp


# Apple follows the exact same shape as Google above, once engine/oauth.py's
# apple_configured() is true (needs a paid Apple Developer account — see
# that module's docstring). Apple's callback is a POST (response_mode=
# form_post), so it can't reuse the GET pattern verbatim, but find_or_create
# is identical: db.find_or_create_oauth_user("apple", claims["provider_id"], claims["email"]).


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user=Depends(require_user)):
    return user


@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest, request: Request, background: BackgroundTasks,
                    user=Depends(require_user)):
    try:
        db.change_password(user["id"], req.current_password, req.new_password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    background.add_task(_notify_password_changed, str(request.base_url), user)
    return {"status": "ok"}


@app.post("/api/auth/delete-account", dependencies=[Depends(login_rate_limit)])
def delete_account(req: DeleteAccountRequest, response: Response, user=Depends(require_user)):
    """Permanent, in-app account deletion (App Store requirement). Re-checks
    the password (if the account has one) and a typed confirmation."""
    try:
        db.delete_account(user["id"], req.password, req.confirm)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@app.post("/api/auth/forgot-password", dependencies=[Depends(mail_rate_limit)])
def forgot_password(req: ForgotPasswordRequest, request: Request):
    """Always returns the same generic response whether or not the email
    exists — otherwise this endpoint would let anyone probe which emails
    have accounts (account enumeration)."""
    if not mail_layer.configured():
        # Server-wide condition, so saying so leaks nothing about any one email.
        raise HTTPException(503, "Password reset email isn't available right now. Please try again later.")
    user = db.get_user_by_email(req.email)
    if user:
        token = db.create_reset_token(user["id"])
        reset_url = f"{str(request.base_url).rstrip('/')}/?reset_token={token}"
        try:
            mail_layer.send_password_reset_email(user["email"], user["username"], reset_url)
        except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
            print(f"[mail] couldn't send reset email: {e}")
    return {"status": "ok", "message": "If that email has an account, we're sending a reset link. It can take a minute — check your spam or junk folder, and try again if it never shows up."}


@app.post("/api/auth/reset-password", dependencies=[Depends(reset_rate_limit)])
def reset_password(req: ResetPasswordRequest, request: Request, response: Response, background: BackgroundTasks):
    try:
        user = db.reset_password(req.token, req.new_password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    _set_session_cookie(request, response, db.create_session(user["id"]))
    background.add_task(_notify_password_changed, str(request.base_url), user)
    return user


# --------------------------------------------------------------- settings ----
class SettingsUpdate(BaseModel):
    espn_league_id: Optional[str] = None
    espn_swid: Optional[str] = None
    espn_s2: Optional[str] = None
    scoring_preset: Optional[str] = None
    theme: Optional[str] = None

    @field_validator("theme", mode="before")
    @classmethod
    def _theme_is_a_team_code(cls, v):
        """The favorite-team theme: one of the 32 team codes, or empty to clear. Nothing else is stored, because the
        value is later used to look up a palette and must never carry free text."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("theme must be a team code")
        v = v.strip().upper()
        if not v:
            return None
        if v not in news_layer.TEAM_CODES:
            raise ValueError("unknown team")
        return v


@app.get("/api/settings")
def get_settings(user=Depends(require_user)):
    return db.get_settings(user["id"])


@app.post("/api/settings")
def update_settings(req: SettingsUpdate, user=Depends(require_user)):
    updates = req.dict(exclude_unset=True)
    return db.update_settings(user["id"], updates)


def _effective_scoring(scoring, user):
    """Explicit query-param scoring wins; otherwise fall back to the
    signed-in user's saved preference; otherwise default full PPR."""
    if scoring is not None:
        return scoring
    if user:
        preset = db.get_settings(user["id"]).get("scoring_preset")
        if preset:
            return PRESETS.get(preset)
    return None


# ---------------------------------------------------------------- scoring ----
SCORING_FIELDS = ["reception", "pass_yard", "pass_td", "interception", "rush_yard",
                   "rush_td", "rec_yard", "rec_td", "fumble_lost", "two_pt"]


def scoring_from_query(
    scoring: Optional[str] = Query(None, description="preset: ppr | half_ppr | standard"),
    reception: Optional[float] = None, pass_yard: Optional[float] = None,
    pass_td: Optional[float] = None, interception: Optional[float] = None,
    rush_yard: Optional[float] = None, rush_td: Optional[float] = None,
    rec_yard: Optional[float] = None, rec_td: Optional[float] = None,
    fumble_lost: Optional[float] = None, two_pt: Optional[float] = None,
    return_td: Optional[float] = None, te_reception: Optional[float] = None,
    pass_fd: Optional[float] = None, rush_fd: Optional[float] = None, rec_fd: Optional[float] = None,
    bonus_pass_300: Optional[float] = None, bonus_pass_400: Optional[float] = None,
    bonus_rush_100: Optional[float] = None, bonus_rush_200: Optional[float] = None,
    bonus_rec_100: Optional[float] = None, bonus_rec_200: Optional[float] = None,
):
    overrides = {k: v for k, v in dict(
        reception=reception, pass_yard=pass_yard, pass_td=pass_td, interception=interception,
        rush_yard=rush_yard, rush_td=rush_td, rec_yard=rec_yard, rec_td=rec_td,
        fumble_lost=fumble_lost, two_pt=two_pt, return_td=return_td, te_reception=te_reception,
        pass_fd=pass_fd, rush_fd=rush_fd, rec_fd=rec_fd,
        bonus_pass_300=bonus_pass_300, bonus_pass_400=bonus_pass_400,
        bonus_rush_100=bonus_rush_100, bonus_rush_200=bonus_rush_200,
        bonus_rec_100=bonus_rec_100, bonus_rec_200=bonus_rec_200,
    ).items() if v is not None}
    if scoring is None and not overrides:
        return None  # fast path: nflverse's precomputed full-PPR column
    base = dict(PRESETS.get(scoring or "ppr", PRESETS["ppr"]))
    base.update(overrides)
    return base


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("static/icons/favicon-32.png")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    """Liveness only: is this process up and serving? Deliberately touches no
    network, disk cache or database, so it answers instantly and can only fail
    if the app itself is down. That's what Render's health check and an uptime
    monitor need. /api/health below is NOT safe for that job — on a cold
    process resolve_season() downloads nflverse data and raises if nflverse is
    unreachable, so an upstream outage would read as this app being down and
    could fail a deploy."""
    return "ok"


@app.get("/api/health")
def health():
    season = data_layer.resolve_season()
    return {"status": "ok", "season": season}


# nflverse's team codes (note LA, not LAR) — the same 32 this app's data has
# always produced; see meta() for why this isn't derived from the data anymore.
NFL_TEAMS = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND",
             "JAX", "KC", "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF",
             "TB", "TEN", "WAS"]


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    """Season, positions, teams, weight config, scoring presets — everything
    the frontend needs to build its filters.

    Deliberately does NOT call load_bundle(): the frontend awaits this before
    it draws even the sign-in screen, and load_bundle is the ~25s nflverse
    fetch, so on a cold start the whole UI sat behind it just to learn the
    season and 32 team abbreviations. resolve_season() is cached after its
    first (cheap) probe, and the team list is a constant — nflverse's own
    codes, e.g. LA not LAR, same 32 this endpoint used to derive from the data."""
    return {
        "season": data_layer.resolve_season(),
        "positions": list(POSITIONS),
        "teams": NFL_TEAMS,
        "weights": WEIGHTS,
        "advanced_columns": ADVANCED_COLS,
        "scoring_presets": PRESETS,
        "scoring_fields": SCORING_FIELDS,
        "signed_in": user is not None,
        "mail_configured": mail_layer.configured(),
        "oauth_google": oauth_layer.google_configured(),
        "oauth_apple": oauth_layer.apple_configured(),
        "ai_writeups": startsit_ai.configured(),
    }


_OVERALL_COLUMNS = [
    "player_display_name", "position", "recent_team", "headshot_url", "overall_rank", "tier", "pos_rank",
    "PROJ", "VOR", "VALUE", "replacement_proj", "ecr", "ecr_sd", "ecr_gap", "SCORE", "FORM", "games",
    "fpts_per_game", "floor", "ceiling", "cv", "boom_rate", "bust_rate", "bye_week", "stat_line",
    "injury_status", "injury_body_part", "weeks_since_played",
    "PVS", "PVS_tier", "pvs_vorp", "pvs_vol", "pvs_ceil", "pvs_perf", "pvs_match",
]


def _overall_board_response(limit, teams, superflex, scoring):
    """One list for all four positions, ranked by value over replacement."""
    league = {"teams": teams, "slots": {"SUPERFLEX": 1 if superflex else 0}}
    board = overall_board(scoring=scoring, league=league)
    cols = [c for c in _OVERALL_COLUMNS if c in board.columns]
    out = board.head(limit)[cols].reset_index()
    records = schemas.with_value_fields(_clean(out.to_dict(orient="records")))
    bundle = load_bundle()
    return {"season": bundle["season"], "week": upcoming_week(bundle["schedule"]),
            "position": "ALL", "count": len(records),
            "league": league, "replacement_ranks": board.attrs.get("replacement_ranks"),
            "players": records}


@app.get("/api/board")
def api_board(
    pos: str = Query(..., description="QB, RB, WR, TE, or ALL for one cross-position list"),
    opp: Optional[str] = Query(None, description="opponent defense abbr, e.g. WAS"),
    min_games: int = Query(2, ge=0),
    limit: int = Query(60, ge=1, le=300),
    teams: int = Query(12, ge=4, le=32, description="league size, for pos=ALL replacement level"),
    superflex: bool = Query(False, description="pos=ALL: a second QB slot, which raises QB value"),
    scoring: Optional[dict] = Depends(scoring_from_query),
    user=Depends(current_user),
):
    pos = pos.upper()
    if pos == "ALL":
        return _overall_board_response(limit, teams, superflex, _effective_scoring(scoring, user))
    if pos not in POSITIONS:
        raise HTTPException(400, f"pos must be one of {POSITIONS} or ALL")
    scoring = _effective_scoring(scoring, user)

    bundle = load_bundle()
    board = build_board(pos, min_games=min_games, scoring=scoring)
    if "PVS" in board.columns:   # the list is ordered by the number it displays
        board = board.sort_values("PVS", ascending=False, na_position="last", kind="stable")
    breakdown = []
    if opp:
        opp = opp.upper()
        board = project_vs(board, pos, opp, bundle=bundle, scoring=scoring)
        breakdown = board.attrs.get("matchup_breakdown", [])

    board = board.head(limit).reset_index()
    board.insert(0, "rank", range(1, len(board) + 1))
    records = schemas.with_value_fields(_clean(board.to_dict(orient="records")))
    return {"season": bundle["season"], "week": upcoming_week(bundle["schedule"]),
            "position": pos, "opponent": opp, "count": len(records),
            "matchup_breakdown": breakdown, "players": records}


@app.get("/api/player/{player_id}")
def api_player(player_id: str, opp: Optional[str] = Query(None),
               scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    scoring = _effective_scoring(scoring, user)
    detail = player_detail(player_id, scoring=scoring)
    if detail is None:
        raise HTTPException(404, "player not found or not enough data")
    if opp:
        bundle = load_bundle()
        factor = matchup_multiplier(detail["position"], opp.upper(), bundle)
        detail["matchup_opponent"] = opp.upper()
        detail["matchup_factor"] = factor
    return _clean(detail)


@app.get("/api/player/{player_id}/news", dependencies=[Depends(news_rate_limit)])
def api_player_news(player_id: str, scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    """Real news for one player (ESPN/CBS RSS, full-name matched — see
    engine/news.py), plus a short AI-written summary of those same real
    items when ANTHROPIC_API_KEY is configured (see .env.example) —
    'not every player has an active story' is expected and fine: an
    empty `items` list just means no real story matched this player
    right now, not an error."""
    scoring = _effective_scoring(scoring, user)
    detail = player_detail(player_id, scoring=scoring)
    if detail is None:
        raise HTTPException(404, "player not found or not enough data")
    items = news_layer.player_news(detail["player_display_name"], player_id=player_id, team=detail.get("recent_team"))
    summary = news_layer.ai_summary_for_player(
        detail["player_display_name"], items,
        position=detail.get("position"), injury_status=detail.get("injury_status"),
        player_id=player_id,
    )
    return _clean({
        "player_id": player_id, "player_display_name": detail["player_display_name"],
        "items": items[:8], "ai_summary": summary,
    })


@app.get("/api/player/{player_id}/projection-compare", dependencies=[Depends(projcompare_rate_limit)])
def api_player_projection_compare(player_id: str, opp: Optional[str] = Query(None),
                                   scoring: Optional[dict] = Depends(scoring_from_query),
                                   user=Depends(current_user)):
    """Our PROJ next to real published FantasyPros consensus for the same
    player — see engine/external_projections.py for sourcing. Always
    returns our own number; `consensus.proj` is None (not a guess) when
    FANTASYPROS_API_KEY isn't set, the fetch failed, or this player wasn't
    matched — the frontend renders a real 'not connected' state for that,
    same pattern as player news without ANTHROPIC_API_KEY set."""
    scoring = _effective_scoring(scoring, user)
    detail = player_detail(player_id, scoring=scoring)
    if detail is None:
        raise HTTPException(404, "player not found or not enough data")

    bundle = load_bundle()
    if opp:
        # A specific requested opponent (e.g. viewing this player's card
        # from a Start/Sit matchup) — same math as the no-opp case below,
        # just against that exact defense instead of their real schedule.
        # min_games=0 for the same reason player_detail uses it: one player
        # asked for by id, not a ranked list.
        board = build_board(detail["position"], min_games=0, scoring=scoring)
        our_proj = None
        if player_id in board.index:
            projected = project_vs(board.loc[[player_id]], detail["position"], opp.upper(),
                                    bundle=bundle, scoring=scoring)
            our_proj = round(float(projected["PROJ"].iloc[0]), 1)
    else:
        # Same real, opponent-adjusted PROJ My Team already shows for this
        # player (engine.tools.real_proj_for_player — a thin wrapper
        # around the exact _opponent_adjusted_proj helper My Team uses,
        # resolved against their real upcoming opponent) — never a
        # second, differently-computed number for the same player.
        our_proj = tools.real_proj_for_player(player_id, detail["position"], bundle=bundle, scoring=scoring)

    # FantasyPros' `scoring` query param is one of STD/HALF/PPR — map our
    # settings dict to the closest match by reception value rather than a
    # preset name (custom league scoring has no exact FantasyPros
    # equivalent; PPR is the closest default for anything in between).
    reception = (scoring or {}).get("reception", 1.0)
    fp_scoring = "STD" if reception <= 0.01 else ("HALF" if reception < 0.99 else "PPR")
    consensus = external_projections_layer.projection_for_player(
        detail["player_display_name"], detail["position"], bundle["season"],
        week=detail.get("next_week"), scoring=fp_scoring,
    )
    # Blend only when there is a real expert number AND a kickoff to measure
    # from; otherwise `blend.blended` is None and the UI keeps our own number.
    kickoff = locks.kickoff(bundle["schedule"], detail.get("recent_team"), detail.get("next_week"))
    blend = projection_blend.blend(our_proj, consensus.get("proj"), projection_blend.hours_until(kickoff))
    return _clean({
        "player_id": player_id, "player_display_name": detail["player_display_name"],
        "our_proj": our_proj, "consensus": consensus, "blend": blend,
    })


@app.get("/api/player/{player_id}/ros", dependencies=[Depends(projcompare_rate_limit)])
def api_player_ros(player_id: str, games: Optional[int] = Query(None, ge=1, le=20),
                   scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    """Game-by-game projection for the rest of the season (engine/ros_projection.py)."""
    scoring = _effective_scoring(scoring, user)
    out = ros_projection.player_ros(player_id, scoring=scoring, max_games=games)
    if out is None:
        raise HTTPException(404, "player not found or not enough data")
    return _clean(out)


@app.get("/api/player/{player_id}/explain", dependencies=[Depends(projcompare_rate_limit)])
def api_player_explain(player_id: str, scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    """This week's projection for one player, with what moved it (engine/tools.projection_explain)."""
    scoring = _effective_scoring(scoring, user)
    out = tools.projection_explain(player_id, scoring=scoring)
    if out is None:
        raise HTTPException(404, "player not found or not enough data")
    return _clean(out)


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
    return {"query": q, "results": _clean(search_players(q, limit=limit))}


@app.get("/api/team/{team}/next")
def api_team_next(team: str):
    bundle = load_bundle()
    opp, wk_no = data_layer.next_opponent(bundle["schedule"], team.upper())
    return {"team": team.upper(), "opponent": opp, "week": wk_no}


@app.post("/api/refresh", dependencies=[Depends(refresh_rate_limit)])
def api_refresh():
    """Force-refetch all data (bypasses the disk cache)."""
    bundle = load_bundle(force=True)
    return {"status": "refreshed", "season": bundle["season"]}


# ------------------------------------------------------------ decision tools ----
class StartSitRequest(BaseModel):
    player_ids: List[str]
    opponents: Optional[Dict[str, str]] = None   # {player_id: opp_abbr}
    scoring: Optional[dict] = None
    mode: str = "balanced"   # balanced | safe | upside


# The compare UI holds at most 4 players. Each one costs a full decision-layer
# pass (outcome sampling, script split, usage over pbp), and this endpoint is
# open to signed-out users, so an unbounded list was a cheap way to pin the
# single small instance.
MAX_STARTSIT_PLAYERS = 6


def _check_startsit_size(req: StartSitRequest):
    if len(req.player_ids) < 2:
        raise HTTPException(400, "need at least 2 players to compare")
    if len(req.player_ids) > MAX_STARTSIT_PLAYERS:
        raise HTTPException(400, f"compare at most {MAX_STARTSIT_PLAYERS} players at a time")


@app.post("/api/startsit")
def api_startsit(req: StartSitRequest, user=Depends(current_user)):
    _check_startsit_size(req)
    scoring = _effective_scoring(req.scoring, user)
    result = tools.start_sit(req.player_ids, opponents=req.opponents, scoring=scoring, mode=req.mode)

    # Track record: only for a signed-in user (nothing to attach an
    # anonymous comparison to), and only players this actually has a real
    # tier + a real upcoming week for — see engine/db.py's log_predictions
    # docstring for why this is graded later, not right now.
    if user:
        loggable = [
            {**p, "season": result["season"]}
            for p in result["players"]
            if "error" not in p and p.get("tier") and p.get("week") is not None
        ]
        try:
            db.log_predictions(user["id"], loggable, scoring=scoring)
        except Exception as e:
            print(f"[track-record] failed to log start/sit predictions: {e}")

    return _clean(result)


@app.post("/api/startsit/analysis")
def api_startsit_analysis(req: StartSitRequest, user=Depends(require_user)):
    """Claude's written breakdown of the same comparison /api/startsit makes
    (engine/startsit_ai.py). Signed-in only, since it costs an API call."""
    if not startsit_ai.configured():
        raise HTTPException(503, "AI write-ups aren't turned on for this server")
    _check_startsit_size(req)
    scoring = _effective_scoring(req.scoring, user)
    result = tools.start_sit(req.player_ids, opponents=req.opponents, scoring=scoring, mode=req.mode)
    out = startsit_ai.write_up(result)
    if out is None:
        raise HTTPException(502, "couldn't get a write-up right now; try again in a minute")
    return _clean(out)


lineupadv_rate_limit = rate_limit("lineupadv", limit=10, window_seconds=60)
ADVISOR_MAX_PLAYERS = 30


@app.get("/api/startsit/lineup", dependencies=[Depends(lineupadv_rate_limit)])
def api_startsit_lineup(week: Optional[int] = Query(None, ge=1, le=25),
                        mode: str = Query("balanced", pattern="^(balanced|safe|upside)$"),
                        scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(require_user)):
    """Best whole lineup under a risk lens (engine/lineup_advisor.py): every
    slot, flex included, solved exactly, with the changes from your current one."""
    scoring = _effective_scoring(scoring, user)
    _, result = _load_my_team(user, week, scoring)
    slots, starter_ids, players = _lineup_inputs(result)
    roster = {p["player_id"]: p for p in result["my_team"]["players"]}
    skill = [pid for pid, p in players.items() if p.get("position") in ("QB", "RB", "WR", "TE")][:ADVISOR_MAX_PLAYERS]
    samples = {}
    if skill:
        for r in tools.start_sit(skill, scoring=scoring, mode=mode, keep_samples=True)["players"]:
            if "error" not in r and r.get("outcomes") and r["player_id"] in players:
                o = r["outcomes"]
                if o.get("_samples") is not None:
                    samples[r["player_id"]] = o.pop("_samples")
                players[r["player_id"]]["outcomes"] = o
    wk = result["nfl_week"]
    out = lineup_advisor.advise(slots, starter_ids, players, load_bundle()["schedule"], wk, mode)

    def row(pid):
        p, r = players.get(pid), roster.get(pid, {})
        o = (p or {}).get("outcomes") or {}
        return {"player_id": pid, "name": p.get("name") if p else None, "position": p.get("position") if p else None,
                "team": p.get("team") if p else None, "headshot_url": r.get("headshot_url"),
                "PROJ": p.get("PROJ") if p else None, "p10": o.get("p10"), "p90": o.get("p90"), "out": bool(o.get("out"))}

    out["lineup"] = [{"slot": slots[i], **row(pid)} if pid else {"slot": slots[i], "player_id": None}
                     for i, pid in enumerate(out["chosen"])]
    def total_range(ids):
        ids = [pid for pid in ids if pid in players]
        const = sum(float(players[pid].get("PROJ") or 0.0) for pid in ids if pid not in samples)
        return correlation.lineup_range([samples[pid] for pid in ids if pid in samples], const)

    cur_ids = [pid for pid in starter_ids if pid]
    out["range"] = {"current": total_range(cur_ids), "best": total_range([pid for pid in out["chosen"] if pid])} if samples else None
    out["adds"] = [row(pid) for pid in out["adds"]]
    out["drops"] = [row(pid) for pid in out["drops"]]
    out.pop("chosen")
    out["week"], out["league_name"] = wk, result.get("league_name")
    return _clean(out)


@app.get("/api/startsit/suggestions")
def api_startsit_suggestions(week: Optional[int] = Query(None, ge=1, le=25),
                              scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(require_user)):
    """The real top 3 (or fewer, if there genuinely aren't 3 — never
    padded) start/sit calls worth checking on your own current roster,
    for the Start/Sit tab's own top section. Same active-team resolution
    as /api/myteam (Sleeper or ESPN), reused rather than duplicated."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            roster = tools.my_team_espn(active["league_id"], int(active["roster_id"]), scoring=scoring, week=week,
                                         espn_s2=espn_s2, swid=swid)["my_team"]["players"]
        else:
            roster = tools.my_team(active["league_id"], int(active["roster_id"]), scoring=scoring, week=week)["my_team"]["players"]
        suggestions = tools.start_sit_suggestions_from_roster(roster, scoring=scoring, limit=3)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean({"suggestions": suggestions})


@app.get("/api/track-record")
def api_track_record(user=Depends(require_user)):
    """How often this app's own START calls have actually been right,
    graded only against real, already-played weeks (see engine/db.py's
    get_track_record) — `pending` counts logged-but-not-yet-graded calls
    so a 0-decision season reads as 'nothing resolved yet', not silently
    excluded from a smaller, falsely-clean sample."""
    return _clean(db.get_track_record(user["id"]))


class TradeRequest(BaseModel):
    side_a: List[str]
    side_b: List[str]
    scoring: Optional[dict] = None
    opponent_roster_id: Optional[int] = None   # side B's real roster_id — needed to build a
                                                # needs-aware recommendation, not just player IDs


def _trade_league_ctx(user, opponent_roster_id, scoring):
    """Best-effort context for a needs-aware trade recommendation: both
    sides' full CURRENT rosters + the league's real starting-lineup
    slots. None (not an error) when there's no signed-in active team, no
    opponent picked yet, or the active league is on a platform this
    doesn't support yet (ESPN — see engine/tools.py's _team_needs) —
    /api/trade still returns a full value comparison either way, just
    without the extra recommendation."""
    if not user or opponent_roster_id is None:
        return None
    active = db.get_active_team(user["id"])
    if not active or active.get("platform") == "espn":
        # ESPN's league object doesn't expose starting-lineup slot counts
        # the same shape sleeper's roster_positions does yet — rather
        # than guess, this stays a disclosed gap (see README Roadmap)
        # and the endpoint falls back to value-only for an ESPN team.
        return None
    try:
        roster_a = tools.roster_player_list(active["league_id"], int(active["roster_id"]), scoring=scoring)
        roster_b = tools.roster_player_list(active["league_id"], opponent_roster_id, scoring=scoring)
        roster_positions = sleeper_layer.get_league(active["league_id"]).get("roster_positions")
        return {"roster_a": roster_a, "roster_b": roster_b, "roster_positions": roster_positions}
    except Exception as e:
        print(f"[trade] couldn't build needs context (falling back to value-only): {e}")
        return None


@app.post("/api/trade")
def api_trade(req: TradeRequest, user=Depends(current_user)):
    if not req.side_a or not req.side_b:
        raise HTTPException(400, "both sides need at least 1 player")
    scoring = _effective_scoring(req.scoring, user)
    league_ctx = _trade_league_ctx(user, req.opponent_roster_id, scoring)
    result = tools.trade_analyzer(req.side_a, req.side_b, scoring=scoring, league_ctx=league_ctx)
    # The full trade-engine verdict (gates, fairness index, acceptance odds,
    # negotiation scripts) when both rosters are real Sleeper rosters.
    if league_ctx:
        try:
            active = db.get_active_team(user["id"])
            result["evaluation"] = tools.evaluate_trade(active["league_id"], int(active["roster_id"]),
                                                        req.opponent_roster_id, req.side_a, req.side_b, scoring=scoring)
        except Exception as e:
            print(f"[trade] engine verdict skipped: {e}")
    return _clean(result)


@app.get("/api/waivers")
def api_waivers(
    pos: Optional[str] = Query(None, description="comma-separated positions, default all"),
    rostered: Optional[str] = Query(None, description="comma-separated player_ids to exclude"),
    limit: int = Query(15, ge=1, le=100),
    scoring: Optional[dict] = Depends(scoring_from_query),
    user=Depends(current_user),
):
    positions = [p.upper() for p in pos.split(",")] if pos else None
    if positions and any(p not in POSITIONS for p in positions):
        raise HTTPException(400, f"pos must be a comma-separated subset of {POSITIONS}")

    rostered_ids = set(rostered.split(",")) if rostered else None
    league_info = None
    scoring = _effective_scoring(scoring, user)

    # sync to your active connected team automatically when signed in and
    # no explicit rostered-players list was given
    if rostered_ids is None and user:
        active = db.get_active_team(user["id"])
        if active:
            try:
                if active.get("platform") == "espn":
                    espn_s2, swid = db.get_espn_secrets(user["id"])
                    snap = espn_layer.league_snapshot(active["league_id"], espn_layer.resolve_year(),
                                                        espn_s2=espn_s2, swid=swid)
                    rostered_ids = {p["gsis_id"] for t in snap["teams"] for p in t["roster"] if p["gsis_id"]}
                else:
                    snap = sleeper_layer.league_snapshot(active["league_id"])
                    rostered_ids = set(snap["rostered_player_ids"])
                if scoring is None:
                    scoring = snap["scoring"]
                league_info = {"league_id": active["league_id"], "league_name": snap["league_name"],
                                "team_name": active["team_name"]}
            except Exception as e:
                print(f"[waivers] couldn't sync league: {e}")

    result = tools.waiver_wire(positions=positions, rostered_ids=rostered_ids or set(), scoring=scoring, limit=limit)
    result["league"] = league_info
    return _clean(result)


@app.get("/api/waivers/engine")
def api_waiver_engine(scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    """Smart Match (needs your connected Sleeper team) plus the discovery
    feeds (market movers, deep dive, handcuffs) for everyone."""
    scoring = _effective_scoring(scoring, user)
    league_id = roster_id = None
    espn_ctx = None
    note = None
    if user:
        active = db.get_active_team(user["id"])
        if active and active.get("platform") != "espn":
            league_id, roster_id = active["league_id"], int(active["roster_id"])
            if scoring is None:
                try:
                    scoring = sleeper_layer.league_snapshot(league_id)["scoring"]
                except Exception as e:
                    print(f"[waivers] couldn't load league scoring: {e}")
        elif active:
            try:
                espn_s2, swid = db.get_espn_secrets(user["id"])
                eleague = espn_layer.get_league(active["league_id"], espn_layer.resolve_year(), espn_s2, swid)
                espn_ctx = {"league": eleague, "team_id": int(active["roster_id"])}
                if scoring is None:
                    scoring = espn_layer.scoring_from_espn(eleague)
            except Exception as e:
                print(f"[waivers] couldn't load ESPN league: {e}")
                note = "Couldn't read your ESPN league just now, so these lists don't hide players already rostered. " + _espn_error_message(e)
    try:
        result = waivers_layer.build(league_id, roster_id, scoring=scoring, espn=espn_ctx)
    except Exception as e:
        raise HTTPException(500, f"waiver engine failed: {e}")
    result["note"] = note
    return _clean(result)


# ------------------------------------------------------------- league sync ----
@app.get("/api/sleeper/{league_id}")
def api_sleeper_league(league_id: str, refresh: bool = False):
    try:
        snap = sleeper_layer.league_snapshot(league_id, force=refresh)
    except Exception as e:
        raise HTTPException(400, f"couldn't load Sleeper league {league_id}: {e}")
    return _clean(snap)


@app.get("/api/espn/{league_id}")
def api_espn_league(league_id: str, year: Optional[int] = None, user=Depends(current_user)):
    """Real ESPN league sync (see engine/espn.py) — raw league snapshot,
    same shape /api/sleeper/{league_id} returns. My Team, Waivers, Trade
    (team list + roster browsing), and League News all sync a connected
    ESPN team the same as a Sleeper one now; Trade Finder's auto-suggest
    is the one decision tool still Sleeper-only (see README Roadmap).
    Public leagues work signed out; a private league needs the signed-in
    user's own espn_s2/SWID from Settings (never sent back to the client
    — see engine/db.py get_espn_secrets)."""
    espn_s2, swid = db.get_espn_secrets(user["id"]) if user else (None, None)
    year = year or espn_layer.resolve_year()
    try:
        snap = espn_layer.league_snapshot(league_id, year, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        raise HTTPException(400, f"couldn't load ESPN league {league_id} for {year}: {e}")
    return _clean(snap)


class ConnectTeamRequest(BaseModel):
    league_id_or_url: str
    platform: str = "sleeper"


def _espn_teams_for_lookup(league_id, user):
    """Same shape api_teams_lookup already returns for Sleeper
    (league_id/league_name/scoring/teams[roster_id,team_name,owner,
    avatar_url,player_ids]) built from engine/espn.py's own richer
    per-team shape, so the frontend's existing pick-your-team flow (see
    static/app.js renderGateConnectLeague) works unmodified for either
    platform."""
    espn_s2, swid = db.get_espn_secrets(user["id"]) if user else (None, None)
    year = espn_layer.resolve_year()
    snap = espn_layer.league_snapshot(league_id, year, espn_s2=espn_s2, swid=swid)
    return {
        "league_id": snap["league_id"], "league_name": snap["league_name"], "scoring": snap["scoring"],
        "teams": [{
            "roster_id": t["team_id"], "team_name": t["team_name"], "owner": t["owner"],
            "avatar_url": t["logo_url"], "player_ids": [p["espn_id"] for p in t["roster"]],
        } for t in snap["teams"]],
    }


def _espn_error_message(e):
    """Plain-English reason an ESPN league couldn't be loaded. ESPN gives
    the same refusal for a private league as for bad cookies, and the
    library's own wording means nothing to a user."""
    name = type(e).__name__
    if name == "ESPNAccessDenied":
        return ("That ESPN league isn't public, so Lineup Lab can't read it. "
                "In ESPN go to League → Settings → Basic Settings and tick "
                "\"Make League Viewable to Public\" (commissioner only), then try again.")
    if name == "ESPNInvalidLeague":
        return ("ESPN says that league doesn't exist for this season. Check the league ID "
                "(the number after leagueId= in the ESPN URL).")
    return f"Couldn't load that ESPN league right now ({e}). If it keeps happening, check the league is public."


@app.post("/api/teams/lookup")
def api_teams_lookup(req: ConnectTeamRequest, user=Depends(current_user)):
    """Step 1 of connecting a team: accepts a bare league ID OR a pasted
    league URL for either platform, and returns that league's teams to
    pick from. A private ESPN league needs the signed-in user's own
    espn_s2/SWID already saved in Settings (see engine/db.py
    get_espn_secrets) — a public one works signed out, same as Sleeper."""
    if req.platform == "espn":
        league_id = espn_layer.parse_league_id(req.league_id_or_url)
        if not league_id:
            raise HTTPException(400, "Couldn't find a league ID in that — paste the league URL or its numeric ID.")
        try:
            return _clean(_espn_teams_for_lookup(league_id, user))
        except Exception as e:
            raise HTTPException(400, _espn_error_message(e))

    league_id = sleeper_layer.parse_league_id(req.league_id_or_url)
    if not league_id:
        raise HTTPException(400, "Couldn't find a league ID in that — paste the league URL or its numeric ID.")
    try:
        snap = sleeper_layer.league_snapshot(league_id)
    except Exception as e:
        raise HTTPException(400, f"Couldn't load that Sleeper league: {e}")
    return _clean(snap)


class AddTeamRequest(BaseModel):
    league_id: str
    league_name: Optional[str] = None
    roster_id: int
    team_name: str
    avatar_url: Optional[str] = None
    platform: str = "sleeper"


@app.get("/api/teams")
def api_teams_list(user=Depends(require_user)):
    return {"teams": db.list_connected_teams(user["id"])}


@app.post("/api/teams")
def api_teams_add(req: AddTeamRequest, user=Depends(require_user)):
    team = db.add_connected_team(
        user["id"], req.platform, req.league_id, req.roster_id, req.team_name, req.league_name, req.avatar_url,
    )
    return team


@app.post("/api/teams/{team_id}/activate")
def api_teams_activate(team_id: int, user=Depends(require_user)):
    try:
        db.set_active_team(user["id"], team_id)
    except db.AuthError as e:
        raise HTTPException(404, str(e))
    return {"teams": db.list_connected_teams(user["id"])}


@app.delete("/api/teams/{team_id}")
def api_teams_remove(team_id: int, user=Depends(require_user)):
    try:
        db.remove_connected_team(user["id"], team_id)
    except db.AuthError as e:
        raise HTTPException(404, str(e))
    return {"teams": db.list_connected_teams(user["id"])}


# ------------------------------------------------------------- league chat ----
def user_rate_limit(key_prefix: str, limit: int, window_seconds: int):
    """Same sliding window as rate_limit, keyed by signed-in user so a league
    sharing one network address (a dorm, a bar) doesn't share one budget."""
    def dep(user=Depends(require_user)):
        bucket = _RATE_BUCKETS[f"{key_prefix}:u{user['id']}"]
        now = time.time()
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(429, "Slow down a little and try again.")
        bucket.append(now)
    return dep


chat_challenge_limit = user_rate_limit("chat_challenge", limit=5, window_seconds=10 * 60)
chat_join_limit = user_rate_limit("chat_join", limit=10, window_seconds=10 * 60)
chat_poll_limit = user_rate_limit("chat_poll", limit=30, window_seconds=60)
chat_post_limit = user_rate_limit("chat_post", limit=10, window_seconds=60)
chat_report_limit = user_rate_limit("chat_report", limit=10, window_seconds=60)


class ChatLeague(BaseModel):
    platform: str = "sleeper"
    league_id: str


class ChatJoin(ChatLeague):
    token: str


class ChatPost(ChatLeague):
    body: str


class ChatReport(BaseModel):
    message_id: int


class ChatMute(ChatLeague):
    user_id: int
    minutes: int


def _chat(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except chat_layer.ChatError as e:
        raise HTTPException(e.status, str(e))


def _valid_league_id(league_id: str):
    """Sleeper league IDs are plain digits. This id goes into a Sleeper URL and a
    cache filename, so anything else is refused before it gets there."""
    if not re.fullmatch(r"\d{1,32}", league_id or ""):
        raise HTTPException(400, "That doesn't look like a Sleeper league ID.")


def _sleeper_only(platform: str):
    if platform != "sleeper":
        raise HTTPException(400, "League chat is Sleeper-only for now.")


@app.post("/api/chat/challenge", dependencies=[Depends(chat_challenge_limit)])
def api_chat_challenge(req: ChatLeague, user=Depends(require_user)):
    """Step 1 of joining: a one-time code to paste into the user's Sleeper team name."""
    _sleeper_only(req.platform)
    _valid_league_id(req.league_id)
    token = _chat(chat_layer.create_challenge, user["id"], req.platform, req.league_id)
    return {"token": token, "expires_in": chat_layer.CHALLENGE_TTL}


@app.post("/api/chat/join", dependencies=[Depends(chat_join_limit)])
def api_chat_join(req: ChatJoin, user=Depends(require_user)):
    """Step 2: re-read the league from Sleeper, find the code in a team name, add the member."""
    _sleeper_only(req.platform)
    _valid_league_id(req.league_id)
    proof = _chat(chat_layer.verify_sleeper_owner, user["id"], req.league_id, req.token)
    role = "moderator" if proof["is_commissioner"] else "member"
    member = _chat(chat_layer.add_member, user["id"], req.platform, req.league_id, proof["external_id"], role)
    return {"member": member}


@app.get("/api/chat/messages", dependencies=[Depends(chat_poll_limit)])
def api_chat_messages(platform: str = "sleeper", league_id: str = Query(...), after: str = "0",
                      user=Depends(require_user)):
    member = _chat(chat_layer.require_member, user["id"], platform, league_id)
    try:
        after_id = max(0, int(after))
    except ValueError:
        raise HTTPException(400, "after must be a message id.")
    messages = _chat(chat_layer.list_messages, platform, league_id, after=after_id)
    return _clean({"messages": messages, "role": member["role"]})


@app.post("/api/chat/messages", dependencies=[Depends(chat_post_limit)])
def api_chat_post(req: ChatPost, user=Depends(require_user)):
    return _clean({"message": _chat(chat_layer.post_message, user["id"], req.platform, req.league_id, req.body)})


@app.delete("/api/chat/messages/{message_id}")
def api_chat_delete(message_id: int, user=Depends(require_user)):
    _chat(chat_layer.delete_message, user["id"], message_id)
    return {"ok": True}


@app.post("/api/chat/report", dependencies=[Depends(chat_report_limit)])
def api_chat_report(req: ChatReport, user=Depends(require_user)):
    _chat(chat_layer.report_message, user["id"], req.message_id)
    return {"ok": True}


@app.post("/api/chat/mute")
def api_chat_mute(req: ChatMute, user=Depends(require_user)):
    _chat(chat_layer.mute_member, user["id"], req.user_id, req.platform, req.league_id, req.minutes)
    return {"ok": True}


def _load_my_team(user, week, scoring):
    """my_team()/my_team_espn() for the user's active connected league."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            result = tools.my_team_espn(active["league_id"], int(active["roster_id"]), scoring=scoring, week=week,
                                         espn_s2=espn_s2, swid=swid)
        else:
            result = tools.my_team(active["league_id"], int(active["roster_id"]), scoring=scoring, week=week)
    except Exception as e:
        raise HTTPException(400, str(e))
    return active, result


@app.get("/api/myteam")
def api_my_team(week: Optional[int] = Query(None, ge=1, le=25),
                 scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(require_user)):
    _, result = _load_my_team(user, week, scoring)
    return _clean(result)


# --------------------------------------------------- lineup inputs (Start/Sit lineup advisor) ----
def _lineup_inputs(result):
    """(slots, starter_ids, players_by_id) from a my_team() result."""
    roster = result["my_team"]["players"]
    starters = [p for p in roster if p.get("is_starter")]
    slots = [p.get("slot") or p.get("position") for p in starters]
    players = {p["player_id"]: {"name": p.get("player_display_name"), "position": p.get("position"),
                                "team": p.get("recent_team"), "PROJ": p.get("PROJ") or 0.0,
                                "injury_status": p.get("injury_status")} for p in roster}
    return slots, [p["player_id"] for p in starters], players


@app.get("/api/league/trades")
def api_league_trades(seen: str = Query("", description="comma-separated trade ids already seen"),
                      user=Depends(require_user)):
    """Completed trades in the user's Sleeper league, newest first, with the
    ones not in `seen` flagged new."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    if active.get("platform") == "espn":
        try:
            espn_s2, swid = db.get_espn_secrets(user["id"])
            league = espn_layer.get_league(active["league_id"], espn_layer.resolve_year(), espn_s2, swid)
            try:
                activity = league.recent_activity(size=100, msg_type="TRADED") if (espn_s2 and swid) else []
            except Exception:
                activity = []  # the completed-trade feed needs a login; pending trades are public
            trades = league_trades_layer.espn_trade_log(league, activity)
        except Exception as e:
            raise HTTPException(400, str(e))
        new_ids = {t["id"] for t in league_trades_layer.new_trades(trades, [x for x in seen.split(",") if x])}
        for t in trades:
            t["is_new"] = t["id"] in new_ids
        return _clean({"trades": trades})
    try:
        live = sleeper_layer.get_nfl_state().get("week") or 1
        trades = league_trades_layer.league_trades(active["league_id"], range(1, max(1, int(live)) + 1))
    except Exception as e:
        raise HTTPException(400, str(e))
    new_ids = {t["id"] for t in league_trades_layer.new_trades(trades, [x for x in seen.split(",") if x])}
    for t in trades:
        t["is_new"] = t["id"] in new_ids
    return _clean({"trades": trades})


# --------------------------------------------------------------------- draft ----
@app.get("/api/myteam/drafts")
def api_my_drafts(user=Depends(require_user)):
    """List the active team's league's drafts (usually one), so the frontend
    can find the draft_id without the user hunting for it."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    if active.get("platform") == "espn":
        # Live draft support is Sleeper-only by design (see README
        # Roadmap) — an empty list here just hides the draft-board entry
        # point in the UI, same as "no active draft" for a Sleeper
        # league, rather than surfacing an error for a totally normal
        # "your league is ESPN" case.
        return {"roster_id": active["roster_id"], "drafts": []}
    try:
        drafts = sleeper_layer.get_league_drafts(active["league_id"])
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"roster_id": active["roster_id"], "drafts": _clean(drafts)}


@app.get("/api/draft/{draft_id}")
def api_draft_board(draft_id: str, roster_id: Optional[int] = Query(None),
                     scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(current_user)):
    scoring = _effective_scoring(scoring, user)
    if roster_id is None and user:
        # convenience: if signed in, default to the active team's roster_id
        # (the frontend gets draft_id from /api/myteam/drafts, which is
        # already scoped to that same league, so this is a safe default —
        # an explicit ?roster_id= always overrides it)
        active = db.get_active_team(user["id"])
        if active:
            roster_id = int(active["roster_id"])
    try:
        result = tools.draft_board(draft_id, my_roster_id=roster_id, scoring=scoring)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean(result)


@app.get("/api/trade-finder")
def api_trade_finder(target_roster_id: Optional[int] = Query(None),
                      give: Optional[List[str]] = Query(None, description="player_id(s) you want to shop — omit for need-driven auto suggestions"),
                      scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(require_user)):
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            result = tools.trade_finder_espn(active["league_id"], int(active["roster_id"]),
                                             target_roster_id=target_roster_id, give_player_ids=give,
                                             scoring=scoring, espn_s2=espn_s2, swid=swid)
        else:
            result = tools.trade_finder(active["league_id"], int(active["roster_id"]),
                                         target_roster_id=target_roster_id, give_player_ids=give, scoring=scoring)
    except Exception as e:
        raise HTTPException(400, str(e))
    if result.get("suggestions"):
        # Activation: this user just got a real, non-empty result for their own
        # league. Best-effort only — analytics must never break the feature, and
        # the table won't exist until its migration is applied.
        try:
            db.record_activation_event(user["id"], "trade_finder_result_viewed", active["league_id"])
        except Exception as e:
            print(f"[activation] couldn't record trade_finder_result_viewed: {e}")
    return _clean(result)


@app.get("/api/trade/teams")
def api_trade_teams(user=Depends(require_user)):
    """Every team in your active league — populates the Trade tab's
    opponent switcher."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    try:
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            teams = tools.league_team_list_espn(active["league_id"], espn_s2=espn_s2, swid=swid)
        else:
            teams = tools.league_team_list(active["league_id"])
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean({"my_roster_id": int(active["roster_id"]), "teams": teams})


@app.get("/api/trade/roster")
def api_trade_roster(roster_id: int = Query(...), scoring: Optional[dict] = Depends(scoring_from_query),
                      user=Depends(require_user)):
    """One team's full roster with real values — either side of the Trade
    tab's split-screen builder."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            result = tools.roster_player_list_espn(active["league_id"], roster_id, scoring=scoring,
                                                     espn_s2=espn_s2, swid=swid)
        else:
            result = tools.roster_player_list(active["league_id"], roster_id, scoring=scoring)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean(result)


# --------------------------------------------------------------------- news ----
@app.get("/api/news")
def api_news(scope: str = Query("team", pattern="^(team|opponent|league|favorite)$"),
             team: Optional[str] = Query(None, max_length=3), user=Depends(current_user)):
    """Four tabs, one feed underneath:
      - favorite: every headline naming the favorite NFL team in `team` (public, no roster needed)
      - team: headlines matched to your own roster
      - opponent: headlines matched to this week's real head-to-head opponent
      - league: every headline, with ones matching anyone rostered in your
        league surfaced first (an item's own `matched_players` — attached
        whether or not the whole feed is filtered to it — tells the client
        which player a given headline is about)."""
    items = news_layer.all_headlines()

    if scope == "favorite":
        code = (team or "").upper()
        if code not in news_layer.TEAM_CODES:
            raise HTTPException(422, "team must be an NFL team code")
        return {"scope": "favorite", "team": code, "items": _clean(news_layer.team_headlines(items, code)),
                "sources": list(news_layer.FEEDS)}

    if scope == "league":
        league_players = []
        if user:
            active = db.get_active_team(user["id"])
            if active:
                try:
                    if active.get("platform") == "espn":
                        espn_s2, swid = db.get_espn_secrets(user["id"])
                        league_players = tools.league_all_player_names_espn(active["league_id"],
                                                                              espn_s2=espn_s2, swid=swid)
                    else:
                        league_players = tools.league_all_player_names(active["league_id"])
                except Exception as e:
                    print(f"[news] couldn't build league name list: {e}")
        matched = news_layer.filter_for_players(items, league_players)          # strongest match first
        seen = {it["link"] for it in matched}
        rest = sorted((it for it in items if it["link"] not in seen), key=lambda it: -(it.get("ts") or 0))
        return {"scope": "league", "items": _clean((matched + rest)[:40]), "sources": list(news_layer.FEEDS)}

    if not user:
        return {"scope": scope, "items": [], "requires_team": True}
    active = db.get_active_team(user["id"])
    if not active:
        return {"scope": scope, "items": [], "requires_team": True}
    try:
        # Same platform split as _load_my_team: an ESPN team's league id
        # means nothing to Sleeper, so the Sleeper-only my_team() 400'd the
        # Team and Opponent news tabs for every ESPN-connected user.
        if active.get("platform") == "espn":
            espn_s2, swid = db.get_espn_secrets(user["id"])
            team = tools.my_team_espn(active["league_id"], int(active["roster_id"]), espn_s2=espn_s2, swid=swid)
        else:
            # names and teams only; my_team() would project every player just to get these
            team = tools.news_rosters(active["league_id"], int(active["roster_id"]))
    except Exception as e:
        raise HTTPException(400, str(e))

    if scope == "opponent":
        if not team["opponent"]:
            return {"scope": "opponent", "team_name": None, "items": [],
                     "message": f"No head-to-head opponent set for week {team['nfl_week']} yet."}
        filtered = news_layer.filter_for_players(items, team["opponent"]["players"], include_team_news=True)
        return {"scope": "opponent", "team_name": team["opponent"]["team_name"], "items": _clean(filtered),
                "sources": list(news_layer.FEEDS)}

    filtered = news_layer.filter_for_players(items, team["my_team"]["players"], include_team_news=True)
    return {"scope": "team", "team_name": team["my_team"]["team_name"], "items": _clean(filtered),
            "sources": list(news_layer.FEEDS)}


@app.get("/api/live-scores")
def api_live_scores():
    """Real in-game NFL scores for the current week (see engine/live_scores.py)
    — public data, no sign-in required, cached for 20s server-side so a
    room full of open tabs doesn't turn into a request per tab."""
    return {"games": live_scores_layer.live_scoreboard()}


boxscore_rate_limit = rate_limit("boxscore", limit=60, window_seconds=60)


@app.get("/api/live-scores/{game_id}", dependencies=[Depends(boxscore_rate_limit)])
def api_game_boxscore(game_id: str, scoring: Optional[dict] = Depends(scoring_from_query),
                      user=Depends(current_user)):
    """Both teams' player stat lines for one game (engine/boxscore.py). Public;
    when the caller is signed in with a connected league, their players are
    flagged `mine` and every skill player carries fantasy points under that
    league's scoring. A roster that can't be loaded just means no highlights."""
    if not boxscore_layer.valid_game_id(game_id):
        raise HTTPException(400, "bad game id")
    parsed = boxscore_layer.game_boxscore(game_id)
    roster = None
    if user:
        try:
            _, team = _load_my_team(user, None, scoring)
            roster = team["my_team"]["players"]
        except Exception as e:
            print(f"[boxscore] no roster to highlight: {e}")
    try:
        pts_scoring = _effective_scoring(scoring, user)
    except Exception as e:   # settings store down: show default-PPR points rather than failing public data
        print(f"[boxscore] scoring settings unavailable, using default: {e}")
        pts_scoring = scoring
    return _clean(boxscore_layer.annotate(parsed, roster, pts_scoring))


# ---- image proxy ----
# Player headshots and news photos hotlink straight to their real publisher
# CDNs (nfl.com, sleepercdn.com, espncdn.com, cbsistatic.com) — real images,
# not something we host. Some browsers' ad/privacy blockers flag those CDN
# hostnames anyway (they're known ad-network-adjacent domains on several
# filter lists) and silently drop the request, which looks identical to a
# broken image with no error to debug. Proxying through this same-origin
# endpoint sidesteps that: the browser only ever talks to this server.
# Restricted to a real allowlist, not an open proxy — SSRF risk otherwise.
_IMG_PROXY_ALLOWED_HOSTS = {
    "static.www.nfl.com", "sleepercdn.com", "a.espncdn.com",
    "sportshub.cbsistatic.com", "static.nfl.com",
}
_IMG_PROXY_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache", "img_proxy")
os.makedirs(_IMG_PROXY_CACHE_DIR, exist_ok=True)


@app.get("/api/img")
def api_img_proxy(url: str = Query(...)):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in _IMG_PROXY_ALLOWED_HOSTS:
        raise HTTPException(400, "That image host isn't on the allowlist.")

    cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = os.path.join(_IMG_PROXY_CACHE_DIR, cache_key)
    meta_path = cache_path + ".type"
    if os.path.exists(cache_path) and (time.time() - os.path.getmtime(cache_path)) < 24 * 60 * 60:
        content_type = open(meta_path).read().strip() if os.path.exists(meta_path) else "image/jpeg"
        return FileResponse(cache_path, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})

    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            raise HTTPException(502, "That URL didn't return an image.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Couldn't fetch that image: {e}")

    with open(cache_path, "wb") as f:
        f.write(resp.content)
    with open(meta_path, "w") as f:
        f.write(content_type)
    return Response(content=resp.content, media_type=content_type, headers={"Cache-Control": "public, max-age=86400"})


# The two files that change on every deploy and are correctness-critical
# if stale (a returning user silently running yesterday's JS against
# today's API shape) get an explicit `Cache-Control: no-cache` — NOT
# "don't cache," but "always revalidate with the server first" (a cheap
# conditional GET against the Last-Modified/ETag the StaticFiles mount
# below already sets; a 304 costs basically nothing). Found this the hard
# way while testing the Projection Breakdown/GONE DARK work above: with
# no Cache-Control at all (StaticFiles' default), a browser can serve a
# stale app.js indefinitely with no revalidation, which — combined with
# this app's deploy-and-forget workflow (commit + push, Render
# auto-deploys, no version-hashed filenames) — means a real returning
# user could silently keep running old frontend code after a deploy until
# something forces a hard refresh. Registered before the catch-all mount
# so these two take priority for their exact paths; everything else
# (icons, images, manifest, sw.js) keeps the mount's default behavior,
# which is fine for assets that don't change every deploy.
@app.get("/app.js", include_in_schema=False)
def _app_js():
    return FileResponse("static/app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


# The theme files are correctness-critical on every load for the same reason: theme-boot.js runs before first paint.
for _theme_js in ("team-themes.js", "theme-boot.js", "theme.js"):
    def _theme_script(_f=_theme_js):
        return FileResponse(f"static/{_f}", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
    app.add_api_route(f"/{_theme_js}", _theme_script, methods=["GET"], include_in_schema=False)


@app.get("/style.css", include_in_schema=False)
def _style_css():
    return FileResponse("static/style.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


# The page shell itself has the exact same staleness risk as app.js/
# style.css above, and it's the one that actually bit real testing
# tonight: a browser served a cached index.html with none of a brand-new
# section's markup (the Start/Sit toolbar) even on a fresh navigation,
# because the catch-all mount below sets no Cache-Control on "/" either.
# Same fix, same reasoning.
@app.get("/", include_in_schema=False)
def _index():
    return FileResponse("static/index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})



_LEGAL_PAGES = {"terms": "legal/TERMS_OF_SERVICE.md", "privacy": "legal/PRIVACY_POLICY.md"}


@app.get("/legal/{page}", include_in_schema=False)
def _legal(page: str):
    """Serve the Terms / Privacy markdown (repo files we author, not user input) as a readable page."""
    import markdown
    path = _LEGAL_PAGES.get(page)
    if not path:
        raise HTTPException(status_code=404, detail="Not found")
    with open(path, encoding="utf-8") as fh:
        body = markdown.markdown(fh.read(), extensions=["tables", "sane_lists"])
    page_html = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                 "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                 "<title>Lineup Lab \u2014 " + page.capitalize() + "</title>"
                 "<style>body{margin:0;background:#0b1020;color:#e6e9f2;font:16px/1.65 system-ui,-apple-system,sans-serif}"
                 "main{max-width:760px;margin:0 auto;padding:24px 18px 64px}a{color:#7aa2ff}"
                 "h1{font-size:28px;margin:8px 0 4px}h2{font-size:20px;margin:32px 0 8px}"
                 "code{background:#1a2238;padding:1px 5px;border-radius:4px;font-size:.9em}"
                 "table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}"
                 "th,td{border:1px solid #2a3350;padding:8px 10px;text-align:left;vertical-align:top}"
                 "th{background:#141b30}li{margin:4px 0}</style></head><body><main>"
                 "<p><a href=\"/\">&larr; Back to Lineup Lab</a></p>" + body + "</main></body></html>")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(page_html, headers={"Cache-Control": "no-cache"})


# ---- static frontend (must be mounted last so /api/* above takes priority) ----
app.mount("/", StaticFiles(directory="static", html=True), name="static")
