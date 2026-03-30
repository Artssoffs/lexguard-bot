code
Python
download
content_copy
expand_less
import os
import re
import hmac
import logging
import hashlib
import random
import textwrap
import asyncio
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
    PicklePersistence,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

# =========================
# CONFIGURATION PRO 5.3 (Upgraded)
# =========================
# Безопасное получение токенов из переменных окружения
TOKEN = os.getenv("BOT_TOKEN", "ЗДЕСЬ_ВАШ_ТОКЕН") 
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "8061332993"))
REPORT_SIGNING_SECRET = os.getenv("REPORT_SIGNING_SECRET", "CHANGE_THIS_LEXGUARD_SECRET")

BOT_NAME = "LexGuard AML"
BOT_TAGLINE = "Premium Wallet Screening & Compliance"

FULL_REPORT_PRICE_USD = Decimal("1400")
PAYMENT_NETWORK = "USDT TRC20"
PAYMENT_WALLET = "TRND8fBYLQWuy8xMpmRcq77eTLWrdbBH61"

TRON_ADDRESS_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_HASH_RE = re.compile(r"^(0x)?[A-Fa-f0-9]{32,64}$")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("lexguard_pro")

# =========================
# LOCALIZATION (I18N)
# =========================
UI_TEXTS = {
    "ENG": {
        "welcome": f"🛡 <b>{BOT_NAME}</b>\n<i>{BOT_TAGLINE}</i>\n\nSelect an action:",
        "pricing": f"💳 <b>Services & Pricing</b>\n\n• <b>Quick AI Scan:</b> Free (Basic scoring)\n• <b>Custom Manual Audit:</b> ${FULL_REPORT_PRICE_USD} (Detailed audit by our expert team)\n\n<i>We guarantee complete confidentiality.</i>",
        "about": "🌐 <b>About LexGuard</b>\n\nLexGuard AML is a cutting-edge solution to protect your business from illicit cryptocurrency.\n\nWe conduct comprehensive blockchain analysis, identifying links to Darknet, mixers, and sanction lists.",
        "support": "💬 <b>Support Chat</b>\n\nSend your message, and it will be forwarded to admin.",
        "btn_scan": "🔍 Quick Scan (Free)",
        "btn_report": "🛡 Custom Manual Audit",
        "btn_pricing": "💳 Services & Pricing",
        "btn_about": "🌐 About LexGuard",
        "btn_support": "💬 Support Chat",
        "btn_settings": "⚙️ Settings (Language)",
        "btn_back": "⬅ Main Menu",
        "scan_prompt": "<b>Send wallet address or TX hash:</b>",
        "report_prompt": "<b>Send wallet address for the report:</b>",
        "settings_prompt": "⚙️ <b>Settings</b>\n\nSelect your preferred language:",
        "payment_instruction": f"💸 <b>Payment Instructions</b>\n\nSend <b>${FULL_REPORT_PRICE_USD} USDT</b> (TRC20) to:\n\n<code>{PAYMENT_WALLET}</code>\n\nAfter payment, send the transaction hash here.",
        "processing": "⏳ Processing your request...",
        "verifying": "⏳ Verifying payment...",
        "generating": "⏳ Generating custom PDF report...",
        "support_sent": "✅ Message sent to support. Please wait for a reply.",
        "err_start": "❌ Error. Please start again with /start",
    },
    "RUS": {
        "welcome": f"🛡 <b>{BOT_NAME}</b>\n<i>{BOT_TAGLINE}</i>\n\nВыберите действие:",
        "pricing": f"💳 <b>Услуги и Цены</b>\n\n• <b>Быстрый ИИ Скан:</b> Бесплатно (Базовая оценка)\n• <b>Ручной Премиум Аудит:</b> ${FULL_REPORT_PRICE_USD} (Детальный аудит командой экспертов)\n\n<i>Мы гарантируем полную конфиденциальность.</i>",
        "about": "🌐 <b>О LexGuard</b>\n\nLexGuard AML — это передовое решение для защиты вашего бизнеса от нелегальной криптовалюты.\n\nМы проводим комплексный анализ блокчейна, выявляя связи с Darknet, миксерами и санкционными списками.",
        "support": "💬 <b>Поддержка</b>\n\nОтправьте ваше сообщение, и оно будет передано администратору.",
        "btn_scan": "🔍 Быстрый скан (Бесплатно)",
        "btn_report": "🛡 Ручной Премиум Аудит",
        "btn_pricing": "💳 Услуги и Цены",
        "btn_about": "🌐 О проекте",
        "btn_support": "💬 Поддержка",
        "btn_settings": "⚙️ Настройки (Язык)",
        "btn_back": "⬅ Главное меню",
        "scan_prompt": "<b>Отправьте адрес кошелька или TX хеш:</b>",
        "report_prompt": "<b>Отправьте адрес кошелька для создания отчета:</b>",
        "settings_prompt": "⚙️ <b>Настройки</b>\n\nВыберите предпочитаемый язык:",
        "payment_instruction": f"💸 <b>Инструкция по оплате</b>\n\nОтправьте <b>${FULL_REPORT_PRICE_USD} USDT</b> (TRC20) на адрес:\n\n<code>{PAYMENT_WALLET}</code>\n\nПосле оплаты отправьте сюда хеш транзакции (TXID).",
        "processing": "⏳ Обработка вашего запроса...",
        "verifying": "⏳ Проверка платежа...",
        "generating": "⏳ Генерация PDF отчета...",
        "support_sent": "✅ Сообщение отправлено в поддержку. Ожидайте ответа.",
        "err_start": "❌ Ошибка. Пожалуйста, начните заново через /start",
    }
}

