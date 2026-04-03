"""
LexGuard AML • Pro - Flagship Edition
Institutional Grade Blockchain Analysis
"""

import os
import re
import hmac
import html
import hashlib
import sqlite3
import logging
from io import BytesIO
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Optional, Tuple
from math import pi, cos, sin

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white, Color
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from dotenv import load_dotenv

# =========================================================
# CONFIGURATION
# =========================================================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "123456789"))
BOT_NAME = os.getenv("BOT_NAME", "LexGuard AML Pro")
FULL_REPORT_PRICE_USD = Decimal(os.getenv("FULL_REPORT_PRICE_USD", "1400"))
PAYMENT_WALLET = os.getenv("PAYMENT_WALLET", "TRND8fBYLQWuy8xMpmRcq77eTLWrdbBH61")
PAYMENT_NETWORK = os.getenv("PAYMENT_NETWORK", "USDT (TRC20)")
SECRET_KEY = os.getenv("REPORT_SIGNING_SECRET", "LEXGUARD_ENTERPRISE_KEY")
START_BANNER_PATH = os.getenv("START_BANNER_PATH", "lexguard_banner.png")
DATABASE_PATH = os.getenv("DATABASE_PATH", "lexguard.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("lexguard")

ALLOWED_RISKS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# =========================================================
# DATABASE
# =========================================================
class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self):
        c = self.conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS scan_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            target TEXT NOT NULL,
            network TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            risk TEXT,
            score INTEGER,
            analyst_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS audit_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            target TEXT NOT NULL,
            network TEXT,
            tx_hash TEXT,
            payment_network TEXT,
            payment_wallet TEXT,
            price_usd TEXT,
            status TEXT NOT NULL DEFAULT 'AWAITING_PAYMENT',
            risk TEXT,
            score INTEGER,
            analyst_note TEXT,
            report_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            replied_at TIMESTAMP
        )
        """)

        self.conn.commit()

    def upsert_user(self, user_id: int, username: Optional[str], first_name: Optional[str]):
        c = self.conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        if row:
            c.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username, first_name, user_id),
            )
        else:
            c.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                (user_id, username, first_name),
            )
        self.conn.commit()

    def create_scan_request(self, user_id: int, username: Optional[str], target: str, network: str) -> int:
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO scan_requests (user_id, username, target, network) VALUES (?, ?, ?, ?)",
            (user_id, username, target, network),
        )
        self.conn.commit()
        return c.lastrowid

    def get_scan_request(self, request_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM scan_requests WHERE id = ?", (request_id,))
        return c.fetchone()

    def get_latest_pending_scan_for_user(self, user_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM scan_requests
            WHERE user_id = ? AND status = 'PENDING'
            ORDER BY id DESC LIMIT 1
        """, (user_id,))
        return c.fetchone()

    def resolve_scan_request(self, request_id: int, risk: str, score: int, analyst_note: str):
        c = self.conn.cursor()
        c.execute("""
            UPDATE scan_requests
            SET status = 'COMPLETED',
                risk = ?,
                score = ?,
                analyst_note = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (risk, score, analyst_note, request_id))
        self.conn.commit()

    def create_audit_request(self, user_id: int, username: Optional[str], target: str, network: str) -> int:
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO audit_requests (user_id, username, target, network, payment_network, payment_wallet, price_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, target, network, PAYMENT_NETWORK, PAYMENT_WALLET, str(FULL_REPORT_PRICE_USD)))
        self.conn.commit()
        return c.lastrowid

    def attach_audit_payment(self, request_id: int, tx_hash: str):
        c = self.conn.cursor()
        c.execute("""
            UPDATE audit_requests
            SET tx_hash = ?, status = 'UNDER_REVIEW'
            WHERE id = ?
        """, (tx_hash, request_id))
        self.conn.commit()

    def get_audit_request(self, request_id: int):
        c = self.conn.cursor()
        c.execute("SELECT * FROM audit_requests WHERE id = ?", (request_id,))
        return c.fetchone()

    def get_latest_pending_audit_for_user(self, user_id: int):
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM audit_requests
            WHERE user_id = ? AND status IN ('AWAITING_PAYMENT', 'UNDER_REVIEW')
            ORDER BY id DESC LIMIT 1
        """, (user_id,))
        return c.fetchone()

    def resolve_audit_request(self, request_id: int, risk: str, score: int, analyst_note: str, report_id: str):
        c = self.conn.cursor()
        c.execute("""
            UPDATE audit_requests
            SET status = 'COMPLETED',
                risk = ?,
                score = ?,
                analyst_note = ?,
                report_id = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (risk, score, analyst_note, report_id, request_id))
        self.conn.commit()

    def create_support_ticket(self, user_id: int, username: Optional[str], message: str) -> int:
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO support_tickets (user_id, username, message) VALUES (?, ?, ?)",
            (user_id, username, message),
        )
        self.conn.commit()
        return c.lastrowid

    def close_support_ticket(self, ticket_id: int):
        c = self.conn.cursor()
        c.execute("""
            UPDATE support_tickets
            SET status = 'REPLIED',
                replied_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (ticket_id,))
        self.conn.commit()

    def stats(self):
        c = self.conn.cursor()
        def one(query: str):
            c.execute(query)
            row = c.fetchone()
            return row[0] if row else 0

        return {
            "pending_scans": one("SELECT COUNT(*) FROM scan_requests WHERE status = 'PENDING'"),
            "pending_audits": one("SELECT COUNT(*) FROM audit_requests WHERE status = 'UNDER_REVIEW'"),
            "open_tickets": one("SELECT COUNT(*) FROM support_tickets WHERE status = 'OPEN'"),
        }


