async def set_lang_eng(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch report language to English."""
    context.user_data["report_lang"] = "ENG"
    await update.message.reply_text("✅ Report language set to English.")

async def set_lang_rus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch report language to Russian."""
    context.user_data["report_lang"] = "RUS"
    await update.message.reply_text("✅ Язык отчёта установлен: Русский.")
async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Позволяет админу отвечать пользователю поддержки: /reply <user_id> текст"""
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split(maxsplit=2)
        if len(parts) < 3:
            raise ValueError
        target_uid = int(parts[1])
        reply_text = parts[2]
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"<b>👨‍💼 Ответ поддержки LexGuard:</b>\n\n{reply_text}",
            parse_mode="HTML",
        )
        await update.message.reply_text("✅ Ответ отправлен пользователю!")
    except Exception:
        await update.message.reply_text("❌ Формат: /reply <user_id> <текст ответа>")

"""
LexGuard AML Telegram Bot
------------------------
Многофункциональный Telegram-бот для проверки криптовалютных кошельков и транзакций на риски (AML), генерации PDF-отчётов с цифровой подписью, приёма платежей USDT TRC20, поддержки ручного и автоматического режимов, панели администратора и расширенной аналитики.

Возможности:
- Быстрая проверка кошельков и транзакций (AI/ручной режим)
- Генерация PDF-отчётов с цифровой подписью
- Приём оплаты USDT TRC20
- Панель администратора
- История запросов, статистика, справка
- Многоязычность (RU/EN, TODO)
- Расширяемая архитектура (TODO: вынести обработчики в модули)
"""

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
from typing import Tuple, Dict, Any

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
TOKEN = "8785738588:AAGAG07a8miJwbYWBT6IYX6ZgeE7ivBg88M"
ADMIN_USER_ID = 8061332993

BOT_NAME = "LexGuard AML"
BOT_TAGLINE = "Premium Wallet Screening & Compliance"

FULL_REPORT_PRICE_USD = Decimal("1400")
PAYMENT_NETWORK = "USDT TRC20"
PAYMENT_WALLET = "TRND8fBYLQWuy8xMpmRcq77eTLWrdbBH61"
REPORT_SIGNING_SECRET = os.getenv(
    "lexguard_aml_pdf_seal_9f3c7a1e_2026", "CHANGE_THIS_LEXGUARD_SECRET"
)

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRONGRID_API_BASE = os.getenv("TRONGRID_API_BASE", "https://api.trongrid.io").rstrip("/")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_HASH_RE = re.compile(r"^(0x)?[A-Fa-f0-9]{32,64}$")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger("lexguard_pro")

# TODO: Вынести обработчики команд и вспомогательные функции в отдельные модули для масштабируемости.


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



    c.setFillColor(HexColor("#0F172A"))
    """
    Generate a PDF report in English or Russian (lang="ENG" or "RUS").
    """
    # English and Russian labels
    labels = {
        "ENG": {
            "title": "LexGuard AML",
            "subtitle": "Premium Manual Audit",
            "report": "Custom Manual Audit Report",
            "report_id": "REPORT ID",
            "issued": "ISSUED",
            "risk": "RISK",
            "score": "SCORE",
            "client_target": "Client Target",
            "network": "Network",
            "status": "Status",
            "methodology": "Methodology",
            "methodology_val": "Custom Manual Report by LexGuard AML Company",
            "payment_network": "Payment Network",
            "payment_hash": "Payment Hash",
            "flags": "Flags Detected",
            "summary": "Summary",
            "signature": "Digital Signature",
            "signature_note": "This signature confirms report integrity and issuance by LexGuard AML.",
            "disclaimer": "Disclaimer: This report is provided for informational and compliance screening purposes only. It does not constitute legal, financial, or investment advice.",
        },
        "RUS": {
            "title": "LexGuard AML",
            "subtitle": "Премиальный ручной аудит",
            "report": "Индивидуальный ручной отчет",
            "report_id": "ID ОТЧЕТА",
            "issued": "ВЫДАНО",
            "risk": "РИСК",
            "score": "ОЦЕНКА",
            "client_target": "Клиентский адрес",
            "network": "Сеть",
            "status": "Статус",
            "methodology": "Методология",
            "methodology_val": "Ручной отчет компании LexGuard AML",
            "payment_network": "Платежная сеть",
            "payment_hash": "Хеш платежа",
            "flags": "Обнаруженные флаги",
            "summary": "Резюме",
            "signature": "Цифровая подпись",
            "signature_note": "Данная подпись подтверждает целостность и выпуск отчета LexGuard AML.",
            "disclaimer": "Отказ от ответственности: данный отчет предоставлен только для информационных и комплаенс-целей. Не является юридической, финансовой или инвестиционной рекомендацией.",
        },
    }
    L = labels[lang.upper()] if lang.upper() in labels else labels["ENG"]
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

    left_x = 58
    right_x = 305
    y_left = info_top - 24
    y_right = info_top - 24

    y_left = _draw_label_value(c, L["client_target"], target, left_x, y_left, 215)
    y_left = _draw_label_value(c, L["network"], network, left_x, y_left, 215)
    y_left = _draw_label_value(c, L["status"], profile["status"], left_x, y_left, 215)
    y_left = _draw_label_value(
        c,
        L["methodology"],
        L["methodology_val"],
        left_x,
        y_left,
        215,
    )

    y_right = _draw_label_value(
        c, L["payment_network"], PAYMENT_NETWORK, right_x, y_right, 220
    )
    y_right = _draw_label_value(c, L["payment_hash"], payment_ref, right_x, y_right, 220)
    y_right = _draw_label_value(
        c, L["flags"], profile["flags"], right_x, y_right, 220
    )

    summary_y = info_top - 152
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left_x, summary_y, L["summary"])

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
    c.drawString(58, sig_box_y - 20, L["signature"])

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
        L["signature_note"],
    )

    _draw_digital_seal(c, width - 100, sig_box_y - 46, signature[:10])

    _draw_multiline(
        c,
        L["disclaimer"],
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
    return buffer, f"{report_id}.pdf"
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
        "Custom Manual Report by LexGuard AML Company",
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
    return buffer, f"{report_id}.pdf"


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Quick Scan (Free)", callback_data="scan")],
            [InlineKeyboardButton("🛡 Custom Manual Audit", callback_data="report")],
            [InlineKeyboardButton("💳 Services & Pricing", callback_data="pricing")],
            [InlineKeyboardButton("🌐 About LexGuard", callback_data="about")],
            [InlineKeyboardButton("💬 Support Chat", callback_data="support")],
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

    BANNER_URL = "https://raw.githubusercontent.com/Artssoffs/lexguard-bot/main/lexguard_banner.png"

    await update.message.reply_photo(
        photo=BANNER_URL,
        caption="🛡 <b>LexGuard AML</b>\n<i>Premium Wallet Screening</i>",
        parse_mode="HTML",
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
            await update.message.reply_text("❌ Request not found or already answered.")
            return

        report = (
            f"<b>📊 LEXGUARD MANUAL SCAN RESULT</b>\n\n"
            f"<b>Target:</b> <code>{pending['target']}</code>\n"
            f"<b>Risk Level:</b> {risk_badge(risk)}\n"
            f"<b>Threat Score:</b> {score}/100\n\n"
            f"<i>Engine: LexGuard Deep Manual Scan | {now_utc()}</i>"
        )

        await context.bot.edit_message_text(
            chat_id=pending["chat_id"],
            message_id=pending["msg_id"],
            text=report,
            parse_mode="HTML",
            reply_markup=back_menu(),
        )
        await update.message.reply_text("✅ Result sent to client!")
    except Exception:
        await update.message.reply_text(
            "❌ Format: /res <ID> <LOW/MEDIUM/HIGH> <SCORE>"
        )


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data, uid = q.data, q.from_user.id

    # --- Support Chat ---
    if data == "support":
        context.user_data["flow"] = "support_chat"
        await q.edit_message_text(
            "<b>💬 Поддержка LexGuard</b>\n\nОпишите ваш вопрос или проблему. Наш оператор ответит вам прямо здесь!\n\n<b>Для выхода — /exit</b>",
            parse_mode="HTML",
            reply_markup=back_menu(),
        )
        return

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
            "🛡 <b>Custom Manual Report by LexGuard AML</b>\n\n"
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
        await q.edit_message_text(
            "💸 Please send your USDT TRC20 payment and then enter the transaction hash.",
            parse_mode="HTML",
            reply_markup=back_menu(),
        )

    # ...existing code...


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", lambda u, c: u.message.reply_text(
        "⚙️ Admin Panel",
        reply_markup=admin_menu(c),
    ) if is_admin(u.effective_user.id) else None))
    app.add_handler(CommandHandler("res", admin_res))
    app.add_handler(CommandHandler("ENG", set_lang_eng))
    app.add_handler(CommandHandler("RUS", set_lang_rus))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("LexGuard Pro Intercept Module Active.")
    app.run_polling()