def get_t(context: ContextTypes.DEFAULT_TYPE, key: str) -> str:
    lang = context.user_data.get("lang", "ENG")
    return UI_TEXTS.get(lang, UI_TEXTS["ENG"]).get(key, f"Missing text: {key}")

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
    badges = {"LOW": "🟢 LOW", "MEDIUM": "🟡 MEDIUM", "HIGH": "🔴 HIGH", "CRITICAL": "⛔ CRITICAL"}
    return badges.get(risk.upper(), "⚪ UNKNOWN")

def normalize_risk(risk_str: str) -> str:
    r = risk_str.upper()
    return r if r in["LOW", "MEDIUM", "HIGH", "CRITICAL"] else "LOW"

def _sign_report(payload: str) -> str:
    signature = hmac.new(REPORT_SIGNING_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return signature.upper()

def _risk_profile(risk: str, lang: str = "ENG"):
    profiles = {
        "ENG": {
            "LOW": {"color": HexColor("#10B981"), "status": "✅ Clean", "flags": "None detected", "summary": "No significant risk indicators found. Wallet appears legitimate with normal transaction patterns."},
            "MEDIUM": {"color": HexColor("#F59E0B"), "status": "⚠️ Moderate Risk", "flags": "Minor flags detected", "summary": "Some suspicious activity detected. Recommend additional due diligence before proceeding."},
            "HIGH": {"color": HexColor("#EF4444"), "status": "🚫 High Risk", "flags": "Multiple red flags", "summary": "Significant risk indicators present. Strong links to suspicious entities or activities detected."}
        },
        "RUS": {
            "LOW": {"color": HexColor("#10B981"), "status": "✅ Чисто", "flags": "Не обнаружено", "summary": "Значительных индикаторов риска не найдено. Кошелек выглядит легитимным с нормальными паттернами транзакций."},
            "MEDIUM": {"color": HexColor("#F59E0B"), "status": "⚠️ Умеренный риск", "flags": "Обнаружены незначительные флаги", "summary": "Обнаружена некоторая подозрительная активность. Рекомендуется дополнительная проверка."},
            "HIGH": {"color": HexColor("#EF4444"), "status": "🚫 Высокий риск", "flags": "Множественные красные флаги", "summary": "Присутствуют значительные индикаторы риска. Обнаружены прочные связи с подозрительными субъектами."}
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
        "ENG": {"title": "LexGuard AML", "subtitle": "Premium Manual Audit", "report": "Custom Manual Audit Report", "report_id": "REPORT ID", "issued": "ISSUED", "risk": "RISK", "score": "SCORE", "client_target": "Client Target", "network": "Network", "status": "Status", "methodology": "Methodology", "methodology_val": "Custom Manual Report by LexGuard AML", "payment_network": "Payment Network", "payment_hash": "Payment Hash", "flags": "Flags Detected", "summary": "Summary", "signature": "Digital Signature", "signature_note": "This signature confirms report integrity and issuance by LexGuard AML.", "disclaimer": "Disclaimer: This report is provided for informational and compliance screening purposes only."},
        "RUS": {"title": "LexGuard AML", "subtitle": "Премиальный ручной аудит", "report": "Индивидуальный ручной отчет", "report_id": "ID ОТЧЕТА", "issued": "ВЫДАНО", "risk": "РИСК", "score": "ОЦЕНКА", "client_target": "Клиентский адрес", "network": "Сеть", "status": "Статус", "methodology": "Методология", "methodology_val": "Ручной отчет компании LexGuard AML", "payment_network": "Платежная сеть", "payment_hash": "Хеш платежа", "flags": "Обнаруженные флаги", "summary": "Резюме", "signature": "Цифровая подпись", "signature_note": "Данная подпись подтверждает целостность и выпуск отчета LexGuard AML.", "disclaimer": "Отказ от ответственности: данный отчет предоставлен только для информационных и комплаенс-целей."}
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
def main_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_t(context, "btn_scan"), callback_data="scan")],
        [InlineKeyboardButton(get_t(context, "btn_report"), callback_data="report")],
        [InlineKeyboardButton(get_t(context, "btn_pricing"), callback_data="pricing")],[
            InlineKeyboardButton(get_t(context, "btn_about"), callback_data="about"),
            InlineKeyboardButton(get_t(context, "btn_support"), callback_data="support"),
        ],[InlineKeyboardButton(get_t(context, "btn_settings"), callback_data="settings")],
    ])