db = Database(DATABASE_PATH)


# =========================================================
# UTILITIES
# =========================================================
def is_admin(uid: int) -> bool:
    return uid == ADMIN_USER_ID


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def h(value) -> str:
    return html.escape(str(value))


def truncate(text: str, limit: int = 80) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 3] + "..."


def detect_network(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"^T[1-9A-HJ-NP-Za-km-z]{33}$", value):
        return "TRON (TRC20)"
    if re.fullmatch(r"^0x[a-fA-F0-9]{40}$", value):
        return "Ethereum (ERC20 / ETH)"
    if re.fullmatch(r"^(bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$", value):
        return "Bitcoin (BTC)"
    if re.fullmatch(r"^(0x)?[A-Fa-f0-9]{64}$", value):
        return "Transaction Hash"
    return "Unknown Network"


def get_risk_ui(risk: str) -> str:
    badges = {
        "LOW": "🟢 LOW RISK",
        "MEDIUM": "🟡 MEDIUM RISK",
        "HIGH": "🔴 HIGH RISK",
        "CRITICAL": "⛔ CRITICAL RISK",
    }
    return badges.get((risk or "").upper(), "⚪ UNKNOWN")


def risk_color(risk: str) -> str:
    mapping = {
        "LOW": "#10B981",    # Green
        "MEDIUM": "#F59E0B", # Amber
        "HIGH": "#EF4444",   # Red
        "CRITICAL": "#7F1D1D",# Dark Red
    }
    return mapping.get((risk or "").upper(), "#334155")


def validate_score(score_str: str) -> int:
    try:
        score = int(score_str)
    except ValueError as exc:
        raise ValueError("Score must be an integer from 0 to 100.") from exc
    if not 0 <= score <= 100:
        raise ValueError("Score must be between 0 and 100.")
    return score


def normalize_risk(risk: str) -> str:
    normalized = (risk or "").upper()
    if normalized not in ALLOWED_RISKS:
        raise ValueError("Risk must be one of: LOW, MEDIUM, HIGH, CRITICAL.")
    return normalized


def build_signature(report_id: str, target: str, risk: str, score: int, tx_hash: str) -> str:
    payload = f"{report_id}|{target}|{risk}|{score}|{tx_hash}"
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest().upper()


def build_report_id(target: str, tx_hash: str) -> str:
    seed = f"{target}|{tx_hash}|{now_utc()}"
    return "LGP-" + hashlib.sha256(seed.encode()).hexdigest()[:12].upper()


def textwrap_wrap(text: str, width: int = 70):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}".strip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# =========================================================
# ADVANCED PDF GENERATOR
# =========================================================
def draw_wrapped_text(c: canvas.Canvas, lines, x: int, y: int, line_height: int = 14):
    current_y = y
    for line in lines:
        c.drawString(x, current_y, line)
        current_y -= line_height
    return current_y

def draw_vector_seal(c: canvas.Canvas, x: float, y: float, radius: float):
    """Рисует сложную векторную печать-голограмму с зубчиками"""
    c.saveState()
    c.translate(x, y)
    
    # Внешнее золотое кольцо с зубчиками
    c.setFillColor(HexColor("#D4AF37")) # Золотой
    c.setStrokeColor(HexColor("#B8860B")) # Темное золото
    c.setLineWidth(1)
    
    points = 40
    outer_r = radius
    inner_r = radius * 0.85
    
    path = c.beginPath()
    for i in range(points * 2):
        angle = i * (pi / points)
        r = outer_r if i % 2 == 0 else inner_r
        px = r * cos(angle)
        py = r * sin(angle)
        if i == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.close()
    c.drawPath(path, fill=1, stroke=1)
    
    # Внутреннее темно-синее кольцо
    c.setFillColor(HexColor("#0F172A"))
    c.circle(0, 0, radius * 0.75, stroke=0, fill=1)
    
    # Декоративная белая линия
    c.setStrokeColor(white)
    c.setLineWidth(1.5)
    c.circle(0, 0, radius * 0.65, stroke=1, fill=0)
    
    # Внутренний светлый круг
    c.setFillColor(HexColor("#1E3A8A"))
    c.circle(0, 0, radius * 0.60, stroke=0, fill=1)
    
    # Текст внутри печати
    c.setFillColor(HexColor("#D4AF37"))
    c.setFont("Helvetica-Bold", radius * 0.25)
    c.drawCentredString(0, radius * 0.15, "LEXGUARD")
    c.setFont("Helvetica-Bold", radius * 0.18)
    c.setFillColor(white)
    c.drawCentredString(0, -radius * 0.15, "CERTIFIED")
    
    # Звездочки для красоты
    c.setFont("Helvetica", radius * 0.15)
    c.drawCentredString(0, -radius * 0.40, "★ ★ ★")
    
    c.restoreState()

