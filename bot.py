import os
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# ===== LOGGING =====
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ALPACA_KEY = os.environ.get("ALPACA_KEY", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET", "")

ALPACA_BASE = "https://data.alpaca.markets/v2"

# ===== GET PRICE FROM ALPACA =====
def get_price(symbol: str):
    try:
        headers = {
            "APCA-API-KEY-ID": ALPACA_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET
        }
        url = f"{ALPACA_BASE}/stocks/{symbol}/bars/latest"
res = requests.get(url, headers=headers, timeout=8)
if res.status_code == 200:
    data = res.json()
    price = data["bar"]["c"]
    return float(price)

    except Exception as e:
        logger.error(f"Price error: {e}")
    return None

# ===== GET BARS FOR ANALYSIS =====
def get_bars(symbol: str, timeframe="1Day", limit=20):
    try:
        headers = {
            "APCA-API-KEY-ID": ALPACA_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET
        }
        url = f"{ALPACA_BASE}/stocks/{symbol}/bars"
        params = {"timeframe": timeframe, "limit": limit}

        res = requests.get(url, headers=headers, params=params, timeout=8)
        if res.status_code == 200:
            bars = res.json().get("bars", [])
            return bars
    except Exception as e:
        logger.error(f"Bars error: {e}")
    return []

# ===== TECHNICAL ANALYSIS =====
def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def analyze(symbol: str):
    bars = get_bars(symbol, limit=30)
    if not bars:
        # Fallback mock if no API key
        price = 150.0
        return {
            "symbol": symbol,
            "price": price,
            "change": 0.0,
            "rsi": 50.0,
            "ema20": price * 0.98,
            "ema50": price * 0.96,
            "signal": "⏳ انتظار",
            "signal_type": "wait",
            "confidence": 50,
            "stop_loss": round(price * 0.97, 2),
            "target": round(price * 1.05, 2),
            "note": "⚠️ تحقق من إعداد مفاتيح Alpaca API"
        }

    closes = [b["c"] for b in bars]
    opens  = [b["o"] for b in bars]
    price  = closes[-1]
    prev   = closes[-2] if len(closes) > 1 else price
    change = round(((price - prev) / prev) * 100, 2)

    rsi   = calculate_rsi(closes)
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50) if len(closes) >= 50 else calculate_ema(closes, len(closes))

    # Signal logic
    bull = 0
    bear = 0

    if rsi < 35: bull += 2
    elif rsi > 65: bear += 2
    elif rsi > 50: bull += 1

    if price > ema20: bull += 1
    else: bear += 1

    if price > ema50: bull += 1
    else: bear += 1

    if change > 0: bull += 1
    else: bear += 1

    total = bull + bear
    conf  = round((max(bull, bear) / total) * 100)

    if bull > bear + 1:
        signal = "🟢 شراء"
        stype  = "buy"
        stop   = round(price * 0.97, 2)
        target = round(price * 1.06, 2)
    elif bear > bull + 1:
        signal = "🔴 بيع / تجنب"
        stype  = "sell"
        stop   = round(price * 1.03, 2)
        target = round(price * 0.94, 2)
    else:
        signal = "⏳ انتظار"
        stype  = "wait"
        stop   = round(price * 0.97, 2)
        target = round(price * 1.04, 2)

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "signal": signal,
        "signal_type": stype,
        "confidence": conf,
        "stop_loss": stop,
        "target": target,
        "note": ""
    }

# ===== FORMAT MESSAGE =====
def format_analysis(a: dict) -> str:
    arrow = "📈" if a["change"] >= 0 else "📉"
    change_str = f"+{a['change']}%" if a["change"] >= 0 else f"{a['change']}%"

    rsi_comment = "تشبع بيعي 🔥" if a["rsi"] < 35 else ("تشبع شرائي ⚠️" if a["rsi"] > 65 else "محايد")
    ema_comment = "✅ فوق EMA" if a["price"] > a["ema20"] else "⛔ تحت EMA"

    msg = f"""
━━━━━━━━━━━━━━━━━
📊 *تحليل {a['symbol']}*
━━━━━━━━━━━━━━━━━

{arrow} *السعر:* `${a['price']}`
📉 *التغيير:* `{change_str}`

*── المؤشرات الفنية ──*
• RSI (14): `{a['rsi']}` — {rsi_comment}
• EMA 20: `${a['ema20']}` — {ema_comment}
• EMA 50: `${a['ema50']}`

*── الإشارة ──*
{a['signal']}
🎯 نسبة الثقة: `{a['confidence']}%`

*── إدارة المخاطر ──*
🛑 وقف الخسارة: `${a['stop_loss']}`
🎯 الهدف: `${a['target']}`
"""
    if a["note"]:
        msg += f"\n{a['note']}"

    msg += "\n\n_⚠️ للأغراض التعليمية فقط، ليست نصيحة مالية._"
    return msg

