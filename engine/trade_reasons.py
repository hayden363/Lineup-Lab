"""
TRADE REASONS — why each side might say yes
===============================================
Templated, rule-based explanations for one suggested trade, every line tied
to a real number from the roster, schedule or standings. No language model:
the same inputs always give the same text.

Inputs per side:
  give / get lists of {name, position, value, form, injury_status, bye}
  need  {position: starters needed}, have {position: players rostered}
  record (wins, losses) or None

Rules (each fires only when its condition is true):
  * need       the team is at or below the number of starters it needs at the
               position it would receive
  * surplus    the team has 2+ more players than starters needed at the
               position it would give away
  * value      value gap between the two sides (fair within 15%)
  * form       a received player is trending up 10%+ / a given player is down 10%+
  * injury     a received player is Questionable/Doubtful/Out (a risk), or a
               given player is (the other side is taking it on)
  * bye        a received player's bye week matches one the team already has
               a player on (a bye-week crunch), or avoids one
  * standing   a team with 2+ more losses than wins is a seller of
               older/high-value vets; 2+ more wins is a buyer
"""


def _fmt(players):
    return " + ".join(p["name"] for p in players)


def _n(x):
    return f"{round(x):d}" if abs(x - round(x)) < 0.05 else f"{x:.1f}"


def _side_reasons(subj, give, get, need, have, record, other_name):
    """`subj` is "you" or the team's name; the sentences read from that side."""
    you = subj == "you"
    start, carry, gives, comes = ("start", "carry", "Gives up", "come out") if you else ("starts", "carries", "Gives up", "comes out")
    S = "you" if you else subj
    out = []
    for p in get:
        pos = p["position"]
        if need.get(pos) is not None and have.get(pos, 0) <= need[pos]:
            out.append(f"Fills a need at {pos}: {S} {start} {_n(need[pos])} and {carry} {have.get(pos, 0)}.")
            break
    for p in give:
        pos = p["position"]
        if need.get(pos) is not None and have.get(pos, 0) - need[pos] >= 2:
            out.append(f"Gives up depth {S} {'don' if you else 'doesn'}'t use: {have[pos]} {pos}s for {_n(need[pos])} starting spots.")
            break
    gv, tv = sum(p["value"] for p in give), sum(p["value"] for p in get)
    if gv > 0:
        gap = (tv - gv) / max(gv, tv, 1)
        if abs(gap) <= 0.15:
            out.append(f"Close in value: {_fmt(give)} ({gv:.1f}) for {_fmt(get)} ({tv:.1f}).")
        elif gap > 0:
            out.append(f"{S.capitalize()} {comes} ahead by {tv - gv:.1f} points per game of projected value.")
        else:
            out.append(f"{S.capitalize()} give{'' if you else 's'} up {gv - tv:.1f} points per game of value; only worth it for the need above.")
    for p in get:
        if (p.get("form") or 0) >= 10:
            out.append(f"{p['name']} is trending up (+{p['form']:.0f}% over his season average).")
            break
    for p in give:
        if (p.get("form") or 0) <= -10:
            out.append(f"{p['name']} is cooling off ({p['form']:.0f}% vs his season average): sell before it shows.")
            break
    for p in get:
        if p.get("injury_status") in ("Questionable", "Doubtful", "Out"):
            out.append(f"Risk: {p['name']} is listed {p['injury_status']}.")
    my_byes = {p["bye"] for p in give if p.get("bye")}
    new_byes = {p["bye"] for p in get if p.get("bye")}
    shared = my_byes & new_byes
    if shared:
        out.append(f"Keeps {S if not you else 'your'}{'' if you else chr(39)+'s'} week {min(shared)} bye pattern unchanged.")
    elif new_byes and my_byes:
        out.append(f"Moves a bye from week {min(my_byes)} to week {min(new_byes)}: check that week's depth.")
    if record:
        w, l = record
        if l - w >= 2:
            out.append(f"At {w}-{l}, {S} {'are' if you else 'is'} better off trading for the future than chasing this week.")
        elif w - l >= 2:
            out.append(f"At {w}-{l}, {S} {'are' if you else 'is'} a buyer: current production beats future value.")
    return out


def build_reasons(you_give, you_get, my_need, my_have, their_need, their_have, my_record, their_record, their_name):
    """{'you': [...], 'them': [...]} — why you'd do it, why they might. Every
    entry is a plain sentence tied to a number; empty lists mean no rule fired."""
    return {
        "you": _side_reasons("you", you_give, you_get, my_need, my_have, my_record, their_name),
        "them": _side_reasons(their_name, you_get, you_give, their_need, their_have, their_record, "you"),
    }