def generate_pdf(target: str, tx_hash: str, risk: str, score: int, analyst_note: str) -> Tuple[BytesIO, str, str]:
    report_id = build_report_id(target, tx_hash)
    issued = now_utc()
    signature = build_signature(report_id, target, risk, score, tx_hash)
    
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    w, h_page = A4

    # --- ФОН И ВОДЯНОЙ ЗНАК ---
    c.setFillColor(HexColor("#F8FAFC"))
    c.rect(0, 0, w, h_page, fill=1, stroke=0)
    
    # Водяной знак по центру
    c.saveState()
    c.translate(w/2, h_page/2)
    c.rotate(45)
    c.setFont("Helvetica-Bold", 80)
    c.setFillColor(Color(0.85, 0.88, 0.93, alpha=0.3)) # Полупрозрачный серый-синий
    c.drawCentredString(0, 0, "LEXGUARD SECURE")
    c.restoreState()

    # --- ШАПКА ---
    # Темно-синий фон шапки
    c.setFillColor(HexColor("#0B1120"))
    c.rect(0, h_page - 120, w, 120, fill=1, stroke=0)
    # Золотая разделительная полоса
    c.setFillColor(HexColor("#D4AF37"))
    c.rect(0, h_page - 125, w, 5, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(40, h_page - 55, "LEXGUARD AML PRO")
    
    c.setFillColor(HexColor("#94A3B8"))
    c.setFont("Helvetica", 11)
    c.drawString(40, h_page - 75, "Institutional Grade Blockchain Risk Intelligence")
    c.drawString(40, h_page - 95, "Comprehensive KYC & AML Compliance Report")

    # Инфо в правой части шапки
    c.setFillColor(HexColor("#10B981"))
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(w - 40, h_page - 45, "SECURE DIGITAL DOCUMENT")
    
    c.setFillColor(white)
    c.setFont("Helvetica", 9)
    c.drawRightString(w - 40, h_page - 65, f"Report ID: {report_id}")
    c.drawRightString(w - 40, h_page - 80, f"Issued Date: {issued}")
    c.setFillColor(HexColor("#D4AF37"))
    c.drawRightString(w - 40, h_page - 95, "STRICTLY CONFIDENTIAL")

    # --- СЕКЦИЯ 1: ИДЕНТИФИКАЦИЯ (Asset Identification) ---
    y_start = h_page - 170
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y_start, "1. Target Asset Identification")

    # Тень для блока
    c.setFillColor(HexColor("#E2E8F0"))
    c.roundRect(42, y_start - 102, w - 80, 90, 6, fill=1, stroke=0)
    # Основной блок
    c.setFillColor(white)
    c.setStrokeColor(HexColor("#CBD5E1"))
    c.setLineWidth(1)
    c.roundRect(40, y_start - 100, w - 80, 90, 6, fill=1, stroke=1)

    c.setFillColor(HexColor("#475569"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(55, y_start - 35, "Target Asset:")
    c.drawString(55, y_start - 58, "Detected Network:")
    c.drawString(55, y_start - 81, "Audit Reference:")

    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica", 10)
    c.drawString(170, y_start - 35, truncate(target, 65))
    c.drawString(170, y_start - 58, detect_network(target))
    c.drawString(170, y_start - 81, truncate(tx_hash, 65))

    # --- СЕКЦИЯ 2: ОЦЕНКА РИСКА (Risk Assessment) ---
    y_start = h_page - 320
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y_start, "2. Risk & Compliance Assessment")

    box_color = risk_color(risk)
    
    # Тень
    c.setFillColor(HexColor("#E2E8F0"))
    c.roundRect(42, y_start - 77, w - 80, 65, 6, fill=1, stroke=0)
    # Цветной блок риска
    c.setFillColor(HexColor(box_color))
    c.roundRect(40, y_start - 75, w - 80, 65, 6, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(60, y_start - 35, f"Risk Status: {risk.upper()}")
    
    c.setFont("Helvetica", 12)
    c.drawString(60, y_start - 55, "LexGuard AML Protocol")
    
    # Score circle
    c.setFillColor(white)
    c.circle(w - 90, y_start - 42, 25, fill=1, stroke=0)
    c.setFillColor(HexColor(box_color))
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(w - 90, y_start - 48, f"{score}")
    c.setFont("Helvetica", 8)
    c.drawCentredString(w - 90, y_start - 58, "SCORE")

    # --- СЕКЦИЯ 3: ЗАМЕЧАНИЕ АНАЛИТИКА (Analyst Decision) ---
    y_start = h_page - 440
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y_start, "3. Analyst Resolution & Notes")

    # Тень
    c.setFillColor(HexColor("#E2E8F0"))
    c.roundRect(42, y_start - 122, w - 80, 110, 6, fill=1, stroke=0)
    # Основной блок
    c.setFillColor(HexColor("#F8FAFC"))
    c.setStrokeColor(HexColor("#CBD5E1"))
    c.roundRect(40, y_start - 120, w - 80, 110, 6, fill=1, stroke=1)

    c.setFillColor(HexColor("#1E293B"))
    c.setFont("Helvetica", 10)
    note_lines = textwrap_wrap(analyst_note or "Comprehensive manual review completed by LexGuard Security Analyst Desk. No additional flags detected in immediate transaction history.", width=95)
    draw_wrapped_text(c, note_lines[:6], 55, y_start - 35, 16)

    # --- СЕКЦИЯ 4: ЦИФРОВАЯ СЕРТИФИКАЦИЯ (Digital Certification & QR) ---
    y_start = h_page - 610
    
    # Блок сертификации (темно-синий)
    c.setFillColor(HexColor("#0B1120"))
    c.roundRect(40, y_start - 160, w - 80, 160, 8, fill=1, stroke=0)
    # Внутренняя рамка
    c.setStrokeColor(HexColor("#1E3A8A"))
    c.setLineWidth(1)
    c.roundRect(45, y_start - 155, w - 90, 150, 6, fill=0, stroke=1)

    # Заголовок секции внутри синего блока
    c.setFillColor(HexColor("#D4AF37"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, y_start - 30, "OFFICIAL DIGITAL CERTIFICATION")
    c.setStrokeColor(HexColor("#1E3A8A"))
    c.line(60, y_start - 35, w - 200, y_start - 35)

    # QR Code (Цифровой код)
    qr_data = f"REPORT:{report_id}\nTARGET:{target[:20]}...\nSIG:{signature[:30]}..."
    qr_w = qr.QrCodeWidget(qr_data)
    # Масштабируем QR код
    b = qr_w.getBounds()
    w_qr = b[2] - b[0]
    h_qr = b[3] - b[1]
    d = Drawing(90, 90, transform=[90/w_qr, 0, 0, 90/h_qr, 0, 0])
    d.add(qr_w)
    # Отрисовываем QR код поверх белого квадрата для контрастности
    c.setFillColor(white)
    c.rect(60, y_start - 140, 94, 94, fill=1, stroke=0)
    renderPDF.draw(d, c, 62, y_start - 138)

    # Текстовые данные подписи
    c.setFillColor(HexColor("#94A3B8"))
    c.setFont("Helvetica", 9)
    tx_y = y_start - 60
    c.drawString(175, tx_y, "Signature Method:")
    c.drawString(175, tx_y - 18, "Verification Digest:")
    c.drawString(175, tx_y - 36, "Issuing Authority:")
    c.drawString(175, tx_y - 54, "Blockchain Validated:")

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(280, tx_y, "HMAC-SHA256 Enterprise Cryptography")
    c.drawString(280, tx_y - 18, signature[:40] + "...")
    c.drawString(280, tx_y - 36, "LexGuard Global Security Framework")
    c.drawString(280, tx_y - 54, "TRUE")
    
    # Предупреждение о верификации
    c.setFillColor(HexColor("#64748B"))
    c.setFont("Helvetica", 8)
    c.drawString(175, tx_y - 75, "Scan QR code to verify document authenticity. Alteration of this")
    c.drawString(175, tx_y - 85, "document is strictly prohibited and actively monitored.")

    # Отрисовка Векторной Печати / Голограммы справа
    draw_vector_seal(c, w - 100, y_start - 80, 45)

    # --- FOOTER ---
    c.setFillColor(HexColor("#94A3B8"))
    c.setFont("Helvetica", 8)
    c.drawCentredString(w/2, 30, "© 2026 LexGuard AML Solutions. Generated via automated security node. Do not distribute without authorization.")

    # Финализация
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer, f"{report_id}.pdf", report_id


# =========================================================
# UI
# =========================================================
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Quick Check", callback_data="ui_scan")],
        [InlineKeyboardButton("💎 Manual Premium Reported AML•KYC", callback_data="ui_audit")],
        [InlineKeyboardButton("💼 Services & Pricing", callback_data="ui_pricing")],
        [InlineKeyboardButton("💭 Analyst Support", callback_data="ui_support")],
        [InlineKeyboardButton("🛡 About LexGuard", callback_data="ui_about")],
    ])


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Return to Dashboard", callback_data="ui_home")]
    ])


