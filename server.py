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
  - rate limiting on auth endpoints (login/signup/resend/forgot-password)
  - standard hardening response headers (nosniff, frame-deny, referrer policy)
  - no wildcard CORS — this process serves its own frontend, same-origin only
  - parameterized SQL everywhere (see engine/db.py); no string-built queries
  - this is a LAN-local dev app, not TLS-terminated — see README before
    exposing it beyond your own network
"""

import hashlib
import math
import os
import secrets
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import data as data_layer
from engine import db
from engine import mail as mail_layer
from engine import news as news_layer
from engine import oauth as oauth_layer
from engine import sleeper as sleeper_layer
from engine import tools
from engine.advanced import ADVANCED_COLS
from engine.board import (POSITIONS, build_board, load_bundle, matchup_multiplier,
                           player_detail, project_vs, search_players)
from engine.metrics import WEIGHTS
from engine.scoring import PRESETS

app = FastAPI(title="Lineup Lab API")

SESSION_COOKIE = "eb_session"


# ------------------------------------------------------------- security ----
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    # this app has no external script/style/image dependencies — a strict
    # CSP costs nothing here and blocks injected-script XSS even if a data
    # value somehow slipped past escaping
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    )
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

OAUTH_STATE_COOKIE = "eb_oauth_state"


def _clean(obj):
    """Recursively replace NaN/inf with None so the JSON encoder doesn't choke."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
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


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _send_verification(request: Request, user):
    """Best-effort: signup/resend never fails because mail isn't set up —
    the account just stays unverified until it is."""
    if not mail_layer.configured():
        print("[mail] GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set — skipping verification email "
              "(see .env.example)")
        return
    token = db.create_verification_token(user["id"])
    verify_url = f"{str(request.base_url).rstrip('/')}/api/auth/verify?token={token}"
    try:
        mail_layer.send_verification_email(user["email"], user["username"], verify_url)
    except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
        print(f"[mail] couldn't send verification email: {e}")


