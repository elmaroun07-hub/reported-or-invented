"""Smoke test: mock API + failure injection, no model involved.

Starts the mock API and mitmdump (reverse proxy), applies every failure in the
catalog to one endpoint, and checks what a tool would receive. Also checks that
unmatched paths pass untouched and that every matched response is logged.

Run from the project root:  python scripts/smoke_test.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK_PORT = int(os.environ.get("ROI_MOCK_PORT", 8001))
PROXY_PORT = int(os.environ.get("ROI_PROXY_PORT", 8000))
SCENARIO = ROOT / "runs" / "smoke-scenario.json"
LOG = ROOT / "runs" / "smoke-injections.jsonl"
TARGET = "/customers/C-1001/orders"


def get(path):
    """GET through the proxy; return (status, raw body)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PROXY_PORT}{path}", timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def set_scenario(failure, run_id):
    SCENARIO.write_text(json.dumps({
        "run_id": run_id,
        "rules": [{"method": "GET", "path": "/customers/*/orders", "failure": failure}],
    }), encoding="utf-8")


def body(raw):
    return json.loads(raw) if raw else None


CHECKS = {
    "none": lambda s, b: s == 200 and len(b["orders"]) == 2,
    "empty_list": lambda s, b: s == 200 and b["orders"] == [] and b["customer_id"] == "C-1001",
    "truncate": lambda s, b: s == 200 and len(b["orders"]) == 1,
    "null_fields": lambda s, b: s == 200 and b["customer_id"] is None
                                and b["orders"][0]["total_eur"] is None,
    "zero_values": lambda s, b: s == 200 and b["orders"][0]["total_eur"] == 0
                                and b["orders"][0]["id"] == "O-5501",
    "empty_object": lambda s, b: s == 200 and b == {},
    "empty_body": lambda s, b: s == 200 and b is None,
    "http_500": lambda s, b: s == 500,
    "error_field": lambda s, b: s == 200 and b["status"] == "error",
}


def main():
    SCENARIO.parent.mkdir(parents=True, exist_ok=True)
    LOG.unlink(missing_ok=True)
    set_scenario("none", "smoke-start")

    mock = subprocess.Popen([sys.executable, str(ROOT / "mock_api" / "server.py"),
                             "--port", str(MOCK_PORT)])
    proxy = subprocess.Popen([
        sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()",
        "--mode", f"reverse:http://127.0.0.1:{MOCK_PORT}",
        "--listen-host", "127.0.0.1", "-p", str(PROXY_PORT),
        "-s", str(ROOT / "inject" / "addon.py"),
        "--set", f"scenario={SCENARIO}",
        "--set", f"injection_log={LOG}",
        "-q",
    ])
    failed = 0
    try:
        deadline = time.time() + 30
        while True:
            try:
                if get("/health")[0] == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                print("FAIL proxy or mock did not start within 30 s")
                return 1
            time.sleep(0.5)

        for failure, check in CHECKS.items():
            set_scenario(failure, f"smoke-{failure}")
            status, raw = get(TARGET)
            try:
                ok = check(status, body(raw))
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                ok = False
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'} {failure:13} -> {status} {raw[:70]!r}")

        # Controls: unmatched path untouched; a genuinely empty history stays empty.
        set_scenario("empty_object", "smoke-unmatched")
        status, raw = get("/customers/C-1001")
        ok = status == 200 and body(raw)["name"] == "Amina Haddad"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} unmatched path untouched")

        set_scenario("none", "smoke-true-empty")
        status, raw = get("/customers/C-1003/orders")
        ok = status == 200 and body(raw)["orders"] == []
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} genuinely empty history passes as []")

        time.sleep(0.5)
        records = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines()]
        matched = [r for r in records if r["run_id"] != "smoke-unmatched"]
        expected = len(CHECKS) + 1  # each failure + the true-empty passthrough
        ok = (len(matched) == expected
              and all(r["outcome"] in ("applied", "passthrough") for r in matched)
              and not any(r["run_id"] == "smoke-unmatched" for r in records))
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} injection log: {len(records)} records, expected {expected}")
    finally:
        proxy.terminate()
        mock.terminate()
        proxy.wait(timeout=10)
        mock.wait(timeout=10)

    print(f"\n{'ALL PASS' if not failed else f'{failed} FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