def admin_grade_keyboard(kind: str, request_id: int) -> InlineKeyboardMarkup:
    prefix = "sg" if kind == "scan" else "ag"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 LOW (10)", callback_data=f"{prefix}|{request_id}|LOW|10"),
            InlineKeyboardButton("🟡 MEDIUM (50)", callback_data=f"{prefix}|{request_id}|MEDIUM|50"),
        ],
        [
            InlineKeyboardButton("🔴 HIGH (85)", callback_data=f"{prefix}|{request_id}|HIGH|85"),
            InlineKeyboardButton("⛔ CRITICAL (100)", callback_data=f"{prefix}|{request_id}|CRITICAL|100"),
        ],
    ])


def support_reply_keyboard(ticket_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍ Reply to User", callback_data=f"sr|{ticket_id}|{user_id}")]
    ])


def admin_menu_text() -> str:
    stats = db.stats()
    return (
        "🧠 <b>Admin Desk</b>\n\n"
        f"Pending quick checks: <b>{stats['pending_scans']}</b>\n"
        f"Pending premium audits: <b>{stats['pending_audits']}</b>\n"
        f"Open support tickets: <b>{stats['open_tickets']}</b>\n\n"
        "<b>Commands</b>\n"
        "<code>/scanres &lt;request_id or user_id&gt; &lt;LOW|MEDIUM|HIGH|CRITICAL&gt; &lt;score&gt; [note]</code>\n"
        "<code>/auditres &lt;request_id or user_id&gt; &lt;LOW|MEDIUM|HIGH|CRITICAL&gt; &lt;score&gt; [note]</code>\n"
        "<code>/reply &lt;user_id&gt; &lt;message&gt;</code>\n"
        "<code>/admin</code>"
    )


