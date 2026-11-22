"""Build free, search-friendly industry pages from live USAspending data.

One page per industry code: the small-business firms with the most federal awards in
the last five years, refreshed weekly by GitHub Actions. Each page links to the paid
custom shortlist. Also writes /industries/ (an index), sitemap.xml and robots.txt,
then notifies search engines through IndexNow (no account needed).

Run: python -m finder.pages
"""
from __future__ import annotations

import datetime as dt
import html
import os
import time

import requests

from finder import usaspending

SITE = "https://teamingscout.com"
BUY = os.environ.get("BUY_URL", "https://buy.stripe.com/eVq28tbnTcFy1Ig27O08g00")
INDEXNOW_KEY = "6f3b1c9e2a7d4e8f9b0c1d2e3f4a5b6c"

INDUSTRIES = {
    "541330": "Engineering Services",
    "541511": "Custom Computer Programming",
    "541512": "Computer Systems Design",
    "541513": "Computer Facilities Management",
    "541519": "Other Computer Related Services",
    "518210": "Data Processing and Web Hosting",
    "541611": "Management Consulting",
    "541618": "Other Management Consulting",
    "541620": "Environmental Consulting",
    "541690": "Scientific and Technical Consulting",
    "541715": "Research and Development (Physical, Engineering, Life Sciences)",
    "541720": "Research and Development (Social Sciences)",
    "541810": "Advertising Agencies",
    "541930": "Translation and Interpretation",
    "541990": "Other Professional, Scientific and Technical Services",
    "541380": "Testing Laboratories",
    "541370": "Surveying and Mapping",
    "541360": "Geophysical Surveying and Mapping",
    "541310": "Architectural Services",
    "561210": "Facilities Support Services",
    "561320": "Temporary Help Services",
    "561612": "Security Guards and Patrol Services",
    "561720": "Janitorial Services",
    "561730": "Landscaping Services",
    "562111": "Solid Waste Collection",
    "562910": "Environmental Remediation Services",
    "562211": "Hazardous Waste Treatment and Disposal",
    "236220": "Commercial and Institutional Building Construction",
    "237310": "Highway, Street and Bridge Construction",
    "237990": "Other Heavy and Civil Engineering Construction",
    "238210": "Electrical Contractors",
    "238220": "Plumbing, Heating and Air-Conditioning Contractors",
    "238160": "Roofing Contractors",
    "238990": "Other Specialty Trade Contractors",
    "611430": "Professional and Management Training",
    "611710": "Educational Support Services",
    "621999": "Other Ambulatory Health Care Services",
    "488190": "Air Transportation Support",
    "488510": "Freight Transportation Arrangement",
    "493110": "General Warehousing and Storage",
    "811310": "Commercial and Industrial Machinery Repair",
}

STYLE = """
  :root { --ink:#14202b; --muted:#5b6670; --line:#e3e6e8; --accent:#1f6f5c; --bg:#fbfaf7; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:Georgia,'Times New Roman',serif; color:var(--ink); background:var(--bg); line-height:1.55; }
  .wrap { max-width:860px; margin:0 auto; padding:0 24px; }
  header { padding:28px 0 0; font-family:Arial,sans-serif; font-weight:700; }
  header a { color:var(--ink); text-decoration:none; }
  h1 { font-size:34px; line-height:1.2; font-weight:400; margin:40px 0 12px; }
  .lead { color:var(--muted); font-size:18px; }
  table { width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px; margin:24px 0; }
  th, td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:var(--muted); font-weight:600; }
  td.num, th.num { text-align:right; white-space:nowrap; }
  .cta { display:inline-block; margin:8px 0; padding:13px 24px; background:var(--accent); color:#fff;
         text-decoration:none; font-family:Arial,sans-serif; font-weight:700; border-radius:6px; }
  .box { border:1px solid var(--line); background:#fff; border-radius:8px; padding:20px; margin:28px 0; }
  .fine { font-family:Arial,sans-serif; font-size:12px; color:var(--muted); }
  ul.cols { columns:2; font-family:Arial,sans-serif; font-size:15px; padding-left:18px; }
  a { color:var(--accent); }
"""


def usaspending_money(x: float) -> str:
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}K"
    return f"${x:,.0f}"


def page(title: str, desc: str, path: str, body: str) -> str:
    e = html.escape
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE}{path}">
<style>{STYLE}</style></head>
<body><div class="wrap">
<header><a href="/">TeamingScout</a></header>
{body}
<p class="fine" style="margin:48px 0 40px">Data: USAspending.gov public award records (contracts, last five years).
TeamingScout is independent and not affiliated with any government agency. Listing does not mean a firm is
available or endorses this site. Questions: <a href="mailto:reports@teamingscout.com">reports@teamingscout.com</a></p>
</div></body></html>"""


def industry_page(code: str, label: str, firms: list[dict], updated: str) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{i}</td><td>{e(f['name'])}"
        + (f' · <a href="{e(f["profile_url"])}">awards</a>' if f["profile_url"] else "")
        + f"</td><td class='num'>{f['award_count']}</td><td class='num'>{usaspending_money(f['total'])}</td>"
        f"<td>{e(', '.join(f['agencies'][:2]) or '—')}</td><td>{e(f['latest_end'] or '—')}</td></tr>"
        for i, f in enumerate(firms, 1)
    )
    cta = f"""<div class="box"><b>Bidding on {e(label.lower())} work?</b><br>
