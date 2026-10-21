"""
START/SIT DECISION ENGINE — ranges, odds, ratings and flags
===========================================================
Turns each player's projection into a range of outcomes and a decision:

  * Outcome range: a gamma distribution with mean = the projection and a
    spread from his own game-to-game variation, shrunk toward his position's
    typical spread by how few games he has (8 games of weight on the
    position, x1.15 width). Fitted on the full 2025 season; checked on 2026
    weeks 3-6 (662 player-games): 13% of games finished above the 90th
    percentile and 15% below the 10th, against 10% each if it were perfect,
    and the median split 49/51. P(10+) and P(20+) come from the same curve.
  * Start/Sit Rating (0-100):
        0.40 role & expected points   (xFP/g, snap share, target share / HVT;
                                        +/-15 if his last 4 games' xFP moved vs season)
        0.30 matchup                   (defense vs his position, league-relative)
        0.20 game script & team total  (Vegas implied total, spread fit, his
                                        share of work when leading vs trailing)
        0.10 recent form & health      (FORM, usage trend, injury tag)
  * Verdict by win condition: floor (protect a lead), balanced, ceiling
    (chasing as an underdog), with the chance each player outscores the other.

Not modelled (no free source): route participation, DVOA, man/zone coverage
splits, two-minute-drill snaps.
"""

import numpy as np
import pandas as pd

from . import defense as defense_layer, play_prob

CV_SCALE = 1.15
CV_PRIOR_GAMES = 8
SAMPLES = 4000
WEIGHTS = {"role": 0.40, "matchup": 0.30, "script": 0.20, "recent": 0.10}
MODES = {"safe": "floor", "balanced": "balanced", "upside": "ceiling"}

DEF_LABELS = {
    "ypt_allowed": "yards per target", "pass_td_rate_allowed": "passing TD rate", "sep_allowed": "receiver separation",
    "yac_oe_allowed": "yards after catch", "ypc_allowed": "yards per carry", "rush_td_rate_allowed": "rushing TD rate",
    "rush_efficiency_allowed": "rushing efficiency", "ypa_allowed": "yards per attempt", "comp_pct_allowed": "completion %",
    "pass_epa_cpoe_allowed": "passing efficiency", "explosive_pass_rate_allowed": "explosive pass rate",
    "explosive_run_rate_allowed": "explosive run rate",
}
POS_DEF_COLS = {
    "QB": ["ypa_allowed", "pass_td_rate_allowed", "comp_pct_allowed", "explosive_pass_rate_allowed"],
    "RB": ["ypc_allowed", "rush_td_rate_allowed", "explosive_run_rate_allowed", "ypt_allowed"],
    "WR": ["ypt_allowed", "pass_td_rate_allowed", "sep_allowed", "yac_oe_allowed", "explosive_pass_rate_allowed"],
    "TE": ["ypt_allowed", "pass_td_rate_allowed", "sep_allowed", "yac_oe_allowed"],
}


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ------------------------------------------------------------- outcomes ----
def shrunk_cv(cv, games, pos_cv):
    """His own game-to-game spread (std/mean), pulled toward his position's
    typical spread by how few games he has, then widened by CV_SCALE."""
    if cv is None or pd.isna(cv) or not games:
        base = pos_cv
    else:
        base = (games * float(cv) + CV_PRIOR_GAMES * pos_cv) / (games + CV_PRIOR_GAMES)
    return max(0.15, base * CV_SCALE)


def outcomes(proj, cv, seed=0, p_play=1.0):
    """Range of outcomes for a projection: p10/p50/p90, P(10+), P(20+), and
    the samples (for head-to-head odds). Deterministic for a given seed.
    `proj` is his score if he plays; with p_play < 1 that share of games is a
    zero, so a Questionable player keeps his upside but loses his floor."""
    proj = max(0.1, float(proj))
    k = 1.0 / cv ** 2
    rng = np.random.default_rng(seed)
    s = rng.gamma(k, proj / k, SAMPLES)
    if p_play < 1.0:
        s = np.where(rng.random(SAMPLES) < p_play, s, 0.0)
    q = np.percentile(s, [10, 50, 90])
    return {"p10": round(float(q[0]), 1), "p50": round(float(q[1]), 1), "p90": round(float(q[2]), 1),
            "mean": round(proj * p_play, 1), "cv": round(cv, 3), "p_play": round(p_play, 3),
            "p_10plus": round(float((s >= 10).mean()) * 100), "p_20plus": round(float((s >= 20).mean()) * 100),
            "_samples": s}


WONT_PLAY = ("Out", "IR", "PUP", "Sus")