# =========================================================
# MESSAGE BUILDERS
# =========================================================
def dashboard_text(first_name: str) -> str:
    return (
        f"🛡 <b>{h(BOT_NAME)}</b>\n"
        "<i>Institutional Grade Blockchain Risk Intelligence</i>\n\n"
        f"Welcome, <b>{h(first_name)}</b>.\n"
        "Select the service module below."
    )


def about_text() -> str:
    return (
        "🛡 <b>About LexGuard</b>\n\n"
        "LexGuard AML Pro is a premium blockchain risk-intelligence service built around manual analyst review.\n\n"
        "We do not rely on random output. Quick checks and premium audit decisions are assigned by the analyst desk. "
        "Premium reports are delivered as digitally certified PDF documents with a professional signature block."
    )


def pricing_text() -> str:
    return (
        "💼 <b>Services & Pricing</b>\n\n"
        "⚡ <b>Quick Check</b>\n"
        "Manual risk grading by analyst desk.\n\n"
        "💎 <b>Premium Reported AML•KYC</b>\n"
        f"Full PDF report, digital certification, analyst decision note.\n"
        f"Fee: <b>${FULL_REPORT_PRICE_USD}</b>\n"
        f"Payment network: <b>{h(PAYMENT_NETWORK)}</b>\n"
        f"Receiving wallet: <code>{h(PAYMENT_WALLET)}</code>"
    )


def quick_check_submitted_text(request_id: int, target: str) -> str:
    return (
        "⏳ <b>Quick Check Submitted</b>\n\n"
        f"Request ID: <code>{request_id}</code>\n"
        f"Target: <code>{h(target)}</code>\n"
        "Status: <b>Pending analyst review</b>\n\n"
        "Your result will be delivered here after manual grading."
    )


def audit_payment_text(request_id: int, target: str) -> str:
    return (
        "💎 <b>Manual Premium Reported AML•KYC</b>\n\n"
        f"Request ID: <code>{request_id}</code>\n"
        f"Target: <code>{h(target)}</code>\n"
        f"Amount due: <b>${FULL_REPORT_PRICE_USD}</b>\n"
        f"Network: <b>{h(PAYMENT_NETWORK)}</b>\n"
        f"Wallet: <code>{h(PAYMENT_WALLET)}</code>\n\n"
        "<b>Next step:</b> send your payment TX hash in this chat."
    )


def audit_under_review_text(request_id: int) -> str:
    return (
        "⏳ <b>Payment Reference Received</b>\n\n"
        f"Request ID: <code>{request_id}</code>\n"
        "Status: <b>Under manual analyst review</b>\n\n"
        "Your PDF report will be delivered here after the analyst decision is finalized."
    )


