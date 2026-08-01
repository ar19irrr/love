# chat_handler.py
import sqlite3
import logging
from telegram import Update

logger = logging.getLogger(__name__)

async def handle_chat_message(update: Update, context):
    logger.info(f"🚀 handle_chat_message called! user: {update.effective_user.id}")
    
    if not update.message:
        return
    
    if 'active_chat' not in context.user_data:
        await update.message.reply_text("❌ شما در هیچ چتی نیستید!")
        return
    
    chat_id = context.user_data['active_chat']
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT user1, user2 FROM chats WHERE id=? AND is_active=1", (chat_id,))
    chat = c.fetchone()
    conn.close()
    
    if not chat:
        await update.message.reply_text("❌ چت فعال نیست!")
        context.user_data.pop('active_chat', None)
        return
    
    partner_id = chat[1] if chat[0] == user_id else chat[0]
    logger.info(f"🔍 sender={user_id}, partner={partner_id}")
    
    if update.message.text:
        logger.info(f"📝 Text: {update.message.text}")
        try:
            await context.bot.send_message(chat_id=partner_id, text=f"📩 {update.message.text}")
            await update.message.reply_text("✅")
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌")
    
    elif update.message.photo:
        logger.info(f"📸 Photo received")
        try:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(chat_id=partner_id, photo=file_id, caption="📸 عکس جدید")
            await update.message.reply_text("✅")
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌")
    
    elif update.message.sticker:
        logger.info(f"🎨 Sticker received")
        try:
            await context.bot.send_sticker(chat_id=partner_id, sticker=update.message.sticker.file_id)
            await update.message.reply_text("✅")
        except Exception as e:
            logger.error(f"Error: {e}")
            await update.message.reply_text("❌")
