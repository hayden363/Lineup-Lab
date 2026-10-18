import unittest
from fastapi.testclient import TestClient
import server


class LegalPages(unittest.TestCase):
    def test_pages_served_and_unknown_404(self):
        c = TestClient(server.app)
        for p in ("terms", "privacy"):
            r = c.get("/legal/" + p)
            self.assertEqual(r.status_code, 200)
            self.assertIn("lineuplabfootball@gmail.com", r.text)
        self.assertEqual(c.get("/legal/../server.py").status_code, 404)
        self.assertEqual(c.get("/legal/other").status_code, 404)

    def test_markdown_is_rendered_and_no_placeholders_ship(self):
        c = TestClient(server.app)
        for p in ("terms", "privacy"):
            html = c.get("/legal/" + p).text
            self.assertIn("<h2>", html)            # headings rendered, not literal '##'
            self.assertNotIn("## ", html)
            self.assertNotIn("**", html)
            self.assertNotIn("[ ]", html)          # no unfilled placeholders
            self.assertNotIn("DRAFT", html)
        priv = c.get("/legal/privacy").text
        self.assertIn("<table>", priv)              # the data table renders as a table
        self.assertIn("Delete account", priv)


if __name__ == "__main__":
    unittest.main()
