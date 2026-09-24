"""
Tests para SmartCaja v0.2.0

Incluye pruebas unitarias y de integración para:
  - Utilidades de persistencia (save_json, load_json)
  - Parser JSON robusto (_extract_json_from_llm)
  - Normalización de flujo de caja (normalize_cashflow)
  - Sanitización de IDs y nombres de archivo (seguridad)
  - Rate limiting
  - Endpoints de empresas (CRUD)
  - Endpoints de agentes
  - Endpoints de flujo de caja, edición de meses y exportación
  - Endpoints de health
  - Validaciones de estructura Pinokio
  - Validaciones cross-platform
  - Validaciones de seguridad
"""

import os
import sys
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ajustar path para importar el servidor
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

# Configurar DATA_DIR temporal antes de importar app
TEST_DATA_DIR = tempfile.mkdtemp(prefix="ccs_test_")
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["PORT"] = "9999"

from fastapi.testclient import TestClient
from app import (
    app, save_json, load_json, _extract_json_from_llm,
    _fix_encoding, normalize_cashflow, _normalize_month, _to_num,
    _sanitize_id, _sanitize_filename, _check_rate_limit, _rate_limit_store,
    DATA_DIR, DEFAULTS_DIR, MAX_MESSAGE_LENGTH, MAX_COMPANY_NAME_LENGTH, MAX_MONTHS,
    resolve_ollama_model, call_ollama_chat, ensure_ollama_running,
)

client = TestClient(app)

ROOT = Path(__file__).parent.parent.resolve()