@app.post("/api/auth/signup", dependencies=[Depends(signup_rate_limit)])
def signup(req: SignupRequest, request: Request, response: Response):
    try:
        user = db.create_user(req.username, req.email, req.password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    _set_session_cookie(request, response, db.create_session(user["id"]))
    _send_verification(request, user)
    return user


@app.get("/api/auth/verify", include_in_schema=False)
def verify_email(token: str):
    try:
        db.consume_verification_token(token)
        return RedirectResponse(url="/?verified=1")
    except db.AuthError:
        return RedirectResponse(url="/?verified=0")


@app.post("/api/auth/resend-verification", dependencies=[Depends(mail_rate_limit)])
def resend_verification(request: Request, user=Depends(require_user)):
    if user["email_verified"]:
        return {"status": "already_verified"}
    if not mail_layer.configured():
        raise HTTPException(400, "Email isn't set up on this server yet — see .env.example.")
    _send_verification(request, user)
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
def oauth_google_callback(request: Request, response: Response, code: Optional[str] = None,
                           state: Optional[str] = None, error: Optional[str] = None):
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
def change_password(req: ChangePasswordRequest, user=Depends(require_user)):
    try:
        db.change_password(user["id"], req.current_password, req.new_password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@app.post("/api/auth/forgot-password", dependencies=[Depends(mail_rate_limit)])
def forgot_password(req: ForgotPasswordRequest, request: Request):
    """Always returns the same generic response whether or not the email
    exists — otherwise this endpoint would let anyone probe which emails
    have accounts (account enumeration)."""
    user = db.get_user_by_email(req.email)
    if user and mail_layer.configured():
        token = db.create_reset_token(user["id"])
        reset_url = f"{str(request.base_url).rstrip('/')}/?reset_token={token}"
        try:
            mail_layer.send_password_reset_email(user["email"], user["username"], reset_url)
        except (mail_layer.MailNotConfigured, mail_layer.MailSendError) as e:
            print(f"[mail] couldn't send reset email: {e}")
    return {"status": "ok", "message": "If that email has an account, a reset link is on its way."}


@app.post("/api/auth/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request, response: Response):
    try:
        user = db.reset_password(req.token, req.new_password)
    except db.AuthError as e:
        raise HTTPException(400, str(e))
    _set_session_cookie(request, response, db.create_session(user["id"]))
    return user


# --------------------------------------------------------------- settings ----
class SettingsUpdate(BaseModel):
    espn_league_id: Optional[str] = None
    espn_swid: Optional[str] = None
    espn_s2: Optional[str] = None
    scoring_preset: Optional[str] = None
    theme: Optional[str] = None


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
):
    overrides = {k: v for k, v in dict(
        reception=reception, pass_yard=pass_yard, pass_td=pass_td, interception=interception,
        rush_yard=rush_yard, rush_td=rush_td, rec_yard=rec_yard, rec_td=rec_td,
        fumble_lost=fumble_lost, two_pt=two_pt,
    ).items() if v is not None}
    if scoring is None and not overrides:
        return None  # fast path: nflverse's precomputed full-PPR column
    base = dict(PRESETS.get(scoring or "ppr", PRESETS["ppr"]))
    base.update(overrides)
    return base


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse("static/icons/favicon-32.png")


@app.get("/api/health")
def health():
    season = data_layer.resolve_season()
    return {"status": "ok", "season": season}


@app.get("/api/meta")
def meta(user=Depends(current_user)):
    """Season, positions, teams, weight config, scoring presets — everything
    the frontend needs to build its filters."""
    bundle = load_bundle()
    teams = sorted(bundle["wk"]["recent_team"].dropna().unique().tolist())
    return {
        "season": bundle["season"],
        "positions": list(POSITIONS),
        "teams": teams,
        "weights": WEIGHTS,
        "advanced_columns": ADVANCED_COLS,
        "scoring_presets": PRESETS,
        "scoring_fields": SCORING_FIELDS,
        "signed_in": user is not None,
        "mail_configured": mail_layer.configured(),
        "oauth_google": oauth_layer.google_configured(),
        "oauth_apple": oauth_layer.apple_configured(),
    }


@app.get("/api/board")
def api_board(
    pos: str = Query(..., description="QB, RB, WR, or TE"),
    opp: Optional[str] = Query(None, description="opponent defense abbr, e.g. WAS"),
    min_games: int = Query(2, ge=0),
    limit: int = Query(60, ge=1, le=300),
    scoring: Optional[dict] = Depends(scoring_from_query),
    user=Depends(current_user),
):
    pos = pos.upper()
    if pos not in POSITIONS:
        raise HTTPException(400, f"pos must be one of {POSITIONS}")
    scoring = _effective_scoring(scoring, user)

    bundle = load_bundle()
    board = build_board(pos, min_games=min_games, scoring=scoring)
    breakdown = []
    if opp:
        opp = opp.upper()
        board = project_vs(board, pos, opp, bundle=bundle, scoring=scoring)
        breakdown = board.attrs.get("matchup_breakdown", [])

    board = board.head(limit).reset_index()
    board.insert(0, "rank", range(1, len(board) + 1))
    records = _clean(board.to_dict(orient="records"))
    return {"season": bundle["season"], "position": pos, "opponent": opp, "count": len(records),
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


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=50)):
    return {"query": q, "results": _clean(search_players(q, limit=limit))}


@app.get("/api/team/{team}/next")
def api_team_next(team: str):
    bundle = load_bundle()
    opp, wk_no = data_layer.next_opponent(bundle["schedule"], team.upper())
    return {"team": team.upper(), "opponent": opp, "week": wk_no}


@app.post("/api/refresh")
def api_refresh():
    """Force-refetch all data (bypasses the disk cache)."""
    bundle = load_bundle(force=True)
    return {"status": "refreshed", "season": bundle["season"]}


# ------------------------------------------------------------ decision tools ----
class StartSitRequest(BaseModel):
    player_ids: List[str]
    opponents: Optional[Dict[str, str]] = None   # {player_id: opp_abbr}
    scoring: Optional[dict] = None


@app.post("/api/startsit")
def api_startsit(req: StartSitRequest, user=Depends(current_user)):
    if len(req.player_ids) < 2:
        raise HTTPException(400, "need at least 2 players to compare")
    scoring = _effective_scoring(req.scoring, user)
    result = tools.start_sit(req.player_ids, opponents=req.opponents, scoring=scoring)
    return _clean(result)


class TradeRequest(BaseModel):
    side_a: List[str]
    side_b: List[str]
    scoring: Optional[dict] = None


@app.post("/api/trade")
def api_trade(req: TradeRequest, user=Depends(current_user)):
    if not req.side_a or not req.side_b:
        raise HTTPException(400, "both sides need at least 1 player")
    scoring = _effective_scoring(req.scoring, user)
    result = tools.trade_analyzer(req.side_a, req.side_b, scoring=scoring)
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


# ------------------------------------------------------------- league sync ----
@app.get("/api/sleeper/{league_id}")
def api_sleeper_league(league_id: str, refresh: bool = False):
    try:
        snap = sleeper_layer.league_snapshot(league_id, force=refresh)
    except Exception as e:
        raise HTTPException(400, f"couldn't load Sleeper league {league_id}: {e}")
    return _clean(snap)


class ConnectTeamRequest(BaseModel):
    league_id_or_url: str


@app.post("/api/teams/lookup")
def api_teams_lookup(req: ConnectTeamRequest):
    """Step 1 of connecting a team: accepts a bare Sleeper league ID OR a
    pasted Sleeper league URL, and returns the league's teams to pick from."""
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


@app.get("/api/teams")
def api_teams_list(user=Depends(require_user)):
    return {"teams": db.list_connected_teams(user["id"])}


@app.post("/api/teams")
def api_teams_add(req: AddTeamRequest, user=Depends(require_user)):
    team = db.add_connected_team(
        user["id"], "sleeper", req.league_id, req.roster_id, req.team_name, req.league_name, req.avatar_url,
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


@app.get("/api/myteam")
def api_my_team(week: Optional[int] = Query(None, ge=1, le=25),
                 scoring: Optional[dict] = Depends(scoring_from_query), user=Depends(require_user)):
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a Sleeper league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        result = tools.my_team(active["league_id"], int(active["roster_id"]), scoring=scoring, week=week)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean(result)


# --------------------------------------------------------------------- draft ----
@app.get("/api/myteam/drafts")
def api_my_drafts(user=Depends(require_user)):
    """List the active team's league's drafts (usually one), so the frontend
    can find the draft_id without the user hunting for it."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a Sleeper league in Settings first")
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
        raise HTTPException(400, "connect a Sleeper league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        result = tools.trade_finder(active["league_id"], int(active["roster_id"]),
                                     target_roster_id=target_roster_id, give_player_ids=give, scoring=scoring)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean(result)


@app.get("/api/trade/teams")
def api_trade_teams(user=Depends(require_user)):
    """Every team in your active league — populates the Trade tab's
    opponent switcher."""
    active = db.get_active_team(user["id"])
    if not active:
        raise HTTPException(400, "connect a Sleeper league in Settings first")
    try:
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
        raise HTTPException(400, "connect a Sleeper league in Settings first")
    scoring = _effective_scoring(scoring, user)
    try:
        result = tools.roster_player_list(active["league_id"], roster_id, scoring=scoring)
    except Exception as e:
        raise HTTPException(400, str(e))
    return _clean(result)


# --------------------------------------------------------------------- news ----
@app.get("/api/news")
def api_news(scope: str = Query("team", pattern="^(team|opponent|league)$"), user=Depends(current_user)):
    """Three tabs, one feed underneath:
      - team: headlines matched to your own roster
      - opponent: headlines matched to this week's real head-to-head opponent
      - league: every headline, with ones matching anyone rostered in your
        league surfaced first (an item's own `matched_players` — attached
        whether or not the whole feed is filtered to it — tells the client
        which player a given headline is about)."""
    items = news_layer.all_headlines()

    if scope == "league":
        league_players = []
        if user:
            active = db.get_active_team(user["id"])
            if active:
                try:
                    league_players = tools.league_all_player_names(active["league_id"])
                except Exception as e:
                    print(f"[news] couldn't build league name list: {e}")
        tagged_by_link = {it["link"]: it for it in news_layer.filter_for_players(items, league_players)}
        ordered = [tagged_by_link.get(it["link"], it) for it in items]
        ordered.sort(key=lambda it: "matched_players" not in it)  # featured (matched) first, stable otherwise
        return {"scope": "league", "items": _clean(ordered[:30])}

    if not user:
        return {"scope": scope, "items": [], "requires_team": True}
    active = db.get_active_team(user["id"])
    if not active:
        return {"scope": scope, "items": [], "requires_team": True}
    try:
        team = tools.my_team(active["league_id"], int(active["roster_id"]))
    except Exception as e:
        raise HTTPException(400, str(e))

    if scope == "opponent":
        if not team["opponent"]:
            return {"scope": "opponent", "team_name": None, "items": [],
                     "message": f"No head-to-head opponent set for week {team['nfl_week']} yet."}
        filtered = news_layer.filter_for_players(items, team["opponent"]["players"])
        return {"scope": "opponent", "team_name": team["opponent"]["team_name"], "items": _clean(filtered)}

    filtered = news_layer.filter_for_players(items, team["my_team"]["players"])
    return {"scope": "team", "team_name": team["my_team"]["team_name"], "items": _clean(filtered)}


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


# ---- static frontend (must be mounted last so /api/* above takes priority) ----
app.mount("/", StaticFiles(directory="static", html=True), name="static")
