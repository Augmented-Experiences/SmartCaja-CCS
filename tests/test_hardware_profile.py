"""Perfiles de RAM. SmartCaja no usa OCR ni moondream: extra_models vacío."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

from hardware_profile import access_for_ram, select_profile


class TestHardwareProfile(unittest.TestCase):
    def test_6_9_blocks_liviano(self):
        self.assertEqual(select_profile(6.9)["id"], "liviano")
        self.assertEqual(select_profile(6.9)["model"], "llama3.2:1b")
        self.assertEqual(select_profile(6.9)["extra_models"], [])
        self.assertEqual(access_for_ram(6.9)["level"], "block")

    def test_7_is_estandar_warn(self):
        p = select_profile(7.0)
        self.assertEqual(p["id"], "estandar")
        self.assertEqual(p["model"], "llama3.2:3b")
        self.assertEqual(access_for_ram(7.0)["level"], "warn")

    def test_8_and_12_use_3b_without_vision(self):
        for gb in (8, 12):
            p = select_profile(gb)
            self.assertEqual(p["id"], "estandar")
            self.assertEqual(p["model"], "llama3.2:3b")
            self.assertEqual(p["extra_models"], [])
            self.assertEqual(access_for_ram(gb)["level"], "warn")

    def test_16_is_completo_without_moondream(self):
        p = select_profile(16)
        self.assertEqual(p["id"], "completo")
        self.assertEqual(p["model"], "llama3.2:3b")
        self.assertEqual(p["extra_models"], [])
        self.assertEqual(access_for_ram(16)["level"], "ok")

    def test_32_uses_8b_without_moondream(self):
        p = select_profile(32)
        self.assertEqual(p["id"], "maximo")
        self.assertEqual(p["model"], "llama3.1:8b")
        self.assertEqual(p["extra_models"], [])
        self.assertEqual(access_for_ram(32)["level"], "ok")

    def test_ram_zero_fails_open(self):
        self.assertEqual(access_for_ram(0)["level"], "ok")

    def test_override_env(self):
        with patch.dict("os.environ", {"SMARTSUITE_ALLOW_LOW_RAM": "1"}):
            self.assertEqual(access_for_ram(4)["level"], "ok")
            self.assertTrue(access_for_ram(4)["override"])

    def test_product_alias_override(self):
        with patch.dict("os.environ", {"SMARTCAJA_ALLOW_LOW_RAM": "1"}):
            self.assertEqual(access_for_ram(4)["level"], "ok")
            self.assertTrue(access_for_ram(4)["override"])


if __name__ == "__main__":
    unittest.main()