def back_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(get_t(context, "btn_back"), callback_data="back")]])

def settings_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    lang = context.user_data.get("lang", "ENG")
    return InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{'✅ ' if lang == 'ENG' else ''}English", callback_data="lang:ENG"),
            InlineKeyboardButton(f"{'✅ ' if lang == 'RUS' else ''}Русский", callback_data="lang:RUS"),
        ],[InlineKeyboardButton(get_t(context, "btn_back"), callback_data="back")]
    ])

def admin_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    state = get_state(context)
    return InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{'✅ ' if state['risk_mode'] == 'auto' else ''}Auto AI", callback_data="mode:auto"),
            InlineKeyboardButton(f"{'✅ ' if state['risk_mode'] == 'manual' else ''}Manual Intercept", callback_data="mode:manual"),
        ],
        [InlineKeyboardButton("⬅ Main Menu", callback_data="back")],
    ])

def admin_status_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    state = get_state(context)
    return f"⚙️ <b>Admin Panel</b>\n\nCurrent mode: <b>{state['risk_mode'].upper()}</b>"


# =========================
# COMMAND HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_flow(context)
    
    # Пытаемся открыть локальную картинку, если нет - берем по ссылке
    try:
        photo = open("lexguard_banner.png", "rb")
    except FileNotFoundError:
        photo = "https://raw.githubusercontent.com/Artssoffs/lexguard-bot/main/lexguard_banner.png"

    await update.message.reply_photo(
        photo=photo,
        caption=get_t(context, "welcome"),
        parse_mode="HTML",
        reply_markup=main_menu(context)
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text(admin_status_text(context), parse_mode="HTML", reply_markup=admin_menu(context))

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split(maxsplit=2)
        if len(parts) < 3: raise ValueError("Format error")
        target_uid = int(parts[1])
        reply_text = parts[2]
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"<b>👨‍💼 LexGuard Support:</b>\n\n{reply_text}",
            parse_mode="HTML",
        )
        await update.message.reply_text("✅ Ответ успешно отправлен пользователю!")
    except ValueError:
        await update.message.reply_text("❌ Формат: /reply <user_id> <текст ответа>")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка отправки (Возможно, юзер заблокировал бота): {e}")

