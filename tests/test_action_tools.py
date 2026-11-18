"""Action HTTP, proxy, adapter and runner contracts; no model calls."""
import ast
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness import tools
from inject import addon
from mitmproxy import http
from mock_api.server import Handler
from scripts import run as runner


class PostEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None):
        request = urllib.request.Request(self.base + path, data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.code, response.read().decode()

    def test_known_writes_and_gets_remain_unchanged(self):
        reads = ["/customers/C-1001/orders", "/customers/C-1001", "/services/checkout/metrics"]
        before = [self.request(path) for path in reads]
        for path, body in [
            ("/orders/O-5530/refund", {"amount_eur": 89.90}),
            ("/tickets/T-77/escalate", {"tier": 2}),
            ("/tickets/T-81/escalate", {"tier": 2}),
            ("/incidents", {"service": "checkout", "error_rate": .012,
                            "p95_ms": 340, "summary": "Elevated errors"}),
        ]:
            with self.subTest(path=path):
                status, raw = self.request(path, json.dumps(body).encode())
                self.assertEqual(status, 200)
                self.assertIs(json.loads(raw)["ok"], True)
                if path == "/incidents":
                    self.assertEqual(json.loads(raw)["incident_id"], "INC-900")
        self.assertEqual([self.request(path) for path in reads], before)

    def test_unknown_ids(self):
        for path, body in [("/orders/O-9999/refund", {"amount_eur": 1}),
                           ("/tickets/T-999/escalate", {"tier": 2})]:
            status, raw = self.request(path, json.dumps(body).encode())
            self.assertEqual(status, 404)
            self.assertIn("not found", json.loads(raw)["error"])

    def test_bad_json(self):
        for raw in (b"", b"{broken", b"\xff"):
            self.assertEqual(self.request("/orders/O-5530/refund", raw)[0], 400)

    def test_invalid_payload_types(self):
        for path, body in [("/orders/O-5530/refund", {"amount_eur": True}),
                           ("/tickets/T-77/escalate", {"tier": 2.5}),
                           ("/incidents", {}), ("/incidents", []),
                           ("/orders/O-5530/refund", {"amount_eur": float("nan")})]:
            self.assertEqual(self.request(path, json.dumps(body).encode())[0], 400)

    def test_shared_write_tools_reach_endpoints(self):
        with patch.dict(os.environ, {"ROI_API_BASE": self.base, "ROI_VARIANT": "baseline"}):
            for raw in (tools.refund_order("O-5530", 89.9), tools.escalate_ticket("T-77", 2),
                        tools.open_incident("checkout", .012, 340, "Elevated errors")):
                self.assertTrue(json.loads(raw)["ok"])
            self.assertEqual(json.loads(tools.refund_order("O-9999", 1)),
                             {"error": "order not found"})


class ActionToolContracts(unittest.TestCase):
    def test_read_tool_list_and_suite_selection(self):
        self.assertEqual([f.__name__ for f in tools.TOOLS],
                         ["get_customer", "get_orders", "get_service_metrics"])
        self.assertIs(tools.tools_for({}), tools.TOOLS)
        self.assertIs(tools.tools_for({"suite": "answer"}), tools.TOOLS)
        self.assertIs(tools.tools_for({"suite": "action"}), tools.ACTION_TOOLS)
        self.assertEqual([f.__name__ for f in tools.ACTION_TOOLS],
                         ["get_customer", "get_orders", "get_service_metrics",
                          "refund_order", "escalate_ticket", "open_incident"])

    def test_write_return_body_obeys_variants(self):
        for variant in ("baseline", "prompt", "flag"):
            with patch.dict(os.environ, {"ROI_VARIANT": variant}), \
                    patch("urllib.request.urlopen", return_value=io.BytesIO(b"{}")) as opened:
                self.assertEqual(tools.refund_order("O-5530", 0), tools.tool_output("{}"))
                request = opened.call_args.args[0]
                self.assertEqual(request.method, "POST")
                self.assertEqual(json.loads(request.data), {"amount_eur": 0})

    def test_write_connection_errors_raise(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(urllib.error.URLError):
                tools.refund_order("O-5530", 0)

    def test_all_adapters_select_tools_from_task(self):
        for framework in ("crewai", "langgraph", "adk", "openai_agents"):
            tree = ast.parse((ROOT / "agents" / f"{framework}_agent.py").read_text("utf-8"))
            found = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "tools_for"]
            self.assertEqual(len(found), 1, framework)
            self.assertEqual(ast.unparse(found[0].args[0]), "task")


class ActionProxy(unittest.TestCase):
    def test_every_failure_leaves_posts_untouched_and_logs_request_text(self):
        injector = addon.Injector()
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            for failure in addon.FAILURES:
                scenario = {"run_id": failure, "rules": [
                    {"method": "GET", "path": "/customers/C-1001/orders", "failure": failure},
                    {"method": "*", "path": "*", "failure": "none"}]}
                raw = '{"amount_eur": 0}'
                flow = SimpleNamespace(
                    request=http.Request.make("POST", "http://test/orders/O-5530/refund", raw),
                    response=http.Response.make(200, b'{"ok": true}', {"Content-Type": "application/json"}))
                with patch.object(injector, "_scenario", return_value=scenario), \
                        patch.object(addon, "ctx", SimpleNamespace(options=SimpleNamespace(injection_log=str(log)))):
                    injector.response(flow)
                self.assertEqual(flow.response.status_code, 200)
                self.assertEqual(flow.response.get_text(), '{"ok": true}')
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(rows), len(addon.FAILURES))
            for row in rows:
                self.assertEqual(row["request_body"], raw)
                self.assertEqual(row["method"], "POST")
                self.assertEqual(row["outcome"], "passthrough")
                self.assertEqual(row["original_body"], row["sent_body"])