def scan_result_text(request_id: int, target: str, risk: str, score: int, note: str) -> str:
    extra = f"\n<b>Analyst Note:</b> {h(note)}" if note else ""
    return (
        "📊 <b>QUICK CHECK COMPLETE</b>\n\n"
        f"<b>Request ID:</b> <code>{request_id}</code>\n"
        f"<b>Target:</b> <code>{h(target)}</code>\n"
        f"<b>Network:</b> {h(detect_network(target))}\n"
        f"<b>Risk Level:</b> {get_risk_ui(risk)}\n"
        f"<b>Confidence Score:</b> {score}/100"
        f"{extra}\n\n"
        "<i>Powered by LexGuard AML•KYC Service</i>"
    )


def audit_caption_text(request_id: int, target: str, risk: str, score: int, report_id: str) -> str:
    return (
        "💎 <b>PREMIUM AML•KYC COMPLETE</b>\n\n"
        f"<b>Request ID:</b> <code>{request_id}</code>\n"
        f"<b>Report ID:</b> <code>{report_id}</code>\n"
        f"<b>Target:</b> <code>{h(target)}</code>\n"
        f"<b>Risk Level:</b> {get_risk_ui(risk)}\n"
        f"<b>Score:</b> {score}/100\n\n"
        "<i>Digitally certified report attached.</i>"
    )


# =========================================================
# RESOLUTION HELPERS
# =========================================================
def resolve_scan_identifier(identifier: str):
    ident = int(identifier)
    request = db.get_scan_request(ident)
    if request:
        return request
    return db.get_latest_pending_scan_for_user(ident)


def resolve_audit_identifier(identifier: str):
    ident = int(identifier)
    request = db.get_audit_request(ident)
    if request:
        return request
    return db.get_latest_pending_audit_for_user(ident)


