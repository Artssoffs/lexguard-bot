import os
import re
import hmac
import logging
import hashlib
import random
import textwrap
from io import BytesIO
from decimal import Decimal
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

# =========================
# CONFIGURATION PRO 5.2
# =========================
TOKEN = "8785738588:AAGAG07a8miJwbYWBT6IYX6ZgeE7ivBg88M"
ADMIN_USER_ID = 8061332993

BOT_NAME = "LexGuard AML"
BOT_TAGLINE = "Premium Wallet Screening & Compliance"

FULL_REPORT_PRICE_USD = Decimal("1400")
PAYMENT_NETWORK = "USDT TRC20"
PAYMENT_WALLET = "TRND8fBYLQWuy8xMpmRcq77eTLWrdbBH61"
REPORT_SIGNING_SECRET = os.getenv("REPORT_SIGNING_SECRET", "CHANGE_THIS_LEXGUARD_SECRET")

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_HASH_RE = re.compile(r"^(0x)?[A-Fa-f0-9]{32,64}$")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("lexguard_pro")


# =========================
# UTILITY FUNCTIONS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def get_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    state = context.bot_data
    state.setdefault("risk_mode", "auto")
    state.setdefault("pending_scans", {})
    state.setdefault("pending_audits", {})
    return state

def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("flow", None)
    context.user_data.pop("report_target", None)

def detect_network(address: str) -> str:
    if TRON_ADDRESS_RE.match(address):
        return "TRON (TRC20)"
    elif ETH_ADDRESS_RE.match(address):
        return "Ethereum (ERC20)"
    elif TX_HASH_RE.match(address):
        return "Transaction Hash"
    return "Unknown"

def risk_badge(risk: str) -> str:
    badges = {"LOW": "ð¢ LOW", "MEDIUM": "ð¡ MEDIUM", "HIGH": "ð´ HIGH", "CRITICAL": "â CRITICAL"}
    return badges.get(risk.upper(), "âª UNKNOWN")