def ruled_out():
    """A player who won't play scores zero."""
    return {"p10": 0.0, "p50": 0.0, "p90": 0.0, "mean": 0.0, "cv": None, "p_10plus": 0, "p_20plus": 0,
            "out": True, "_samples": np.zeros(SAMPLES)}


def curve(samples, lo, hi, bins=40):
    """Smoothed density over [lo, hi] for the chart: list of heights 0-1."""
    h, _ = np.histogram(samples, bins=bins, range=(lo, hi), density=True)
    h = np.convolve(h, np.ones(3) / 3, mode="same")
    m = h.max() or 1
    return [round(float(v / m), 3) for v in h]


def beat_prob(a, b):
    """Chance player a outscores player b (independent draws)."""
    return round(float((a > b).mean()) * 100)


# --------------------------------------------------------- script split ----
def snap_trend(snaps):
    """Change in snap share (points) when BOTH of his last 2 games moved the
    same way vs his earlier median; 0 when they disagree (one odd game, like
    leaving early hurt, isn't a trend). None with fewer than 4 games."""
    if len(snaps) < 4:
        return None
    med = float(np.median(snaps[:-2]))
    a, b = snaps[-2:]
    down, up = max(a, b) - med, min(a, b) - med
    return down if down < 0 else up if up > 0 else 0.0


def script_split(pbp, player_id, team, margin=7, weeks=None):
    """His share of his team's targets + carries when leading by `margin`+ vs
    trailing by `margin`+, counting only games he played (`weeks`). None
    without enough plays either way."""
    if "score_differential" not in pbp.columns:
        return None
    p = pbp[(pbp["posteam"] == team) & pbp["play_type"].isin(["run", "pass"])]
    if weeks is not None:
        p = p[p["week"].isin(weeks)]
    p = p[p["rusher_player_id"].notna() | p["receiver_player_id"].notna()]
    out = {}
    for name, mask in (("leading", p["score_differential"] >= margin), ("trailing", p["score_differential"] <= -margin)):
        sub = p[mask]
        if len(sub) < 25:
            return None
        mine = ((sub["rusher_player_id"] == player_id) | (sub["receiver_player_id"] == player_id)).sum()
        out[name] = round(100 * mine / len(sub), 1)
        out[f"{name}_plays"] = int(len(sub))
    return out


# ------------------------------------------------------------ recent form ----
RECENT_GAMES = 4


def recent_usage(player_id, position, wk, snaps, xfp, rz_carries, n=RECENT_GAMES):
    """Opportunity over his last `n` games next to his season average:
    {games, weeks, snap_pct, target_share, hvt_pg, xfp_pg} with each value a
    {recent, season} pair. Target share is a percent; HVT (red-zone carries +
    targets) is RBs only; xFP is skipped for QBs (passing isn't modelled)."""
    g = wk[wk["player_id"] == player_id].sort_values("week")
    if g.empty:
        return None
    weeks = [int(w) for w in g["week"]]
    last = weeks[-n:]

    def pair(series_by_week, scale=1.0):
        vals = {w: v for w, v in series_by_week.items() if v is not None and not pd.isna(v)}
        if not vals:
            return None
        rec = [vals[w] for w in last if w in vals]
        return {"recent": round(float(np.mean(rec)) * scale, 1) if rec else None,
                "season": round(float(np.mean(list(vals.values()))) * scale, 1)}

    ts = dict(zip(g["week"].astype(int), g["target_share"])) if "target_share" in g.columns else {}
    out = {"games": len(last), "weeks": last,
           "snap_pct": pair({w: snaps.get(w) for w in weeks}),
           "target_share": pair(ts, 100.0) if position != "QB" else None}
    if position == "RB":
        tg = dict(zip(g["week"].astype(int), g["targets"].fillna(0)))
        out["hvt_pg"] = pair({w: tg.get(w, 0) + rz_carries.get(w, 0) for w in weeks})
    else:
        out["hvt_pg"] = None
    if position != "QB" and xfp is not None:
        out["xfp_pg"] = pair({w: xfp.get(w, 0.0) for w in weeks})
    else:
        out["xfp_pg"] = None
    return out


# --------------------------------------------------------------- matchup ----
def defense_rank(position, opp, factors):
    """1 = easiest matchup for this position among every defense."""
    if opp not in factors.index:
        return None, None
    vals = {t: defense_layer.composite_multiplier(position, t, factors) for t in factors.index}
    order = sorted(vals, key=lambda t: -vals[t])
    return order.index(opp) + 1, len(order)