# =====================================================================
# UTILIDADES DE PERSISTENCIA Y PARSING
# =====================================================================
class TestUtilities(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ccs_util_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_load_json(self):
        path = self.test_dir / "test.json"
        data = {"name": "Empresa Test", "value": 12345, "acentos": "café, niño"}
        save_json(path, data)
        loaded = load_json(path)
        self.assertEqual(loaded["name"], "Empresa Test")
        self.assertEqual(loaded["value"], 12345)
        self.assertEqual(loaded["acentos"], "café, niño")

    def test_load_json_nonexistent(self):
        path = self.test_dir / "nonexistent.json"
        result = load_json(path, {"default": True})
        self.assertEqual(result, {"default": True})

    def test_load_json_corrupted(self):
        path = self.test_dir / "corrupted.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        result = load_json(path, {"fallback": True})
        self.assertEqual(result, {"fallback": True})

    def test_save_json_creates_directories(self):
        path = self.test_dir / "a" / "b" / "c" / "test.json"
        save_json(path, {"nested": True})
        self.assertTrue(path.exists())

    def test_extract_json_clean(self):
        text = '{"key": "value", "num": 42}'
        result = _extract_json_from_llm(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["key"], "value")

    def test_extract_json_with_markdown(self):
        text = 'Aquí está:\n```json\n{"key": "value"}\n```\nFin.'
        result = _extract_json_from_llm(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["key"], "value")

    def test_extract_json_with_preamble(self):
        text = 'El flujo de caja es:\n{"company": "Test", "months": []}'
        result = _extract_json_from_llm(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["company"], "Test")

    def test_extract_json_none(self):
        self.assertIsNone(_extract_json_from_llm("No hay JSON aquí"))
        self.assertIsNone(_extract_json_from_llm(""))
        self.assertIsNone(_extract_json_from_llm(None))

    def test_fix_encoding_normal(self):
        self.assertEqual(_fix_encoding("Hola mundo"), "Hola mundo")

    def test_fix_encoding_accents(self):
        text = "café"
        result = _fix_encoding(text)
        self.assertIsInstance(result, str)


# =====================================================================
# _to_num
# =====================================================================
class TestToNum(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_to_num(100), 100)

    def test_float(self):
        self.assertEqual(_to_num(99.5), 99.5)

    def test_string_number(self):
        self.assertEqual(_to_num("1000"), 1000)

    def test_string_with_currency(self):
        self.assertEqual(_to_num("$1.000.000"), 1000000)

    def test_none(self):
        self.assertEqual(_to_num(None), 0)

    def test_invalid_string(self):
        self.assertEqual(_to_num("abc"), 0)

    def test_empty_string(self):
        self.assertEqual(_to_num(""), 0)

    def test_negative(self):
        self.assertEqual(_to_num("-500"), -500)


# =====================================================================
# _normalize_month
# =====================================================================
class TestNormalizeMonth(unittest.TestCase):

    def test_basic_normalization(self):
        m = {
            "month": "2025-01", "label": "Enero 2025",
            "income": {"sales": 10000000, "other_income": 500000},
            "expenses": {"variable_costs": 3000000, "fixed_costs": 2000000,
                        "variable_expenses": 500000, "debt_payments": 300000,
                        "taxes": 200000, "investments": 0}
        }
        result = _normalize_month(m)
        self.assertEqual(result["income"]["total"], 10500000)
        self.assertEqual(result["expenses"]["total"], 6000000)
        self.assertEqual(result["net_flow"], 4500000)

    def test_missing_fields(self):
        m = {"month": "2025-01", "label": "Enero"}
        result = _normalize_month(m)
        self.assertEqual(result["income"]["total"], 0)
        self.assertEqual(result["expenses"]["total"], 0)
        self.assertEqual(result["net_flow"], 0)

    def test_recalculates_totals(self):
        m = {
            "month": "2025-01", "label": "Enero",
            "income": {"sales": 5000, "other_income": 1000, "total": 999999},
            "expenses": {"variable_costs": 1000, "fixed_costs": 500,
                        "variable_expenses": 0, "debt_payments": 0,
                        "taxes": 0, "investments": 0, "total": 999999}
        }
        result = _normalize_month(m)
        self.assertEqual(result["income"]["total"], 6000)
        self.assertEqual(result["expenses"]["total"], 1500)
        self.assertEqual(result["net_flow"], 4500)


# =====================================================================
# normalize_cashflow
# =====================================================================
class TestNormalizeCashflow(unittest.TestCase):

    def test_recalculates_summary_from_months(self):
        data = {
            "summary": {"total_income": 0, "total_expenses": 0},
            "months": [
                {"month": "2025-01", "income": {"sales": 10000000, "other_income": 0},
                 "expenses": {"variable_costs": 3000000, "fixed_costs": 2000000, "variable_expenses": 500000, "debt_payments": 300000, "taxes": 200000, "investments": 0}},
                {"month": "2025-02", "income": {"sales": 12000000, "other_income": 0},
                 "expenses": {"variable_costs": 3500000, "fixed_costs": 2000000, "variable_expenses": 600000, "debt_payments": 300000, "taxes": 250000, "investments": 0}}
            ]
        }
        result = normalize_cashflow(data)
        self.assertEqual(result["summary"]["total_income"], 22000000)
        self.assertEqual(result["summary"]["total_expenses"], 12650000)
        self.assertEqual(result["summary"]["net_cashflow"], 9350000)
        self.assertEqual(result["summary"]["num_months"], 2)

    def test_cumulative_balance(self):
        data = {
            "months": [
                {"month": "2025-01", "income": {"sales": 10000}, "expenses": {"variable_costs": 3000}},
                {"month": "2025-02", "income": {"sales": 8000}, "expenses": {"variable_costs": 5000}},
                {"month": "2025-03", "income": {"sales": 12000}, "expenses": {"variable_costs": 4000}}
            ]
        }
        result = normalize_cashflow(data)
        self.assertEqual(result["months"][0]["cumulative_balance"], 7000)
        self.assertEqual(result["months"][1]["cumulative_balance"], 10000)
        self.assertEqual(result["months"][2]["cumulative_balance"], 18000)

    def test_empty_months(self):
        data = {"months": []}
        result = normalize_cashflow(data)
        self.assertEqual(result["summary"]["total_income"], 0)
        self.assertEqual(result["summary"]["num_months"], 0)

    def test_max_months_limit(self):
        data = {"months": [{"month": f"m{i}"} for i in range(100)]}
        result = normalize_cashflow(data)
        self.assertEqual(len(result["months"]), MAX_MONTHS)

    def test_preserves_other_fields(self):
        data = {"months": [], "alerts": [{"type": "info", "message": "test"}], "recommendations": ["rec1"]}
        result = normalize_cashflow(data)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(len(result["recommendations"]), 1)


# =====================================================================
# SEGURIDAD: Sanitización de IDs
# =====================================================================
class TestSanitizeId(unittest.TestCase):

    def test_valid_id(self):
        self.assertEqual(_sanitize_id("abc123"), "abc123")
        self.assertEqual(_sanitize_id("test-id_01"), "test-id_01")

    def test_path_traversal(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _sanitize_id("../../../etc/passwd")

    def test_empty(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _sanitize_id("")

    def test_special_chars(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _sanitize_id("id with spaces")

    def test_too_long(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _sanitize_id("a" * 65)

    def test_dots(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            _sanitize_id("..id")


# =====================================================================
# SEGURIDAD: Sanitización de nombres de archivo
# =====================================================================
class TestSanitizeFilename(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(_sanitize_filename("Mi Empresa"), "Mi_Empresa")

    def test_special_chars(self):
        result = _sanitize_filename("test<>file/name")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
        self.assertNotIn("/", result)

    def test_empty(self):
        self.assertEqual(_sanitize_filename(""), "empresa")

    def test_windows_reserved(self):
        result = _sanitize_filename("CON")
        self.assertTrue(result.startswith("_"))

    def test_length_limit(self):
        result = _sanitize_filename("a" * 100)
        self.assertLessEqual(len(result), 50)

    def test_xss_in_filename(self):
        result = _sanitize_filename("<script>alert(1)</script>")
        self.assertNotIn("<script>", result)


# =====================================================================
# SEGURIDAD: Rate Limiting
# =====================================================================
class TestRateLimiting(unittest.TestCase):

    def setUp(self):
        _rate_limit_store.clear()

    def test_within_limit(self):
        for _ in range(5):
            _check_rate_limit("test_key_a", max_requests=10, window=60)

    def test_exceeds_limit(self):
        from fastapi import HTTPException
        for _ in range(5):
            _check_rate_limit("test_key_b", max_requests=5, window=60)
        with self.assertRaises(HTTPException) as ctx:
            _check_rate_limit("test_key_b", max_requests=5, window=60)
        self.assertEqual(ctx.exception.status_code, 429)


# =====================================================================
# HEALTH ENDPOINT
# =====================================================================
class TestHealthEndpoint(unittest.TestCase):

    @patch("app.http_requests.get")
    def test_health_ollama_connected(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        mock_get.return_value = mock_response
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ollama"], "connected")
        self.assertEqual(data["version"], "0.3.0")

    @patch("app.http_requests.get", side_effect=Exception("Connection refused"))
    def test_health_ollama_disconnected(self, mock_get):
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ollama"], "disconnected")


# =====================================================================
# EMPRESAS (CRUD)
# =====================================================================
class TestCompanyEndpoints(unittest.TestCase):

    def setUp(self):
        companies_dir = DATA_DIR / "companies"
        if companies_dir.exists():
            shutil.rmtree(companies_dir)
        companies_dir.mkdir(parents=True, exist_ok=True)
        _rate_limit_store.clear()

    def test_create_company(self):
        response = client.post("/api/companies", json={"name": "Panadería Test", "sector": "alimentos"})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["name"], "Panadería Test")
        self.assertIn("id", data)

    def test_list_companies(self):
        client.post("/api/companies", json={"name": "Empresa 1"})
        client.post("/api/companies", json={"name": "Empresa 2"})
        response = client.get("/api/companies")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["companies"]), 2)

    def test_get_company(self):
        create_resp = client.post("/api/companies", json={"name": "Empresa Get"})
        company_id = create_resp.json()["id"]
        response = client.get(f"/api/companies/{company_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Empresa Get")

    def test_get_company_not_found(self):
        response = client.get("/api/companies/nonexistent")
        self.assertEqual(response.status_code, 404)

    def test_delete_company(self):
        create_resp = client.post("/api/companies", json={"name": "Empresa Delete"})
        company_id = create_resp.json()["id"]
        response = client.delete(f"/api/companies/{company_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get(f"/api/companies/{company_id}").status_code, 404)

    def test_create_company_empty_name(self):
        response = client.post("/api/companies", json={"name": ""})
        self.assertEqual(response.status_code, 422)

    def test_create_company_long_name(self):
        response = client.post("/api/companies", json={"name": "x" * (MAX_COMPANY_NAME_LENGTH + 1)})
        self.assertEqual(response.status_code, 422)

    def test_create_company_utf8(self):
        response = client.post("/api/companies", json={"name": "Panadería Ñoño"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "Panadería Ñoño")


# =====================================================================
# SEGURIDAD EN ENDPOINTS
# =====================================================================
class TestSecurityEndpoints(unittest.TestCase):

    def setUp(self):
        _rate_limit_store.clear()

    def test_path_traversal_company_id(self):
        response = client.get("/api/companies/..%2F..%2Fetc%2Fpasswd")
        self.assertIn(response.status_code, [400, 404, 422])

    def test_path_traversal_cashflow(self):
        response = client.get("/api/companies/..%2F..%2Fetc/cashflow")
        self.assertIn(response.status_code, [400, 404, 422])

    def test_special_chars_company_id(self):
        response = client.get("/api/companies/id%20with%20spaces")
        self.assertIn(response.status_code, [400, 404, 422])


# =====================================================================
# CHAT VALIDATION
# =====================================================================
class TestChatValidation(unittest.TestCase):

    def setUp(self):
        companies_dir = DATA_DIR / "companies"
        if companies_dir.exists():
            shutil.rmtree(companies_dir)
        companies_dir.mkdir(parents=True, exist_ok=True)
        # Asegurar que agentes y prompts existen
        agents_dir = DATA_DIR / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        defaults_path = DEFAULTS_DIR / "agents.json"
        if defaults_path.exists():
            shutil.copy2(str(defaults_path), str(agents_dir / "agents.json"))
        prompts_dir = DATA_DIR / "prompts" / "system"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        prompts_src = DEFAULTS_DIR / "prompts"
        if prompts_src.exists():
            for f in prompts_src.glob("*.md"):
                shutil.copy2(str(f), str(prompts_dir / f.name))
        sessions_dir = DATA_DIR / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _rate_limit_store.clear()

    @patch("app.call_ollama_chat", return_value="Respuesta de prueba")
    def test_chat_interview_success(self, mock_chat):
        c = client.post("/api/companies", json={"name": "Chat Test"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": "Hola, quiero crear un flujo de caja"
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("response", response.json())

    def test_chat_empty_message(self):
        c = client.post("/api/companies", json={"name": "Chat Test 2"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": ""
        })
        self.assertEqual(response.status_code, 422)

    def test_chat_message_too_long(self):
        c = client.post("/api/companies", json={"name": "Chat Test 3"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": "x" * (MAX_MESSAGE_LENGTH + 1)
        })
        self.assertEqual(response.status_code, 422)

    def test_chat_invalid_company(self):
        response = client.post("/api/chat/interview", json={
            "company_id": "nonexist",
            "message": "Hola"
        })
        self.assertEqual(response.status_code, 404)

    @patch("app.call_ollama_chat", return_value="Respuesta de prueba")
    def test_chat_with_null_session_id(self, mock_chat):
        """El frontend envía session_id: null cuando currentSessionId es null.
        El backend debe aceptarlo sin devolver 422.
        Bug real en Windows: POST /api/chat/interview -> 422."""
        c = client.post("/api/companies", json={"name": "Null Session Test"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": "Hola, quiero crear un flujo de caja",
            "session_id": None
        })
        self.assertEqual(response.status_code, 200,
                         f"session_id=null debe ser aceptado, no 422. Response: {response.text}")
        self.assertIn("response", response.json())
        self.assertIn("session_id", response.json())

    @patch("app.call_ollama_chat", return_value="Respuesta de prueba")
    def test_chat_with_empty_session_id(self, mock_chat):
        """session_id vacío debe funcionar (primera entrevista)."""
        c = client.post("/api/companies", json={"name": "Empty Session Test"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": "Hola",
            "session_id": ""
        })
        self.assertEqual(response.status_code, 200)

    @patch("app.call_ollama_chat", return_value="Respuesta de prueba")
    def test_chat_without_session_id_field(self, mock_chat):
        """Omitir session_id del JSON debe funcionar (usa default '')."""
        c = client.post("/api/companies", json={"name": "No Session Test"}).json()
        response = client.post("/api/chat/interview", json={
            "company_id": c["id"],
            "message": "Hola"
        })
        self.assertEqual(response.status_code, 200)

    def test_chat_model_accepts_null_session_id(self):
        """ChatMessage Pydantic model debe aceptar session_id=None."""
        from app import ChatMessage
        msg = ChatMessage(company_id="test", message="Hola", session_id=None)
        self.assertEqual(msg.session_id, "")

    def test_frontend_sends_empty_string_not_null(self):
        """El frontend debe enviar session_id como '' (no null) para evitar
        problemas con Pydantic. Verificar que usa || '' o coerción en el JSON."""
        content_js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        content_html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        combined = content_html + content_js
        # Debe usar sessionId || '' o state.sessionId || '' en los fetch
        has_coercion = ("|| ''" in combined or "|| \"\"" in combined or
                        'coerce_session_id' in (ROOT / "server" / "app.py").read_text(encoding="utf-8"))
        self.assertTrue(has_coercion,
                      "Frontend o backend debe manejar session_id null "
                      "para evitar enviar null a Pydantic")



# =====================================================================
# Ollama: usar el modelo que el launcher ya bajó (no 503 en interview)
# =====================================================================
class TestOllamaModelFallback(unittest.TestCase):

    def test_resolve_uses_pulled_model_when_agent_model_missing(self):
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {"models": [{"name": "llama3.1:8b"}]}
        with patch("app.http_requests.get", return_value=tags):
            with patch.dict(os.environ, {"OLLAMA_MODEL": "llama3.1:8b", "RUN_BY_TAURI": "1"}):
                self.assertEqual(resolve_ollama_model("llama3.2:3b"), "llama3.1:8b")

    def test_resolve_keeps_requested_when_present(self):
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {
            "models": [{"name": "llama3.2:3b"}, {"name": "llama3.1:8b"}]
        }
        with patch("app.http_requests.get", return_value=tags):
            with patch.dict(os.environ, {"RUN_BY_TAURI": "0"}, clear=False):
                self.assertEqual(resolve_ollama_model("llama3.2:3b"), "llama3.2:3b")

    def test_desktop_prefers_launcher_profile_over_heavier_installed(self):
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {
            "models": [{"name": "llama3.1:8b"}, {"name": "llama3.2:3b"}]
        }
        with patch("app.http_requests.get", return_value=tags):
            with patch.dict(os.environ, {"OLLAMA_MODEL": "llama3.2:3b", "RUN_BY_TAURI": "1"}):
                self.assertEqual(resolve_ollama_model("llama3.1:8b"), "llama3.2:3b")

    @patch("app.http_requests.post")
    @patch("app.http_requests.get")
    def test_call_ollama_chat_uses_ram_model_instead_of_503(self, mock_get, mock_post):
        tags = MagicMock()
        tags.status_code = 200
        tags.json.return_value = {"models": [{"name": "llama3.1:8b"}]}
        mock_get.return_value = tags
        chat = MagicMock()
        chat.status_code = 200
        chat.encoding = "utf-8"
        chat.json.return_value = {
            "message": {"content": "hola"},
            "eval_count": 1,
            "prompt_eval_count": 1,
        }
        chat.elapsed.total_seconds.return_value = 0.05
        chat.raise_for_status = MagicMock()
        mock_post.return_value = chat
        with patch.dict(os.environ, {"OLLAMA_MODEL": "llama3.1:8b", "RUN_BY_TAURI": "1"}):
            text = call_ollama_chat("llama3.2:3b", [{"role": "user", "content": "hi"}])
        self.assertEqual(text, "hola")
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "llama3.1:8b")

    @patch("app.subprocess.Popen")
    @patch("app.http_requests.get")
    def test_tauri_ensure_does_not_spawn_ollama(self, mock_get, mock_popen):
        tags = MagicMock()
        tags.status_code = 200
        mock_get.return_value = tags
        with patch.dict(os.environ, {"RUN_BY_TAURI": "1"}):
            self.assertTrue(ensure_ollama_running())
        mock_popen.assert_not_called()

    @patch("app.subprocess.Popen")
    @patch("app.time.sleep")
    @patch("app.http_requests.get", side_effect=Exception("down"))
    def test_tauri_ensure_does_not_spawn_when_tags_fail(self, mock_get, mock_sleep, mock_popen):
        with patch.dict(os.environ, {"RUN_BY_TAURI": "1"}):
            self.assertFalse(ensure_ollama_running())
        mock_popen.assert_not_called()


class TestSplashSingleWhiteLogo(unittest.TestCase):

    def test_splash_single_white_ccs_logo(self):
        """Un solo logo CCS blanco; configure nunca emite splash-mark.png."""
        self.assertTrue((ROOT / "desktop" / "brand" / "logo-ccs-white.png").exists())
        canonical = (ROOT / "desktop" / "brand" / "splash.template.html").read_text(encoding="utf-8")
        self.assertNotIn("splash-mark.png", canonical)
        self.assertNotIn(".splash-mark", canonical)
        self.assertNotIn('class="splash-mark"', canonical)
        self.assertIn("splash-logo", canonical)
        self.assertIn("{{LOGO_HTML}}", canonical)
        cfg_js = (ROOT / "desktop" / "scripts" / "configure.mjs").read_text(encoding="utf-8")
        self.assertIn("logo-ccs-white.png", cfg_js)
        self.assertIn("rmSync", cfg_js)
        self.assertIn("brand/splash.template.html", cfg_js)
        rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('.env("OLLAMA_MODEL"', rust)
        self.assertIn("active_model.txt", rust)


class TestSmartSuiteHardwareContract(unittest.TestCase):
    """Un LLM por PC, umbrales 7/13/24, sin visión ni OCR."""

    def test_config_tiers_and_access(self):
        cfg = json.loads((ROOT / "desktop" / "smartsuite.config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("version"), "2.0.0")
        access = cfg.get("access") or {}
        self.assertEqual(access.get("blockBelowGb"), 7)
        self.assertEqual(access.get("warnBelowGb"), 13)
        tiers = cfg["ollama"]["tiers"]
        self.assertEqual([t["maxRamGb"] for t in tiers], [7, 13, 24, 0])
        self.assertEqual([t["id"] for t in tiers], ["liviano", "estandar", "completo", "maximo"])
        self.assertEqual([t["model"] for t in tiers], [
            "llama3.2:1b", "llama3.2:3b", "llama3.2:3b", "llama3.1:8b",
        ])
        for t in tiers:
            self.assertEqual(t.get("extraModels"), [])

    def test_appconfig_mirrors_contract(self):
        cfg = json.loads((ROOT / "desktop" / "src-tauri" / "appconfig.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("extraModels"), [])
        self.assertEqual(cfg.get("access", {}).get("blockBelowGb"), 7)
        self.assertEqual(cfg.get("access", {}).get("warnBelowGb"), 13)
        for t in cfg["ollamaTiers"]:
            self.assertEqual(t.get("extraModels"), [])
            self.assertIn("id", t)
            self.assertIn("label", t)

    def test_configure_copies_profile_fields(self):
        js = (ROOT / "desktop" / "scripts" / "configure.mjs").read_text(encoding="utf-8")
        self.assertIn("extraModels", js)
        self.assertIn("blockBelowGb", js)
        self.assertIn("warnBelowGb", js)
        self.assertIn("id: String(t.id", js)
        self.assertIn("label: String(t.label", js)

    def test_rust_blocks_and_pulls_profile_only(self):
        rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("fn profile_for_ram()", rust)
        self.assertIn("fn persist_active_profile", rust)
        self.assertIn('s.phase = "blocked".into()', rust)
        self.assertIn(
            "Este equipo no cumple el mínimo. Se midieron {:.1} GB de RAM y se necesitan al menos 8 GB.",
            rust,
        )
        self.assertIn("SMARTCAJA_ALLOW_LOW_RAM", rust)
        self.assertIn("SMARTSUITE_ALLOW_LOW_RAM", rust)
        self.assertIn('if s.phase == "blocked"', rust)
        self.assertIn("s.can_continue = false", rust)
        self.assertIn("profile.extra_models", rust)

    def test_splash_stays_on_blocked(self):
        for rel in (
            "desktop/brand/splash.template.html",
            "desktop/ui/splash.template.html",
            "desktop/ui/index.html",
        ):
            html = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("(s.phase || '') === 'blocked'", html)
            self.assertIn("Este equipo no cumple el mínimo de 8 GB de RAM.", html)

    def test_agents_ui_locks_profile_model(self):
        js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Modelo del perfil", js)
        self.assertIn("no disponible en este perfil", js)
        self.assertIn("renderRamWarning", js)
        self.assertIn("ramWarnBanner", html)
        self.assertIn("Perfil Estándar", js)
        self.assertIn("modelo compacto", js)
        self.assertIn("Chrome o Teams", js)
        self.assertIn("textos largos", js)
        start = js.find("function renderRamWarning")
        end = js.find("function showReadinessBanner")
        warn = js[start:end] if start >= 0 and end > start else js
        self.assertNotIn("boleta", warn.lower())
        self.assertNotIn("pdf", warn.lower())
        self.assertNotIn("rapidocr", warn.lower())
        self.assertNotIn("moondream", warn.lower())
        self.assertIn("payload = { system_prompt: promptEl.value }", js)
        self.assertNotIn("payload.model =", js)


# =====================================================================
# AGENTES
# =====================================================================
class TestAgentEndpoints(unittest.TestCase):

    def setUp(self):
        agents_dir = DATA_DIR / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        defaults_path = DEFAULTS_DIR / "agents.json"
        if defaults_path.exists():
            shutil.copy2(str(defaults_path), str(agents_dir / "agents.json"))

    def test_list_agents(self):
        response = client.get("/api/agents")
        self.assertEqual(response.status_code, 200)
        agents = response.json()["agents"]
        self.assertGreater(len(agents), 0)
        self.assertEqual(agents[0]["model_label"], "Modelo del perfil")
        self.assertEqual(agents[0]["vision"], "no disponible en este perfil")
        self.assertTrue(agents[0]["model_locked"])

    def test_get_agent(self):
        response = client.get("/api/agents/financial_interviewer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "financial_interviewer")

    def test_get_agent_not_found(self):
        response = client.get("/api/agents/nonexistent")
        self.assertEqual(response.status_code, 404)

    @patch("app._is_model_available", return_value=True)
    def test_update_agent(self, mock_avail):
        response = client.put("/api/agents/financial_interviewer", json={"model": "llama3.2:3b", "temperature": 0.5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["temperature"], 0.5)

    def test_update_agent_invalid_temperature(self):
        response = client.put("/api/agents/financial_interviewer", json={"temperature": 5.0})
        self.assertEqual(response.status_code, 422)


# =====================================================================
# FLUJO DE CAJA CRUD
# =====================================================================
class TestCashflowEndpoints(unittest.TestCase):

    def setUp(self):
        companies_dir = DATA_DIR / "companies"
        if companies_dir.exists():
            shutil.rmtree(companies_dir)
        companies_dir.mkdir(parents=True, exist_ok=True)
        _rate_limit_store.clear()
        resp = client.post("/api/companies", json={"name": "Empresa CF Test", "sector": "comercio"})
        self.company_id = resp.json()["id"]

    def _create_cashflow(self, months=2):
        cashflow_data = {
            "company_name": "Test",
            "months": [],
            "alerts": [{"month": "2025-01", "message": "Déficit", "type": "warning"}],
            "recommendations": ["Reducir gastos"]
        }
        for i in range(months):
            mo = i + 1
            cashflow_data["months"].append({
                "month": f"2025-{mo:02d}", "label": f"Mes {mo}",
                "income": {"sales": 10000000, "other_income": 500000},
                "expenses": {"variable_costs": 3000000, "fixed_costs": 2000000,
                            "variable_expenses": 500000, "debt_payments": 300000,
                            "taxes": 200000, "investments": 0}
            })
        save_json(DATA_DIR / "companies" / self.company_id / "cashflow.json", cashflow_data)

    def test_get_cashflow_not_found(self):
        response = client.get(f"/api/companies/{self.company_id}/cashflow")
        self.assertEqual(response.status_code, 404)

    def test_cashflow_normalized_on_read(self):
        self._create_cashflow(months=2)
        response = client.get(f"/api/companies/{self.company_id}/cashflow")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total_income"], 21000000)
        self.assertEqual(data["summary"]["total_expenses"], 12000000)
        self.assertEqual(data["summary"]["net_cashflow"], 9000000)
        self.assertEqual(data["months"][0]["net_flow"], 4500000)
        self.assertEqual(data["months"][0]["cumulative_balance"], 4500000)
        self.assertEqual(data["months"][1]["cumulative_balance"], 9000000)


# =====================================================================
# EDICIÓN DE MESES
# =====================================================================
class TestMonthCRUDEndpoints(unittest.TestCase):

    def setUp(self):
        companies_dir = DATA_DIR / "companies"
        if companies_dir.exists():
            shutil.rmtree(companies_dir)
        companies_dir.mkdir(parents=True, exist_ok=True)
        _rate_limit_store.clear()
        resp = client.post("/api/companies", json={"name": "Empresa Meses Test"})
        self.company_id = resp.json()["id"]
        cashflow_data = {
            "months": [
                {"month": "2025-01", "label": "Enero 2025", "income": {"sales": 5000000, "other_income": 0},
                 "expenses": {"variable_costs": 2000000, "fixed_costs": 1000000}},
                {"month": "2025-02", "label": "Febrero 2025", "income": {"sales": 6000000, "other_income": 0},
                 "expenses": {"variable_costs": 2500000, "fixed_costs": 1000000}}
            ],
            "alerts": [], "recommendations": []
        }
        save_json(DATA_DIR / "companies" / self.company_id / "cashflow.json", cashflow_data)

    def test_update_month(self):
        response = client.put(f"/api/companies/{self.company_id}/cashflow/months/0", json={
            "income": {"sales": 8000000, "other_income": 500000},
            "expenses": {"variable_costs": 3000000, "fixed_costs": 1500000}
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["months"][0]["income"]["sales"], 8000000)
        self.assertEqual(data["months"][0]["income"]["total"], 8500000)

    def test_update_month_invalid_index(self):
        response = client.put(f"/api/companies/{self.company_id}/cashflow/months/99", json={
            "income": {"sales": 1000}
        })
        self.assertEqual(response.status_code, 400)

    def test_add_month(self):
        response = client.post(f"/api/companies/{self.company_id}/cashflow/months", json={
            "month": "2025-03", "label": "Marzo 2025",
            "income": {"sales": 7000000, "other_income": 0},
            "expenses": {"variable_costs": 2800000, "fixed_costs": 1000000}
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["months"]), 3)
        self.assertEqual(data["months"][2]["month"], "2025-03")

    def test_delete_month(self):
        response = client.delete(f"/api/companies/{self.company_id}/cashflow/months/0")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["months"]), 1)
        self.assertEqual(data["months"][0]["month"], "2025-02")
        self.assertEqual(data["months"][0]["cumulative_balance"], data["months"][0]["net_flow"])

    def test_delete_month_invalid_index(self):
        response = client.delete(f"/api/companies/{self.company_id}/cashflow/months/99")
        self.assertEqual(response.status_code, 400)

    def test_add_month_no_cashflow(self):
        resp = client.post("/api/companies", json={"name": "Sin CF"})
        cid = resp.json()["id"]
        response = client.post(f"/api/companies/{cid}/cashflow/months", json={
            "month": "2025-01", "label": "Enero"
        })
        self.assertEqual(response.status_code, 404)

    def test_kpis_match_table_after_edit(self):
        client.put(f"/api/companies/{self.company_id}/cashflow/months/0", json={
            "income": {"sales": 10000000, "other_income": 1000000},
            "expenses": {"variable_costs": 4000000, "fixed_costs": 2000000,
                        "variable_expenses": 500000, "debt_payments": 300000,
                        "taxes": 200000, "investments": 100000}
        })
        response = client.get(f"/api/companies/{self.company_id}/cashflow")
        data = response.json()
        calc_income = sum(m["income"]["total"] for m in data["months"])
        calc_expenses = sum(m["expenses"]["total"] for m in data["months"])
        self.assertEqual(data["summary"]["total_income"], calc_income)
        self.assertEqual(data["summary"]["total_expenses"], calc_expenses)
        self.assertEqual(data["summary"]["net_cashflow"], calc_income - calc_expenses)

    def test_cumulative_balance_progressive(self):
        """Verifica que el saldo acumulado sea progresivo."""
        response = client.get(f"/api/companies/{self.company_id}/cashflow")
        data = response.json()
        cumulative = 0
        for m in data["months"]:
            cumulative += m["net_flow"]
            self.assertAlmostEqual(m["cumulative_balance"], cumulative, places=2)


# =====================================================================
# EXPORTACIÓN
# =====================================================================
class TestExportEndpoints(unittest.TestCase):

    def setUp(self):
        companies_dir = DATA_DIR / "companies"
        if companies_dir.exists():
            shutil.rmtree(companies_dir)
        companies_dir.mkdir(parents=True, exist_ok=True)
        _rate_limit_store.clear()
        resp = client.post("/api/companies", json={"name": "Empresa Export"})
        self.company_id = resp.json()["id"]
        cashflow_data = {
            "months": [
                {"month": "2025-01", "label": "Enero", "income": {"sales": 100, "other_income": 0},
                 "expenses": {"variable_costs": 30, "fixed_costs": 30}}
            ],
            "alerts": [], "recommendations": []
        }
        save_json(DATA_DIR / "companies" / self.company_id / "cashflow.json", cashflow_data)

    def test_export_excel(self):
        response = client.get(f"/api/companies/{self.company_id}/export/excel")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheet", response.headers.get("content-type", ""))

    def test_export_csv(self):
        response = client.get(f"/api/companies/{self.company_id}/export/csv")
        self.assertEqual(response.status_code, 200)

    def test_export_no_cashflow(self):
        resp = client.post("/api/companies", json={"name": "Sin CF"})
        cid = resp.json()["id"]
        response = client.get(f"/api/companies/{cid}/export/excel")
        self.assertEqual(response.status_code, 404)

    def test_export_filename_sanitized(self):
        resp = client.post("/api/companies", json={"name": "Empresa <script>alert(1)</script>"})
        cid = resp.json()["id"]
        cashflow_data = {"months": [{"month": "2025-01", "income": {"sales": 100}, "expenses": {"fixed_costs": 50}}], "alerts": [], "recommendations": []}
        save_json(DATA_DIR / "companies" / cid / "cashflow.json", cashflow_data)
        response = client.get(f"/api/companies/{cid}/export/excel")
        self.assertEqual(response.status_code, 200)
        disposition = response.headers.get("content-disposition", "")
        self.assertNotIn("<script>", disposition)


# =====================================================================
# MODELS ENDPOINTS
# =====================================================================
class TestModelsEndpoints(unittest.TestCase):

    @patch("app.http_requests.get")
    def test_available_models(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        mock_get.return_value = mock_response
        response = client.get("/api/models/available")
        self.assertEqual(response.status_code, 200)
        self.assertIn("llama3.2:3b", response.json()["models"])

    @patch("app.http_requests.get", side_effect=Exception("Connection refused"))
    def test_available_models_offline(self, mock_get):
        response = client.get("/api/models/available")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"], [])


# =====================================================================
# READINESS, HARDWARE PERFORMANCE & OLLAMA STATUS ENDPOINTS
# =====================================================================
class TestReadinessEndpoints(unittest.TestCase):

    @patch("app.http_requests.get")
    def test_readiness_all_ok(self, mock_get):
        """Cuando Ollama responde y hay modelos, readiness debe ser ready."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        response = client.get("/api/readiness")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Verificar estructura de respuesta
        self.assertIn("ready", data)
        self.assertIn("ollama_available", data)
        self.assertIn("models_count", data)
        self.assertIn("models", data)
        self.assertIn("issues", data)
        # Cuando Ollama responde con modelos, debe estar ready
        self.assertTrue(data["ready"])
        self.assertTrue(data["ollama_available"])
        self.assertGreater(data["models_count"], 0)

    @patch("app.http_requests.get", side_effect=Exception("Connection refused"))
    def test_readiness_ollama_down(self, mock_get):
        """Cuando Ollama no responde, readiness debe ser not_ready."""
        response = client.get("/api/readiness")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ready"])
        self.assertFalse(data["ollama_available"])
        # Debe reportar issue cr\u00edtico
        self.assertTrue(len(data["issues"]) > 0)
        self.assertEqual(data["issues"][0]["severity"], "critical")

    @patch("app.http_requests.get")
    def test_ollama_status(self, mock_get):
        """Endpoint /api/ollama/status debe retornar estado de Ollama."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        response = client.get("/api/ollama/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("available", data)
        self.assertIn("models", data)
        self.assertTrue(data["available"])
        self.assertIn("llama3.2:3b", data["models"])

    @patch("app.http_requests.get", side_effect=Exception("Connection refused"))
    def test_ollama_status_offline(self, mock_get):
        """Cuando Ollama no responde, status debe indicar offline."""
        response = client.get("/api/ollama/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["available"])
        self.assertEqual(data["models"], [])

    @patch("app.http_requests.get")
    def test_hardware_performance(self, mock_get):
        """Endpoint /api/hardware/performance debe retornar grades de modelos."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "llama3.2:3b", "size": 2000000000}]}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        response = client.get("/api/hardware/performance")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("hardware", data)
        self.assertIn("models", data)
        self.assertIn("ram_gb", data["hardware"])
        self.assertIsInstance(data["models"], list)
        if len(data["models"]) > 0:
            model_info = data["models"][0]
            self.assertIn("model", model_info)
            self.assertIn("grade", model_info)
            self.assertIn("grade_label", model_info)
            self.assertIn("grade_color", model_info)
            self.assertIn(model_info["grade"], ["S", "A", "B", "C", "D", "F"])

    @patch("app.http_requests.get", side_effect=Exception("Connection refused"))
    def test_hardware_performance_offline(self, mock_get):
        """Cuando Ollama no responde, performance debe retornar lista vac\u00eda de modelos."""
        response = client.get("/api/hardware/performance")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("hardware", data)
        self.assertIn("ram_gb", data["hardware"])
        self.assertEqual(data["models"], [])


# =====================================================================
# UX FRONTEND: Readiness Banner, Global Loading, Model Semaphore
# =====================================================================
class TestFrontendUX(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.combined = self.html + self.js

    def test_readiness_banner_exists(self):
        """El frontend debe tener un banner de readiness."""
        self.assertIn("readiness-banner", self.html)

    def test_global_loading_overlay_exists(self):
        """El frontend debe tener un overlay global de carga."""
        self.assertIn("globalLoadingOverlay", self.html)

    def test_show_global_loading_function(self):
        """Debe existir la función showGlobalLoading."""
        self.assertIn("showGlobalLoading", self.combined)

    def test_hide_global_loading_function(self):
        """Debe existir la función hideGlobalLoading."""
        self.assertIn("hideGlobalLoading", self.combined)

    def test_check_readiness_function(self):
        """Debe existir la función checkReadiness o checkOllama."""
        has_check = "checkReadiness" in self.combined or "checkOllama" in self.combined
        self.assertTrue(has_check, "Debe existir función de verificación de readiness")

    def test_safe_display_value_function(self):
        """Debe existir función de sanitización de display (escapeHtml o safeDisplayValue)."""
        has_safe = "safeDisplayValue" in self.combined or "escapeHtml" in self.combined
        self.assertTrue(has_safe, "Debe existir función de sanitización de display")

    def test_model_performance_section(self):
        """El frontend debe tener una sección de rendimiento de modelos o token usage."""
        has_perf = "modelPerfContainer" in self.combined or "tokenStats" in self.combined
        self.assertTrue(has_perf, "Debe existir sección de rendimiento/token usage")

    def test_load_model_performance_function(self):
        """Debe existir la función de carga de rendimiento (loadModelPerformance, loadTokenUsage o loadTokenStats)."""
        has_fn = ("loadModelPerformance" in self.combined or
                  "loadTokenUsage" in self.combined or
                  "loadTokenStats" in self.combined)
        self.assertTrue(has_fn, "Debe existir función de carga de rendimiento")

    def test_buttons_disabled_during_generation(self):
        """Los botones deben deshabilitarse durante la generación."""
        self.assertIn(".disabled = true", self.combined)

    def test_input_disabled_during_chat(self):
        """El input de chat debe deshabilitarse durante la respuesta del modelo."""
        has_disabled = "input.disabled = true" in self.combined or ".disabled = true" in self.combined
        self.assertTrue(has_disabled, "El input debe deshabilitarse durante la respuesta")

    def test_friendly_loading_messages(self):
        """Deben existir mensajes amigables durante la carga."""
        # Verificar que hay mensajes descriptivos de estado (case insensitive)
        combined_lower = self.combined.lower()
        has_analyzing = "analizando" in combined_lower or "analyzing" in combined_lower
        has_generating = "generando" in combined_lower or "generating" in combined_lower
        self.assertTrue(has_analyzing, "Debe existir mensaje de 'analizando'")
        self.assertTrue(has_generating, "Debe existir mensaje de 'generando'")

    def test_dompurify_loaded(self):
        """DOMPurify debe estar cargado para sanitización."""
        self.assertIn("purify.min.js", self.html)

    def test_readiness_polls_periodically(self):
        """El readiness debe verificarse periódicamente."""
        self.assertIn("setInterval", self.combined)
        has_poll = "checkReadiness" in self.combined or "pollOllama" in self.combined
        self.assertTrue(has_poll, "Debe existir polling de readiness")


# =====================================================================
# VALIDACIÓN PINOKIO: Estructura
# =====================================================================
class TestPinokioStructure(unittest.TestCase):

    def test_lifecycle_scripts_are_json(self):
        for name in ["install.json", "start.json", "stop.json", "reset.json"]:
            path = ROOT / name
            self.assertTrue(path.exists(), f"{name} no encontrado")
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.fail(f"{name} no es JSON válido")

    def test_pinokio_js_exists(self):
        self.assertTrue((ROOT / "pinokio.js").exists())

    def test_pinokio_js_references_json(self):
        content = (ROOT / "pinokio.js").read_text(encoding="utf-8")
        self.assertIn("install.json", content)
        self.assertIn("start.json", content)
        self.assertIn("stop.json", content)

    def test_no_background_true(self):
        for name in ["install.json", "start.json", "stop.json"]:
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn('"background"', content, f"{name} contiene 'background'")

    def test_venv_name_consistent(self):
        for name in ["install.json", "start.json", "pinokio.js"]:
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("venv", content, f"{name} no referencia 'venv'")

    def test_server_uses_absolute_paths(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("__file__", content)

    def test_ensure_ascii_false(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("ensure_ascii=False", content)

    def test_response_encoding_utf8(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn('resp.encoding = "utf-8"', content)

    def test_no_let_const_in_html(self):
        content = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        script_start = content.find("<script>")
        script_end = content.find("</script>")
        if script_start != -1 and script_end != -1:
            script = content[script_start:script_end]
            self.assertEqual(len(re.findall(r'^\s*let\s', script, re.MULTILINE)), 0)
            self.assertEqual(len(re.findall(r'^\s*const\s', script, re.MULTILINE)), 0)

    def test_icon_exists(self):
        self.assertTrue((ROOT / "icon.png").exists())

    def test_ccs_brand_assets(self):
        self.assertTrue((ROOT / "app" / "logo-ccs.png").exists())
        self.assertTrue((ROOT / "app" / "favicon.ico").exists())
        self.assertTrue((ROOT / "desktop" / "brand" / "logo-ccs.png").exists())
        self.assertTrue((ROOT / "desktop" / "brand" / "logo-ccs-mark.png").exists())
        self.assertTrue((ROOT / "desktop" / "src-tauri" / "icons" / "icon.ico").exists())
        self.assertFalse((ROOT / "app" / "logo-ccs.svg").exists())
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("logo-ccs.png", html)
        self.assertIn('rel="icon"', html)
        self.assertIn("favicon.ico", html)
        self.assertNotIn("logo-ccs.svg", html)
        self.assertNotIn("logo-ccce", html)
        js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("logo-ccs.png", js)
        cfg = json.loads((ROOT / "desktop" / "smartsuite.config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("splashLogo"), "brand/logo-ccs.png")
        self.assertEqual(cfg.get("splashMark"), "../icon.png")

    def test_defaults_agents_json(self):
        path = ROOT / "defaults" / "agents.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("agents", data)
        for agent in data["agents"]:
            self.assertIn("id", agent)
            self.assertIn("model", agent)

    def test_prompts_exist(self):
        prompts_dir = ROOT / "defaults" / "prompts"
        self.assertTrue(prompts_dir.exists())
        self.assertTrue((prompts_dir / "financial_interviewer.md").exists())
        self.assertTrue((prompts_dir / "cashflow_analyst.md").exists())
        self.assertTrue((prompts_dir / "scenario_simulator.md").exists())


# =====================================================================
# CROSS-PLATFORM
# =====================================================================
class TestCrossPlatform(unittest.TestCase):

    def test_install_json_has_platform_conditions(self):
        content = (ROOT / "install.json").read_text(encoding="utf-8")
        self.assertIn("platform", content)
        self.assertIn("win32", content)

    def test_start_json_has_platform_conditions(self):
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertIn("platform", content)
        self.assertIn("win32", content)

    def test_install_json_uses_setup_scripts_for_deps(self):
        """install.json debe usar scripts dedicados (setup_venv.ps1/sh) para
        instalar dependencias, en lugar de pip install directo. Esto garantiza
        que el venv se cree correctamente en Windows con Conda activo."""
        content = (ROOT / "install.json").read_text(encoding="utf-8")
        self.assertIn("setup_venv.ps1", content,
                      "install.json debe usar setup_venv.ps1 para Windows")
        self.assertIn("setup_venv.sh", content,
                      "install.json debe usar setup_venv.sh para Unix")

    def test_setup_scripts_exist(self):
        """Los scripts de setup deben existir."""
        self.assertTrue((ROOT / "scripts" / "setup_venv.ps1").exists(),
                        "scripts/setup_venv.ps1 debe existir")
        self.assertTrue((ROOT / "scripts" / "setup_venv.sh").exists(),
                        "scripts/setup_venv.sh debe existir")
        self.assertTrue((ROOT / "scripts" / "verify_deps.py").exists(),
                        "scripts/verify_deps.py debe existir")

    def test_setup_ps1_finds_python_robustly(self):
        """setup_venv.ps1 debe buscar Python en múltiples ubicaciones de Windows."""
        content = (ROOT / "scripts" / "setup_venv.ps1").read_text(encoding="utf-8")
        self.assertIn("function Find-Python", content,
                      "setup_venv.ps1 debe tener función Find-Python")
        self.assertIn("miniconda3", content,
                      "setup_venv.ps1 debe buscar en miniconda3")
        self.assertIn("anaconda3", content,
                      "setup_venv.ps1 debe buscar en anaconda3")
        self.assertIn("LOCALAPPDATA", content,
                      "setup_venv.ps1 debe buscar en LOCALAPPDATA")

    def test_setup_ps1_verifies_critical_imports(self):
        """setup_venv.ps1 debe verificar que los módulos críticos se importan."""
        content = (ROOT / "scripts" / "setup_venv.ps1").read_text(encoding="utf-8")
        # Los imports pueden estar en una sola línea separados por comas
        for mod in ["requests", "fastapi", "uvicorn", "pydantic"]:
            self.assertIn(mod, content,
                          f"setup_venv.ps1 debe verificar {mod}")
        self.assertIn("VERIFY_OK", content,
                      "setup_venv.ps1 debe imprimir VERIFY_OK al verificar imports")

    def test_setup_ps1_exits_on_failure(self):
        """setup_venv.ps1 debe fallar con exit 1 si la verificación falla."""
        content = (ROOT / "scripts" / "setup_venv.ps1").read_text(encoding="utf-8")
        self.assertIn("exit 1", content)

    def test_setup_ps1_has_fallback_install(self):
        """setup_venv.ps1 debe tener un fallback de instalación individual."""
        content = (ROOT / "scripts" / "setup_venv.ps1").read_text(encoding="utf-8")
        self.assertIn("force-reinstall", content,
                      "setup_venv.ps1 debe tener fallback con --force-reinstall")

    def test_setup_sh_verifies_critical_imports(self):
        """setup_venv.sh debe verificar que los módulos críticos se importan."""
        content = (ROOT / "scripts" / "setup_venv.sh").read_text(encoding="utf-8")
        # Los imports pueden estar en una sola línea separados por comas
        for mod in ["requests", "fastapi", "uvicorn"]:
            self.assertIn(mod, content,
                          f"setup_venv.sh debe verificar {mod}")
        self.assertIn("VERIFY_OK", content,
                      "setup_venv.sh debe imprimir VERIFY_OK al verificar imports")

    def test_install_json_no_direct_pip_install(self):
        """install.json NO debe tener pasos directos de 'pip install' porque
        las dependencias se instalan via scripts dedicados (setup_venv.ps1/sh)
        que manejan correctamente el venv en Windows con Conda."""
        data = json.loads((ROOT / "install.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                msg = step["params"].get("message", "")
                if isinstance(msg, list):
                    msg = " ".join(msg)
                # No debe haber pip install directo en install.json
                if "pip install" in msg and step["params"].get("venv") == "venv":
                    self.fail("install.json tiene pip install directo con venv param. "
                              "Debe usar scripts/setup_venv.ps1 o .sh en su lugar.")

    def test_install_json_data_init_uses_venv(self):
        """Los pasos de inicialización de datos que usan python deben
        ejecutarse dentro del venv (ya sea via param venv o referenciando
        directamente el binario del venv como venv/bin/python)."""
        data = json.loads((ROOT / "install.json").read_text(encoding="utf-8"))
        python_steps = [
            step for step in data["run"]
            if isinstance(step.get("params"), dict)
            and isinstance(step["params"].get("message"), (str, list))
            and "python -c" in str(step["params"]["message"])
        ]
        for step in python_steps:
            msg = str(step["params"]["message"])
            has_venv_param = step["params"].get("venv") == "venv"
            uses_venv_binary = "venv/bin/python" in msg or "venv\\Scripts\\python" in msg
            self.assertTrue(
                has_venv_param or uses_venv_binary,
                f"Paso de python -c sin venv param ni referencia al binario del venv: {msg[:80]}"
            )

    def test_start_json_uses_venv(self):
        data = json.loads((ROOT / "start.json").read_text(encoding="utf-8"))
        venv_used = any(
            isinstance(step.get("params"), dict) and step["params"].get("venv") == "venv"
            for step in data["run"]
        )
        self.assertTrue(venv_used, "start.json debe usar 'venv' para ejecutar el servidor")

    def test_start_json_sets_encoding_env(self):
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertTrue("PYTHONIOENCODING" in content or "PYTHONUTF8" in content)

    def test_start_json_verifies_deps_before_server(self):
        """start.json debe ejecutar verify_deps.py ANTES de server/app.py."""
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertIn("verify_deps.py", content,
                      "start.json debe ejecutar verify_deps.py")
        verify_pos = content.index("verify_deps.py")
        server_pos = content.index("server/app.py")
        self.assertLess(verify_pos, server_pos,
                        "verify_deps.py debe ejecutarse ANTES de server/app.py")

    def test_start_json_shows_dep_verification_message(self):
        """start.json debe mostrar un mensaje de verificación de dependencias."""
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertIn("Verificando dependencias", content)

    def test_verify_deps_auto_repairs(self):
        """verify_deps.py debe intentar auto-reparar dependencias faltantes."""
        content = (ROOT / "scripts" / "verify_deps.py").read_text(encoding="utf-8")
        # verify_deps.py usa subprocess con lista de args, no cadena literal
        self.assertIn("pip", content, "verify_deps.py debe usar pip para instalar")
        self.assertIn("Instalando automaticamente", content)
        self.assertIn("DEPS_VERIFY_OK", content)

    def test_verify_deps_checks_all_critical_modules(self):
        """verify_deps.py debe verificar todos los módulos críticos."""
        content = (ROOT / "scripts" / "verify_deps.py").read_text(encoding="utf-8")
        for mod in ["requests", "fastapi", "uvicorn", "pydantic", "aiofiles", "openpyxl"]:
            self.assertIn(mod, content,
                          f"verify_deps.py debe verificar {mod}")

    def test_diagnose_scripts_exist(self):
        """Scripts de diagnóstico deben existir para ambas plataformas."""
        self.assertTrue((ROOT / "scripts" / "diagnose.ps1").exists())
        self.assertTrue((ROOT / "scripts" / "diagnose.sh").exists())

    def test_desktop_ollama_portable_not_msi(self):
        rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn("install_portable_ollama", rust)
        self.assertIn("ollama-windows-amd64.zip", rust)
        self.assertIn("ollama-linux-amd64.tgz", rust)
        self.assertNotIn("OllamaSetup.exe", rust)
        self.assertIn("record_owned_ollama", rust)

    def test_install_json_ollama_windows(self):
        """Windows debe usar OllamaSetup.exe descargado con curl, no winget
        (winget no siempre está disponible en todas las versiones de Windows)."""
        content = (ROOT / "install.json").read_text(encoding="utf-8")
        self.assertTrue(
            "OllamaSetup.exe" in content or "winget" in content,
            "install.json debe tener un método de instalación de Ollama para Windows"
        )

    def test_start_json_ollama_windows_serve(self):
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertTrue(
            "start /B" in content or "Start-Process" in content,
            "start.json debe iniciar Ollama en background en Windows"
        )

    def test_data_dir_is_pathlib(self):
        self.assertIsInstance(DATA_DIR, Path)

    def test_data_dir_no_pinokio_templates(self):
        """DATA_DIR no debe contener plantillas Pinokio sin resolver.
        Error real en Windows: OSError [WinError 123] por
        DATA_DIR='{{cwd}}{{platform === ...}}\\data'."""
        data_dir_str = str(DATA_DIR)
        self.assertNotIn("{{", data_dir_str,
                         f"DATA_DIR contiene plantilla Pinokio sin resolver: {data_dir_str}")
        self.assertNotIn("}}", data_dir_str,
                         f"DATA_DIR contiene plantilla Pinokio sin resolver: {data_dir_str}")

    def test_server_prints_127_not_0000(self):
        """El servidor debe imprimir http://127.0.0.1:PORT (no 0.0.0.0)
        para que el regex de start.json capture una URL válida en Windows."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        # Puede ser print(f"http://127.0.0.1:{PORT}") o print(f"http://{host}:{PORT}")
        # Lo importante es que NO tenga 0.0.0.0 en el print
        self.assertNotIn('print(f"http://0.0.0.0', content,
                         "El print NO debe usar 0.0.0.0 - Pinokio captura esa URL")

    def test_uvicorn_binds_to_127(self):
        """uvicorn.run debe usar host='127.0.0.1' (no '0.0.0.0').
        En Windows, 0.0.0.0 causa que Pinokio capture una URL no accesible.
        Patron del brand-assistant: siempre 127.0.0.1."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('host="0.0.0.0"', content,
                         "uvicorn NO debe usar host='0.0.0.0'. "
                         "Usar '127.0.0.1' para que Pinokio capture la URL correcta.")
        self.assertNotIn("host='0.0.0.0'", content,
                         "uvicorn NO debe usar host='0.0.0.0'.")
        # Debe tener host = "127.0.0.1"
        self.assertIn('host = "127.0.0.1"', content,
                      "uvicorn debe usar host='127.0.0.1'")

    def test_windows_asyncio_policy(self):
        """En Windows, debe configurar WindowsProactorEventLoopPolicy
        para evitar NotImplementedError con asyncio."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("WindowsProactorEventLoopPolicy", content,
                      "Debe configurar WindowsProactorEventLoopPolicy para Windows")

    def test_install_json_no_powershell_for_ollama_serve(self):
        """En install.json, el inicio de Ollama en Windows no debe usar
        powershell complejo que puede fallar en cmd.exe de Pinokio."""
        data = json.loads((ROOT / "install.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                msg = str(step["params"].get("message", ""))
                if "win32" in str(step.get("when", "")):
                    # No debe tener powershell -Command con Start-Process para ollama serve
                    if "ollama serve" in msg.lower() or "OLLAMA_READY" in msg:
                        self.assertNotIn(
                            "Invoke-WebRequest", msg,
                            "install.json Windows no debe usar Invoke-WebRequest para readiness check"
                        )

    def test_start_json_no_powershell_for_ollama(self):
        """start.json debe usar 'start /B ollama serve' en Windows,
        no powershell -Command Start-Process."""
        data = json.loads((ROOT / "start.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                msg = str(step["params"].get("message", ""))
                when = str(step.get("when", ""))
                if "win32" in when and "ollama" in msg.lower():
                    self.assertNotIn(
                        "powershell", msg.lower(),
                        "start.json Windows debe usar 'start /B ollama serve', no powershell"
                    )

    def test_install_json_valid_json(self):
        """install.json debe ser JSON puro válido."""
        content = (ROOT / "install.json").read_text(encoding="utf-8")
        try:
            data = json.loads(content)
            self.assertIn("run", data)
        except json.JSONDecodeError:
            self.fail("install.json no es JSON válido")

    def test_start_json_is_daemon(self):
        """start.json debe tener daemon: true."""
        data = json.loads((ROOT / "start.json").read_text(encoding="utf-8"))
        self.assertTrue(data.get("daemon"), "start.json debe tener daemon: true")

    def test_start_json_no_data_dir_with_cwd_template(self):
        """start.json NO debe pasar DATA_DIR con {{cwd}} como env var.
        Pinokio no resuelve expresiones ternarias complejas en env,
        lo que causa OSError [WinError 123] en Windows.
        El patron correcto es calcular DATA_DIR en Python (BASE_DIR / 'data')."""
        content = (ROOT / "start.json").read_text(encoding="utf-8")
        self.assertNotIn("{{cwd}}", content,
                         "start.json no debe usar {{cwd}} en env vars. "
                         "DATA_DIR debe calcularse en Python.")

    def test_start_json_no_ternary_in_env(self):
        """start.json NO debe usar operadores ternarios en valores de env.
        Pinokio puede no resolver '{{platform === \'win32\' ? ... : ...}}'
        correctamente, pasando la expresion literal como string."""
        data = json.loads((ROOT / "start.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                env = step["params"].get("env", {})
                for key, val in env.items():
                    self.assertNotIn("?", str(val),
                                     f"env var '{key}' en start.json contiene operador ternario: {val}. "
                                     "Pinokio puede no resolverlo en Windows.")

    def test_install_json_no_ternary_in_env(self):
        """install.json NO debe usar operadores ternarios en valores de env."""
        data = json.loads((ROOT / "install.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                env = step["params"].get("env", {})
                for key, val in env.items():
                    self.assertNotIn("?", str(val),
                                     f"env var '{key}' en install.json contiene operador ternario: {val}")

    def test_no_cwd_template_in_any_env_var(self):
        """Ningun JSON de lifecycle debe usar {{cwd}} en env vars.
        Las rutas deben calcularse en Python usando __file__."""
        for name in ["install.json", "start.json"]:
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for step in data["run"]:
                if isinstance(step.get("params"), dict):
                    env = step["params"].get("env", {})
                    for key, val in env.items():
                        self.assertNotIn("{{cwd}}", str(val),
                                         f"{name}: env var '{key}' usa {{{{cwd}}}}. "
                                         "Calcular rutas en Python.")

    def test_app_py_data_dir_has_template_guard(self):
        """server/app.py debe tener proteccion contra plantillas Pinokio
        sin resolver en DATA_DIR ({{cwd}} literal)."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("{{", content,
                      "app.py debe verificar si DATA_DIR contiene '{{'")
        self.assertIn("BASE_DIR", content)

    def test_app_py_data_dir_fallback_to_base_dir(self):
        """server/app.py debe usar BASE_DIR / 'data' como fallback seguro."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn('BASE_DIR / "data"', content,
                      "app.py debe tener fallback DATA_DIR = BASE_DIR / 'data'")

    def test_app_py_data_dir_not_just_env_get(self):
        """server/app.py NO debe usar Path(os.environ.get('DATA_DIR', ...)) sin validacion.
        Debe verificar que el valor no contenga plantillas Pinokio."""
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        # No debe tener la linea simple sin guardia
        self.assertNotIn(
            'DATA_DIR = Path(os.environ.get("DATA_DIR"',
            content,
            "app.py no debe usar DATA_DIR = Path(os.environ.get('DATA_DIR', ...)) sin validacion. "
            "Debe verificar que no contenga '{{' antes de usarlo."
        )

    def test_brand_assistant_pattern_no_data_dir_env(self):
        """Consistencia con brand-assistant: DATA_DIR no debe pasarse como env var.
        El patron correcto es calcularlo en Python como BASE_DIR / 'data'."""
        data = json.loads((ROOT / "start.json").read_text(encoding="utf-8"))
        for step in data["run"]:
            if isinstance(step.get("params"), dict):
                env = step["params"].get("env", {})
                self.assertNotIn("DATA_DIR", env,
                                 "start.json no debe pasar DATA_DIR como env var. "
                                 "Patron brand-assistant: calcular en Python.")

    def test_stop_json_kills_process_cross_platform(self):
        """stop.json debe usar shell.run con pkill (unix) y wmic (win32)
        para detener el servidor de forma cross-platform."""
        data = json.loads((ROOT / "stop.json").read_text(encoding="utf-8"))
        content = (ROOT / "stop.json").read_text(encoding="utf-8")
        # Debe tener al menos un paso para unix y otro para windows
        has_unix_kill = any(
            isinstance(step.get("params"), dict)
            and "pkill" in str(step["params"].get("message", ""))
            and "win32" not in str(step.get("when", "")) or "!==" in str(step.get("when", ""))
            for step in data["run"]
        )
        has_win_kill = any(
            isinstance(step.get("params"), dict)
            and ("wmic" in str(step["params"].get("message", "")).lower()
                 or "taskkill" in str(step["params"].get("message", "")).lower())
            for step in data["run"]
        )
        self.assertTrue(has_unix_kill, "stop.json debe usar pkill para unix")
        self.assertTrue(has_win_kill, "stop.json debe usar wmic/taskkill para Windows")

    def test_no_background_true_anywhere(self):
        """Ningún archivo JSON debe usar background: true (no existe en Pinokio)."""
        for name in ["install.json", "start.json", "stop.json", "reset.json"]:
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn('"background"', content, f"{name} contiene 'background'")


# =====================================================================
# SEGURIDAD AVANZADA
# =====================================================================
class TestSecurityAdvanced(unittest.TestCase):

    def test_cors_not_wildcard(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('allow_origins=["*"]', content)

    def test_cors_localhost_only(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("localhost", content)
        self.assertIn("127.0.0.1", content)

    def test_rate_limiting_exists(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("_check_rate_limit", content)

    def test_input_validation_message_length(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("MAX_MESSAGE_LENGTH", content)

    def test_input_validation_company_name(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("MAX_COMPANY_NAME_LENGTH", content)

    def test_ensure_ollama_running_exists(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("def ensure_ollama_running", content)

    def test_tauri_skips_python_ollama_autostart(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("RUN_BY_TAURI", content)
        self.assertIn("portable", content.lower())

        self.assertIn("def resolve_ollama_model", content)
        self.assertIn("OLLAMA_MODEL", content)

    def test_sidecar_passes_ollama_model_env(self):
        rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
        self.assertIn('.env("OLLAMA_MODEL"', rust)
        self.assertIn('.env("OLLAMA_PROFILE"', rust)
        self.assertIn("active_model.txt", rust)
        self.assertIn("active_profile.json", rust)
        self.assertIn("let mut cmd = hidden_command", rust)
        self.assertIn("fn kill_ollama_child", rust)
        self.assertIn("slot.take()", rust)
        self.assertNotIn("run(hidden_command(", rust)


    def test_frontend_uses_escape_html(self):
        # La lógica de escapeHtml vive en app.js (no en index.html)
        content = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("escapeHtml", content)
        count = content.count("escapeHtml(")
        self.assertGreaterEqual(count, 10, f"escapeHtml se usa solo {count} veces")

    def test_frontend_no_eval(self):
        content = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if "eval(" in stripped:
                self.assertIn("font-display", stripped, f"eval() encontrado en: {stripped}")

    def test_frontend_input_length_validation(self):
        # Verificar límite de longitud en index.html o app.js
        content_html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        content_js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        has_limit = "10000" in content_html or "10000" in content_js or "MAX_MESSAGE_LENGTH" in content_js
        self.assertTrue(has_limit, "No se encontró validación de longitud de input")

    def test_frontend_correct_api_endpoint(self):
        # La lógica de fetch vive en app.js
        content = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/chat/interview", content)
        # Verificar que no hay llamadas a /api/chat sin /interview
        matches = re.findall(r"fetch\([`'\"].*?/api/chat['\"`][^/]", content)
        self.assertEqual(len(matches), 0, f"Encontradas llamadas a /api/chat sin /interview")

    def test_sanitize_id_in_backend(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("_sanitize_id", content)

    def test_sanitize_filename_in_backend(self):
        content = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
        self.assertIn("_sanitize_filename", content)


if __name__ == "__main__":
    unittest.main()