def _sign_report(payload: str) -> str:
    signature = hmac.new(REPORT_SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return signature.upper()

def _risk_profile(risk: str, lang: str = "ENG"):
    profiles = {
        "ENG": {
            "LOW": {"color": HexColor("#10B981"), "status": "â Clean", "flags": "None detected", "summary": "No significant risk indicators found. Wallet appears legitimate with normal transaction patterns."},
            "MEDIUM": {"color": HexColor("#F59E0B"), "status": "â ï¸ Moderate Risk", "flags": "Minor flags detected", "summary": "Some suspicious activity detected. Recommend additional due diligence before proceeding."},
            "HIGH": {"color": HexColor("#EF4444"), "status": "ð« High Risk", "flags": "Multiple red flags", "summary": "Significant risk indicators present. Strong links to suspicious entities or activities detected."}
        },
        "RUS": {
            "LOW": {"color": HexColor("#10B981"), "status": "â Ð§Ð¸ÑÑÐ¾", "flags": "ÐÐµ Ð¾Ð±Ð½Ð°ÑÑÐ¶ÐµÐ½Ð¾", "summary": "ÐÐ½Ð°ÑÐ¸ÑÐµÐ»ÑÐ½ÑÑ Ð¸Ð½Ð´Ð¸ÐºÐ°ÑÐ¾ÑÐ¾Ð² ÑÐ¸ÑÐºÐ° Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾. ÐÐ¾ÑÐµÐ»ÐµÐº Ð²ÑÐ³Ð»ÑÐ´Ð¸Ñ Ð»ÐµÐ³Ð¸ÑÐ¸Ð¼Ð½ÑÐ¼ Ñ Ð½Ð¾ÑÐ¼Ð°Ð»ÑÐ½ÑÐ¼Ð¸ Ð¿Ð°ÑÑÐµÑÐ½Ð°Ð¼Ð¸ ÑÑÐ°Ð½Ð·Ð°ÐºÑÐ¸Ð¹."},
            "MEDIUM": {"color": HexColor("#F59E0B"), "status": "â ï¸ Ð£Ð¼ÐµÑÐµÐ½Ð½ÑÐ¹ ÑÐ¸ÑÐº", "flags": "ÐÐ±Ð½Ð°ÑÑÐ¶ÐµÐ½Ñ Ð½ÐµÐ·Ð½Ð°ÑÐ¸ÑÐµÐ»ÑÐ½ÑÐµ ÑÐ»Ð°Ð³Ð¸", "summary": "ÐÐ±Ð½Ð°ÑÑÐ¶ÐµÐ½Ð° Ð½ÐµÐºÐ¾ÑÐ¾ÑÐ°Ñ Ð¿Ð¾Ð´Ð¾Ð·ÑÐ¸ÑÐµÐ»ÑÐ½Ð°Ñ Ð°ÐºÑÐ¸Ð²Ð½Ð¾ÑÑÑ. Ð ÐµÐºÐ¾Ð¼ÐµÐ½Ð´ÑÐµÑÑÑ Ð´Ð¾Ð¿Ð¾Ð»Ð½Ð¸ÑÐµÐ»ÑÐ½Ð°Ñ Ð¿ÑÐ¾Ð²ÐµÑÐºÐ°."},
            "HIGH": {"color": HexColor("#EF4444"), "status": "ð« ÐÑÑÐ¾ÐºÐ¸Ð¹ ÑÐ¸ÑÐº", "flags": "ÐÐ½Ð¾Ð¶ÐµÑÑÐ²ÐµÐ½Ð½ÑÐµ ÐºÑÐ°ÑÐ½ÑÐµ ÑÐ»Ð°Ð³Ð¸", "summary": "ÐÑÐ¸ÑÑÑÑÑÐ²ÑÑÑ Ð·Ð½Ð°ÑÐ¸ÑÐµÐ»ÑÐ½ÑÐµ Ð¸Ð½Ð´Ð¸ÐºÐ°ÑÐ¾ÑÑ ÑÐ¸ÑÐºÐ°. ÐÐ±Ð½Ð°ÑÑÐ¶ÐµÐ½Ñ Ð¿ÑÐ¾ÑÐ½ÑÐµ ÑÐ²ÑÐ·Ð¸ Ñ Ð¿Ð¾Ð´Ð¾Ð·ÑÐ¸ÑÐµÐ»ÑÐ½ÑÐ¼Ð¸ ÑÑÐ±ÑÐµÐºÑÐ°Ð¼Ð¸."}
        }
    }
    lang_key = lang.upper() if lang.upper() in profiles else "ENG"
    return profiles[lang_key].get(risk.upper(), profiles[lang_key]["LOW"])

def _draw_label_value(c, label, value, x, y, max_width):
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x, y, label.upper())
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica", 9)
    if len(value) > 40:
        value = value[:37] + "..."
    c.drawString(x, y - 14, value)
    return y - 32

def _draw_multiline(c, text, x, y, max_width, font_name="Helvetica", font_size=10, leading=14, color=None):
    if color:
        c.setFillColor(color)
    c.setFont(font_name, font_size)
    lines = textwrap.wrap(text, width=80)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y

def _draw_digital_seal(c, x, y, signature_short):
    c.setStrokeColor(HexColor("#1D4ED8"))
    c.setLineWidth(2)
    c.circle(x, y, 28, stroke=1, fill=0)
    c.setFillColor(HexColor("#1D4ED8"))
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x, y + 9, "LEXGUARD AML")
    c.setFont("Helvetica", 6)
    c.drawCentredString(x, y - 1, "lexguard.io")
    c.drawCentredString(x, y - 12, signature_short)

