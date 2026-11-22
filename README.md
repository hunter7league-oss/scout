# TeamingScout: automated federal teaming-partner shortlists

A customer pays $49 on a Stripe Payment Link and describes the work they're bidding on.
Every 15 minutes, GitHub Actions picks up new paid orders, searches five years of
USAspending.gov contract awards, ranks the firms that did that work, and emails a report.
Orders with fewer than 5 matching firms are refunded automatically (if `AUTO_REFUND=true`)
or flagged to you.

Nothing runs on your computer. Total running cost: ~$0–$5/month plus a ~$10/year domain at low volume, plus Stripe fees.

## Setup (about 45 minutes)

Do everything in **Stripe test mode first**, make a test purchase, then repeat step 2 in live mode.

### 1. GitHub (10 min)
1. Create a **public** repository named `scout` (GitHub Pages is free only for public repos;
   no secrets are stored in the code).
2. Upload every file in this folder, keeping the folder structure
   (or connect your GitHub to Claude and it will push them).
3. Settings → Pages → Source: *Deploy from a branch* → `main` / `/docs` → Save.
   Your site will be at `https://<your-username>.github.io/scout/`.

### 2. Stripe (15 min)
1. Create a Stripe account (identity and bank details are entered by you).
2. Product catalog → Add product: **Federal teaming partner shortlist**, one-time, **$49**.
3. Payment Links → New → choose that product. Under *Options*:
   - Add custom field, **Text**: `Describe the work you're bidding on (or NAICS code)`, required.
   - Add custom field, **Text**: `State of the work (2 letters)`, **optional**.
   - Add custom field, **Dropdown**: `Partner certification`, options:
     `Any`, `Small business`, `Woman-owned`, `Service-disabled veteran-owned`, `8(a)`, `HUBZone`.
   - After payment → *Show confirmation page*:
     "Thanks! Your shortlist will arrive by email within about an hour."
4. Create the link. Copy its URL (for the website) and its ID, which starts with `plink_`
   (in the link's page in the Dashboard).
5. Developers → API keys → **Create restricted key** with:
   Checkout Sessions **Read**, Payment Intents **Write**, Refunds **Write**. Copy it.

### 3. Email from your own domain (15 min)
A custom address (e.g., `reports@teamingscout.com`) looks far more trustworthy than Gmail.
1. Buy a domain at Cloudflare Registrar (sold at cost): https://dash.cloudflare.com → Domain Registration.
2. Receive replies free: Cloudflare → your domain → Email → Email Routing → forward
   `reports@yourdomain` to your personal inbox.
3. Send through Resend (free up to 3,000 emails/month): sign up at https://resend.com,
   add your domain and click the Cloudflare auto-setup (or copy the DNS records it shows).
4. Create a Resend API key with *Sending access*. It is the SMTP password below.

(Quick alternative for testing only: a Gmail app password, with `SMTP_HOST`/`FROM_EMAIL` left blank.)

### 4. Anthropic API key (3 min)
Create a key at https://console.anthropic.com and set a monthly spend limit (e.g., $20).
Each report costs a fraction of a cent to a few cents.

### 5. Health check, optional (3 min)
Create a free check at https://healthchecks.io with a 15-minute period and 30-minute grace.
Copy its ping URL. You'll get an email or text if runs stop.

### 6. Add settings to GitHub (5 min)
Repository → Settings → Secrets and variables → Actions.

**Secrets** (enter these yourself):

| Name | Value |
| --- | --- |
| `STRIPE_KEY` | the restricted key from 2.5 |
| `STRIPE_PAYMENT_LINK_ID` | the `plink_...` ID |
| `ANTHROPIC_API_KEY` | from step 4 |
| `SMTP_USER` | `resend` (or your Gmail address if using Gmail) |
| `SMTP_PASS` | the Resend API key (or Gmail app password) |
| `OWNER_EMAIL` | where you want copies and alerts |
| `HEALTHCHECK_URL` | optional, from step 5 |

**Variables**:

| Name | Value |
| --- | --- |
| `SMTP_HOST` | `smtp.resend.com` (blank for Gmail) |
| `SMTP_PORT` | `465` |
| `FROM_EMAIL` | `reports@yourdomain.com` (blank for Gmail) |
| `BUSINESS_NAME` | `TeamingScout` (or your name for it) |
| `BUSINESS_ADDRESS` | a mailing address for the email footer |
| `AUTO_REFUND` | `true` to refund under-5-firm orders automatically |

### 7. Website text (2 min)
In `docs/index.html`, replace `STRIPE_PAYMENT_LINK_URL`, `OWNER_EMAIL` and `BUSINESS_ADDRESS`.

### 8. Make the sample report (2 min)
Actions → *Process orders* → Run workflow → Sample work: `environmental remediation 562910`,
State: blank → Run. It writes `docs/sample.html` from live data and the site links to it.

### 9. Test, then go live
Buy from the **test-mode** link with Stripe's test card `4242 4242 4242 4242`.
Within ~15 minutes (or run the workflow by hand) the report should reach the buyer email,
with a copy to you. Then create the live-mode link and key, update the two Stripe secrets
and the website button, and you're open.

## How it stays hands-off
- **No duplicates:** each order is marked on its Stripe payment (`report_status`).
- **Retries:** failed orders retry on the next 3 runs, then email you.
- **Facts are never AI-written:** names, amounts, dates and agencies come straight from the data;
  AI notes containing any digit are discarded.
- **Alerts:** crashes and stuck orders email `OWNER_EMAIL`; missed runs trigger the health check.

## Run the tests
`pip install -r requirements.txt pytest && python -m pytest -q tests`