async def admin_res(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        if len(parts) != 4: raise ValueError("Format error")
        target_uid = int(parts[1])
        risk = parts[2].upper()
        score = int(parts[3])

        pending = context.bot_data.get("pending_scans", {}).pop(target_uid, None)
        if not pending:
            await update.message.reply_text("❌ Запрос не найден (или уже отвечен).")
            return

        report = (
            f"<b>📊 LEXGUARD MANUAL SCAN RESULT</b>\n\n"
            f"<b>Target:</b> <code>{pending['target']}</code>\n"
            f"<b>Risk Level:</b> {risk_badge(risk)}\n"
            f"<b>Threat Score:</b> {score}/100\n\n"
            f"<i>Engine: LexGuard Deep Manual Scan | {now_utc()}</i>"
        )
        await context.bot.edit_message_text(chat_id=pending["chat_id"], message_id=pending["msg_id"], text=report, parse_mode="HTML", reply_markup=back_menu(context))
        await update.message.reply_text("✅ Результат отправлен клиенту!")
    except ValueError:
        await update.message.reply_text("❌ Формат: /res <ID> <LOW/MEDIUM/HIGH> <SCORE>")
    except Exception as e:
        await update.message.reply_text(f"❌ Критическая ошибка: {e}")

async def admin_auditres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        if len(parts) != 4: raise ValueError("Format error")
        target_uid = int(parts[1])
        risk = parts[2].upper()
        score = int(parts[3])

        if risk not in {"LOW", "MEDIUM", "HIGH"}: raise ValueError("Invalid risk")

        pending = context.bot_data.get("pending_audits", {}).pop(target_uid, None)
        if not pending:
            await update.message.reply_text("❌ Запрос на аудит не найден.")
            return

        pdf_buffer, pdf_name = make_report_file(pending["target"], pending["payment_ref"], risk, score, pending["lang"])

        await context.bot.send_document(
            chat_id=pending["chat_id"],
            document=pdf_buffer,
            filename=pdf_name,
            caption=(
                f"✅ <b>Your Custom Manual Audit Report</b>\n\n"
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
                text=f"✅ <b>Manual audit completed</b>\n\n<b>Target:</b> <code>{pending['target']}</code>\n<b>Risk Level:</b> {risk_badge(risk)}\n<b>Threat Score:</b> {score}/100",
                parse_mode="HTML",
                reply_markup=back_menu(context),
            )
        except Exception:
            pass
        await update.message.reply_text("✅ PDF отчет отправлен клиенту!")
    except ValueError:
        await update.message.reply_text("❌ Формат: /auditres <ID> <LOW/MEDIUM/HIGH> <SCORE>")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка отправки файла: {e}")


# =========================
# CALLBACK HANDLER
# =========================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer(cache_time=0)
    data = q.data
    uid = q.from_user.id

    if data.startswith("lang:"):
        context.user_data["lang"] = data.split(":")[1]
        await q.edit_message_text(get_t(context, "settings_prompt"), parse_mode="HTML", reply_markup=settings_menu(context))
        return

    if data == "settings":
        await q.edit_message_text(get_t(context, "settings_prompt"), parse_mode="HTML", reply_markup=settings_menu(context))
        return

    if data == "scan":
        context.user_data["flow"] = "scan"
        await q.edit_message_text(get_t(context, "scan_prompt"), parse_mode="HTML", reply_markup=back_menu(context))
        return

    if data == "report":
        context.user_data["flow"] = "report_target"
        await q.edit_message_text(get_t(context, "report_prompt"), parse_mode="HTML", reply_markup=back_menu(context))
        return

    if data == "pricing":
        await q.edit_message_text(get_t(context, "pricing"), parse_mode="HTML", reply_markup=back_menu(context))
        return

    if data == "about":
        await q.edit_message_text(get_t(context, "about"), parse_mode="HTML", reply_markup=back_menu(context))
        return

    if data == "support":
        context.user_data["flow"] = "support_chat"
        await q.edit_message_text(get_t(context, "support"), parse_mode="HTML", reply_markup=back_menu(context))
        return

    if data == "back":
        clear_flow(context)
        await q.edit_message_text(get_t(context, "welcome"), parse_mode="HTML", reply_markup=main_menu(context))
        return

    # Админские коллбеки
    if data.startswith("mode:") and is_admin(uid):
        state = get_state(context)
        state["risk_mode"] = data.split(":", 1)[1]
        await q.edit_message_text(admin_status_text(context), parse_mode="HTML", reply_markup=admin_menu(context))


# =========================
# TEXT MESSAGE HANDLER
# =========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    flow = context.user_data.get("flow")
    uid = update.effective_user.id

    if flow == "support_chat":
        await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"<b>💬 Новое сообщение поддержки от {uid} (@{update.effective_user.username}):</b>\n\n{text}\n\n<i>Ответить: /reply {uid} текст</i>", parse_mode="HTML")
        await update.message.reply_text(get_t(context, "support_sent"))
        return

    if flow == "scan":
        state = get_state(context)
        msg = await update.message.reply_text(get_t(context, "processing"))
        
        if state["risk_mode"] == "manual":
            state["pending_scans"][uid] = {"target": text, "chat_id": update.effective_chat.id, "msg_id": msg.message_id}
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=f"🔔 <b>MANUAL SCAN REQUEST</b>\n\nUser: {uid}\nTarget: <code>{text}</code>\n\nRespond with:\n/res {uid} <RISK> <SCORE>", parse_mode="HTML")
            return

        # Имитация работы ИИ в автоматическом режиме
        await asyncio.sleep(2.5) 
        risk, score = random.choice(["LOW", "LOW", "MEDIUM", "HIGH"]), random.randint(10, 90)
        report = f"<b>📊 QUICK SCAN RESULT</b>\n\n<b>Target:</b> <code>{text}</code>\n<b>Network:</b> {detect_network(text)}\n<b>Risk Level:</b> {risk_badge(risk)}\n<b>Threat Score:</b> {score}/100\n\n<i>Engine: LexGuard AI Quick Scan | {now_utc()}</i>\n\nFor detailed audit, use /start → Custom Manual Audit"
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg.message_id, text=report, parse_mode="HTML", reply_markup=back_menu(context))
        clear_flow(context)

    elif flow == "report_target":
        context.user_data["report_target"] = text
        context.user_data["flow"] = "report_tx"
        await update.message.reply_text(get_t(context, "payment_instruction"), parse_mode="HTML", reply_markup=back_menu(context))

    elif flow == "report_tx":
        target = context.user_data.get("report_target")
        if not target:
            await update.message.reply_text(get_t(context, "err_start"))
            return

        lang = context.user_data.get("lang", "ENG")
        state = get_state(context)
        
        msg_wait = await update.message.reply_text(get_t(context, "verifying"), parse_mode="HTML")

        if state["risk_mode"] == "manual":
            state["pending_audits"][uid] = {
                "target": target, "payment_ref": text, "chat_id": update.effective_chat.id, "msg_id": msg_wait.message_id, "lang": lang,
            }
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"🛡 <b>PAID MANUAL AUDIT REQUEST</b>\n\n👤 User: <code>{uid}</code>\n🎯 Target: <code>{target}</code>\n💳 Payment TX: <code>{text}</code>\n🌐 Language: <b>{lang}</b>\n\nRespond with:\n<code>/auditres {uid} LOW 15</code>\n<code>/auditres {uid} MEDIUM 55</code>\n<code>/auditres {uid} HIGH 89</code>",
                parse_mode="HTML",
            )
            return

        # Имитация проверки и генерации PDF
        await asyncio.sleep(2)
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_wait.message_id, text=get_t(context, "generating"))
        await asyncio.sleep(2)
        
        risk, score = random.choice(["LOW", "MEDIUM", "HIGH"]), random.randint(20, 95)
        pdf_buffer, pdf_name = make_report_file(target, text, risk, score, lang)
        
        await update.message.reply_document(
            document=pdf_buffer,
            filename=pdf_name,
            caption=f"✅ <b>Your Custom Manual Audit Report</b>\n\n<b>Target:</b> <code>{target}</code>\n<b>Risk Level:</b> {risk_badge(risk)}\n<b>Threat Score:</b> {score}/100\n\n<i>Report ID: {pdf_name}</i>",
            parse_mode="HTML",
        )
        clear_flow(context)

# =========================
# MAIN
# =========================
def main():
    if TOKEN == "ЗДЕСЬ_ВАШ_ТОКЕН" or not TOKEN:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Не установлен BOT_TOKEN в переменных окружения!")
        return

    # Создаем папку data, если её нет (для Railway Volume)
    os.makedirs("/app/data", exist_ok=True)
    persistence = PicklePersistence(filepath="/app/data/lexguard_data.pickle")

    app = ApplicationBuilder().token(TOKEN).persistence(persistence).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("res", admin_res))
    app.add_handler(CommandHandler("auditres", admin_auditres))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("✅ LexGuard Pro Intercept Module Active (With Persistence & I18N).")
    app.run_polling()

if __name__ == "__main__":
    main()
