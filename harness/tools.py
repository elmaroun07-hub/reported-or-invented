"""HTTP tools shared by every framework adapter.

Each tool calls the API through the injection proxy. Baseline and prompt return
the body exactly as received, whatever the status code: the common
"return response.text" pattern. So the framework never sees an exception for
an HTTP error; a failure reaches the model only through what the body says.
The flag variant appends a descriptive note for missing or unreadable data.

Connection errors (proxy or mock down) are raised on purpose: they are
infrastructure faults, not test conditions, and must not be scored.
"""
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote


def _missing_paths(value, path="$"):
    if value is None or value == [] or value == {}:
        return [path]
    paths = []
    if isinstance(value, dict):
        for key, item in value.items():
            suffix = "." + key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else f"[{json.dumps(key)}]"
            paths.extend(_missing_paths(item, path + suffix))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_missing_paths(item, f"{path}[{index}]"))
    return paths


def _invalid_constant(value):
    # Python accepts NaN/Infinity by default, but they are not valid JSON.
    raise ValueError(f"invalid JSON constant: {value}")


def tool_output(body: str) -> str:
    """Preserve the body; only the flag arm appends a descriptive missing-data note.

    Also used by the runner to record the model-visible text alongside the raw
    proxy body. The raw body remains the input to the unchanged fact judge.
    """
    if os.environ.get("ROI_VARIANT", "baseline") != "flag":
        return body
    try:
        value = json.loads(body, parse_constant=_invalid_constant)
    except ValueError:
        paths = ["whole body"]
    else:
        paths = _missing_paths(value)
    if paths:
        return body + "\n\n[tool note] The API returned no data at: " + ", ".join(paths) + "."
    return body


def _get(path: str) -> str:
    base = os.environ.get("ROI_API_BASE", "http://127.0.0.1:8000")
    try:
        with urllib.request.urlopen(base + path, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
    return tool_output(body)


def get_customer(customer_id: str) -> str:
    """Look up a customer record by customer ID (e.g. C-1001): name, plan, balance in EUR and open support tickets."""
    return _get(f"/customers/{quote(customer_id)}")


def get_orders(customer_id: str) -> str:
    """List a customer's orders by customer ID (e.g. C-1001): order ID, date, total in EUR and status."""
    return _get(f"/customers/{quote(customer_id)}/orders")


def get_service_metrics(service: str) -> str:
    """Get the last hour of metrics for a service (e.g. checkout): requests, error rate, p95 latency in ms and incidents."""
    return _get(f"/services/{quote(service)}/metrics")


TOOLS = [get_customer, get_orders, get_service_metrics]