def matchup_flags(position, opp, factors):
    """(good, bad) strings about this defense vs this position, strongest first."""
    good, bad = [], []
    if opp not in factors.index:
        return good, bad
    rows = []
    for col in POS_DEF_COLS.get(position, []):
        if col not in factors.columns:
            continue
        v = float(factors.loc[opp, col])
        rank = int((factors[col] > v).sum()) + 1   # 1 = allows the most
        rows.append((abs(v - 1), col, v, rank, len(factors)))
    for _, col, v, rank, n in sorted(rows, reverse=True)[:3]:
        label = DEF_LABELS.get(col, col)
        pct = round(abs(v - 1) * 100)
        if v >= 1.08:
            good.append(f"{opp} gives up {label} {pct}% above average ({_ord(rank)}-worst of {n} defenses)")
        elif v <= 0.92:
            bad.append(f"{opp} holds {label} {pct}% below average ({_ord(n - rank + 1)}-best of {n} defenses)")
    if position == "QB" and "pressure_rate_generated" in factors.columns:
        pr = float(factors.loc[opp, "pressure_rate_generated"])
        if pr >= 1.10:
            bad.append(f"{opp} pressures QBs {round((pr - 1) * 100)}% more than average")
        elif pr <= 0.90:
            good.append(f"{opp} pressures QBs {round((1 - pr) * 100)}% less than average")
    return good, bad


# ---------------------------------------------------------------- rating ----
def _clip(v):
    return float(np.clip(v, 0, 100))


def role_shift(recent):
    """Points (+/-15) for a role growing or shrinking: his last-4-games xFP
    (or snap share for QBs) vs his season average."""
    if not recent:
        return 0.0
    x = recent.get("xfp_pg") or recent.get("snap_pct")
    if not x or x.get("recent") is None or not x.get("season"):
        return 0.0
    return float(np.clip((x["recent"] - x["season"]) / x["season"] * 50, -15, 15))


def rating(r, usage_pct, ctx, split, mrank, recent=None):
    """(rating 0-100, components) for one player row."""
    role = _clip((usage_pct if usage_pct is not None else 50.0) + role_shift(recent))
    mf = r.get("matchup_factor")
    m_score = _clip(((mf or 1.0) - 0.85) / 0.30 * 100)
    if mrank and mrank[0]:
        m_score = 0.5 * m_score + 0.5 * _clip(100 * (1 - (mrank[0] - 1) / max(1, mrank[1] - 1)))
    script = 50.0
    if ctx and ctx.get("implied_total") is not None:
        script = _clip((ctx["implied_total"] - 16) / 13 * 100)
        margin = ctx.get("margin") or 0
        if split:
            likely = split["leading"] if margin >= 3 else split["trailing"] if margin <= -3 else None
            other = split["trailing"] if margin >= 3 else split["leading"] if margin <= -3 else None
            if likely is not None and other:
                script = _clip(script + (likely - other) / other * 40)
    form = r.get("FORM") or 0
    recent = _clip(50 + form * 2)
    u = r.get("usage") or {}
    if u.get("label") == "rising":
        recent = _clip(recent + 15)
    elif u.get("label") == "falling":
        recent = _clip(recent - 15)
    if r.get("injury_status") in ("Questionable",):
        pp = play_prob.play_probability(r.get("position"), "Questionable", r.get("injury_report"))
        recent = _clip(recent - (round((1 - pp["p_play"]) * 50) if pp else 20))
    elif r.get("injury_status") in ("Doubtful", "Out", "IR"):
        recent = 0.0
    comps = {"role": round(role, 1), "matchup": round(m_score, 1), "script": round(script, 1), "recent": round(recent, 1)}
    return round(sum(WEIGHTS[k] * v for k, v in comps.items()), 1), comps


