"""Order loop: find paid Stripe orders, build reports, email them, mark them done.

Run every 15 minutes by GitHub Actions. Safe to re-run: each order is marked on its
Stripe PaymentIntent (metadata report_status) so it is never processed twice.

Modes:
  python -m finder.main            process new paid orders
  python -m finder.main --sample "environmental remediation 562910" VA
                                   write docs/sample.html from live data (no Stripe, no email)
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import time
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from finder import report, usaspending

BUSINESS = os.environ.get("BUSINESS_NAME") or "TeamingScout"
OWNER = os.environ.get("OWNER_EMAIL", "")
FOOTER = os.environ.get("BUSINESS_ADDRESS", "")
AUTO_REFUND = (os.environ.get("AUTO_REFUND") or "false").lower() == "true"
MAX_ATTEMPTS = 3


def env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Missing required setting: {name}")
    return val


# ---------- email ----------
def send_email(to: str, subject: str, html_body: str, bcc_owner: bool = True) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    sender = os.environ.get("FROM_EMAIL") or env("SMTP_USER")
    msg["From"] = f"{BUSINESS} <{sender}>"
    msg["To"] = to
    if OWNER:
        msg["Reply-To"] = OWNER
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    rcpts = [to] + ([OWNER] if bcc_owner and OWNER and OWNER != to else [])
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(env("SMTP_USER"), env("SMTP_PASS"))
        s.sendmail(sender, rcpts, msg.as_string())


def alert_owner(subject: str, text: str) -> None:
    print(f"[alert] {subject}\n{text}")
    if OWNER:
        try:
            send_email(OWNER, f"[{BUSINESS}] {subject}", f"<pre>{text}</pre>", bcc_owner=False)
        except Exception as exc:
            print(f"[warn] could not email owner: {exc}")


# ---------- orders ----------
def plain(obj) -> dict:
    """Turn a Stripe object into plain nested dicts (newer SDKs drop dict methods)."""
    if isinstance(obj, dict) and not hasattr(obj, "to_dict"):
        return obj
    return json.loads(str(obj))


def custom_fields(session) -> dict:
    """Map Stripe custom fields to work/state/certification.

    Matches on the field key or its label, so it works whether the Payment Link was
    made in the Dashboard (auto-generated keys) or through the API.
    """
    out = {}
    for f in session.get("custom_fields") or []:
        kind = f.get("type")
        val = ((f.get(kind) or {}).get("value") or "").strip()
        label = ((f.get("label") or {}).get("custom") or "")
        tag = f"{f.get('key', '')} {label}".lower()
        if "cert" in tag:
            out["certification"] = val
        elif "state" in tag:
            out["state"] = val
        elif "work" in tag or "naics" in tag:
            out["work"] = val
    return out


def parse_order(session) -> dict:
    cf = custom_fields(session)
    state = (cf.get("state") or "").upper()[:2]
    c = "".join(ch for ch in (cf.get("certification") or "").lower() if ch.isalnum())
    if "veteran" in c or "sdvosb" in c:
        cert = "Service-disabled veteran-owned"
    elif "wom" in c or "wosb" in c:
        cert = "Woman-owned"
    elif "hubzone" in c:
        cert = "HUBZone"
    elif c.startswith("8a"):
        cert = "8(a)"
    elif "small" in c:
        cert = "Small business"
    else:
        cert = "Any"
    return {
        "work": cf.get("work") or "",
        "state": state if state.isalpha() and len(state) == 2 else None,
        "cert": cert,
        "email": (session.get("customer_details") or {}).get("email"),
    }


def build(order: dict) -> tuple[str | None, int, list[str]]:
    naics = report.work_to_naics(order["work"])
    if not naics:
        return None, 0, ["Could not identify an industry code for the work described."]
    firms, notes = usaspending.find_partners(naics, order["state"], order["cert"])
    if len(firms) < 5:
        return None, len(firms), notes
    ai = report.firm_notes(order["work"], firms)
    return report.render(order, naics, firms, notes, ai, BUSINESS, FOOTER), len(firms), notes


def process_orders() -> int:
    import stripe
    stripe.api_key = env("STRIPE_KEY")
    link = env("STRIPE_PAYMENT_LINK_ID")
    # A live key automatically uses the live payment link, so switching to live mode
    # only means replacing STRIPE_KEY.
    if stripe.api_key.startswith(("rk_live_", "sk_live_")) and os.environ.get("STRIPE_PAYMENT_LINK_ID_LIVE"):
        link = os.environ["STRIPE_PAYMENT_LINK_ID_LIVE"]
    print(f"Stripe mode: {'LIVE' if '_live_' in stripe.api_key else 'TEST'}")
    since = int(time.time()) - 7 * 24 * 3600
    handled = 0

    for s in stripe.checkout.Session.list(payment_link=link, status="complete",
                                          created={"gte": since}, limit=100,
                                          expand=["data.payment_intent"]).auto_paging_iter():
        s = plain(s)
        if s.get("payment_status") != "paid" or not s.get("payment_intent"):
            continue
        pi = s["payment_intent"]
        meta = pi.get("metadata") or {}
        if meta.get("report_status") in ("sent", "refunded", "manual"):
            continue
        attempts = int(meta.get("report_attempts") or 0)
        if attempts >= MAX_ATTEMPTS:
            stripe.PaymentIntent.modify(pi["id"], metadata={"report_status": "manual"})
            alert_owner("Order needs a person", f"Order {s['id']} failed {attempts} times.")
            continue

        order = parse_order(s)
        try:
            body, n, notes = build(order)
            if body:
                send_email(order["email"], f"Your {BUSINESS} partner shortlist", body)
                stripe.PaymentIntent.modify(pi["id"], metadata={"report_status": "sent", "firms": str(n)})
            elif AUTO_REFUND:
                stripe.Refund.create(payment_intent=pi["id"])
                send_email(order["email"], f"{BUSINESS}: refund issued",
                           f"<p>We found only {n} firm(s) with matching federal awards for "
                           f"&ldquo;{order['work']}&rdquo;, below our 5-firm minimum, so we have refunded "
                           f"your payment in full. Reply to this email if you'd like to try a different "
                           f"description.</p><p>{' '.join(notes)}</p>")
                stripe.PaymentIntent.modify(pi["id"], metadata={"report_status": "refunded"})
            else:
                stripe.PaymentIntent.modify(pi["id"], metadata={"report_status": "manual"})
                alert_owner("Order below 5 firms: refund or follow up",
                            f"Order {s['id']} ({order}) found {n} firms. Notes: {notes}")
            handled += 1
        except Exception:
            stripe.PaymentIntent.modify(pi["id"], metadata={"report_attempts": str(attempts + 1)})
            alert_owner("Order failed, will retry", f"Order {s['id']}\n{traceback.format_exc()}")
    return handled


def make_sample(work: str, state: str | None) -> None:
    order = {"work": work, "state": state, "cert": "Small business"}
    body, n, notes = build(order)
    if not body:
        sys.exit(f"Sample produced only {n} firms: {notes}")
    os.makedirs("docs", exist_ok=True)
    with open("docs/sample.html", "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Wrote docs/sample.html with {n} firms")


def ping(suffix: str = "") -> None:
    url = os.environ.get("HEALTHCHECK_URL")
    if url:
        try:
            requests.get(url + suffix, timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        make_sample(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        sys.exit(0)
    if not os.environ.get("STRIPE_KEY"):
        print("Not configured yet: add the STRIPE_KEY secret to start processing orders.")
        sys.exit(0)
    try:
        print(f"Handled {process_orders()} order(s)")
        ping()
    except Exception:
        ping("/fail")
        alert_owner("Run crashed", traceback.format_exc())
        raise
