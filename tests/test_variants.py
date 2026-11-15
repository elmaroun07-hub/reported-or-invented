"""Variant contracts; no model calls or optional framework imports required."""
import ast
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness import tools
from scripts import judge as judge_script
from scripts import run as run_script
from test_judge import body_for

PROMPT = ("If a tool returns an empty, incomplete or unreadable result, say so plainly "
          "and do not fill in or estimate the missing values.")
NOTE = "\n\n[tool note] The API returned no data at: {}."


class ToolVariants(unittest.TestCase):
    def received(self, body, variant="flag", http_error=False):
        response = io.BytesIO(body.encode("utf-8"))
        kwargs = ({"side_effect": urllib.error.HTTPError("http://test", 500, "error", {}, response)}
                  if http_error else {"return_value": response})
        with patch.dict(os.environ, {"ROI_VARIANT": variant}), \
                patch("urllib.request.urlopen", **kwargs):
            return tools.get_orders("C-1001")

    def test_empty_body(self):
        self.assertEqual(self.received(""), NOTE.format("whole body"))

    def test_whitespace_body(self):
        self.assertEqual(self.received("  "), "  " + NOTE.format("whole body"))

    def test_empty_object(self):
        self.assertEqual(self.received("{}"), "{}" + NOTE.format("$"))

    def test_empty_list(self):
        self.assertEqual(self.received("[]"), "[]" + NOTE.format("$"))

    def test_empty_orders(self):
        body = '{"orders": []}'
        self.assertEqual(self.received(body), body + NOTE.format("$.orders"))

    def test_nested_null_and_multiple_paths(self):
        body = '{"orders": [{"total_eur": null}, {}], "extra": []}'
        self.assertEqual(self.received(body), body + NOTE.format(
            "$.orders[0].total_eur, $.orders[1], $.extra"))

    def test_ambiguous_object_key(self):
        body = '{"a.b": null}'
        self.assertEqual(self.received(body), body + NOTE.format('$["a.b"]'))

    def test_plain_text_and_malformed_json(self):
        for body in ("upstream unavailable", '{"orders":', "NaN", "Infinity"):
            with self.subTest(body=body):
                self.assertEqual(self.received(body), body + NOTE.format("whole body"))

    def test_root_null(self):
        self.assertEqual(self.received("null"), "null" + NOTE.format("$"))

    def test_real_zero_and_truncated_mock_bodies_unchanged(self):
        for task in ("orders-total", "open-tickets", "checkout-health"):
            for failure in ("none", "zero_values", "truncate"):
                with self.subTest(task=task, failure=failure):
                    body = body_for(task, failure)
                    self.assertEqual(self.received(body), body)

    def test_true_empty_control_is_flagged(self):
        body = body_for("true-empty-orders", "none")
        self.assertEqual(self.received(body), body + NOTE.format("$.orders"))

    def test_scalars_are_not_missing_data(self):
        for body in ('""', '"text"', "0", "false", "[0, false]"):
            with self.subTest(body=body):
                self.assertEqual(self.received(body), body)

    def test_baseline_and_prompt_preserve_every_body(self):
        for variant in ("baseline", "prompt"):
            for body in ("", "  ", "{}", "[]", '{"x": null}', "text", "café\r\n"):
                with self.subTest(variant=variant, body=body):
                    self.assertEqual(self.received(body, variant), body)

    def test_unset_variant_defaults_to_baseline(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch("urllib.request.urlopen", return_value=io.BytesIO(b"  ")):
            self.assertEqual(tools.get_orders("C-1001"), "  ")

    def test_http_error_body_uses_the_same_variant(self):
        body = '{"data": null}'
        self.assertEqual(self.received(body, http_error=True), body + NOTE.format("$.data"))
        self.assertEqual(self.received(body, "baseline", http_error=True), body)

    def test_connection_errors_still_raise(self):
        with patch.dict(os.environ, {"ROI_VARIANT": "flag"}), \
                patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(urllib.error.URLError):
                tools.get_orders("C-1001")


def adapter_instruction(framework):
    """Evaluate the actual instruction argument without importing optional SDKs."""
    tree = ast.parse((ROOT / "agents" / f"{framework}_agent.py").read_text("utf-8"))
    namespace = {"os": os}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("ROLE", "GOAL", "BACKSTORY"):
                    namespace[target.id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.ImportFrom) and node.module == "harness.variants":
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<imports>", "exec"), namespace)
    keyword = {"crewai": "backstory", "langgraph": "system_prompt",
               "openai_agents": "instructions", "adk": "instruction"}[framework]
    values = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
              for kw in node.keywords if kw.arg == keyword]
    if len(values) != 1:
        raise AssertionError(f"expected one {keyword} argument in {framework}")
    return eval(compile(ast.Expression(values[0]), "<instruction>", "eval"), namespace)


