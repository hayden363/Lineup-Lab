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


if __name__ == "__main__":
    build()