def player_flags(r, ctx, split, xfp, td_share, snap_trend):
    """(good, bad) plain-English flags beyond the matchup."""
    good, bad = [], []
    pos = r["position"]
    if ctx:
        it, margin = ctx.get("implied_total"), ctx.get("margin")
        if it is not None:
            if it >= 26:
                good.append(f"Team implied for {it:g} points, a high-scoring spot")
            elif it <= 18.5:
                bad.append(f"Team implied for just {it:g} points")
        if margin is not None and split:
            if margin >= 3 and split["leading"] < split["trailing"] - 3:
                bad.append(f"Favored by {margin:g}, but his share drops to {split['leading']:g}% when his team leads (vs {split['trailing']:g}% trailing)")
            elif margin <= -3 and split["trailing"] < split["leading"] - 3:
                bad.append(f"Underdog by {abs(margin):g}, and his share drops to {split['trailing']:g}% when trailing (vs {split['leading']:g}% leading)")
            elif margin >= 3 and split["leading"] > split["trailing"] + 3:
                good.append(f"Favored by {margin:g}; he gets {split['leading']:g}% of the work when his team leads")
            elif margin <= -3 and split["trailing"] > split["leading"] + 3:
                good.append(f"Underdog by {abs(margin):g}; he gets {split['trailing']:g}% of the work when trailing")
        wx = ctx.get("weather")
        if wx and wx.get("index", 0) >= 25 and not wx.get("maybe_closed") and pos != "RB":
            bad.append(f"Weather: {', '.join(wx['reasons'])} at kickoff")
    if xfp and xfp.get("xfp_pg") is not None and xfp.get("diff") is not None:
        if xfp["diff"] <= -3:
            good.append(f"Due for more: {xfp['xfp_pg']:.1f} expected pts/game on his work, scoring {abs(xfp['diff']):.1f} under that")
        elif xfp["diff"] >= 4:
            bad.append(f"Running hot: scoring {xfp['diff']:.1f} pts/game above what his work usually produces")
    if td_share is not None and td_share >= 45:
        bad.append(f"TD-dependent: {td_share:.0f}% of his points have come from touchdowns")
    if snap_trend is not None and snap_trend <= -15:
        bad.append(f"Snap share down {abs(snap_trend):.0f} points over his last 2 games")
    elif snap_trend is not None and snap_trend >= 15:
        good.append(f"Snap share up {snap_trend:.0f} points over his last 2 games")
    if r.get("injury_status") in ("Questionable", "Doubtful", "Out", "IR"):
        pp = play_prob.play_probability(pos, r["injury_status"], r.get("injury_report"))
        bad.append(f"Listed {r['injury_status']}" + (f": {pp['basis']}" if pp else ""))
    return good, bad


# --------------------------------------------------------------- verdict ----
def mode_value(o, mode):
    """What each win condition ranks by. Protecting a lead leans on the 10th
    percentile (fewest duds), chasing leans on the 90th (biggest weeks); a
    quarter of the median keeps a pure lottery ticket from winning."""
    if mode == "safe":
        return 0.25 * o["p50"] + 0.75 * o["p10"]
    if mode == "upside":
        return 0.25 * o["p50"] + 0.75 * o["p90"]
    return o["mean"]


def confidence(p):
    return "Slam dunk" if p >= 72 else "High" if p >= 62 else "Moderate" if p >= 55 else "Low"


def verdict(players, mode):
    """Top-level call: who to start in each win condition, how sure, and the
    one-line pivot rule when floor and ceiling disagree."""
    if len(players) < 2:
        return None
    pick = {m: max(players, key=lambda p: mode_value(p["outcomes"], m)) for m in MODES}
    best = pick[mode]
    rest = [p for p in players if p is not best]
    runner = max(rest, key=lambda p: mode_value(p["outcomes"], mode))
    p_win = beat_prob(best["outcomes"]["_samples"], runner["outcomes"]["_samples"])
    name = lambda p: p["player_display_name"]
    if mode == "upside":
        # Chasing: the question is who gets you a big week, not who wins a
        # typical one, so confidence comes from the 20+ odds.
        a, b = best["outcomes"]["p_20plus"], runner["outcomes"]["p_20plus"]
        ratio = a / b if b else (2.0 if a else 1.0)
        conf = "Slam dunk" if ratio >= 2 else "High" if ratio >= 1.5 else "Moderate" if ratio >= 1.2 else "Low"
        edge = f"{a}% chance of 20+ vs {b}%"
    else:
        conf = confidence(p_win)
        edge = f"{p_win}% to outscore {name(runner).split(' ')[-1]}"
    if pick["safe"] is pick["upside"]:
        line = f"Start {name(pick['safe'])} whether you're protecting a lead or chasing points."
    else:
        f, c = pick["safe"], pick["upside"]
        line = (f"Start {name(f)} for the safer floor ({f['outcomes']['p10']:g}+ in 9 of 10 games); "
                f"start {name(c)} if you need a ceiling ({c['outcomes']['p_20plus']}% chance of 20+ vs "
                f"{f['outcomes']['p_20plus']}%).")
    if pick["safe"] is pick["upside"]:
        archetype = "Best in every scenario"
    else:
        archetype = "Floor / safe play" if best is pick["safe"] else "Ceiling / boom-bust play" if best is pick["upside"] else "Best median"
    return {"pick": best["player_id"], "pick_name": name(best), "over": runner["player_id"], "over_name": name(runner),
            "mode": MODES[mode], "win_pct": p_win, "confidence": conf, "edge": edge, "archetype": archetype,
            "line": line, "by_mode": {MODES[m]: p["player_id"] for m, p in pick.items()}}
