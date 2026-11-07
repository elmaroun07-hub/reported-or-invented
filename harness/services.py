"""Start and stop the mock API and the injection proxy; set scenarios; read the log."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Services:
    """Context manager: mock API + mitmdump in reverse mode, ready on exit of __enter__."""

    def __init__(self, scenario_path: Path, injection_log: Path,
                 mock_port: int = 8001, proxy_port: int = 8000):
        self.scenario_path = Path(scenario_path)
        self.injection_log = Path(injection_log)
        self.mock_port = mock_port
        self.proxy_port = proxy_port
        self._procs = []

    def __enter__(self):
        self.scenario_path.parent.mkdir(parents=True, exist_ok=True)
        self.set_scenario("startup", [])
        self._procs.append(subprocess.Popen(
            [sys.executable, str(ROOT / "mock_api" / "server.py"), "--port", str(self.mock_port)],
            stdout=subprocess.DEVNULL))
        self._procs.append(subprocess.Popen([
            sys.executable, "-c", "from mitmproxy.tools.main import mitmdump; mitmdump()",
            "--mode", f"reverse:http://127.0.0.1:{self.mock_port}",
            "--listen-host", "127.0.0.1", "-p", str(self.proxy_port),
            "-s", str(ROOT / "inject" / "addon.py"),
            "--set", f"scenario={self.scenario_path}",
            "--set", f"injection_log={self.injection_log}",
            "-q",
        ]))
        deadline = time.time() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.proxy_port}/health", timeout=2) as r:
                    if r.status == 200:
                        return self
            except OSError:
                pass
            if time.time() > deadline:
                self.__exit__(None, None, None)
                raise RuntimeError("mock API or proxy did not start within 30 s")
            time.sleep(0.5)

    def __exit__(self, *exc):
        for p in self._procs:
            p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        self._procs = []

    def set_scenario(self, run_id: str, rules: list) -> None:
        self.scenario_path.write_text(json.dumps({"run_id": run_id, "rules": rules}),
                                      encoding="utf-8")

    def records(self, run_id: str) -> list:
        """Every proxied call logged for this run, in order."""
        if not self.injection_log.exists():
            return []
        out = []
        for line in self.injection_log.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("run_id") == run_id:
                out.append(rec)
        return out