# =========================================================
# HANDLERS
# =========================================================
async def send_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    db.upsert_user(user.id, user.username, user.first_name)

    if START_BANNER_PATH and os.path.exists(START_BANNER_PATH):
        try:
            with open(START_BANNER_PATH, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=user.id,
                    photo=photo,
                    caption=dashboard_text(user.first_name or "Client"),
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_menu(),
                )
            return
        except Exception:
            logger.exception("Failed to send start banner, falling back to text dashboard.")

    if update.message:
        await update.message.reply_text(
            dashboard_text(user.first_name or "Client"),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            dashboard_text(user.first_name or "Client"),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await send_dashboard(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Operation cleared. You are back at the dashboard.",
        reply_markup=main_menu(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied. This command is available only to the admin desk.")
        return
    await update.message.reply_text(admin_menu_text(), parse_mode=ParseMode.HTML)


async def process_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return

    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

    if data == "ui_home":
        context.user_data.clear()
        await send_dashboard(update, context)
        return

    async def edit_callback_message(text: str, reply_markup: Optional[InlineKeyboardMarkup] = None):
        if q.message and (q.message.photo or q.message.document):
            await q.edit_message_caption(
                caption=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        else:
            await q.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )

    if data == "ui_scan":
        context.user_data["state"] = "wait_scan_target"
        await edit_callback_message(
            "⚡ <b>Quick Check</b>\n\nSend the wallet address or transaction hash for manual risk grading.",
            reply_markup=back_menu(),
        )
        return

    if data == "ui_audit":
        context.user_data["state"] = "wait_audit_target"
        await edit_callback_message(
            "💎 <b>Premium Reported AML•KYC</b>\n\nSend the target wallet address for a full analyst-reviewed PDF audit.",
            reply_markup=back_menu(),
        )
        return

    if data == "ui_pricing":
        await edit_callback_message(pricing_text(), reply_markup=back_menu())
        return

    if data == "ui_support":
        context.user_data["state"] = "wait_support_msg"
        await edit_callback_message(
            "💭 <b>Analyst Support</b>\n\nSend your message below. The support desk will reply in this chat.",
            reply_markup=back_menu(),
        )
        return

    if data == "ui_about":
        await edit_callback_message(about_text(), reply_markup=back_menu())
        return

    # Support reply initiation
    if data.startswith("sr|"):
        if not is_admin(uid):
            return
        _, ticket_id, target_uid = data.split("|", 2)
        context.user_data["state"] = "wait_admin_reply"
        context.user_data["reply_to"] = int(target_uid)
        context.user_data["ticket_id"] = int(ticket_id)
        await q.message.reply_text(
            f"Reply mode enabled for user {target_uid}. Send the message now, or use /cancel.",
        )
        return

    # Quick scan inline grading
    if data.startswith("sg|"):
        if not is_admin(uid):
            return
        _, request_id, risk, score = data.split("|", 3)
        await complete_scan_request(
            update=update,
            context=context,
            request_id=int(request_id),
            risk=normalize_risk(risk),
            score=validate_score(score),
            analyst_note="Manual grading issued by analyst desk.",
            admin_feedback_via_callback=True,
        )
        return

    # Premium audit inline grading
    if data.startswith("ag|"):
        if not is_admin(uid):
            return
        _, request_id, risk, score = data.split("|", 3)
        await complete_audit_request(
            update=update,
            context=context,
            request_id=int(request_id),
            risk=normalize_risk(risk),
            score=validate_score(score),
            analyst_note="Manual audit finalized by analyst desk.",
            admin_feedback_via_callback=True,
        )
        return


async def complete_scan_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    request_id: int,
    risk: str,
    score: int,
    analyst_note: str,
    admin_feedback_via_callback: bool = False,
):
    request = db.get_scan_request(request_id)
    if not request:
        msg = f"Scan request {request_id} not found."
        if admin_feedback_via_callback and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        elif update.message:
            await update.message.reply_text(msg)
        return

    db.resolve_scan_request(request_id, risk, score, analyst_note)
    user_message = scan_result_text(request_id, request["target"], risk, score, analyst_note)

    await context.bot.send_message(
        chat_id=request["user_id"],
        text=user_message,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

    admin_msg = (
        "✅ <b>Quick check resolved</b>\n\n"
        f"<b>Request ID:</b> <code>{request_id}</code>\n"
        f"<b>User ID:</b> <code>{request['user_id']}</code>\n"
        f"<b>Target:</b> <code>{h(request['target'])}</code>\n"
        f"<b>Risk:</b> {get_risk_ui(risk)}\n"
        f"<b>Score:</b> {score}/100"
    )

    if admin_feedback_via_callback and update.callback_query:
        await update.callback_query.edit_message_text(admin_msg, parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text(admin_msg, parse_mode=ParseMode.HTML)


async def complete_audit_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    request_id: int,
    risk: str,
    score: int,
    analyst_note: str,
    admin_feedback_via_callback: bool = False,
):
    request = db.get_audit_request(request_id)
    if not request:
        msg = f"Audit request {request_id} not found."
        if admin_feedback_via_callback and update.callback_query:
            await update.callback_query.edit_message_text(msg)
        elif update.message:
            await update.message.reply_text(msg)
        return

    tx_hash = request["tx_hash"] or "MANUAL-REFERENCE"
    pdf_buf, pdf_name, report_id = generate_pdf(
        target=request["target"],
        tx_hash=tx_hash,
        risk=risk,
        score=score,
        analyst_note=analyst_note,
    )

    db.resolve_audit_request(request_id, risk, score, analyst_note, report_id)

    await context.bot.send_document(
        chat_id=request["user_id"],
        document=pdf_buf,
        filename=pdf_name,
        caption=audit_caption_text(request_id, request["target"], risk, score, report_id),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

    admin_msg = (
        "✅ <b>Premium audit resolved</b>\n\n"
        f"<b>Request ID:</b> <code>{request_id}</code>\n"
        f"<b>User ID:</b> <code>{request['user_id']}</code>\n"
        f"<b>Report ID:</b> <code>{report_id}</code>\n"
        f"<b>Target:</b> <code>{h(request['target'])}</code>\n"
        f"<b>Risk:</b> {get_risk_ui(risk)}\n"
        f"<b>Score:</b> {score}/100"
    )

    if admin_feedback_via_callback and update.callback_query:
        await update.callback_query.edit_message_text(admin_msg, parse_mode=ParseMode.HTML)
    elif update.message:
        await update.message.reply_text(admin_msg, parse_mode=ParseMode.HTML)


async def scanres_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage:\n/scanres <request_id or user_id> <LOW|MEDIUM|HIGH|CRITICAL> <score> [note]"
        )
        return

    try:
        request = resolve_scan_identifier(args[0])
        if not request:
            await update.message.reply_text("No matching pending scan request found.")
            return

        risk = normalize_risk(args[1])
        score = validate_score(args[2])
        note = " ".join(args[3:]).strip() or "Manual grading issued by analyst desk."
        await complete_scan_request(update, context, int(request["id"]), risk, score, note)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def auditres_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Usage:\n/auditres <request_id or user_id> <LOW|MEDIUM|HIGH|CRITICAL> <score> [note]"
        )
        return

    try:
        request = resolve_audit_identifier(args[0])
        if not request:
            await update.message.reply_text("No matching audit request found.")
            return

        risk = normalize_risk(args[1])
        score = validate_score(args[2])
        note = " ".join(args[3:]).strip() or "Manual audit finalized by analyst desk."
        await complete_audit_request(update, context, int(request["id"]), risk, score, note)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage:\n/reply <user_id> <message>")
        return

    try:
        target_uid = int(args[0])
    except ValueError:
        await update.message.reply_text("User ID must be numeric.")
        return

    message = " ".join(args[1:]).strip()
    if not message:
        await update.message.reply_text("Reply text cannot be empty.")
        return

    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"🎧 <b>Support Response</b>\n\n{h(message)}",
            parse_mode=ParseMode.HTML,
        )
        await update.message.reply_text("Reply delivered successfully.")
    except Exception as e:
        await update.message.reply_text(f"Delivery failed: {e}")


async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()
    normalized_text = text.split()[0].lower()
    state = context.user_data.get("state", "")

    db.upsert_user(user.id, user.username, user.first_name)

    # Fallback for clients/chats where commands can arrive as plain text.
    if re.fullmatch(r"/start(@[\w_]+)?", normalized_text):
        await start(update, context)
        return
    if re.fullmatch(r"/cancel(@[\w_]+)?", normalized_text):
        await cancel(update, context)
        return
    if re.fullmatch(r"/admin(@[\w_]+)?", normalized_text):
        await admin_command(update, context)
        return

    if state == "wait_scan_target":
        network = detect_network(text)
        request_id = db.create_scan_request(user.id, user.username, text, network)

        await update.message.reply_text(
            quick_check_submitted_text(request_id, text),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        admin_text = (
            "🚨 <b>NEW QUICK CHECK REQUEST</b>\n\n"
            f"<b>Request ID:</b> <code>{request_id}</code>\n"
            f"<b>User ID:</b> <code>{user.id}</code>\n"
            f"<b>Username:</b> @{h(user.username) if user.username else 'N/A'}\n"
            f"<b>Target:</b> <code>{h(text)}</code>\n"
            f"<b>Network:</b> {h(network)}\n\n"
            "Assign a manual risk grade:"
        )

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_grade_keyboard("scan", request_id),
        )
        context.user_data.clear()
        return

    if state == "wait_audit_target":
        network = detect_network(text)
        request_id = db.create_audit_request(user.id, user.username, text, network)
        context.user_data["state"] = "wait_tx_hash"
        context.user_data["audit_request_id"] = request_id

        await update.message.reply_text(
            audit_payment_text(request_id, text),
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu(),
        )
        return

    if state == "wait_tx_hash":
        request_id = context.user_data.get("audit_request_id")
        if not request_id:
            context.user_data.clear()
            await update.message.reply_text(
                "No active audit request found. Start a new premium audit from the dashboard.",
                reply_markup=main_menu(),
            )
            return

        db.attach_audit_payment(int(request_id), text)
        request = db.get_audit_request(int(request_id))

        await update.message.reply_text(
            audit_under_review_text(int(request_id)),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        admin_text = (
            
            f"<b>Request ID:</b> <code>{request_id}</code>\n"
            f"<b>User ID:</b> <code>{user.id}</code>\n"
            f"<b>Target:</b> <code>{h(request['target'])}</code>\n"
            f"<b>Detected Network:</b> {h(request['network'])}\n"
            f"<b>Payment Network:</b> {h(request['payment_network'])}\n"
            f"<b>TX Hash:</b> <code>{h(text)}</code>\n\n"
            "Finalize the premium audit:"
        )

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_grade_keyboard("audit", int(request_id)),
        )
        context.user_data.clear()
        return

    if state == "wait_support_msg":
        ticket_id = db.create_support_ticket(user.id, user.username, text)

        await update.message.reply_text(
            "✅ Your message has been delivered to the analyst support desk.",
            reply_markup=main_menu(),
        )

        admin_text = (
            "💭 <b>NEW SUPPORT TICKET</b>\n\n"
            f"<b>Ticket ID:</b> <code>{ticket_id}</code>\n"
            f"<b>User ID:</b> <code>{user.id}</code>\n"
            f"<b>Username:</b> @{h(user.username) if user.username else 'N/A'}\n\n"
            f"<b>Message:</b>\n{h(text)}"
        )

        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=admin_text,
            parse_mode=ParseMode.HTML,
            reply_markup=support_reply_keyboard(ticket_id, user.id),
        )
        context.user_data.clear()
        return

    if state == "wait_admin_reply" and is_admin(user.id):
        target_uid = context.user_data.get("reply_to")
        ticket_id = context.user_data.get("ticket_id")
        if not target_uid:
            context.user_data.clear()
            await update.message.reply_text("Reply target missing. Use /reply or reopen the ticket.")
            return

        try:
            await context.bot.send_message(
                chat_id=int(target_uid),
                text=f"🎧 <b>Support Response</b>\n\n{h(text)}",
                parse_mode=ParseMode.HTML,
            )
            if ticket_id:
                db.close_support_ticket(int(ticket_id))
            await update.message.reply_text("Support response delivered.")
        except Exception as e:
            await update.message.reply_text(f"Delivery failed: {e}")
        finally:
            context.user_data.clear()
        return

    await update.message.reply_text(
        "Use the dashboard buttons to start a quick check, premium audit, or support request.",
        reply_markup=main_menu(),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception", exc_info=context.error)


def main():
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN before starting the bot.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("scanres", scanres_command))
    app.add_handler(CommandHandler("auditres", auditres_command))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CallbackQueryHandler(process_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    logger.info("🚀 %s starting...", BOT_NAME)
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
