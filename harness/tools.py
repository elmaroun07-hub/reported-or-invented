"""HTTP tools shared by every framework adapter.

Each tool calls the API through the injection proxy and returns the response
body exactly as received, whatever the status code: the common
"return response.text" pattern. So the framework never sees an exception for
an HTTP error; a failure reaches the model only through what the body says.

Connection errors (proxy or mock down) are raised on purpose: they are
infrastructure faults, not test conditions, and must not be scored.
"""
import os
import urllib.error
import urllib.request
from urllib.parse import quote


def _get(path: str) -> str:
    base = os.environ.get("ROI_API_BASE", "http://127.0.0.1:8000")
    try:
        with urllib.request.urlopen(base + path, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace")


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
