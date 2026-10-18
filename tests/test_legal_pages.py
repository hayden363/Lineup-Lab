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


if __name__ == "__main__":
    unittest.main()
