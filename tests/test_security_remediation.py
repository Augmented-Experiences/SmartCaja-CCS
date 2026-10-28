"""Regresion de la remediacion Checkmarx 2026-10: logs, rutas y Host."""
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ccs_sec_"))
os.environ.setdefault("PORT", "9997")

from fastapi import HTTPException
from log_sanitize import sanitize_log
from path_guard import guarded_child


class TestLogSanitize(unittest.TestCase):
    def test_injection_becomes_one_line(self):
        payload = "ok\r\nERROR admin\x00\x1b[31mlogin"
        line = sanitize_log(payload)
        self.assertNotIn("\n", line)
        self.assertNotIn("\r", line)
        self.assertNotIn("\x00", line)
        self.assertNotIn("\x1b", line)
        record = logging.LogRecord("smartcaja", logging.INFO, __file__, 1, line, (), None)
        rendered = record.getMessage()
        self.assertEqual(rendered.count("\n"), 0)
        self.assertNotIn("\r", rendered)
        self.assertIn("ok", rendered)
        self.assertIn("ERROR admin", rendered)


class TestPathGuard(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ccs_paths_"))
        self.root.mkdir(exist_ok=True)

    def test_rejects_dotdot_and_absolute(self):
        with self.assertRaises(HTTPException):
            guarded_child(self.root, "../secret.json")
        with self.assertRaises(HTTPException):
            guarded_child(self.root, str(self.root / "inside.json"))

    def test_rejects_symlink_escape(self):
        outside = Path(tempfile.mkdtemp(prefix="ccs_out_"))
        link = self.root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("el sistema no permite crear symlinks")
        with self.assertRaises(HTTPException):
            guarded_child(link, "note.json")

    def test_accepts_plain_name(self):
        path = guarded_child(self.root, "cashflow.json")
        self.assertEqual(path.parent.resolve(), self.root.resolve())


class TestLoopbackHost(unittest.TestCase):
    def test_rejects_foreign_host(self):
        from fastapi.testclient import TestClient
        import app as server_app
        client = TestClient(server_app.app)
        response = client.get("/api/health", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
