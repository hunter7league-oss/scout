"""Offline checks: ranking, order parsing and report rendering with fake data."""
from finder import main, report, usaspending

ROWS = [
    {"Recipient Name": f"Firm {c}", "recipient_id": f"id-{c}", "Award Amount": amt,
     "Awarding Agency": agency, "End Date": end, "Description": "SITE REMEDIATION SERVICES",
     "Place of Performance State Code": "VA"}
    for c, amt, agency, end in [
        ("A", 1_200_000, "Department of Defense", "2026-03-01"),
        ("A", 300_000, "Department of Energy", "2027-01-15"),
        ("B", 5_000_000, "Department of Defense", "2025-12-31"),
        ("C", 80_000, "Environmental Protection Agency", "2026-06-30"),
        ("D", 45_000, "Department of the Interior", "2026-09-30"),
        ("E", 2_500, "Department of Agriculture", "2025-11-01"),
        ("F", 999_000, "Department of Defense", "2028-02-01"),
    ]
] + [{"Recipient Name": "MULTIPLE RECIPIENTS", "Award Amount": 1}]


def test_rank():
    firms = usaspending.rank_firms(ROWS)
    assert firms[0]["name"] == "Firm A" and firms[0]["award_count"] == 2
    assert firms[0]["latest_end"] == "2027-01-15"
    assert all(f["name"] != "MULTIPLE RECIPIENTS" for f in firms)
    assert len(firms) == 6


def test_parse_order():
    session = {"customer_details": {"email": "x@example.com"}, "custom_fields": [
        {"key": "work", "type": "text", "text": {"value": " soil remediation 562910 "}},
        {"key": "state", "type": "text", "text": {"value": "va"}},
        {"key": "certification", "type": "dropdown", "dropdown": {"value": "sdvosb"}},
    ]}
    o = main.parse_order(session)
    assert o == {"work": "soil remediation 562910", "state": "VA",
                 "cert": "Service-disabled veteran-owned", "email": "x@example.com"}
    assert report.work_to_naics(o["work"]) == ["562910"]


def test_render_and_digit_guard(monkeypatch):
    firms = usaspending.rank_firms(ROWS)
    monkeypatch.setattr(report, "_ask", lambda *a, **k:
                        '{"Firm A": "Works for defense and energy clients.", "Firm B": "Won 3 awards."}')
    notes = report.firm_notes("remediation", firms)
    assert "Firm A" in notes and "Firm B" not in notes  # sentence with digits dropped
    html = report.render({"work": "remediation", "state": "VA", "cert": "Any"}, ["562910"],
                         firms, ["test note"], notes, "TeamingScout", "123 Main St")
    assert "$1.5M total" in html and "Works for defense" in html and "SAM.gov" in html
    open("/tmp/preview.html", "w").write(html)


def test_dashboard_style_fields():
    session = {"customer_details": {"email": "y@example.com"}, "custom_fields": [
        {"key": "describetheworkyourebiddingon", "type": "text",
         "label": {"custom": "Describe the work you're bidding on (or NAICS code)"},
         "text": {"value": "drone mapping"}},
        {"key": "stateofthework", "type": "text", "label": {"custom": "State of the work"},
         "text": {"value": ""}},
        {"key": "partnercertification", "type": "dropdown", "label": {"custom": "Partner certification"},
         "dropdown": {"value": "womanownedsmallbusiness"}},
    ]}
    o = main.parse_order(session)
    assert o["work"] == "drone mapping" and o["state"] is None and o["cert"] == "Woman-owned"


def test_clean_and_agency_order():
    assert usaspending._clean("IGF::OT::IGF REMEDIAL ACTION") == "REMEDIAL ACTION"
    rows = [{"Recipient Name": "X", "Award Amount": 1, "Awarding Agency": a} for a in
            ["Department of the Interior", "Environmental Protection Agency", "Environmental Protection Agency"]]
    assert usaspending.rank_firms(rows)[0]["agencies"][0] == "Environmental Protection Agency"


def test_claude_failure_does_not_look_like_no_match(monkeypatch):
    import pytest
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        report.work_to_naics("soil cleanup")
    assert report.work_to_naics("soil cleanup 562910") == ["562910"]