Get a shortlist built for your bid: filtered by state and certification (small business, WOSB, SDVOSB, 8(a), HUBZone),
with each firm's award history and where to find its contacts. Delivered by email in about an hour.<br>
<a class="cta" href="{BUY}">Get a custom shortlist · $49</a><br>
<span class="fine">Full refund if we find fewer than 5 firms. <a href="/sample.html">See a sample report</a>.</span></div>"""
    body = f"""<h1>Small-business federal contractors in {e(label)} (NAICS {code})</h1>
<p class="lead">Small businesses behind the largest federal contract awards under NAICS {code} in the last five
years, ranked by how many of those awards they won. Use it to find teaming partners and subcontractors for your next bid.
Updated {updated}.</p>
{cta}
<table><thead><tr><th>#</th><th>Firm</th><th class="num">Awards</th><th class="num">Total obligated</th>
<th>Main agencies</th><th>Latest contract end</th></tr></thead><tbody>{rows}</tbody></table>
<p class="fine">Award values are obligated amounts reported to USAspending.gov and may include options.
"Latest contract end" helps spot work that may be recompeted soon.</p>
<p><a href="/industries/">Browse all industries</a></p>"""
    return page(f"Top small-business federal contractors: {label} (NAICS {code}) | TeamingScout",
                f"Small businesses with the most federal contract awards in {label} (NAICS {code}), "
                f"from USAspending.gov data. Find teaming partners and subcontractors.",
                f"/industries/{code}.html", body)


def index_page(built: dict[str, str], updated: str) -> str:
    items = "".join(f'<li><a href="/industries/{c}.html">{html.escape(l)}</a> <span class="fine">{c}</span></li>'
                    for c, l in sorted(built.items(), key=lambda kv: kv[1]))
    body = f"""<h1>Find federal teaming partners by industry</h1>
<p class="lead">Free lists of small businesses winning large federal contracts in each industry, from public
USAspending.gov data. Updated {updated}.</p>
<ul class="cols">{items}</ul>
<div class="box">Need partners for a specific bid, state or certification?
<a class="cta" href="{BUY}">Get a custom shortlist · $49</a></div>"""
    return page("Federal teaming partners by industry | TeamingScout",
                "Free lists of small businesses winning federal contracts, by NAICS industry code.",
                "/industries/", body)


def ping_indexnow(urls: list[str]) -> None:
    try:
        r = requests.post("https://api.indexnow.org/indexnow", timeout=30, json={
            "host": "teamingscout.com", "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE}/{INDEXNOW_KEY}.txt", "urlList": urls})
        print(f"IndexNow: HTTP {r.status_code}")
    except Exception as exc:
        print(f"[warn] IndexNow ping failed: {exc}")


def main() -> None:
    updated = dt.date.today().strftime("%B %-d, %Y")
    os.makedirs("docs/industries", exist_ok=True)
    built: dict[str, str] = {}
    for code, label in INDUSTRIES.items():
        try:
            firms = usaspending.rank_firms(
                usaspending.search_awards([code], None, "small_business", max_pages=2), top=15)
        except Exception as exc:
            print(f"[warn] {code}: {exc}")
            continue
        if len(firms) < 5:
            print(f"skip {code}: only {len(firms)} firms")
            continue
        with open(f"docs/industries/{code}.html", "w", encoding="utf-8") as fh:
            fh.write(industry_page(code, label, firms, updated))
        built[code] = label
        print(f"built {code} ({len(firms)} firms)")
        time.sleep(1)

    with open("docs/industries/index.html", "w", encoding="utf-8") as fh:
        fh.write(index_page(built, updated))

    urls = [f"{SITE}/", f"{SITE}/sample.html", f"{SITE}/industries/"] + \
           [f"{SITE}/industries/{c}.html" for c in built]
    today = dt.date.today().isoformat()
    with open("docs/sitemap.xml", "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 + "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
                 + "</urlset>\n")
    with open("docs/robots.txt", "w", encoding="utf-8") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    with open(f"docs/{INDEXNOW_KEY}.txt", "w", encoding="utf-8") as fh:
        fh.write(INDEXNOW_KEY)
    print(f"Built {len(built)} industry pages")
    if os.environ.get("PING_SEARCH") == "true":
        ping_indexnow(urls)


if __name__ == "__main__":
    main()
