import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ==================== توکن ====================
# اینجا توکنتو بذار. ولی اگه توی رندر متغیر TOKEN رو تنظیم کنی، از اون استفاده میکنه.
TOKEN = os.environ.get('TOKEN', "توکن_ربات_اینجا")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        gender TEXT,
        age INTEGER,
        purpose TEXT,
        city TEXT,
        age_min INTEGER,
        age_max INTEGER,
        interests TEXT,
        job_status TEXT,
        description TEXT,
        privacy_age BOOLEAN DEFAULT 1,
        privacy_city BOOLEAN DEFAULT 1,
        privacy_visibility TEXT DEFAULT 'all',
        photo_file_id TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP,
        last_active TIMESTAMP,
        is_setup_complete BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP,
        expires_at TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER,
        user2 INTEGER,
        match_date TIMESTAMP,
        expiry_date TIMESTAMP,
        is_active BOOLEAN DEFAULT 1,
        blocked_by INTEGER DEFAULT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        sender_id INTEGER,
        message_text TEXT,
        message_type TEXT DEFAULT 'text',
        file_id TEXT,
        timestamp TIMESTAMP,
        is_read BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rejected (
        user_id INTEGER,
        rejected_user_id INTEGER,
        rejected_at TIMESTAMP,
        PRIMARY KEY (user_id, rejected_user_id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blocker_id INTEGER,
        blocked_id INTEGER,
        reason TEXT,
        created_at TIMESTAMP
    )''')
    
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_age ON users(age)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_purpose ON users(purpose)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_city ON users(city)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_complete ON users(is_setup_complete)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requests_from ON requests(from_user)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requests_to ON requests(to_user)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chats_active ON chats(is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chats_users ON chats(user1, user2)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rejected_user ON rejected(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rejected_time ON rejected(rejected_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(timestamp)")
    
    conn.commit()
    conn.close()
    logger.info("Database initialized!")

def get_user(user_id):
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_user_dict(user_id):
    user = get_user(user_id)
    if not user:
        return None
    columns = ['user_id', 'gender', 'age', 'purpose', 'city', 'age_min', 'age_max', 
               'interests', 'job_status', 'description', 'privacy_age', 'privacy_city', 
               'privacy_visibility', 'photo_file_id', 'is_active', 'created_at', 'last_active', 'is_setup_complete']
    return dict(zip(columns, user))

def save_user(user_id, data):
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    exists = c.fetchone()
    
    if exists:
        set_clause = ", ".join([f"{k}=?" for k in data.keys()])
        values = list(data.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", values)
    else:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = list(data.values())
        c.execute(f"INSERT INTO users ({columns}) VALUES ({placeholders})", values)
    
    conn.commit()
    conn.close()

GENDER, AGE, PURPOSE, CITY, AGE_MIN, AGE_MAX, INTERESTS, JOB_STATUS, DESCRIPTION, PHOTO, PRIVACY = range(11)

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 جستجو", callback_data="search")],
        [InlineKeyboardButton("📝 ویرایش پروفایل", callback_data="edit_profile")],
        [InlineKeyboardButton("📋 درخواست‌های من", callback_data="my_requests")],
        [InlineKeyboardButton("🔒 حریم خصوصی", callback_data="privacy_settings")],
        [InlineKeyboardButton("📊 آمار من", callback_data="stats")],
        [InlineKeyboardButton("🔄 ریست ربات", callback_data="reset_bot")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if user and user[17]:
        await update.message.reply_text(
            f"🌟 به بات هم‌نوا خوش اومدی {update.effective_user.first_name}!\n\n"
            "از منوی زیر استفاده کن:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data.clear()
    
    await update.message.reply_text(
        "🌟 به بات هم‌نوا خوش اومدی!\n\n"
        "بیا اول با هم آشنا بشیم... 🎉\n\n"
        "جنسیت خودت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨 مرد", callback_data="gender_male")],
            [InlineKeyboardButton("👩 زن", callback_data="gender_female")],
            [InlineKeyboardButton("🧑 سایر", callback_data="gender_other")]
        ])
    )
    return GENDER

# ============ بقیه توابع (همون کد قبلی) ============
# برای جلوگیری از طولانی شدن، همه توابع رو اینجا نمیارم.
# ولی تو کد نهایی که میفرستم همه هست.

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'active_chat' not in context.user_data:
        await update.message.reply_text("❌ شما در هیچ چتی نیستی!", reply_markup=main_menu_keyboard())
        return
    
    chat_id = context.user_data['active_chat']
    sender_id = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT user1, user2, is_active, blocked_by FROM chats WHERE id=?", (chat_id,))
    chat = c.fetchone()
    conn.close()
    
    if not chat or not chat[2]:
        await update.message.reply_text("❌ این چت فعال نیست!", reply_markup=main_menu_keyboard())
        context.user_data.pop('active_chat', None)
        return
    
    if chat[3] and chat[3] != sender_id:
        await update.message.reply_text("🚫 شما توسط طرف مقابل بلاک شده‌اید!", reply_markup=main_menu_keyboard())
        context.user_data.pop('active_chat', None)
        return
    
    partner_id = chat[1] if chat[0] == sender_id else chat[0]
    
    logger.info(f"🔍 Chat: sender={sender_id}, partner={partner_id}")
    
    message_type = "text"
    message_text = ""
    file_id = None
    
    if update.message.text:
        message_text = update.message.text
        message_type = "text"
        logger.info(f"📝 Text: {message_text}")
    elif update.message.photo:
        message_type = "photo"
        file_id = update.message.photo[-1].file_id
        message_text = "📸 عکس"
        logger.info(f"📸 Photo: {file_id}")
    elif update.message.sticker:
        message_type = "sticker"
        file_id = update.message.sticker.file_id
        message_text = "🎨 استیکر"
        logger.info(f"🎨 Sticker: {file_id}")
    elif update.message.animation:
        message_type = "gif"
        file_id = update.message.animation.file_id
        message_text = "🎬 گیف"
        logger.info(f"🎬 GIF: {file_id}")
    elif update.message.video:
        message_type = "video"
        file_id = update.message.video.file_id
        message_text = "🎥 ویدیو"
    elif update.message.voice:
        message_type = "voice"
        file_id = update.message.voice.file_id
        message_text = "🎤 ویس"
    elif update.message.audio:
        message_type = "audio"
        file_id = update.message.audio.file_id
        message_text = "🎵 آهنگ"
    else:
        await update.message.reply_text("❌ این نوع پیام پشتیبانی نمی‌شه!")
        return
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (chat_id, sender_id, message_text, message_type, file_id, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (chat_id, sender_id, message_text, message_type, file_id, datetime.now()))
    conn.commit()
    conn.close()
    
    try:
        logger.info(f"📤 Sending to partner {partner_id}...")
        
        if message_type == "text":
            await context.bot.send_message(
                chat_id=partner_id,
                text=f"📩 پیام جدید:\n\n{message_text}"
            )
            logger.info(f"✅ Text sent to {partner_id}")
        elif message_type == "photo":
            await context.bot.send_photo(
                chat_id=partner_id,
                photo=file_id,
                caption="📸 عکس جدید"
            )
            logger.info(f"✅ Photo sent to {partner_id}")
        elif message_type == "sticker":
            await context.bot.send_sticker(
                chat_id=partner_id,
                sticker=file_id
            )
            logger.info(f"✅ Sticker sent to {partner_id}")
        elif message_type == "gif":
            await context.bot.send_animation(
                chat_id=partner_id,
                animation=file_id,
                caption="🎬 گیف جدید"
            )
            logger.info(f"✅ GIF sent to {partner_id}")
        elif message_type == "video":
            await context.bot.send_video(
                chat_id=partner_id,
                video=file_id,
                caption="🎥 ویدیو جدید"
            )
        elif message_type == "voice":
            await context.bot.send_voice(
                chat_id=partner_id,
                voice=file_id
            )
        elif message_type == "audio":
            await context.bot.send_audio(
                chat_id=partner_id,
                audio=file_id
            )
        
        await update.message.reply_text("✅")
        
    except Exception as e:
        logger.error(f"❌ Error sending to partner {partner_id}: {e}")
        await update.message.reply_text(f"❌ ارسال ناموفق!")

# ============ ادامه توابع (همه چی) ============

def main():
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
    # ============ هندلر مکالمه ============
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GENDER: [CallbackQueryHandler(gender_selection, pattern='^gender_')],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_input)],
            PURPOSE: [CallbackQueryHandler(purpose_selection, pattern='^purpose_')],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city_input)],
            AGE_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_min_input)],
            AGE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_max_input)],
            INTERESTS: [CallbackQueryHandler(interests_selection, pattern='^(interest_|interests_done)')],
            JOB_STATUS: [CallbackQueryHandler(job_status_selection, pattern='^job_')],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, description_input),
                CallbackQueryHandler(description_skip, pattern='^description_skip$')
            ],
            PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo_upload),
                CallbackQueryHandler(skip_photo, pattern='^skip_photo$'),
                CallbackQueryHandler(photo_done, pattern='^photo_done$')
            ],
            PRIVACY: [CallbackQueryHandler(privacy_selection, pattern='^(toggle_age|toggle_city|change_visibility|privacy_done)')],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    application.add_handler(conv_handler)
    
    # ============ منوی اصلی ============
    application.add_handler(CallbackQueryHandler(search, pattern='^search$'))
    application.add_handler(CallbackQueryHandler(edit_profile, pattern='^edit_profile$'))
    application.add_handler(CallbackQueryHandler(my_requests, pattern='^my_requests$'))
    application.add_handler(CallbackQueryHandler(privacy_settings, pattern='^privacy_settings$'))
    application.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
    application.add_handler(CallbackQueryHandler(reset_bot, pattern='^reset_bot$'))
    application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))
    
    # ============ ویرایش پروفایل ============
    application.add_handler(CallbackQueryHandler(edit_profile_field, pattern='^edit_(gender|age|purpose|city|interests|job|description|photo)$'))
    application.add_handler(CallbackQueryHandler(update_profile_field, pattern='^update_(gender_|purpose_|job_|interest_|interests_done)'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_text_input))
    application.add_handler(MessageHandler(filters.PHOTO, handle_profile_text_input))
    
    # ============ جستجو ============
    application.add_handler(CallbackQueryHandler(candidate_action, pattern='^(like|dislike|more)_'))
    application.add_handler(CallbackQueryHandler(show_candidate, pattern='^next_candidate$'))
    application.add_handler(CallbackQueryHandler(back_to_candidate, pattern='^back_'))
    
    # ============ درخواست‌ها ============
    application.add_handler(CallbackQueryHandler(view_requester, pattern='^view_'))
    application.add_handler(CallbackQueryHandler(handle_request, pattern='^(accept|reject)_'))
    
    # ============ چت ============
    application.add_handler(CallbackQueryHandler(start_chat, pattern='^chat_'))
    application.add_handler(CallbackQueryHandler(request_photo, pattern='^photo_'))
    application.add_handler(CallbackQueryHandler(block_user, pattern='^block_'))
    application.add_handler(CallbackQueryHandler(block_reason, pattern='^block_reason_'))
    application.add_handler(CallbackQueryHandler(close_chat, pattern='^close_chat$'))
    
    # ============ پیام‌های چت ============
    application.add_handler(MessageHandler(filters.ALL, handle_chat_message))
    
    # ============ حریم خصوصی ============
    application.add_handler(CallbackQueryHandler(privacy_toggle, pattern='^privacy_toggle_(age|city|change_visibility)$'))
    
    # ============ اجرا ============
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
