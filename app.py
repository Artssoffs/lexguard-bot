
"""
Railway entrypoint for LexGuard AML Pro.
Runs the Telegram bot from main.py and serves a lightweight landing + report verification page.
"""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, urlparse

import main as botcore
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

LANDING_HOST = os.getenv("LANDING_HOST", "0.0.0.0")
LANDING_PORT = int(os.getenv("PORT", os.getenv("LANDING_PORT", "8080")))
SITE_URL = os.getenv("SITE_URL", "").rstrip("/") or f"http://{LANDING_HOST}:{LANDING_PORT}"
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/LexAML_Bot")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", BOT_LINK)
RUN_LANDING = os.getenv("RUN_LANDING", "true").lower() == "true"
DROP_PENDING_UPDATES = os.getenv("DROP_PENDING_UPDATES", "true").lower() == "true"

logger = logging.getLogger("lexguard-app")


def query_one(sql: str, params=()):
    cur = botcore.db.conn.cursor()
    cur.execute(sql, params)
    return cur.fetchone()


def verify_url(report_id: str) -> str:
    return f"{SITE_URL}/verify?report={quote_plus(report_id)}"


def landing_stats_html() -> str:
    stats = botcore.db.stats()
    cards = [
        ("Quick checks", stats["pending_scans"]),
        ("Premium audits", stats["pending_audits"]),
        ("Support tickets", stats["open_tickets"]),
        ("Service mode", "Manual analyst desk"),
    ]
    return "".join(
        f'<div class="stat"><span class="k">{botcore.h(label)}</span><span class="v">{botcore.h(value)}</span></div>'
        for label, value in cards
    )


def verify_block(report_id: str) -> str:
    if not report_id:
        return (
            '<div class="verify neutral">'
            '<div class="badge">ENTER REPORT ID</div>'
            '<p>Add <code>?report=LGP-XXXX</code> to the URL to verify a premium report.</p>'
            '</div>'
        )

    row = query_one(
        "SELECT report_id, target, risk, score, status, completed_at FROM audit_requests WHERE report_id = ? ORDER BY id DESC LIMIT 1",
        (report_id.upper(),),
    )

    if not row:
        return (
            '<div class="verify bad">'
            '<div class="badge">NOT FOUND</div>'
            '<p>No completed premium report is registered under this ID.</p>'
            '</div>'
        )

    return (
        '<div class="verify ok">'
        f'<div class="badge">{botcore.h(row["status"])}</div>'
        f'<h2>{botcore.h(row["report_id"])}</h2>'
        f'<p><strong>Target:</strong> <code>{botcore.h(botcore.truncate(row["target"], 56))}</code></p>'
        f'<p><strong>Risk:</strong> {botcore.get_risk_ui(row["risk"] or "")} • <strong>Score:</strong> {botcore.h(row["score"] )}/100</p>'
        f'<p><strong>Completed:</strong> {botcore.h(row["completed_at"] or "N/A")}</p>'
        f'<p><strong>Verification URL:</strong> <code>{botcore.h(verify_url(row["report_id"]))}</code></p>'
        '</div>'
    )


