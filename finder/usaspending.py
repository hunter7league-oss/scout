"""Find firms that have won federal contracts for a given kind of work.

Data source: USAspending.gov public API (no key needed).
Docs: https://api.usaspending.gov/docs/endpoints
"""
from __future__ import annotations

import datetime as dt
import time
import re
from collections import Counter, defaultdict

import requests

API = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
CONTRACT_TYPES = ["A", "B", "C", "D"]  # definitive contracts, POs, delivery/task orders, BPA calls
FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Start Date",
    "End Date",
    "Description",
    "Place of Performance State Code",
    "recipient_id",
]

# Dropdown value on the order form -> USAspending recipient business category.
CERTIFICATIONS = {
    "Any": None,
    "Small business": "small_business",
    "Woman-owned": "woman_owned_business",
    "Service-disabled veteran-owned": "service_disabled_veteran_owned_business",
    "8(a)": "8a_program_participant",
    "HUBZone": "historically_underutilized_business_firm",
}


def _post(payload: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = requests.post(API, json=payload, timeout=60)
        if r.status_code in (400, 422):
            raise ValueError(f"USAspending rejected the query: {r.text[:300]}")
        if r.ok:
            return r.json()
        time.sleep(2 ** attempt * 3)
    r.raise_for_status()
    return {}


def search_awards(naics: list[str], state: str | None, certification: str | None,
                  years: int = 5, max_pages: int = 3) -> list[dict]:
    today = dt.date.today()
    filters: dict = {
        "award_type_codes": CONTRACT_TYPES,
        "naics_codes": {"require": naics},
        "time_period": [{
            "start_date": (today - dt.timedelta(days=365 * years)).isoformat(),
            "end_date": today.isoformat(),
        }],
    }
    if state:
        filters["place_of_performance_locations"] = [{"country": "USA", "state": state}]
    if certification:
        filters["recipient_type_names"] = [certification]

    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        data = _post({"filters": filters, "fields": FIELDS, "limit": 100, "page": page,
                      "sort": "Award Amount", "order": "desc"})
        rows.extend(data.get("results", []))
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        time.sleep(1)
    return rows


def _clean(desc: str | None) -> str:
    """Strip procurement-system prefixes such as 'IGF::OT::IGF' from award descriptions."""
    text = re.sub(r"^(?:IGF::\w+::IGF\s*)+", "", (desc or "").strip())
    return text.strip(" -:")


def rank_firms(rows: list[dict], top: int = 10) -> list[dict]:
    """Group awards by firm; rank by number of awards, then total value."""
    firms: dict[str, dict] = defaultdict(lambda: {"awards": [], "agencies": Counter(), "states": set()})
    for r in rows:
        name = (r.get("Recipient Name") or "").strip()
        if not name or name.upper() in {"MULTIPLE RECIPIENTS", "REDACTED DUE TO PII"}:
            continue
        f = firms[name.upper()]
        f["name"] = name
        f["recipient_id"] = r.get("recipient_id")
        f["awards"].append(r)
        if r.get("Awarding Agency"):
            f["agencies"][r["Awarding Agency"]] += 1
        if r.get("Place of Performance State Code"):
            f["states"].add(r["Place of Performance State Code"])

    out = []
    for f in firms.values():
        amounts = [float(a.get("Award Amount") or 0) for a in f["awards"]]
        ends = sorted(a.get("End Date") or "" for a in f["awards"])
        best = max(f["awards"], key=lambda a: float(a.get("Award Amount") or 0))
        out.append({
            "name": f["name"],
            "recipient_id": f["recipient_id"],
            "award_count": len(f["awards"]),
            "total": sum(amounts),
            "largest": max(amounts) if amounts else 0,
            "largest_desc": _clean(best.get("Description"))[:200],
            "latest_end": ends[-1] if ends else "",
            "agencies": [a for a, _ in f["agencies"].most_common(3)],
            "states": sorted(f["states"])[:5],
            "profile_url": (f"https://www.usaspending.gov/recipient/{f['recipient_id']}/latest"
                            if f["recipient_id"] else None),
        })
    out.sort(key=lambda x: (x["award_count"], x["total"]), reverse=True)
    return out[:top]


def find_partners(naics: list[str], state: str | None, cert_label: str) -> tuple[list[dict], list[str]]:
    """Return ranked firms plus notes on any broadening done to reach 5+ firms."""
    cert = CERTIFICATIONS.get(cert_label)
    notes: list[str] = []
    attempts = [(state, cert)]
    if state:
        attempts.append((None, cert))
    if cert:
        attempts.append((None, None))

    firms: list[dict] = []
    for i, (st, ce) in enumerate(attempts):
        try:
            firms = rank_firms(search_awards(naics, st, ce))
        except ValueError:
            if ce:  # unknown category name: retry without it
                notes.append("The certification filter could not be applied, so all firm types are shown.")
                firms = rank_firms(search_awards(naics, st, None))
            else:
                raise
        if len(firms) >= 5:
            if i > 0 and st is None and state:
                notes.append(f"Fewer than 5 firms had work in {state}, so the search covers all states.")
            if i > 0 and ce is None and cert:
                notes.append(f"Fewer than 5 firms matched the '{cert_label}' filter, so all firm types are shown.")
            break
    return firms, notes
