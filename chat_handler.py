# chat_handler.py
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

def get_chat_partner(chat_id, user_id):
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT user1, user2 FROM chats WHERE id=? AND is_active=1", (chat_id,))
    chat = c.fetchone()
    conn.close()
    
    if not chat:
        return None
    
    return chat[1] if chat[0] == user_id else chat[0]

async def handle_chat_message(update: Update, context):
    user_id = update.effective_user.id
    
    if 'active_chat' not in context.user_data:
        await update.message.reply_text("❌ شما در هیچ چتی نیستید!")
        return
    
    chat_id = context.user_data['active_chat']
    
    # پیدا کردن طرف مقابل
    partner_id = get_chat_partner(chat_id, user_id)
    if not partner_id:
        await update.message.reply_text("❌ چت فعال نیست!")
        context.user_data.pop('active_chat', None)
        return
    
    logger.info(f"📩 User {user_id} sending to {partner_id}")
    
    # تشخیص نوع پیام
    if update.message.text:
        try:
            await context.bot.send_message(
                chat_id=partner_id,
                text=f"📩 {update.message.text}"
            )
            await update.message.reply_text("✅")
            logger.info(f"✅ Text sent to {partner_id}")
            return
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌ ارسال ناموفق!")
    
    elif update.message.photo:
        try:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=partner_id,
                photo=file_id,
                caption="📸 عکس جدید"
            )
            await update.message.reply_text("✅")
            logger.info(f"✅ Photo sent to {partner_id}")
            return
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌ ارسال ناموفق!")
    
    elif update.message.sticker:
        try:
            await context.bot.send_sticker(
                chat_id=partner_id,
                sticker=update.message.sticker.file_id
            )
            await update.message.reply_text("✅")
            logger.info(f"✅ Sticker sent to {partner_id}")
            return
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌ ارسال ناموفق!")
    
    else:
        await update.message.reply_text("❌ این نوع پیام پشتیبانی نمی‌شود!")
