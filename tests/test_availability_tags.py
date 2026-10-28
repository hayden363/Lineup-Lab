"""Every player carries how he is listed: BYE, QUESTIONABLE, DOUBTFUL, OUT, IR, PUP or SUS."""
import json
import os
import subprocess
import unittest
from unittest import mock

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


def run_js(body):
    """statusFlagsHtml and its helpers, lifted out of app.js and run under node with a stubbed `state`."""
    js = read("static/app.js")
    start = js.index("// ---- availability tags")
    end = js.index("function statChipsHtml")
    chunk = js[start:end]
    code = ("const state = { slateWeek: 8, byeTeams: { SF: 8, DET: 6 }, boardWeek: 8 };"
            "const esc = (s) => s == null ? '' : String(s).replace(/[&<>\"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
            "const teamKey = (t) => String(t || '').toUpperCase();" + chunk + f"console.log(JSON.stringify((() => {{ {body} }})()));")
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr[-1500:])
    return json.loads(r.stdout)


class TagTests(unittest.TestCase):
    def test_each_listing_gets_its_own_label(self):
        out = run_js('return ["Questionable","Doubtful","Out","IR","PUP","Sus"].map((s) => statusFlagsHtml({injury_status: s}));')
        for html, label in zip(out, ["QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "PUP", "SUS"]):
            self.assertIn(f">{label}<", html)

    def test_out_ir_and_pup_read_as_unavailable_and_questionable_as_a_warning(self):
        out = run_js('return [statusFlagsHtml({injury_status:"Out"}), statusFlagsHtml({injury_status:"IR"}), statusFlagsHtml({injury_status:"Questionable"})];')
        self.assertIn("unavailable", out[0])
        self.assertIn("unavailable", out[1])
        self.assertNotIn("unavailable", out[2])
        self.assertIn("questionable", out[2])

    def test_a_server_flagged_bye_shows_bye(self):
        self.assertIn(">BYE<", run_js('return statusFlagsHtml({on_bye: true});'))

    def test_a_player_whose_team_is_on_a_bye_this_week_shows_bye_even_without_a_flag(self):
        out = run_js('return [statusFlagsHtml({recent_team:"SF"}), statusFlagsHtml({recent_team:"DET"}), statusFlagsHtml({team:"SF"}), statusFlagsHtml({bye_week: 8}), statusFlagsHtml({bye_week: 9})];')
        self.assertIn(">BYE<", out[0])
        self.assertNotIn("BYE", out[1])           # DET's bye was week 6
        self.assertIn(">BYE<", out[2])
        self.assertIn(">BYE<", out[3])
        self.assertNotIn("BYE", out[4])

    def test_an_explicit_not_on_bye_beats_the_team_lookup(self):
        # My Team looking at week 9: the server says SF is playing even though the slate week is their bye
        self.assertNotIn("BYE", run_js('return statusFlagsHtml({recent_team:"SF", on_bye:false});'))

    def test_bye_and_an_injury_listing_both_show(self):
        out = run_js('return statusFlagsHtml({on_bye:true, injury_status:"Questionable"});')
        self.assertIn(">BYE<", out)
        self.assertIn(">QUESTIONABLE<", out)

    def test_nothing_shows_for_a_healthy_player(self):
        self.assertEqual(run_js('return statusFlagsHtml({recent_team:"KC", injury_status:null});').strip(), "")

    def test_alias_team_codes_resolve_for_the_bye_lookup(self):
        self.assertIn(">BYE<", run_js('return statusFlagsHtml({recent_team:"SF"});'))


class SlateEndpointTests(unittest.TestCase):
    def test_slate_reports_the_week_and_each_teams_bye(self):
        from fastapi.testclient import TestClient
        import server
        rows = [(w, a, h, None, None, "REG") for w, a, h in [(1, "SF", "DET"), (2, "SF", "DET"), (3, "DET", "KC"), (1, "KC", "BUF"), (2, "KC", "BUF"), (3, "BUF", "KC")]]
        sched = pd.DataFrame(rows, columns=["week", "away_team", "home_team", "home_score", "away_score", "game_type"])
        with mock.patch.object(server.data_layer, "load_schedule", return_value=sched):
            body = TestClient(server.app).get("/api/slate").json()
        self.assertEqual(body["week"], 1)
        self.assertEqual(body["byes"]["SF"], 3)


class WiringTests(unittest.TestCase):
    def test_slate_is_loaded_at_start_and_the_picker_blocks_unavailable_players(self):
        js = read("static/app.js")
        self.assertIn("/api/slate", js)
        self.assertIn("state.byeTeams", js)
        body = js[js.index("async function renderStartSitPicker"):][:2500]
        self.assertIn("isUnavailable", body)


if __name__ == "__main__":
    unittest.main()
