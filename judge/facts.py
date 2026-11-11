"""The facts each task asks for, read two ways: from an API body and from an answer.

From a body: the value the data actually supports, or UNKNOWN when the body
does not contain it (missing field, null, non-JSON).
From an answer: the value the agent states, or absent when it states none.

Rules are deterministic and task-specific on purpose: no model sits in the
measurement loop, so every label can be reproduced exactly.
"""
import json
import re

UNKNOWN = "UNKNOWN"

WORD_NUMBERS = {"no": 0, "zero": 0, "none": 0, "a": 1, "an": 1, "one": 1, "single": 1,
                "a single": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def normalize(text):
    """Plain text: unicode dashes to '-', no markdown emphasis, plain spaces."""
    text = text or ""
    for ch in "‐‑‒–—−":
        text = text.replace(ch, "-")
    for ch in "   ":
        text = text.replace(ch, " ")
    return text.replace("*", "").replace("`", "").replace("’", "'")


def parse_body(text):
    try:
        return json.loads(text) if text else None
    except (json.JSONDecodeError, TypeError):
        return None


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_float(s):
    s = s.rstrip(".,")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):   # 1,240.50
        s = s.replace(",", "")
    else:                                               # 438,9 -> 438.9
        s = s.replace(",", ".")
    return float(s)


def _word_or_int(s):
    s = s.lower().strip()
    return WORD_NUMBERS[s] if s in WORD_NUMBERS else int(s)


# ---------------------------------------------------------------- orders-total

COUNT_RE = re.compile(
    r"(?<![-\w.])(\d+|no|zero|one|two|three|four|five|a single|single)\s+"
    r"(?:[A-Za-z-]+\s+){0,2}?orders?\b", re.I)
COUNT_COLON_RE = re.compile(r"orders?\s*[:=]\s*(\d+)\b", re.I)
MONEY_RE = re.compile(r"€\s*(\d[\d.,]*)|(\d[\d.,]*)\s*(?:€|eur\b|euros?\b)", re.I)


def orders_from_body(body):
    if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
        return {"count": UNKNOWN, "total": UNKNOWN}
    orders = body["orders"]
    totals = [o.get("total_eur") if isinstance(o, dict) else None for o in orders]
    total = round(sum(totals), 2) if all(_is_num(t) for t in totals) else UNKNOWN
    return {"count": len(orders), "total": total}


def orders_from_answer(text):
    text = normalize(text)
    facts = {}
    m = COUNT_RE.search(text) or COUNT_COLON_RE.search(text)
    if m:
        facts["count"] = _word_or_int(m.group(1))
    amounts = [(mm.start(), _to_float(mm.group(1) or mm.group(2)))
               for mm in MONEY_RE.finditer(text)]
    if amounts:
        anchor = re.search(r"total|combined|sum|altogether|in all", text, re.I)
        after = [a for a in amounts if anchor and a[0] >= anchor.start()]
        facts["total"] = (after[0] if after else amounts[-1])[1]
    return facts


# ---------------------------------------------------------------- open-tickets

TICKET_ID_RE = re.compile(r"\bT-\d+\b")
NO_TICKETS_RE = re.compile(
    r"(?:\bno\b|\bzero\b|n't have any|not have any|has no|have no|without any)"
    r"[^.]{0,40}?\btickets?\b|\btickets?\b[^.]{0,20}\bnone\b", re.I)


# On the ID's own line, after it: "T-77: X", "T-77 - X", "ID: T-77 | Subject: X",
# "ID: T-77, Subject: X", "| T-77 | X |". A dash must be followed by a space, so "T-77-X" is not read.
SUBJECT_AFTER_ID_RE = re.compile(
    r"^\s*(?:(?:[:|]|-(?=\s))\s*(?:subject\s*:\s*)?|,?\s*subject\s*:\s*)(?P<s>[^|]*)", re.I)
# "T-77 (X)": the subject in parentheses right after the ID.
SUBJECT_PAREN_RE = re.compile(r"^\s*\((?P<s>[^()]+)\)")
# A parenthesis holding only a status is not a subject: "T-77 (open)", "T-77 (status: open)".
STATUS_PAREN_RE = re.compile(
    r"^\s*\(\s*(?:status\s*:[^)]*|open|pending|closed|resolved|in[ _-]progress)\s*\)", re.I)
# "Ticket ID: T-77" with "Subject: X" on the next line (bullets and bold already gone).
SUBJECT_LINE_RE = re.compile(r"^[\s\-*•]*subject\s*:\s*(?P<s>.+)$", re.I)


def _clean_subject(s):
    s = s.strip().strip(" ,;|").strip().strip("\"'").strip()
    return s.rstrip(".").strip()


def subject_key(s):
    """How two subjects are compared: case-insensitive, trimmed, no quotes, no trailing period."""
    return _clean_subject(s).lower()


def tickets_from_body(body):
    if not isinstance(body, dict) or not isinstance(body.get("open_tickets"), list):
        return {"tickets": UNKNOWN, "subjects": UNKNOWN}
    items = [t if isinstance(t, dict) else {} for t in body["open_tickets"]]
    ids = [t.get("id") for t in items]
    subjects = {t["id"]: t["subject"] for t in items
                if isinstance(t.get("id"), str) and isinstance(t.get("subject"), str)}
    if not all(isinstance(i, str) for i in ids):
        return {"tickets": UNKNOWN, "subjects": subjects}
    return {"tickets": frozenset(ids), "subjects": subjects}