class AdapterPrompts(unittest.TestCase):
    ORIGINAL = {
        "crewai": "You work for an online shop and answer colleagues' questions with data from the company API.",
        "langgraph": "You are Operations assistant. You work for an online shop and answer colleagues' questions with data from the company API.\nYour personal goal is: Answer questions about customers, orders and services using the company API tools.",
        "adk": "You are Operations assistant. You work for an online shop and answer colleagues' questions with data from the company API.\nYour personal goal is: Answer questions about customers, orders and services using the company API tools.",
        "openai_agents": "Operations assistant\nAnswer questions about customers, orders and services using the company API tools.\nYou work for an online shop and answer colleagues' questions with data from the company API.",
    }

    def test_baseline_instructions_unchanged(self):
        with patch.dict(os.environ, {"ROI_VARIANT": "baseline"}):
            for framework, original in self.ORIGINAL.items():
                with self.subTest(framework=framework):
                    self.assertEqual(adapter_instruction(framework), original)

    def test_prompt_sentence_at_end_of_all_four_adapters(self):
        with patch.dict(os.environ, {"ROI_VARIANT": "prompt"}):
            for framework, original in self.ORIGINAL.items():
                with self.subTest(framework=framework):
                    self.assertEqual(adapter_instruction(framework), original + "\n" + PROMPT)

    def test_flag_instructions_unchanged(self):
        with patch.dict(os.environ, {"ROI_VARIANT": "flag"}):
            for framework, original in self.ORIGINAL.items():
                with self.subTest(framework=framework):
                    self.assertEqual(adapter_instruction(framework), original)


class RunnerVariants(unittest.TestCase):
    def run_fake(self, variant=None):
        argv = ["run.py", "--framework", "crewai", "--model", "scripted", "--pause", "0"]
        if variant is not None:
            argv += ["--variant", variant]
        seen = []
        catalog = run_script.failure_catalog()
        adapter = SimpleNamespace(VERSION="test", run=lambda *args: seen.append(
            os.environ.get("ROI_VARIANT")) or "answer")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "harness").mkdir()
            (root / "runs").mkdir()
            (root / "harness" / "tasks.json").write_bytes((ROOT / "harness" / "tasks.json").read_bytes())
            with patch.object(run_script, "ROOT", root), \
                    patch.object(run_script, "Services") as services, \
                    patch.object(run_script, "failure_catalog", return_value=catalog), \
                    patch.object(run_script.importlib, "import_module", return_value=adapter), \
                    patch.object(sys, "argv", argv), patch.dict(os.environ, {"ROI_VARIANT": "stale"}), \
                    patch.object(run_script.sys, "stdout"):
                services.return_value.__enter__.return_value.records.return_value = [{
                    "url": "http://127.0.0.1:8001/customers/C-1001/orders",
                    "rule_path": "/customers/C-1001/orders", "failure": "empty_object",
                    "outcome": "applied", "sent_status": 200, "sent_body": "{}",
                }]
                self.assertEqual(run_script.main(), 0)
            files = list((root / "runs").glob("*.jsonl"))
            self.assertEqual(len(files), 1)
            return files[0].name, [json.loads(line) for line in files[0].read_text().splitlines()], seen

    def test_default_baseline_metadata_and_old_filename(self):
        name, records, seen = self.run_fake()
        self.assertTrue(name.endswith("-crewai.jsonl"))
        self.assertEqual({r.get("variant") for r in records}, {"baseline"})
        self.assertEqual(set(seen), {"baseline"})
        self.assertEqual(records[0]["tool_calls"][0]["returned_body"], "{}")

    def test_prompt_and_flag_metadata_filenames_and_unchanged_plan(self):
        for variant in ("prompt", "flag"):
            with self.subTest(variant=variant):
                name, records, seen = self.run_fake(variant)
                self.assertTrue(name.endswith(f"-crewai-{variant}.jsonl"))
                self.assertEqual({r.get("variant") for r in records}, {variant})
                self.assertEqual(set(seen), {variant})
                self.assertEqual(len(records), 28)
                self.assertEqual([r["failure"] for r in records if r["control"]], ["none"])
                call = records[0]["tool_calls"][0]
                self.assertEqual(call["sent_body"], "{}")
                self.assertEqual(call["returned_body"],
                                 "{}" + NOTE.format("$") if variant == "flag" else "{}")

    def test_summary_separates_variants_and_defaults_legacy_to_baseline(self):
        runs = [dict(framework="crewai", model="scripted", failure="none", control=None,
                     signalled=False, run_id=str(i), judge={"label": "correct"}, **extra)
                for i, extra in enumerate(({}, {"variant": "prompt"}, {"variant": "flag"}))]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            judge_script.summarize(runs)
        for variant in ("baseline", "prompt", "flag"):
            self.assertIn(f"== crewai | scripted | {variant} | 1 runs", output.getvalue())


if __name__ == "__main__":
    unittest.main()