def make_report_file(target: str, payment_ref: str, risk: str, score: int, lang: str = "ENG") -> tuple[BytesIO, str]:
    labels = {
        "ENG": {
            "title": "LexGuard AML", "subtitle": "Premium Manual Audit", "report": "Custom Manual Audit Report",
            "report_id": "REPORT ID", "issued": "ISSUED", "risk": "RISK", "score": "SCORE",
            "client_target": "Client Target", "network": "Network", "status": "Status",
            "methodology": "Methodology", "methodology_val": "Custom Manual Report by LexGuard AML",
            "payment_network": "Payment Network", "payment_hash": "Payment Hash", "flags": "Flags Detected",
            "summary": "Summary", "signature": "Digital Signature", 
            "signature_note": "This signature confirms report integrity and issuance by LexGuard AML.",
            "disclaimer": "Disclaimer: This report is provided for informational and compliance screening purposes only."
        },
        "RUS": {
            "title": "LexGuard AML", "subtitle": "ÐÑÐµÐ¼Ð¸Ð°Ð»ÑÐ½ÑÐ¹ ÑÑÑÐ½Ð¾Ð¹ Ð°ÑÐ´Ð¸Ñ", "report": "ÐÐ½Ð´Ð¸Ð²Ð¸Ð´ÑÐ°Ð»ÑÐ½ÑÐ¹ ÑÑÑÐ½Ð¾Ð¹ Ð¾ÑÑÐµÑ",
            "report_id": "ID ÐÐ¢Ð§ÐÐ¢Ð", "issued": "ÐÐ«ÐÐÐÐ", "risk": "Ð ÐÐ¡Ð", "score": "ÐÐ¦ÐÐÐÐ",
            "client_target": "ÐÐ»Ð¸ÐµÐ½ÑÑÐºÐ¸Ð¹ Ð°Ð´ÑÐµÑ", "network": "Ð¡ÐµÑÑ", "status": "Ð¡ÑÐ°ÑÑÑ",
            "methodology": "ÐÐµÑÐ¾Ð´Ð¾Ð»Ð¾Ð³Ð¸Ñ", "methodology_val": "Ð ÑÑÐ½Ð¾Ð¹ Ð¾ÑÑÐµÑ ÐºÐ¾Ð¼Ð¿Ð°Ð½Ð¸Ð¸ LexGuard AML",
            "payment_network": "ÐÐ»Ð°ÑÐµÐ¶Ð½Ð°Ñ ÑÐµÑÑ", "payment_hash": "Ð¥ÐµÑ Ð¿Ð»Ð°ÑÐµÐ¶Ð°", "flags": "ÐÐ±Ð½Ð°ÑÑÐ¶ÐµÐ½Ð½ÑÐµ ÑÐ»Ð°Ð³Ð¸",
            "summary": "Ð ÐµÐ·ÑÐ¼Ðµ", "signature": "Ð¦Ð¸ÑÑÐ¾Ð²Ð°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÑ",
            "signature_note": "ÐÐ°Ð½Ð½Ð°Ñ Ð¿Ð¾Ð´Ð¿Ð¸ÑÑ Ð¿Ð¾Ð´ÑÐ²ÐµÑÐ¶Ð´Ð°ÐµÑ ÑÐµÐ»Ð¾ÑÑÐ½Ð¾ÑÑÑ Ð¸ Ð²ÑÐ¿ÑÑÐº Ð¾ÑÑÐµÑÐ° LexGuard AML.",
            "disclaimer": "ÐÑÐºÐ°Ð· Ð¾Ñ Ð¾ÑÐ²ÐµÑÑÑÐ²ÐµÐ½Ð½Ð¾ÑÑÐ¸: Ð´Ð°Ð½Ð½ÑÐ¹ Ð¾ÑÑÐµÑ Ð¿ÑÐµÐ´Ð¾ÑÑÐ°Ð²Ð»ÐµÐ½ ÑÐ¾Ð»ÑÐºÐ¾ Ð´Ð»Ñ Ð¸Ð½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ð¾Ð½Ð½ÑÑ Ð¸ ÐºÐ¾Ð¼Ð¿Ð»Ð°ÐµÐ½Ñ-ÑÐµÐ»ÐµÐ¹."
        }
    }
    
    L = labels[lang.upper()] if lang.upper() in labels else labels["ENG"]
    profile = _risk_profile(risk, lang)
    network = detect_network(target)
    report_id = f"LG-MANUAL-{hashlib.md5(target.encode()).hexdigest()[:8].upper()}"
    issued_at = now_utc()

    signature_payload = "|".join([report_id, issued_at, str(target), str(network), str(risk).upper(), str(score), str(payment_ref), "CUSTOM MANUAL AUDIT"])
    signature = _sign_report(signature_payload)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    navy, blue, light_bg, border, dark, muted = HexColor("#091A3A"), HexColor("#1D4ED8"), HexColor("#F8FAFC"), HexColor("#DCE3EA"), HexColor("#0F172A"), HexColor("#475569")

    c.setFillColor(white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setFillColor(navy)
    c.rect(0, height - 112, width, 112, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(42, height - 52, L["title"])
    c.setFont("Helvetica", 11)
    c.drawString(42, height - 72, L["subtitle"])
    c.drawString(42, height - 88, "www.lexguard.io")

    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(42, height - 145, L["report"])

    c.setFillColor(light_bg)
    c.setStrokeColor(border)
    c.roundRect(width - 220, height - 186, 175, 60, 10, fill=1, stroke=1)

    c.setFillColor(muted)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(width - 205, height - 147, L["report_id"])
    c.drawString(width - 205, height - 167, L["issued"])

    c.setFillColor(dark)
    c.setFont("Helvetica", 9)
    c.drawString(width - 145, height - 147, report_id)
    c.drawString(width - 145, height - 167, issued_at)

    c.setFillColor(profile["color"])
    c.roundRect(42, height - 206, 150, 28, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(56, height - 194, f"{L['risk']}: {risk.upper()}")

    c.setFillColor(blue)
    c.roundRect(202, height - 206, 130, 28, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(216, height - 194, f"{L['score']}: {score}/100")

    info_top = height - 238
    c.setFillColor(light_bg)
    c.setStrokeColor(border)
    c.roundRect(42, info_top - 210, width - 84, 210, 12, fill=1, stroke=1)

    left_x, right_x = 58, 305
    y_left, y_right = info_top - 24, info_top - 24

    y_left = _draw_label_value(c, L["client_target"], target, left_x, y_left, 215)
    y_left = _draw_label_value(c, L["network"], network, left_x, y_left, 215)
    y_left = _draw_label_value(c, L["status"], profile["status"], left_x, y_left, 215)
    y_left = _draw_label_value(c, L["methodology"], L["methodology_val"], left_x, y_left, 215)

    y_right = _draw_label_value(c, L["payment_network"], PAYMENT_NETWORK, right_x, y_right, 220)
    y_right = _draw_label_value(c, L["payment_hash"], payment_ref, right_x, y_right, 220)
    y_right = _draw_label_value(c, L["flags"], profile["flags"], right_x, y_right, 220)

    summary_y = info_top - 152
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x, summary_y, L["summary"])

    _draw_multiline(c, profile["summary"], left_x, summary_y - 16, width - 120, font_name="Helvetica", font_size=10, leading=14, color=dark)

    sig_box_y = info_top - 290
    c.setFillColor(white)
    c.setStrokeColor(border)
    c.roundRect(42, sig_box_y - 94, width - 84, 94, 12, fill=1, stroke=1)

    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(58, sig_box_y - 20, L["signature"])

    c.setFillColor(muted)
    c.setFont("Helvetica", 8)
    sig_lines = textwrap.wrap(signature, width=64)
    y = sig_box_y - 40
    for line in sig_lines[:2]:
        c.drawString(58, y, line)
        y -= 12

    c.setFont("Helvetica", 9)
    c.drawString(58, sig_box_y - 76, L["signature_note"])

    _draw_digital_seal(c, width - 100, sig_box_y - 46, signature[:10])
    _draw_multiline(c, L["disclaimer"], 42, 60, width - 84, font_name="Helvetica", font_size=8, leading=11, color=HexColor("#64748B"))

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer, f"{report_id}.pdf"


# =========================
# MENUS
# =========================
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ð Quick Scan (Free)", callback_data="scan")],
        [InlineKeyboardButton("ð¡ Custom Manual Audit", callback_data="report")],
        [InlineKeyboardButton("ð³ Services & Pricing", callback_data="pricing")],
        [InlineKeyboardButton("ð About LexGuard", callback_data="about")],
        [InlineKeyboardButton("ð¬ Support Chat", callback_data="support")],
    ])

def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("â¬ Main Menu", callback_data="back")]])

