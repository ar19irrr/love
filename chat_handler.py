# chat_handler.py
import logging
from telegram import Update

logger = logging.getLogger(__name__)

async def handle_chat_message(update: Update, context):
    # فقط برای تست که ببینیم اصلاً اجرا میشه یا نه
    logger.info("✅ handle_chat_message RUNNING!")
    
    if not update.message:
        return
    
    # اینجا فعلاً هیچ کاری نکن، فقط لاگ بده
    await update.message.reply_text("✅ پیام دریافت شد!")
