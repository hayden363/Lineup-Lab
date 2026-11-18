"""THE DAILY DRIVE - the history pool, precomputed.

engine/daily_drive_history_pool.py builds its prompts from 26 seasons of weekly stats (2000-2025) plus the draft table.
That costs ~13 s of downloads on a fresh disk and ~150-200 MB of extra memory while it runs, and the answers can't
change until a season ends. So every passing prompt variant is built ONCE (offline, by this module's build()) into
engine/dd_history_snapshot.json.gz, and the server only reads that file.

At runtime the day's variant for a scoped template is chosen exactly as the live pool would: scope_order(tpl, date)
and the first variant that passed when the snapshot was built.

Rebuild after a season ends (or after changing the history pool):
    python -m engine.daily_drive_history_snapshot
"""
import gzip
import json
import os
import time

from engine import daily_drive_history_pool as hp

PATH = os.path.join(os.path.dirname(__file__), "dd_history_snapshot.json.gz")
_CACHE = {}


def _key(scope):
    return "" if scope is None else str(scope)


def build(path=PATH, verbose=True):
    """Every passing variant of every history template, written to `path`. Returns (templates, variants)."""
    from engine import consensus
    ecr_rank = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
    ctx = hp._prepare_ctx(hp.build_context(None, ecr_rank))
    snap, n = {}, 0
    for tpl in hp.HISTORY_POOL:
        scopes = hp.scope_options(tpl, ctx["last"]) if tpl.get("scope") else [None]
        got = {}
        for sc in scopes:
            p = hp.build_history_prompt(tpl, ctx, sc, ecr_rank)
            if p:
                got[_key(sc)] = p
        if got:
            snap[tpl["key"]] = got
            n += len(got)
    body = {"last": ctx["last"], "built": time.strftime("%Y-%m-%d"), "prompts": snap}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(body, f, separators=(",", ":"), default=str)
    if verbose:
        print(f"[history snapshot] {len(snap)} templates, {n} variants -> {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    return len(snap), n


def load(path=PATH):
    if path not in _CACHE:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            _CACHE[path] = json.load(f)
    return _CACHE[path]


def snapshot_candidates(date_str, path=PATH):
    """The history prompts for `date_str` (one per template), from the snapshot. Never raises: no file -> []."""
    try:
        body = load(path)
    except Exception as e:
        print(f"[daily_drive] history snapshot unavailable: {type(e).__name__}: {e}")
        return []
    snap, last, out = body["prompts"], body["last"], []
    for tpl in hp.HISTORY_POOL:
        got = snap.get(tpl["key"])
        if not got:
            continue
        if not tpl.get("scope"):
            p = got.get("")
        else:
            p = next((got[_key(sc)] for sc in hp.scope_order(tpl, date_str, last) if _key(sc) in got), None)
        if p:
            out.append(p)
    return out


# ----------------------------------------------------------------------------------------------- banded (easy -> hard days)
# From dd.VARIETY_START a template can give up to three variants (easy / medium / hard), and an easy one may have hundreds
# of answers, so this snapshot is stored compactly: each answer is a row [id, name, tier, team, position, headshot#, stat]
# with the headshot URLs in one shared table. Built offline like the original:  python -m engine.daily_drive_history_snapshot
PATH_BANDED = os.path.join(os.path.dirname(__file__), "dd_history_bands.json.gz")
_A_KEYS = ("id", "name", "tier", "team", "position", "headshot", "stat")


def _pack(prompts, heads):
    out = []
    for p in prompts:
        rows = []
        for a in p["answers"]:
            h = a.get("headshot")
            if h and h not in heads:
                heads[h] = len(heads)
            rows.append([a["id"], a["name"], a["tier"], a.get("team"), a.get("position"), heads[h] if h else None, a.get("stat")])
        q = {k: v for k, v in p.items() if k != "answers"}
        q["stat_label"] = p["answers"][0].get("stat_label") if p["answers"] else None
        q["rows"] = rows
        out.append(q)
    return out


def _unpack(q, heads):
    label = q.get("stat_label")
    answers = []
    for r in q["rows"]:
        a = dict(zip(_A_KEYS, r))
        a["headshot"] = heads[a["headshot"]] if a["headshot"] is not None else None
        a["stat_label"] = label
        answers.append(a)
    p = {k: v for k, v in q.items() if k not in ("rows", "stat_label")}
    p["answers"] = answers
    p["text"] = hp.decade_years(p.get("text"), p.get("scope"))   # snapshots built before the years were spelled out
    return p


def build_banded(path=PATH_BANDED, verbose=True):
    """Every band variant of every history template and scope, written to `path`. Returns (templates, variants)."""
    from engine import consensus
    ecr_rank = {k: v["ecr"] for k, v in consensus.overall_lookup().items()}
    ctx = hp._prepare_ctx(hp.build_context(None, ecr_rank))
    snap, heads, n = {}, {}, 0
    for tpl in hp.HISTORY_POOL:
        scopes = hp.scope_options(tpl, ctx["last"]) if tpl.get("scope") else [None]
        got = {}
        for sc in scopes:
            vs = hp.build_history_bands(tpl, ctx, sc, ecr_rank)
            if vs:
                got[_key(sc)] = _pack(vs, heads)
                n += len(vs)
        if got:
            snap[tpl["key"]] = got
    table = [None] * len(heads)
    for h, i in heads.items():
        table[i] = h
    body = {"last": ctx["last"], "built": time.strftime("%Y-%m-%d"), "heads": table, "prompts": snap}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(body, f, separators=(",", ":"), default=str)
    if verbose:
        print(f"[history bands] {len(snap)} templates, {n} variants -> {path} ({os.path.getsize(path) / 1e6:.1f} MB)")
    return len(snap), n


def banded_candidates(date_str, path=PATH_BANDED):
    """The history prompts for `date_str` on an easy -> hard day: every band variant of each template (a scoped template
    uses the first scope in the date's order that has any). Never raises: no file -> []."""
    try:
        body = load(path)
    except Exception as e:
        print(f"[daily_drive] banded history snapshot unavailable: {type(e).__name__}: {e}")
        return []
    snap, last, heads, out = body["prompts"], body["last"], body["heads"], []
    for tpl in hp.HISTORY_POOL:
        got = snap.get(tpl["key"])
        if not got:
            continue
        if not tpl.get("scope"):
            vs = got.get("")
        else:
            vs = next((got[_key(sc)] for sc in hp.scope_order(tpl, date_str, last) if _key(sc) in got), None)
        out.extend(_unpack(q, heads) for q in (vs or ()))
    return out


if __name__ == "__main__":
    import sys
    if "--legacy" in sys.argv:
        build()
    else:
        build_banded()