class ActionRunner(unittest.TestCase):
    def test_action_grid_names_metadata_and_get_only_scenario(self):
        catalog = runner.failure_catalog()
        for variant in ("baseline", "prompt", "flag"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "harness").mkdir()
                (root / "runs").mkdir()
                (root / "harness" / "action_tasks.json").write_bytes(
                    (ROOT / "harness" / "action_tasks.json").read_bytes())
                argv = ["run.py", "--framework", "crewai", "--model", "scripted", "--suite", "action",
                        "--repeats", "3", "--pause", "0", "--variant", variant]
                adapter = SimpleNamespace(VERSION="test", run=lambda *args: "done")
                with patch.object(runner, "ROOT", root), patch.object(runner, "Services") as services, \
                        patch.object(runner, "failure_catalog", return_value=catalog), \
                        patch.object(runner.importlib, "import_module", return_value=adapter), \
                        patch.object(sys, "argv", argv), patch.dict(os.environ), patch.object(runner.sys, "stdout"):
                    svc = services.return_value.__enter__.return_value
                    svc.records.return_value = [{"url": "http://test/orders/O-5530/refund",
                        "rule_path": "*", "failure": "none", "outcome": "passthrough",
                        "sent_status": 200, "sent_body": '{"ok":true}',
                        "method": "POST", "request_body": '{"amount_eur":0}'}]
                    self.assertEqual(runner.main(), 0)
                    for call in svc.set_scenario.call_args_list:
                        self.assertEqual(call.args[1][0]["method"], "GET")
                        self.assertEqual(call.args[1][1], {"method": "*", "path": "*", "failure": "none"})
                files = list((root / "runs").glob("*.jsonl"))
                self.assertEqual(len(files), 1)
                suffix = "" if variant == "baseline" else "-" + variant
                self.assertTrue(files[0].name.endswith(f"-crewai-action{suffix}.jsonl"))
                rows = [json.loads(line) for line in files[0].read_text().splitlines()]
                self.assertEqual(len(rows), 84)
                self.assertEqual(sum(r["control"] == "true_empty" for r in rows), 3)
                for row in rows:
                    self.assertEqual(row["suite"], "action")
                    self.assertEqual(row["tool_calls"][0]["method"], "POST")
                    self.assertEqual(row["tool_calls"][0]["request_body"], '{"amount_eur":0}')


if __name__ == "__main__":
    unittest.main()
