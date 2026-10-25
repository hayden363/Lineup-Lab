"""League chat tab (static/chat.js) — wiring and safety checks.

There is no browser in the test run, so these are source-level guards for the
properties that matter most: message text never reaches innerHTML, polling runs
every 5 s only while the tab is visible, the tab is wired into the app shell,
and ESPN-only users are told chat is Sleeper-only. A syntax check runs when
node is installed.

    .venv/bin/python -m unittest tests.test_league_chat_ui -v
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
CHAT_JS = (STATIC / "chat.js").read_text() if (STATIC / "chat.js").exists() else ""
APP_JS = (STATIC / "app.js").read_text()
INDEX = (STATIC / "index.html").read_text()
SW = (STATIC / "sw.js").read_text()
CSS = (STATIC / "style.css").read_text()


class ChatTabSafety(unittest.TestCase):
    def test_chat_js_exists(self):
        self.assertTrue(CHAT_JS, "static/chat.js is missing")

    def test_message_text_never_goes_through_innerhtml(self):
        for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write"):
            self.assertNotIn(banned, CHAT_JS)

    def test_nothing_chat_related_calls_the_html_building_helper(self):
        # app.js's el(tag, cls, html) assigns its third argument with innerHTML
        self.assertNotRegex(CHAT_JS, r"\bel\(")

    def test_the_input_is_capped_at_500_characters(self):
        self.assertRegex(CHAT_JS, r"maxLength\s*=\s*500")

    def test_poll_interval_is_five_seconds(self):
        self.assertRegex(CHAT_JS, r"CHAT_POLL_MS\s*=\s*5000")

    def test_polling_pauses_when_the_page_is_hidden(self):
        self.assertIn("visibilitychange", CHAT_JS)
        self.assertIn("document.hidden", CHAT_JS)

    def test_leaving_the_tab_stops_polling(self):
        switch = APP_JS[APP_JS.index("function switchTab"):]
        switch = switch[:switch.index("function initTabs")]
        self.assertIn("stopChatPolling()", switch)
        self.assertIn('tab === "chat"', switch)

    def test_switching_tabs_cannot_throw_when_chat_js_failed_to_load(self):
        switch = APP_JS[APP_JS.index("function switchTab"):]
        switch = switch[:switch.index("function initTabs")]
        self.assertIn('typeof stopChatPolling === "function"', switch)
        self.assertIn('typeof loadChatTab === "function"', switch)

    def test_a_deleted_message_disappears_for_others_via_periodic_full_refresh(self):
        self.assertRegex(CHAT_JS, r"CHAT_FULL_REFRESH_EVERY\s*=\s*\d+")

    def test_only_sleeper_leagues_are_offered_and_espn_gets_a_clear_message(self):
        self.assertRegex(CHAT_JS, r'platform\s*===\s*"sleeper"')
        self.assertIn("Sleeper-only for now", CHAT_JS)

    def test_signed_out_users_are_asked_to_sign_in(self):
        self.assertRegex(CHAT_JS, r"state\.user")
        self.assertIn("Sign in", CHAT_JS)


class ChatTabWiring(unittest.TestCase):
    def test_nav_button_section_and_script_exist(self):
        self.assertIn('data-tab="chat"', INDEX)
        self.assertIn('id="tab-chat"', INDEX)
        self.assertIn('id="chat-body"', INDEX)
        self.assertLess(INDEX.index('src="/app.js"'), INDEX.index('src="/chat.js"'))

    def test_tab_is_registered_with_the_app_shell(self):
        ids = re.search(r"const TAB_IDS = \[([^\]]*)\]", APP_JS).group(1)
        self.assertIn('"chat"', ids)

    def test_offline_shell_includes_chat_js_and_the_cache_version_moved(self):
        self.assertIn('"/chat.js"', SW)
        self.assertNotIn("lineup-lab-shell-v4", SW)

    def test_styles_exist_for_the_chat_list_and_composer(self):
        for cls in (".chat-list", ".chat-msg", ".chat-composer"):
            self.assertIn(cls, CSS)

    def diff(self, dom_ids, messages):
        script = (
            "const vm=require('vm'),fs=require('fs');"
            "const ctx=vm.createContext({document:{addEventListener(){},hidden:false},state:{},setInterval(){},clearInterval(){}});"
            "vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);"
            f"process.stdout.write(vm.runInContext('JSON.stringify(chatDiff({json.dumps(dom_ids)},{json.dumps([{'id': i} for i in messages])}))',ctx));"
        )
        r = subprocess.run(["node", "-e", script, str(STATIC / "chat.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        out["add"] = [m["id"] for m in out["add"]]  # chatDiff returns whole messages; compare by id
        return out

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_refresh_only_adds_new_and_removes_deleted_messages(self):
        self.assertEqual(self.diff([5, 6, 7], [5, 7]), {"remove": [6], "add": []})
        self.assertEqual(self.diff([5, 7], [5, 6, 7]), {"remove": [], "add": [6]})
        self.assertEqual(self.diff([], []), {"remove": [], "add": []})

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_refresh_keeps_older_history_that_is_outside_the_newest_page(self):
        self.assertEqual(self.diff([1, 2, 3], [2, 3, 4]), {"remove": [], "add": [4]})

    def test_a_refresh_never_clears_the_list(self):
        refresh = CHAT_JS[CHAT_JS.index("async function pollChat"):]
        refresh = refresh[:refresh.index("function chatMessageNode")]
        self.assertNotIn("replaceChildren", refresh)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_chat_js_parses(self):
        r = subprocess.run(["node", "--check", str(STATIC / "chat.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