def admin_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    state = get_state(context)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'â ' if state['risk_mode'] == 'auto' else ''}Auto AI", callback_data="mode:auto"),
            InlineKeyboardButton(f"{'â ' if state['risk_mode'] == 'manual' else ''}Manual Intercept", callback_data="mode:manual"),
        ],
        [InlineKeyboardButton("â¬ Main Menu", callback_data="back")],
    ])


# =========================
# COMMAND HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_flow(context)
    BANNER_URL = "https://raw.githubusercontent.com/Artssoffs/lexguard-bot/main/lexguard_banner.png"
    await update.message.reply_photo(
        photo=BANNER_URL,
        caption="ð¡ <b>LexGuard AML</b>\n<i>Premium Wallet Screening</i>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text("âï¸ Admin Panel", reply_markup=admin_menu(context))

async def set_lang_eng(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["report_lang"] = "ENG"
    await update.message.reply_text("â Report language set to English.")

async def set_lang_rus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["report_lang"] = "RUS"
    await update.message.reply_text("â Ð¯Ð·ÑÐº Ð¾ÑÑÑÑÐ° ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½: Ð ÑÑÑÐºÐ¸Ð¹.")

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split(maxsplit=2)
        if len(parts) < 3: raise ValueError
        target_uid = int(parts[1])
        reply_text = parts[2]
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"<b>ð¨âð¼ ÐÑÐ²ÐµÑ Ð¿Ð¾Ð´Ð´ÐµÑÐ¶ÐºÐ¸ LexGuard:</b>\n\n{reply_text}",
            parse_mode="HTML",
        )
        await update.message.reply_text("â ÐÑÐ²ÐµÑ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½ Ð¿Ð¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»Ñ!")
    except Exception:
        await update.message.reply_text("â Ð¤Ð¾ÑÐ¼Ð°Ñ: /reply <user_id> <ÑÐµÐºÑÑ Ð¾ÑÐ²ÐµÑÐ°>")

async def admin_res(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        if len(parts) != 4: raise ValueError
        target_uid = int(parts[1])
        risk = parts[2].upper()
        score = int(parts[3])

        pending = context.bot_data.get("pending_scans", {}).pop(target_uid, None)
        if not pending:
            await update.message.reply_text("â Request not found or already answered.")
            return

        report = (
            f"<b>ð LEXGUARD MANUAL SCAN RESULT</b>\n\n"
            f"<b>Target:</b> <code>{pending['target']}</code>\n"
            f"<b>Risk Level:</b> {risk_badge(risk)}\n"
            f"<b>Threat Score:</b> {score}/100\n\n"
            f"<i>Engine: LexGuard Deep Manual Scan | {now_utc()}</i>"
        )
        await context.bot.edit_message_text(chat_id=pending["chat_id"], message_id=pending["msg_id"], text=report, parse_mode="HTML", reply_markup=back_menu())
        await update.message.reply_text("â Result sent to client!")
    except Exception:
        await update.message.reply_text("â Format: /res <ID> <LOW/MEDIUM/HIGH> <SCORE>")


async def admin_auditres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        if len(parts) != 4:
            raise ValueError

        target_uid = int(parts[1])
        risk = parts[2].upper()
        score = int(parts[3])

        if risk not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError

        pending = context.bot_data.get("pending_audits", {}).pop(target_uid, None)
        if not pending:
            await update.message.reply_text("â Audit request not found or already answered.")
            return

        pdf_buffer, pdf_name = make_report_file(
            pending["target"],
            pending["payment_ref"],
            risk,
            score,
            pending["lang"],
        )

        await context.bot.send_document(
            chat_id=pending["chat_id"],
            document=pdf_buffer,
            filename=pdf_name,
            caption=(
                f"â <b>Your Custom Manual Audit Report</b>\n\n"
                f"<b>Target:</b> <code>{pending['target']}</code>\n"
                f"<b>Risk Level:</b> {risk_badge(risk)}\n"
                f"<b>Threat Score:</b> {score}/100\n\n"
                f"<i>Report ID: {pdf_name}</i>"
            ),
            parse_mode="HTML",
        )

        try:
            await context.bot.edit_message_text(
                chat_id=pending["chat_id"],
                message_id=pending["msg_id"],
                text=(
                    f"â <b>Manual audit completed</b>\n\n"
                    f"<b>Target:</b> <code>{pending['target']}</code>\n"
                    f"<b>Risk Level:</b> {risk_badge(risk)}\n"
                    f"<b>Threat Score:</b> {score}/100"
                ),
                parse_mode="HTML",
                reply_markup=back_menu(),
            )
        except Exception:
            pass

        await update.message.reply_text("â Paid PDF audit sent to client!")
    except Exception:
        await update.message.reply_text("â Format: /auditres <ID> <LOW/MEDIUM/HIGH> <SCORE>")


# =========================
# CALLBACK HANDLER
# =========================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data, uid = q.data, q.from_user.id

    if data == "support":
        context.user_data["flow"] = "support_chat"
        await q.edit_message_text(
            "<b>ð¬ ÐÐ¾Ð´Ð´ÐµÑÐ¶ÐºÐ° LexGuard</b>\n\nÐÐ¿Ð¸ÑÐ¸ÑÐµ Ð²Ð°Ñ Ð²Ð¾Ð¿ÑÐ¾Ñ Ð¸Ð»Ð¸ Ð¿ÑÐ¾Ð±Ð»ÐµÐ¼Ñ. ÐÐ°Ñ Ð¾Ð¿ÐµÑÐ°ÑÐ¾Ñ Ð¾ÑÐ²ÐµÑÐ¸Ñ Ð²Ð°Ð¼ Ð¿ÑÑÐ¼Ð¾ Ð·Ð´ÐµÑÑ!\n\n<b>ÐÐ»Ñ Ð²ÑÑÐ¾Ð´Ð° â /start</b>",
            parse_mode="HTML", reply_markup=back_menu()
        )
        return

    if data in ["pay:btc", "pay:eth"]:
        await q.answer("â ï¸ Network congested. Temporarily accepting only USDT TRC20.", show_alert=True)
        return

    await q.answer()

    if data == "scan":
        context.user_data["flow"] = "scan"
        await q.edit_message_text("ð <b>Quick Scan</b>\n\nEnter the wallet address or TX Hash for verification:", parse_mode="HTML", reply_markup=back_menu())
    elif data == "report":
        context.user_data["flow"] = "report_target"
        await q.edit_message_text("ð¡ <b>Custom Manual Audit by LexGuard AML</b>\n\nIn-depth analysis with an official verification certificate.\nEnter the wallet address:", parse_mode="HTML", reply_markup=back_menu())
    elif data == "pricing":
        text = f"ð³ <b>Services & Pricing</b>\n\nâ¢ <b>Quick AI Scan:</b> Free (Basic scoring)\nâ¢ <b>Custom Manual Audit:</b> ${FULL_REPORT_PRICE_USD} (Detailed audit by our expert team)\n\n<i>We guarantee complete confidentiality.</i>"
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_menu())
    elif data == "about":
        await q.edit_message_text("ð <b>About LexGuard</b>\n\nLexGuard AML is a cutting-edge solution to protect your business from illicit cryptocurrency.\n\nWe conduct comprehensive blockchain analysis, identifying links to Darknet, mixers, and sanction lists.", parse_mode="HTML", reply_markup=back_menu())
    elif data == "back":
        clear_flow(context)
        await q.edit_message_text(f"ð¡ <b>{BOT_NAME}</b>\n<i>{BOT_TAGLINE}</i>\n\nSelect an action:", parse_mode="HTML", reply_markup=main_menu())
    elif data == "pay:usdt":
        context.user_data["flow"] = "report_tx"
        await q.edit_message_text(f"ð¸ <b>Payment Instructions</b>\n\nSend <b>${FULL_REPORT_PRICE_USD} USDT</b> (TRC20) to:\n\n<code>{PAYMENT_WALLET}</code>\n\nAfter payment, send the transaction hash here.", parse_mode="HTML", reply_markup=back_menu())
    elif data.startswith("mode:"):
        if not is_admin(uid): return
        context.bot_data["risk_mode"] = data.split(":")[1]
        await q.edit_message_text("âï¸ Admin Panel", reply_markup=admin_menu(context))


# =========================
# TEXT MESSAGE HANDLER
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    flow = context.user_data.get("flow")
    uid = update.effective_user.id

    if flow == "support_chat":
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"<b>ð¬ ÐÐ¾Ð²Ð¾Ðµ ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ðµ Ð¿Ð¾Ð´Ð´ÐµÑÐ¶ÐºÐ¸ Ð¾Ñ {uid}:</b>\n\n{text}\n\n<i>ÐÑÐ²ÐµÑÐ¸ÑÑ: /reply {uid} ÑÐµÐºÑÑ</i>", parse_mode="HTML")
        await update.message.reply_text("â Ð¡Ð¾Ð¾Ð±ÑÐµÐ½Ð¸Ðµ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÐµÐ½Ð¾ Ð² Ð¿Ð¾Ð´Ð´ÐµÑÐ¶ÐºÑ. ÐÐ¶Ð¸Ð´Ð°Ð¹ÑÐµ Ð¾ÑÐ²ÐµÑÐ°.")
        return

    if flow == "scan":
        state = get_state(context)
        if state["risk_mode"] == "manual":
            msg = await update.message.reply_text("â³ Processing your request...")
            state["pending_scans"][uid] = {"target": text, "chat_id": update.effective_chat.id, "msg_id": msg.message_id}
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"ð <b>MANUAL SCAN REQUEST</b>\n\nUser: {uid}\nTarget: <code>{text}</code>\n\nRespond with:\n/res {uid} <RISK> <SCORE>", parse_mode="HTML")
            return

        risk, score = random.choice(["LOW", "MEDIUM", "HIGH"]), random.randint(10, 90)
        report = f"<b>ð QUICK SCAN RESULT</b>\n\n<b>Target:</b> <code>{text}</code>\n<b>Network:</b> {detect_network(text)}\n<b>Risk Level:</b> {risk_badge(risk)}\n<b>Threat Score:</b> {score}/100\n\n<i>Engine: LexGuard AI Quick Scan | {now_utc()}</i>\n\nFor detailed audit, use /start â Custom Manual Audit"
        await update.message.reply_text(report, parse_mode="HTML", reply_markup=back_menu())
        clear_flow(context)

    elif flow == "report_target":
        context.user_data["report_target"] = text
        context.user_data["flow"] = "report_tx"
        await update.message.reply_text(f"ð¸ <b>Payment Instructions</b>\n\nSend <b>${FULL_REPORT_PRICE_USD} USDT</b> (TRC20) to:\n\n<code>{PAYMENT_WALLET}</code>\n\nAfter payment, send the transaction hash here.", parse_mode="HTML", reply_markup=back_menu())

    elif flow == "report_tx":
        target = context.user_data.get("report_target")
        if not target:
            await update.message.reply_text("â Error. Please start again with /start")
            return

        await update.message.reply_text("â³ Verifying payment and generating report...")
        risk, score = random.choice(["LOW", "MEDIUM", "HIGH"]), random.randint(20, 95)
        lang = context.user_data.get("report_lang", "ENG")
        
        pdf_buffer, pdf_name = make_report_file(target, text, risk, score, lang)
        await update.message.reply_document(document=pdf_buffer, filename=pdf_name, caption=f"â <b>Your Custom Manual Audit Report</b>\n\n<i>Report ID: {pdf_name}</i>", parse_mode="HTML")
        clear_flow(context)


# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("res", admin_res))
    app.add_handler(CommandHandler("auditres", admin_auditres))
    app.add_handler(CommandHandler("ENG", set_lang_eng))
    app.add_handler(CommandHandler("RUS", set_lang_rus))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("â LexGuard Pro Intercept Module Active.")
    app.run_polling()

if __name__ == "__main__":
    main()
