import os
import threading
import logging
from flask import Flask, jsonify
from bot import main as start_bot  # فرض میکنیم فایل اصلی bot.py هست

# تنظیم لاگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ایجاد اپ Flask
app = Flask(__name__)

@app.route('/')
def home():
    """صفحه اصلی برای پینگ کرون‌جاب"""
    return jsonify({
        "status": "online",
        "message": "ربات هم‌نوا فعال است!",
        "version": "1.0.0"
    })

@app.route('/health')
def health():
    """بررسی سلامت ربات"""
    return jsonify({"status": "healthy"})

@app.route('/ping')
def ping():
    """پاسخ به درخواست‌های پینگ"""
    return "pong"

def run_bot():
    """اجرای ربات در یک ترد جداگانه"""
    try:
        logger.info("🚀 Starting bot thread...")
        start_bot()
    except Exception as e:
        logger.error(f"❌ Bot thread error: {e}")

if __name__ == '__main__':
    # اجرای ربات در ترد جداگانه
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Bot thread started")
    
    # اجرای وب‌سرویس
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🌐 Starting web service on port {port}")
    app.run(host='0.0.0.0', port=port)