def home_page_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LexGuard AML Pro</title>
<meta name="description" content="Manual blockchain AML / KYC analyst desk with Telegram bot and premium signed PDF reports.">
<style>
:root {{
  --bg:#07111f; --panel:#0f1a2f; --panel2:#142341; --text:#edf3ff; --muted:#98a7bf; --gold:#d4af37; --line:#203556;
}}
* {{ box-sizing:border-box; }}
html, body {{ margin:0; padding:0; }}
body {{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
  color:var(--text);
  background:
    radial-gradient(circle at 18% 0%, rgba(26,74,151,.34), transparent 32%),
    radial-gradient(circle at 82% 8%, rgba(212,175,55,.18), transparent 24%),
    linear-gradient(180deg, #08111e 0%, #040a13 100%);
}}
a {{ text-decoration:none; }}
.wrap {{ max-width:1160px; margin:0 auto; padding:24px 20px 64px; }}
.nav {{
  display:flex; justify-content:space-between; align-items:center; gap:18px; padding:10px 0 28px;
}}
.brand .t {{ font-weight:800; letter-spacing:.18em; font-size:15px; }}
.brand .s {{ color:var(--muted); font-size:13px; margin-top:6px; }}
.links {{ display:flex; gap:10px; flex-wrap:wrap; }}
.btn, .btn2 {{
  display:inline-flex; align-items:center; justify-content:center;
  padding:13px 18px; border-radius:14px; font-weight:700;
}}
.btn {{
  color:#08111f; background:linear-gradient(180deg,#f4d97b,#d4af37);
  box-shadow:0 10px 24px rgba(212,175,55,.16);
}}
.btn2 {{
  color:var(--text); background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
}}
.hero {{
  display:grid; grid-template-columns:1.18fr .82fr; gap:24px;
}}
.panel {{
  background:rgba(15,26,47,.9); border:1px solid var(--line); border-radius:26px; padding:30px;
  box-shadow:0 20px 50px rgba(0,0,0,.28);
}}
.eyebrow {{
  display:inline-block; padding:8px 12px; border-radius:999px;
  color:#f0d885; border:1px solid rgba(212,175,55,.25);
  font-size:12px; letter-spacing:.14em; text-transform:uppercase;
}}
h1 {{
  margin:18px 0 14px; font-size:54px; line-height:1.03;
}}
.sub {{
  color:var(--muted); font-size:17px; line-height:1.72;
}}
.cta {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:22px; }}
.stats {{
  display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:22px;
}}
.stat {{
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07); border-radius:18px; padding:14px 16px;
}}
.stat .k {{
  display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; margin-bottom:6px;
}}
.stat .v {{ font-size:18px; font-weight:800; }}
.side {{ display:flex; flex-direction:column; gap:16px; }}
.signal {{
  background:linear-gradient(180deg, rgba(212,175,55,.12), rgba(255,255,255,.02));
  border:1px solid rgba(212,175,55,.2); border-radius:24px; padding:22px;
}}
.signal h3 {{ margin:0 0 10px; font-size:22px; }}
.signal p {{ margin:0; color:var(--muted); line-height:1.72; }}
.grid {{
  display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:24px;
}}
.card {{
  background:rgba(15,26,47,.9); border:1px solid var(--line); border-radius:22px; padding:22px;
}}
.card h3 {{ margin:0 0 10px; font-size:22px; }}
.card p {{ margin:0; color:var(--muted); line-height:1.72; }}
.strip {{
  display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; margin-top:24px;
}}
.small {{
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08); border-radius:20px; padding:18px;
}}
.small .n {{ color:var(--gold); font-weight:800; font-size:13px; letter-spacing:.14em; text-transform:uppercase; }}
.small p {{ color:var(--muted); line-height:1.72; margin-bottom:0; }}
.footer {{
  margin-top:28px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;
  color:var(--muted); font-size:13px;
}}
.code {{
  margin-top:14px; padding:14px 16px; border-radius:16px;
  background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
  color:#f0d885; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
}}
@media (max-width: 940px) {{
  .hero, .grid, .strip, .stats {{ grid-template-columns:1fr; }}
  h1 {{ font-size:40px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="nav">
    <div class="brand">
      <div class="t">LEXGUARD AML</div>
      <div class="s">Telegram bot • manual analyst desk • certified PDF reports</div>
    </div>
    <div class="links">
      <a class="btn2" href="/verify">Verify report</a>
      <a class="btn" href="{botcore.h(BOT_LINK)}">Join the Bot →</a>
    </div>
  </div>

  <div class="hero">
    <div class="panel">
      <div class="eyebrow">Manual AML / KYC Intelligence</div>
      <h1>Landing + Telegram + premium audit delivery in one Railway deployment.</h1>
      <div class="sub">
        LexGuard AML Pro is a manual blockchain risk-intelligence workflow. Users open the Telegram bot, request
        a quick scan or full premium audit, submit the payment TX hash for manual review, and receive the final result
        in chat. Premium reports are delivered as branded PDF documents with a report ID and verification route.
      </div>
      <div class="cta">
        <a class="btn" href="{botcore.h(BOT_LINK)}">Join the Bot →</a>
        <a class="btn2" href="{botcore.h(SUPPORT_LINK)}">Support</a>
      </div>
      <div class="stats">
        {landing_stats_html()}
      </div>
    </div>

    <div class="side">
      <div class="signal">
        <h3>Included in this build</h3>
        <p>Quick Scan, Custom Manual Audit, admin grading, support desk, certified PDF output and public report verification page.</p>
      </div>
      <div class="panel">
        <div class="eyebrow">Deployment notes</div>
        <div class="sub">
          Set <strong>SITE_URL</strong> to your public Railway domain so the verification link and QR references can point to the live landing.
          Keep only one polling bot instance active to avoid Telegram conflict errors.
        </div>
        <div class="code">Landing: {botcore.h(SITE_URL)}<br>Payment: {botcore.h(botcore.PAYMENT_NETWORK)} • {botcore.h(botcore.PAYMENT_WALLET)}</div>
      </div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Quick Scan (Free)</h3>
      <p>Manual risk grading for wallet addresses and transaction references, delivered directly in Telegram by the analyst desk.</p>
    </div>
    <div class="card">
      <h3>Custom Manual Audit</h3>
      <p>Full premium AML / KYC report with branded PDF output, scoring block and digital certification section.</p>
    </div>
    <div class="card">
      <h3>Report verification</h3>
      <p>Every premium report can be checked through the landing verification route using its report ID.</p>
    </div>
    <div class="card">
      <h3>Support desk</h3>
      <p>User support messages are routed to admin and answered back in the same Telegram chat.</p>
    </div>
  </div>

  <div class="strip">
    <div class="small">
      <div class="n">Step 01</div>
      <p>User opens the bot and selects Quick Scan or Custom Manual Audit.</p>
    </div>
    <div class="small">
      <div class="n">Step 02</div>
      <p>For premium flow, the bot shows the fixed payment wallet and requests the TX hash after transfer.</p>
    </div>
    <div class="small">
      <div class="n">Step 03</div>
      <p>Admin resolves the case manually and the user receives the result or premium PDF in Telegram.</p>
    </div>
  </div>

  <div class="footer">
    <div>Official bot: <a href="{botcore.h(BOT_LINK)}">{botcore.h(BOT_LINK)}</a></div>
    <div>Verification route: <a href="/verify">/verify</a></div>
    <div>Site line: {botcore.h(SITE_URL)}</div>
  </div>
</div>
</body>
</html>"""


def verify_page_html(report_id: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verify Report — LexGuard AML</title>
<style>
:root {{
  --bg:#07111f; --panel:#0f1a2f; --text:#edf3ff; --muted:#98a7bf; --gold:#d4af37; --line:#203556;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Arial,sans-serif;
  color:var(--text);
  background:radial-gradient(circle at top, #13213e 0%, var(--bg) 55%);
}}
.wrap {{ max-width:920px; margin:0 auto; padding:32px 20px 56px; }}
.panel {{
  background:rgba(15,26,47,.92); border:1px solid var(--line); border-radius:24px; padding:28px;
  box-shadow:0 16px 48px rgba(0,0,0,.24);
}}
a {{ color:var(--gold); text-decoration:none; }}
.top {{ display:flex; justify-content:space-between; gap:16px; align-items:center; margin-bottom:28px; }}
.brand {{ font-weight:800; letter-spacing:.16em; }}
.badge {{
  display:inline-block; padding:8px 12px; border-radius:999px; margin-bottom:14px;
  border:1px solid rgba(255,255,255,.12); font-size:12px; letter-spacing:.12em;
}}
.verify.ok .badge {{ background:rgba(16,185,129,.14); color:#b5f5df; }}
.verify.bad .badge {{ background:rgba(239,68,68,.14); color:#fecaca; }}
.verify.neutral .badge {{ background:rgba(212,175,55,.14); color:#f7e3a3; }}
code {{
  background:rgba(255,255,255,.06); padding:3px 7px; border-radius:8px; color:#f8e9b0;
}}
p {{ color:var(--muted); line-height:1.65; }}
.action {{
  display:inline-block; margin-top:18px; padding:12px 16px; border-radius:14px;
  border:1px solid rgba(212,175,55,.35); color:#08111f; background:linear-gradient(180deg,#f2d46c,#d4af37);
  font-weight:700;
}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand">LEXGUARD AML</div>
    <a href="/">← Back to landing</a>
  </div>
  <div class="panel">
    <div class="badge">DIGITAL REPORT VERIFICATION</div>
    <h1>Manual report verification</h1>
    <p>Premium reports issued through the Telegram audit flow can be checked here by report ID.</p>
    {verify_block(report_id)}
    <a class="action" href="{botcore.h(BOT_LINK)}">Open Telegram Bot →</a>
  </div>
</div>
</body>
</html>"""


class LandingHandler(BaseHTTPRequestHandler):
    server_version = "LexGuardLanding/1.0"

    def send_page(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self.send_page(home_page_html())
            return

        if parsed.path in ("/health", "/healthz"):
            payload = {
                "status": "ok",
                "service": "lexguard-landing",
                "site_url": SITE_URL,
                "time_utc": botcore.now_utc(),
            }
            self.send_page(json.dumps(payload), content_type="application/json; charset=utf-8")
            return

        if parsed.path == "/verify":
            report_id = (params.get("report", [""])[0] or "").strip()
            self.send_page(verify_page_html(report_id))
            return

        self.send_page("<h1>404</h1><p>Not found.</p>", status=404)

    def log_message(self, fmt, *args):
        logger.info("landing | %s - %s", self.address_string(), fmt % args)


def start_landing():
    if not RUN_LANDING:
        logger.info("Landing disabled")
        return

    server = ThreadingHTTPServer((LANDING_HOST, LANDING_PORT), LandingHandler)
    logger.info("Landing started on http://%s:%s", LANDING_HOST, LANDING_PORT)
    server.serve_forever()


def build_bot():
    app = ApplicationBuilder().token(botcore.TOKEN).build()
    app.add_error_handler(botcore.error_handler)
    app.add_handler(CommandHandler("start", botcore.start))
    app.add_handler(CommandHandler("cancel", botcore.cancel))
    app.add_handler(CommandHandler("admin", botcore.admin_command))
    app.add_handler(CommandHandler("scanres", botcore.scanres_command))
    app.add_handler(CommandHandler("auditres", botcore.auditres_command))
    app.add_handler(CommandHandler("reply", botcore.reply_command))
    app.add_handler(CallbackQueryHandler(botcore.process_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, botcore.handle_messages))
    return app


def main():
    if botcore.TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN before starting the bot.")

    if RUN_LANDING:
        thread = threading.Thread(target=start_landing, daemon=True, name="landing-server")
        thread.start()

    app = build_bot()
    logger.info("Starting %s with landing wrapper", botcore.BOT_NAME)
    app.run_polling(close_loop=False, drop_pending_updates=DROP_PENDING_UPDATES)


if __name__ == "__main__":
    main()