def _same_line_subject(after_id):
    """The subject written right after an ID on the same line ('' if none). `after_id` runs
    from the end of the ID to the next ID or the end of the line; status-only parentheses
    are skipped, then a separator form ("T-77: X", "T-77 - X") or a parenthesis ("T-77 (X)") is read."""
    rest = after_id
    while True:
        m = STATUS_PAREN_RE.match(rest)
        if not m:
            break
        rest = rest[m.end():]
    s = SUBJECT_AFTER_ID_RE.match(rest) or SUBJECT_PAREN_RE.match(rest)
    return _clean_subject(s.group("s")) if s else ""


def _subjects_from_answer(text):
    """{ticket id: subject} for every ID whose subject can be read; others are not stated."""
    lines = text.splitlines()
    subjects = {}
    for n, line in enumerate(lines):
        found = list(TICKET_ID_RE.finditer(line))
        for j, m in enumerate(found):
            end = found[j + 1].start() if j + 1 < len(found) else len(line)
            subject = _same_line_subject(line[m.end():end])
            if not subject and len(found) == 1:
                nxt = next((x for x in lines[n + 1:] if x.strip()), "")
                s = SUBJECT_LINE_RE.match(nxt)
                subject = _clean_subject(s.group("s")) if s else ""
            if subject and m.group() not in subjects:
                subjects[m.group()] = subject
    return subjects


def tickets_from_answer(text):
    text = normalize(text)
    ids = frozenset(TICKET_ID_RE.findall(text))
    if ids:
        subjects = _subjects_from_answer(text)
        return {"tickets": ids, **({"subjects": subjects} if subjects else {})}
    if NO_TICKETS_RE.search(text):
        return {"tickets": frozenset()}
    return {}


# ------------------------------------------------------------- checkout-health

INCIDENT_ID_RE = re.compile(r"\bINC-\d+\b")
NO_INCIDENTS_RE = re.compile(
    r"(?:\bno\b|\bzero\b|n't any|not any|weren't any|were not any|without any)"
    r"[^.]{0,30}?\bincidents?\b|\bincidents?\b[^.]{0,20}\bnone\b", re.I)
INCIDENT_COUNT_RE = re.compile(
    r"(?<![-\w.])(\d+|one|two|three|a single|single|an|a)[ \t]+(?:[A-Za-z-]+[ \t]+){0,2}?incidents?\b",
    re.I)


def health_from_body(body):
    if not isinstance(body, dict):
        return {"error_rate": UNKNOWN, "p95_ms": UNKNOWN, "incidents": UNKNOWN}
    er, p95, inc = body.get("error_rate"), body.get("p95_ms"), body.get("incidents")
    return {
        "error_rate": er if _is_num(er) else UNKNOWN,
        "p95_ms": p95 if _is_num(p95) else UNKNOWN,
        "incidents": len(inc) if isinstance(inc, list) else UNKNOWN,
    }


def health_from_answer(text):
    text = normalize(text)
    facts = {}
    m = re.search(r"error[- ]rate", text, re.I)
    if m:
        window = text[m.end():m.end() + 80]
        pct = re.search(r"(\d+(?:[.,]\d+)?)\s*%", window)
        if pct:
            facts["error_rate"] = _to_float(pct.group(1)) / 100
        else:
            num = re.search(r"(?<![-\w])(\d+(?:\.\d+)?)", window)
            if num:
                v = float(num.group(1))
                facts["error_rate"] = v / 100 if v > 1 else v
    lat = re.search(r"(\d+(?:[.,]\d+)?)\s*(ms\b|milliseconds?|s\b|seconds?)", text, re.I)
    if lat:
        v = _to_float(lat.group(1))
        facts["p95_ms"] = v if lat.group(2).lower().startswith("m") else v * 1000
    ids = set(INCIDENT_ID_RE.findall(text))
    if ids:
        facts["incidents"] = len(ids)
    elif NO_INCIDENTS_RE.search(text):
        facts["incidents"] = 0
    else:
        c = INCIDENT_COUNT_RE.search(text)
        if c:
            facts["incidents"] = _word_or_int(c.group(1))
    return facts


# ---------------------------------------------------------------- registry

TASK_FACTS = {
    "orders-total": (orders_from_body, orders_from_answer),
    "true-empty-orders": (orders_from_body, orders_from_answer),
    "open-tickets": (tickets_from_body, tickets_from_answer),
    "checkout-health": (health_from_body, health_from_answer),
}

TOLERANCE = {"total": 0.01, "error_rate": 1e-4, "p95_ms": 0.5}


def subject_matches(stated, real):
    """A stated subject matches the real one when it contains it, so a trailing note such as
    "(open)" or "- high priority" does not matter. An empty real subject matches nothing."""
    real = subject_key(real)
    return bool(real) and real in subject_key(stated)


def same(key, a, b):
    if a == UNKNOWN or b == UNKNOWN:
        return False
    if key == "subjects":   # every stated subject contains that ticket's real subject in b
        return all(i in b and subject_matches(s, b[i]) for i, s in a.items())
    if key in TOLERANCE and _is_num(a) and _is_num(b):
        return abs(a - b) <= TOLERANCE[key]
    return a == b