# ===== HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 تحليل AAPL", callback_data="analyze_AAPL"),
         InlineKeyboardButton("📊 تحليل TSLA", callback_data="analyze_TSLA")],
        [InlineKeyboardButton("📊 تحليل NVDA", callback_data="analyze_NVDA"),
         InlineKeyboardButton("📊 تحليل SPY",  callback_data="analyze_SPY")],
        [InlineKeyboardButton("📋 قائمة الأوامر", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 *مرحباً في بوت التداول الأمريكي!*\n\n"
        "أرسل رمز أي سهم للحصول على التحليل الفوري.\n"
        "مثال: `AAPL` أو `TSLA` أو `NVDA`\n\n"
        "أو اختر من الأزرار أدناه 👇",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *الأوامر المتاحة:*\n\n"
        "/start — الشاشة الرئيسية\n"
        "/analyze AAPL — تحليل سهم معين\n"
        "/watchlist — قائمة المراقبة\n"
        "/help — قائمة الأوامر\n\n"
        "أو فقط أرسل رمز السهم مباشرة!\n"
        "مثال: `AAPL` أو `MSFT` أو `AMZN`",
        parse_mode="Markdown"
    )

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ أرسل رمز السهم. مثال: `/analyze AAPL`", parse_mode="Markdown")
        return
    symbol = context.args[0].upper()
    await run_analysis(update, symbol)

async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = ["AAPL", "TSLA", "NVDA", "MSFT", "SPY"]
    msg = "📋 *قائمة المراقبة*\n━━━━━━━━━━━━━━━\n\n"
    await update.message.reply_text("⏳ جاري تحليل القائمة...", parse_mode="Markdown")

    for sym in symbols:
        a = analyze(sym)
        arrow = "📈" if a["change"] >= 0 else "📉"
        ch = f"+{a['change']}%" if a["change"] >= 0 else f"{a['change']}%"
        msg += f"{arrow} *{sym}* — `${a['price']}` ({ch}) — {a['signal']}\n"

    msg += "\n_للتحليل التفصيلي أرسل رمز السهم._"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    # Accept stock symbols (1-6 letters)
    if text.isalpha() and 1 <= len(text) <= 6:
        await run_analysis(update, text)
    else:
        await update.message.reply_text(
            "❓ أرسل رمز سهم صحيح مثل `AAPL` أو `TSLA`\nأو استخدم /help للمساعدة.",
            parse_mode="Markdown"
        )

async def run_analysis(update: Update, symbol: str):
    msg = await update.message.reply_text(f"⏳ جاري تحليل *{symbol}*...", parse_mode="Markdown")
    a = analyze(symbol)
    text = format_analysis(a)
    keyboard = [[
        InlineKeyboardButton("🔄 تحديث", callback_data=f"analyze_{symbol}"),
        InlineKeyboardButton("📋 قائمة المراقبة", callback_data="watchlist")
    ]]
    await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("analyze_"):
        symbol = data.replace("analyze_", "")
        await query.edit_message_text(f"⏳ جاري تحليل *{symbol}*...", parse_mode="Markdown")
        a = analyze(symbol)
        text = format_analysis(a)
        keyboard = [[
            InlineKeyboardButton("🔄 تحديث", callback_data=f"analyze_{symbol}"),
            InlineKeyboardButton("📋 قائمة المراقبة", callback_data="watchlist")
        ]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "watchlist":
        symbols = ["AAPL", "TSLA", "NVDA", "MSFT", "SPY"]
        msg = "📋 *قائمة المراقبة*\n━━━━━━━━━━━━━━━\n\n"
        for sym in symbols:
            a = analyze(sym)
            arrow = "📈" if a["change"] >= 0 else "📉"
            ch = f"+{a['change']}%" if a["change"] >= 0 else f"{a['change']}%"
            msg += f"{arrow} *{sym}* — `${a['price']}` ({ch}) — {a['signal']}\n"
        msg += "\n_للتحليل التفصيلي أرسل رمز السهم._"
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "help":
        await query.edit_message_text(
            "📋 *الأوامر المتاحة:*\n\n"
            "/start — الشاشة الرئيسية\n"
            "/analyze AAPL — تحليل سهم\n"
            "/watchlist — قائمة المراقبة\n\n"
            "أو أرسل رمز السهم مباشرة!",
            parse_mode="Markdown"
        )

# ===== MAIN =====
def main():
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN غير موجود!")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("✅ البوت يعمل...")
    asyncio.run(app.run_polling(drop_pending_updates=True))


if __name__ == "__main__":
    main()
