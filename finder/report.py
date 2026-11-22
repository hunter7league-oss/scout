"""Turn ranked firms into an emailable HTML report.

Facts (names, dollar figures, dates, agencies) are rendered from the data by code.
Claude only writes short plain-language notes, and any note containing digits is
discarded, so the AI can never introduce a wrong number.
"""
from __future__ import annotations

import html
import json
import os
import re

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")


def _client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def _ask(prompt: str, max_tokens: int = 800) -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(model=MODEL, max_tokens=max_tokens,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:  # report still goes out without AI notes
        print(f"[warn] Claude call failed: {exc}")
        return None


def work_to_naics(work: str) -> list[str]:
    """Use codes the buyer typed; otherwise ask Claude for up to 3 NAICS codes."""
    typed = re.findall(r"\b\d{6}\b", work)
    if typed:
        return typed[:3]
    answer = _ask(
        "Return ONLY a JSON list of up to 3 six-digit 2022 NAICS codes that best match "
        f"this description of federal contract work: {work!r}"
    )
    codes = re.findall(r"\b\d{6}\b", answer or "")
    return codes[:3]


def firm_notes(work: str, firms: list[dict]) -> dict[str, str]:
    facts = [{"name": f["name"], "agencies": f["agencies"], "example_work": f["largest_desc"]}
             for f in firms]
    answer = _ask(
        "You are helping a small federal contractor choose teaming partners for this work: "
        f"{work!r}.\nFor each firm below, write ONE sentence (max 30 words) on why it may be "
        "a relevant partner, based only on the facts given. Do not use any numbers or digits. "
        "Do not invent facts. Return ONLY a JSON object mapping firm name to sentence.\n"
        + json.dumps(facts),
        max_tokens=1500,
    )
    try:
        notes = json.loads(re.search(r"\{.*\}", answer or "", re.S).group(0))
    except Exception:
        return {}
    return {k: v for k, v in notes.items() if isinstance(v, str) and not re.search(r"\d", v)}


def _money(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}K"
    return f"${x:,.0f}"


def render(order: dict, naics: list[str], firms: list[dict], notes: list[str],
           ai_notes: dict[str, str], business_name: str, footer: str) -> str:
    e = html.escape
    rows = []
    for i, f in enumerate(firms, 1):
        why = ai_notes.get(f["name"]) or (
            f"Has {f['award_count']} federal award(s) under the same industry code"
            + (f", mainly with {f['agencies'][0]}." if f["agencies"] else "."))
        link = (f'<a href="{e(f["profile_url"])}">Award history</a>' if f["profile_url"] else "")
        sam = ("https://sam.gov/search/?index=ei&q=" + e(f["name"]).replace(" ", "+"))
        rows.append(f"""
<tr><td style="padding:12px 8px;border-bottom:1px solid #e5e5e5;vertical-align:top">
<b>{i}. {e(f['name'])}</b><br>
<span style="color:#555">{e(why)}</span><br>
<span style="font-size:13px;color:#333">
{f['award_count']} award(s) &middot; {_money(f['total'])} total &middot; largest {_money(f['largest'])}
&middot; latest end date {e(f['latest_end'] or 'n/a')}<br>
Agencies: {e(', '.join(f['agencies']) or 'n/a')} &middot; Work locations: {e(', '.join(f['states']) or 'n/a')}<br>
Largest award: {e(f['largest_desc'] or 'no description listed')}<br>
{link} &middot; <a href="{sam}">Find contact details on SAM.gov</a>
</span></td></tr>""")

    note_html = "".join(f"<p style='color:#8a5a00'>Note: {e(n)}</p>" for n in notes)
    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;max-width:680px;margin:auto;color:#111">
<h2 style="margin-bottom:4px">{e(business_name)} partner shortlist</h2>
<p style="color:#555;margin-top:0">For: {e(order['work'])}<br>
Industry codes searched: {e(', '.join(naics))} &middot; Location: {e(order.get('state') or 'All states')}
&middot; Certification: {e(order.get('cert') or 'Any')}</p>
{note_html}
<p>These firms won federal contracts for this kind of work in the last five years, ranked by number of awards.
Use the SAM.gov link on each to find its listed point of contact.</p>
<table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>
<h3>How to approach them</h3>
<ul>
<li>Lead with the specific opportunity, its deadline and what share of the work you propose.</li>
<li>Name the certification or capability you bring that they lack.</li>
<li>Ask for a 20-minute call this week; firms decide on teaming quickly once a solicitation is out.</li>
</ul>
<p style="font-size:12px;color:#777">Source: USAspending.gov public award records. Award values are the
obligated amounts reported to USAspending and may include options. {e(business_name)} is independent and not
affiliated with any government agency. Inclusion here does not mean a firm is available or interested.<br>{e(footer)}</p>
</body></html>"""
