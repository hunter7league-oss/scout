"""Slow, polite outreach to APEX Accelerator offices.

- Sends at most DAILY_LIMIT emails per run (one run per weekday), one email per office,
  never a follow-up.
- Before sending, reads the reports@ inbox over IMAP: anyone who replied with
  "remove", "unsubscribe" or "stop" is added to outreach/suppressed.txt and never
  emailed again.
- Every email carries the business's postal address and an opt-out line (CAN-SPAM).
- Progress lives in outreach/sent.csv, committed back to the repository by the workflow.

Run: python -m finder.outreach
"""
from __future__ import annotations

import csv
import datetime as dt
import email
import imaplib
import os
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

DAILY_LIMIT = int(os.environ.get("OUTREACH_DAILY_LIMIT") or "20")
CONTACTS = "outreach/contacts.csv"
SENT = "outreach/sent.csv"
SUPPRESSED = "outreach/suppressed.txt"
OPT_OUT_WORDS = re.compile(r"\b(remove|unsubscribe|stop|opt[- ]?out)\b", re.I)

SUBJECT = "Free teaming-partner lists for your clients"
BODY = """Hello,

I run TeamingScout, which publishes free lists of the small businesses winning federal
contracts in 41 NAICS codes, updated weekly from public USAspending.gov data:
https://teamingscout.com/industries/

Each list shows award counts, totals, the main agencies and when current contracts end,
which can help your clients find teaming partners and subcontractors or spot upcoming
recompetes. If there are industries your clients ask about most, reply and I'll add them.

Thank you for the work you do for small businesses.

TeamingScout
https://teamingscout.com

---
You received this one-time note because your office's contact address is published for
small-business inquiries. We won't email you again. Reply "remove" and we'll make sure of it.
{address}
"""


def _read_set(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {ln.strip().lower() for ln in fh if ln.strip()}


def update_suppression() -> set[str]:
    """Add anyone who replied asking to opt out. Failures here stop all sending."""
    suppressed = _read_set(SUPPRESSED)
    host = os.environ.get("IMAP_HOST") or "imap.ionos.com"
    box = imaplib.IMAP4_SSL(host, 993)
    box.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    box.select("INBOX", readonly=True)
    since = (dt.date.today() - dt.timedelta(days=60)).strftime("%d-%b-%Y")
    _, ids = box.search(None, f'(SINCE "{since}")')
    new = set()
    for mid in ids[0].split():
        _, data = box.fetch(mid, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
        text = msg.get("Subject", "")
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    text += " " + part.get_payload(decode=True).decode(errors="ignore")[:2000]
                except Exception:
                    pass
        if sender and OPT_OUT_WORDS.search(text):
            new.add(sender)
    box.logout()
    if new - suppressed:
        with open(SUPPRESSED, "a", encoding="utf-8") as fh:
            for s in sorted(new - suppressed):
                fh.write(s + "\n")
        print(f"Added {len(new - suppressed)} opt-out(s)")
    return suppressed | new


def main() -> None:
    address = os.environ.get("BUSINESS_ADDRESS", "").strip()
    if not address:
        raise SystemExit("BUSINESS_ADDRESS is required for outreach (CAN-SPAM).")
    suppressed = update_suppression()

    sent_rows = []
    if os.path.exists(SENT):
        with open(SENT, encoding="utf-8") as fh:
            sent_rows = list(csv.DictReader(fh))
    already = {r["email"].lower() for r in sent_rows}
    with open(CONTACTS, encoding="utf-8") as fh:
        contacts = [r for r in csv.DictReader(fh)
                    if r["email"].lower() not in already and r["email"].lower() not in suppressed]
    batch = contacts[:DAILY_LIMIT]
    if not batch:
        print("Nothing left to send.")
        return

    sender = os.environ.get("FROM_EMAIL") or os.environ["SMTP_USER"]
    host = os.environ.get("SMTP_HOST") or "smtp.ionos.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    write_header = not os.path.exists(SENT)
    with smtplib.SMTP_SSL(host, port) as s, open(SENT, "a", newline="", encoding="utf-8") as out:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        w = csv.DictWriter(out, fieldnames=["date", "email", "office", "state"])
        if write_header:
            w.writeheader()
        for c in batch:
            msg = MIMEMultipart()
            msg["Subject"] = SUBJECT
            msg["From"] = formataddr(("TeamingScout", sender))
            msg["To"] = c["email"]
            msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
            msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=remove>"
            msg.attach(MIMEText(BODY.format(address=address), "plain", "utf-8"))
            try:
                s.sendmail(sender, [c["email"]], msg.as_string())
                w.writerow({"date": dt.date.today().isoformat(), "email": c["email"],
                            "office": c["office"], "state": c["state"]})
                out.flush()
                print(f"sent: {c['office']} ({c['state']})")
            except smtplib.SMTPRecipientsRefused:
                print(f"refused: {c['email']}")
            time.sleep(20)  # spread sends out
    print(f"Sent {len(batch)} today; {len(contacts) - len(batch)} remaining.")


if __name__ == "__main__":
    main()
