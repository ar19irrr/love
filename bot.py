import os
import logging
import sqlite3
import json
import traceback
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from flask import Flask, jsonify

# ============ تنظیمات اولیه ============
TOKEN = os.environ.get('TOKEN', "YOUR_BOT_TOKEN_HERE")
PORT = int(os.environ.get('PORT', 8080))
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ Flask App ============
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return jsonify({"status": "Bot is running!", "time": datetime.now().isoformat()})

@web_app.route('/ping')
def ping():
    return jsonify({"status": "pong", "time": datetime.now().isoformat()})

@web_app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "active"})

def run_flask():
    try:
        logger.info(f"🌐 Starting Flask server on port {PORT}...")
        web_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ Flask error: {e}")

# ============ کلاس مدیریت دیتابیس ============
class Database:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.conn = sqlite3.connect('matchbot.db', check_same_thread=False)
            cls._instance.conn.row_factory = sqlite3.Row
            cls._instance._init_tables()
        return cls._instance
    
    def _init_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
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
            is_setup_complete BOOLEAN DEFAULT 0,
            report_count INTEGER DEFAULT 0,
            is_banned BOOLEAN DEFAULT 0,
            no_photo BOOLEAN DEFAULT 0
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER,
            to_user INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            expires_at TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1 INTEGER,
            user2 INTEGER,
            match_date TIMESTAMP,
            expiry_date TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            blocked_by INTEGER DEFAULT NULL,
            last_message_at TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            sender_id INTEGER,
            message_text TEXT,
            message_type TEXT DEFAULT 'text',
            file_id TEXT,
            timestamp TIMESTAMP,
            is_read BOOLEAN DEFAULT 0
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS rejected (
            user_id INTEGER,
            rejected_user_id INTEGER,
            rejected_at TIMESTAMP,
            PRIMARY KEY (user_id, rejected_user_id)
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocker_id INTEGER,
            blocked_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            chat_id INTEGER
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            blocked_user_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )''')
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_age ON users(age)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_purpose ON users(purpose)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_city ON users(city)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_complete ON users(is_setup_complete)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_banned ON users(is_banned)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_from ON requests(from_user)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_requests_to ON requests(to_user)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_active ON chats(is_active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_users ON chats(user1, user2)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_expiry ON chats(expiry_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rejected_user ON rejected(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rejected_time ON rejected(rejected_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON blocks(blocker_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_reported ON reports(reported_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_admin_blocks_user ON admin_blocks(blocked_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_user ON support_messages(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_status ON support_messages(status)")
        
        self.conn.commit()
        logger.info("✅ Database initialized successfully!")
    
    def execute(self, query: str, params: tuple = None) -> sqlite3.Cursor:
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self.conn.commit()
            return cursor
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise
    
    def fetchone(self, query: str, params: tuple = None) -> Optional[sqlite3.Row]:
        cursor = self.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query: str, params: tuple = None) -> List[sqlite3.Row]:
        cursor = self.execute(query, params)
        return cursor.fetchall()

db = Database()

# ============ توابع کمکی ============
def get_user(user_id: int) -> Optional[sqlite3.Row]:
    return db.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))

def get_user_dict(user_id: int) -> Optional[Dict[str, Any]]:
    user = get_user(user_id)
    if not user:
        return None
    return dict(user)

def save_user(user_id: int, data: Dict[str, Any]):
    try:
        existing = get_user(user_id)
        if existing:
            set_clause = ", ".join([f"{k}=?" for k in data.keys()])
            values = list(data.values()) + [user_id]
            db.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", tuple(values))
        else:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            values = list(data.values())
            db.execute(f"INSERT INTO users ({columns}) VALUES ({placeholders})", tuple(values))
        return True
    except Exception as e:
        logger.error(f"Error saving user {user_id}: {e}")
        return False

def cleanup_expired_chats() -> int:
    try:
        cursor = db.execute("""
            UPDATE chats 
            SET is_active = 0 
            WHERE expiry_date < datetime('now') 
            AND is_active = 1
        """)
        return cursor.rowcount
    except Exception as e:
        logger.error(f"Error cleaning up chats: {e}")
        return 0

def get_active_chats(user_id: int) -> List[sqlite3.Row]:
    return db.fetchall("""
        SELECT id, user1, user2, last_message_at 
        FROM chats 
        WHERE (user1=? OR user2=?) AND is_active=1
        ORDER BY last_message_at DESC
    """, (user_id, user_id))

def is_admin_blocked(user_id: int) -> bool:
    result = db.fetchone("SELECT * FROM admin_blocks WHERE blocked_user_id=?", (user_id,))
    return result is not None

def get_admin_blocked_users() -> List[int]:
    results = db.fetchall("SELECT blocked_user_id FROM admin_blocks")
    return [row['blocked_user_id'] for row in results]

def get_chat_info(chat_id: int) -> Optional[Dict]:
    chat = db.fetchone("SELECT * FROM chats WHERE id=?", (chat_id,))
    if chat:
        return dict(chat)
    return None

def get_user_photo(user_id: int) -> Optional[str]:
    """دریافت عکس کاربر - اول عکس آپلود شده، بعد عکس پروفایل تلگرام"""
    user = get_user_dict(user_id)
    if not user:
        return None
    
    # اگر کاربر انتخاب کرده که عکسی ارسال نشه
    if user.get('no_photo', 0) == 1:
        return None
    
    # اول عکس آپلود شده
    if user.get('photo_file_id'):
        return user['photo_file_id']
    
    return None

# ============ کیبوردها ============
def main_menu_keyboard(is_admin: bool = False):
    keyboard = [
        [InlineKeyboardButton("🔍 جستجو", callback_data="search")],
        [InlineKeyboardButton("💬 چت‌های من", callback_data="show_chats")],
        [InlineKeyboardButton("📝 ویرایش پروفایل", callback_data="edit_profile")],
        [InlineKeyboardButton("📋 درخواست‌های من", callback_data="my_requests")],
        [InlineKeyboardButton("🔒 حریم خصوصی", callback_data="privacy_settings")],
        [InlineKeyboardButton("📊 آمار من", callback_data="stats")],
        [InlineKeyboardButton("🚫 افراد بلاک شده", callback_data="blocked_users")],
        [InlineKeyboardButton("🔄 ریست ربات", callback_data="reset_bot")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
    ]
    if is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def chat_keyboard(other_user: int, chat_id: int):
    """کیبورد داخل چت با مشخصات طرف مقابل"""
    other = get_user_dict(other_user)
    gender = other['gender'] if other else 'نامشخص'
    age = other['age'] if other and other['privacy_age'] else '??'
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👤 {gender} {age}ساله", callback_data=f"chat_info_{chat_id}")],
        [InlineKeyboardButton("📸 درخواست عکس", callback_data=f"photo_{other_user}")],
        [InlineKeyboardButton("🚫 بلاک", callback_data=f"bl_{other_user}")],
        [InlineKeyboardButton("⚠️ گزارش", callback_data=f"rp_{other_user}")],
        [InlineKeyboardButton("📋 چت‌ها", callback_data="show_chats")],
        [InlineKeyboardButton("❌ بستن چت", callback_data="close_chat")],
        [InlineKeyboardButton("🏠 منو", callback_data="back_to_menu")]
    ])

def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 بلاک کاربر", callback_data="admin_block_user")],
        [InlineKeyboardButton("✅ آنبلاک کاربر", callback_data="admin_unblock_user")],
        [InlineKeyboardButton("📋 گزارش‌ها", callback_data="admin_reports")],
        [InlineKeyboardButton("📞 پشتیبانی", callback_data="admin_support")],
        [InlineKeyboardButton("📊 آمار", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
    ])

def get_interests_keyboard(selected=None):
    if selected is None:
        selected = []
    
    interests_list = [
        "🎬 فیلم", "📚 کتاب", "🎵 موسیقی",
        "🏋️ ورزش", "🍳 آشپزی", "🎮 بازی",
        "🧳 سفر", "🌿 طبیعت", "✏️ نقاشی",
        "💻 تکنولوژی", "🧘 مدیتیشن", "🐱 حیوانات"
    ]
    
    keyboard = []
    for i in range(0, len(interests_list), 3):
        row = []
        for item in interests_list[i:i+3]:
            if item in selected:
                row.append(InlineKeyboardButton(f"✅ {item}", callback_data=f"interest_{item}"))
            else:
                row.append(InlineKeyboardButton(f"⬜ {item}", callback_data=f"interest_{item}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ تموم شد", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

# ============ مراحل ثبت‌نام ============
GENDER, AGE, PURPOSE, CITY, AGE_MIN, AGE_MAX, INTERESTS, JOB_STATUS, DESCRIPTION, PHOTO, PRIVACY = range(11)

# ============ هندلرهای ثبت‌نام ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if user and user['is_banned']:
        await update.message.reply_text("🚫 شما مسدود شده‌اید!")
        return
    
    if user and user['is_setup_complete']:
        is_admin = (user_id == ADMIN_ID)
        await update.message.reply_text(
            f"🌟 به بات هم‌نوا خوش اومدی {update.effective_user.first_name}!",
            reply_markup=main_menu_keyboard(is_admin)
        )
        return ConversationHandler.END
    
    context.user_data.clear()
    
    await update.message.reply_text(
        "🌟 **به بات هم‌نوا خوش اومدی!** 🌟\n\n"
        "این بات به تو کمک میکنه تا افراد هم‌فکر رو پیدا کنی.\n"
        "لطفاً اطلاعات زیر رو وارد کن:\n\n"
        "**مرحله ۱ از ۱۱: جنسیت**",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨 مرد", callback_data="gender_male")],
            [InlineKeyboardButton("👩 زن", callback_data="gender_female")],
            [InlineKeyboardButton("🧑 سایر", callback_data="gender_other")]
        ])
    )
    return GENDER

async def gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    gender_map = {"gender_male": "مرد", "gender_female": "زن", "gender_other": "سایر"}
    context.user_data['gender'] = gender_map[query.data]
    
    await query.edit_message_text(
        "🌸 **مرحله ۲ از ۱۱: سن**\n\nچند سالت هست؟ (فقط عدد):",
        parse_mode='Markdown'
    )
    return AGE

async def age_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text("❌ عدد بین ۱۰ تا ۱۰۰ وارد کن:")
            return AGE
        context.user_data['age'] = age
    except ValueError:
        await update.message.reply_text("❌ فقط عدد وارد کن:")
        return AGE
    
    await update.message.reply_text(
        "🎯 **مرحله ۳ از ۱۱: هدف**\n\n"
        "هدف شما از عضویت در این بات چیه؟\n"
        "گزینه مورد نظرت رو انتخاب کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💍 ازدواج", callback_data="purpose_marriage")],
            [InlineKeyboardButton("💑 دوستی", callback_data="purpose_relationship")],
            [InlineKeyboardButton("🎭 رفاقت", callback_data="purpose_friendship")],
            [InlineKeyboardButton("🤷 نمیدونم", callback_data="purpose_unknown")]
        ])
    )
    return PURPOSE

async def purpose_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    purpose_map = {
        "purpose_marriage": "ازدواج",
        "purpose_relationship": "دوستی",
        "purpose_friendship": "رفاقت",
        "purpose_unknown": "نمیدونم"
    }
    context.user_data['purpose'] = purpose_map[query.data]
    
    await query.edit_message_text(
        "🏙️ **مرحله ۴ از ۱۱: شهر**\n\n"
        "در کدوم شهر زندگی می‌کنی؟\n"
        "مثال: **تهران، اصفهان، مشهد**\n\n"
        "نام شهرت رو وارد کن:",
        parse_mode='Markdown'
    )
    return CITY

async def city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['city'] = update.message.text
    
    await update.message.reply_text(
        "📏 **مرحله ۵ از ۱۱: حداقل سن طرف**\n\n"
        "طرف مقابلت حداقل چند سال داشته باشه؟\n"
        "عدد رو وارد کن:",
        parse_mode='Markdown'
    )
    return AGE_MIN

async def age_min_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age_min = int(update.message.text)
        if age_min < 10 or age_min > 100:
            await update.message.reply_text("❌ عدد بین ۱۰ تا ۱۰۰:")
            return AGE_MIN
        context.user_data['age_min'] = age_min
    except ValueError:
        await update.message.reply_text("❌ فقط عدد:")
        return AGE_MIN
    
    await update.message.reply_text(
        "📏 **مرحله ۶ از ۱۱: حداکثر سن طرف**\n\n"
        "طرف مقابلت حداکثر چند سال داشته باشه؟\n"
        "عدد رو وارد کن:",
        parse_mode='Markdown'
    )
    return AGE_MAX

async def age_max_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age_max = int(update.message.text)
        if age_max < context.user_data['age_min'] or age_max > 100:
            await update.message.reply_text(f"❌ بین {context.user_data['age_min']} تا ۱۰۰:")
            return AGE_MAX
        context.user_data['age_max'] = age_max
    except ValueError:
        await update.message.reply_text("❌ فقط عدد:")
        return AGE_MAX
    
    await show_interests(update, context)
    return INTERESTS

async def show_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    text = (
        "🎨 **مرحله ۷ از ۱۱: علایق**\n\n"
        f"**انتخاب شده:** {', '.join(context.user_data['interests']) if context.user_data['interests'] else 'هیچ'}\n\n"
        "روی هر گزینه بزن تا انتخاب یا حذف بشه.\n"
        "⚠️ **حداقل ۱ و حداکثر ۵ علایق** می‌تونی انتخاب کنی.\n\n"
        "✅ وقتی حداقل ۱ علاقه انتخاب کنی، دکمه **تموم شد** فعال میشه."
    )
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_interests_keyboard(context.user_data['interests'])
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=get_interests_keyboard(context.user_data['interests'])
        )

async def interests_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    if query.data == "interests_done":
        if not context.user_data['interests']:
            await query.edit_message_text(
                "❌ **حداقل یک علاقه باید انتخاب کنی!**\n\n"
                "لطفاً حداقل یکی از گزینه‌ها رو انتخاب کن.",
                parse_mode='Markdown',
                reply_markup=None
            )
            await show_interests(update, context)
            return INTERESTS
        
        await query.edit_message_text(
            "💼 **مرحله ۸ از ۱۱: وضعیت شغلی/تحصیلی**\n\n"
            "وضعیت شغلی یا تحصیلیت چیه؟\n"
            "گزینه مورد نظرت رو انتخاب کن:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 دانشجو", callback_data="job_student")],
                [InlineKeyboardButton("💼 شاغل", callback_data="job_employed")],
                [InlineKeyboardButton("🔍 جویای کار", callback_data="job_seeking")],
                [InlineKeyboardButton("🏠 خانه‌دار", callback_data="job_home")]
            ])
        )
        return JOB_STATUS
    
    interest = query.data.replace("interest_", "")
    
    if interest in context.user_data['interests']:
        context.user_data['interests'].remove(interest)
        await query.answer(f"❌ {interest} حذف شد!")
    else:
        if len(context.user_data['interests']) >= 5:
            await query.edit_message_text(
                "❌ **حداکثر ۵ علاقه** می‌تونی انتخاب کنی!",
                parse_mode='Markdown',
                reply_markup=None
            )
            await show_interests(update, context)
            return INTERESTS
        context.user_data['interests'].append(interest)
        await query.answer(f"✅ {interest} اضافه شد!")
    
    await show_interests(update, context)
    return INTERESTS

async def job_status_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    job_map = {"job_student": "دانشجو", "job_employed": "شاغل", "job_seeking": "جویای کار", "job_home": "خانه‌دار"}
    context.user_data['job_status'] = job_map[query.data]
    
    await query.edit_message_text(
        "📝 **مرحله ۹ از ۱۱: توضیحات**\n\n"
        "یه توضیح کوتاه از خودت بنویس (حداکثر ۲۰۰ کاراکتر)\n"
        "یا دکمه رد شدن رو بزن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ رد شدن", callback_data="description_skip")]])
    )
    return DESCRIPTION

async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if len(text) > 200:
        await update.message.reply_text("❌ حداکثر ۲۰۰ کاراکتر!")
        return DESCRIPTION
    context.user_data['description'] = text
    
    await update.message.reply_text(
        "📸 **مرحله ۱۰ از ۱۱: عکس پروفایل**\n\n"
        "عکس خودت رو بفرست.\n\n"
        "📌 **نکات مهم:**\n"
        "• اگه عکس بفرستی، همون عکس برای طرف مقابل ارسال میشه\n"
        "• اگه عکس نفرستی، **عکس پروفایل تلگرامت** برای طرف فرستاده میشه\n"
        "• اگه نمیخوای **هیچ عکسی** برای کسی ارسال بشه، گزینه **بدون عکس** رو انتخاب کن\n"
        "• بعداً از طریق **ویرایش پروفایل** میتونی عکس اضافه کنی\n\n"
        "📤 عکس رو بفرست یا یکی از گزینه‌های زیر رو انتخاب کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ عکس تلگرام", callback_data="skip_photo")],
            [InlineKeyboardButton("🚫 بدون عکس", callback_data="no_photo")]
        ])
    )
    return PHOTO

async def description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['description'] = ""
    
    await query.edit_message_text(
        "📸 **مرحله ۱۰ از ۱۱: عکس پروفایل**\n\n"
        "عکس خودت رو بفرست.\n\n"
        "📌 **نکات مهم:**\n"
        "• اگه عکس بفرستی، همون عکس برای طرف مقابل ارسال میشه\n"
        "• اگه عکس نفرستی، **عکس پروفایل تلگرامت** برای طرف فرستاده میشه\n"
        "• اگه نمیخوای **هیچ عکسی** برای کسی ارسال بشه، گزینه **بدون عکس** رو انتخاب کن\n"
        "• بعداً از طریق **ویرایش پروفایل** میتونی عکس اضافه کنی\n\n"
        "📤 عکس رو بفرست یا یکی از گزینه‌های زیر رو انتخاب کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ عکس تلگرام", callback_data="skip_photo")],
            [InlineKeyboardButton("🚫 بدون عکس", callback_data="no_photo")]
        ])
    )
    return PHOTO

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_file = update.message.photo[-1]
        context.user_data['photo'] = photo_file.file_id
        context.user_data['no_photo'] = 0  # عکس داره
        await update.message.reply_text(
            "✅ عکس شما با موفقیت ذخیره شد!\n\n"
            "برای ادامه دکمه ✅ ادامه رو بزن:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ادامه", callback_data="photo_done")]])
        )
        return PHOTO
    else:
        await update.message.reply_text(
            "❌ لطفاً یک عکس بفرست!\n"
            "یا یکی از گزینه‌های زیر رو انتخاب کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭️ عکس تلگرام", callback_data="skip_photo")],
                [InlineKeyboardButton("🚫 بدون عکس", callback_data="no_photo")]
            ])
        )
        return PHOTO

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استفاده از عکس پروفایل تلگرام"""
    query = update.callback_query
    await query.answer()
    context.user_data['photo'] = None
    context.user_data['no_photo'] = 0  # عکس تلگرام استفاده میشه
    
    await query.edit_message_text(
        "✅ از عکس پروفایل تلگرامت استفاده میشه.\n\n"
        "اگه بعداً خواستی عکس خودت رو آپلود کنی، از **ویرایش پروفایل** استفاده کن.",
        parse_mode='Markdown'
    )
    await show_privacy_settings(update, context)
    return PRIVACY

async def no_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدون عکس - هیچ عکسی ارسال نشه"""
    query = update.callback_query
    await query.answer()
    context.user_data['photo'] = None
    context.user_data['no_photo'] = 1  # هیچ عکسی ارسال نشه
    
    await query.edit_message_text(
        "✅ تنظیم شد: **هیچ عکسی** برای کسی ارسال نمیشه.\n\n"
        "اگه بعداً خواستی عکس اضافه کنی، از **ویرایش پروفایل** استفاده کن.",
        parse_mode='Markdown'
    )
    await show_privacy_settings(update, context)
    return PRIVACY

async def photo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_privacy_settings(update, context)
    return PRIVACY

async def show_privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'privacy' not in context.user_data:
        context.user_data['privacy'] = {'show_age': True, 'show_city': True, 'visibility': 'all'}
    
    age_status = "✅" if context.user_data['privacy']['show_age'] else "❌"
    city_status = "✅" if context.user_data['privacy']['show_city'] else "❌"
    vis_text = {'all': '🌍 همه', 'same_city': '🏙️ همشهری', 'none': '❌ هیچکس'}[context.user_data['privacy']['visibility']]
    
    keyboard = [
        [InlineKeyboardButton(f"{age_status} نمایش سن", callback_data="toggle_age")],
        [InlineKeyboardButton(f"{city_status} نمایش شهر", callback_data="toggle_city")],
        [InlineKeyboardButton(f"🌍 نمایش به: {vis_text}", callback_data="change_visibility")],
        [InlineKeyboardButton("✅ تایید", callback_data="privacy_done")]
    ]
    
    text = "🔒 **مرحله ۱۱ از ۱۱: حریم خصوصی**\n\nتنظیمات حریم خصوصی خودت رو مشخص کن:"
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def privacy_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "toggle_age":
        context.user_data['privacy']['show_age'] = not context.user_data['privacy']['show_age']
        await show_privacy_settings(update, context)
    elif query.data == "toggle_city":
        context.user_data['privacy']['show_city'] = not context.user_data['privacy']['show_city']
        await show_privacy_settings(update, context)
    elif query.data == "change_visibility":
        options = ['all', 'same_city', 'none']
        current = context.user_data['privacy']['visibility']
        next_idx = (options.index(current) + 1) % len(options)
        context.user_data['privacy']['visibility'] = options[next_idx]
        await show_privacy_settings(update, context)
    elif query.data == "privacy_done":
        await finish_registration(update, context)
        return PRIVACY

async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # اگر کاربر "بدون عکس" رو انتخاب کرده
    if context.user_data.get('no_photo', 0) == 1:
        photo_file_id = None
    # اگر عکس آپلود کرده
    elif context.user_data.get('photo'):
        photo_file_id = context.user_data['photo']
    # استفاده از عکس تلگرام
    else:
        try:
            user_photos = await context.bot.get_user_profile_photos(user_id, limit=1)
            if user_photos.total_count > 0:
                photo_file_id = user_photos.photos[0][-1].file_id
            else:
                photo_file_id = None
        except:
            photo_file_id = None
    
    user_data = {
        'user_id': user_id,
        'gender': context.user_data['gender'],
        'age': context.user_data['age'],
        'purpose': context.user_data['purpose'],
        'city': context.user_data['city'],
        'age_min': context.user_data['age_min'],
        'age_max': context.user_data['age_max'],
        'interests': json.dumps(context.user_data['interests']),
        'job_status': context.user_data['job_status'],
        'description': context.user_data['description'],
        'privacy_age': 1 if context.user_data['privacy']['show_age'] else 0,
        'privacy_city': 1 if context.user_data['privacy']['show_city'] else 0,
        'privacy_visibility': context.user_data['privacy']['visibility'],
        'photo_file_id': photo_file_id,
        'no_photo': 1 if context.user_data.get('no_photo', 0) == 1 else 0,
        'is_active': 1,
        'created_at': datetime.now(),
        'last_active': datetime.now(),
        'is_setup_complete': 1,
        'is_banned': 0,
        'report_count': 0
    }
    
    if save_user(user_id, user_data):
        context.user_data.clear()
        is_admin = (user_id == ADMIN_ID)
        
        if isinstance(update, Update) and update.callback_query:
            query = update.callback_query
            await query.edit_message_text(
                "🎉 ثبت‌نام کامل شد!",
                reply_markup=main_menu_keyboard(is_admin)
            )
        else:
            await update.message.reply_text(
                "🎉 ثبت‌نام کامل شد!",
                reply_markup=main_menu_keyboard(is_admin)
            )
    else:
        await update.message.reply_text("❌ خطا!", reply_markup=main_menu_keyboard())
    
    return ConversationHandler.END

# ============ بقیه هندلرها ============

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = get_user_dict(user_id)
    
    if not user or not user['is_setup_complete']:
        await query.edit_message_text("❌ ثبت‌نام کن!", reply_markup=main_menu_keyboard())
        return
    
    if user['is_banned']:
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    cleanup_expired_chats()
    
    try:
        week_ago = datetime.now() - timedelta(days=7)
        rejected = db.fetchall("SELECT rejected_user_id FROM rejected WHERE user_id=? AND rejected_at > ?", (user_id, week_ago))
        rejected_ids = [row['rejected_user_id'] for row in rejected]
        
        active_chats = db.fetchall("SELECT user2 FROM chats WHERE user1=? AND is_active=1 UNION SELECT user1 FROM chats WHERE user2=? AND is_active=1", (user_id, user_id))
        active_ids = [row[0] for row in active_chats]
        
        blocked = db.fetchall("SELECT blocked_id FROM blocks WHERE blocker_id=? UNION SELECT blocker_id FROM blocks WHERE blocked_id=?", (user_id, user_id))
        blocked_ids = [row[0] for row in blocked]
        
        admin_blocked = get_admin_blocked_users()
        
        query_str = """
            SELECT * FROM users 
            WHERE user_id != ? 
            AND is_active = 1 
            AND is_setup_complete = 1
            AND is_banned = 0
            AND age BETWEEN ? AND ?
            AND purpose = ?
        """
        params = [user_id, user['age_min'], user['age_max'], user['purpose']]
        
        if user['privacy_visibility'] == 'same_city':
            query_str += " AND city = ?"
            params.append(user['city'])
        
        if rejected_ids:
            query_str += f" AND user_id NOT IN ({','.join(['?']*len(rejected_ids))})"
            params.extend(rejected_ids)
        if active_ids:
            query_str += f" AND user_id NOT IN ({','.join(['?']*len(active_ids))})"
            params.extend(active_ids)
        if blocked_ids:
            query_str += f" AND user_id NOT IN ({','.join(['?']*len(blocked_ids))})"
            params.extend(blocked_ids)
        if admin_blocked:
            query_str += f" AND user_id NOT IN ({','.join(['?']*len(admin_blocked))})"
            params.extend(admin_blocked)
        
        candidates = db.fetchall(query_str, tuple(params))
        
        if not candidates:
            await query.edit_message_text("😔 کسی پیدا نشد!", reply_markup=main_menu_keyboard())
            return
        
        context.user_data['candidates'] = candidates
        context.user_data['candidate_index'] = 0
        await show_candidate(update, context)
        
    except Exception as e:
        logger.error(f"Error in search: {e}")
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

async def show_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    candidates = context.user_data.get('candidates', [])
    index = context.user_data.get('candidate_index', 0)
    
    if index >= len(candidates):
        await query.edit_message_text("🎯 پایان!", reply_markup=main_menu_keyboard())
        return
    
    candidate = candidates[index]
    user_dict = dict(candidate)
    
    message = f"👤 {index+1}/{len(candidates)}\n\n"
    message += f"سن: {user_dict['age'] if user_dict['privacy_age'] else '❌'}\n"
    message += f"شهر: {user_dict['city'] if user_dict['privacy_city'] else '❌'}\n"
    message += f"هدف: {user_dict['purpose']}\n"
    message += f"وضعیت: {user_dict['job_status']}\n"
    
    interests = json.loads(user_dict['interests']) if user_dict['interests'] else []
    if interests:
        message += f"🎨 علایق: {', '.join(interests[:3])}"
        if len(interests) > 3:
            message += f" +{len(interests)-3}"
    
    keyboard = [
        [InlineKeyboardButton("👍", callback_data=f"like_{user_dict['user_id']}"),
         InlineKeyboardButton("👎", callback_data=f"dislike_{user_dict['user_id']}"),
         InlineKeyboardButton("❓", callback_data=f"more_{user_dict['user_id']}")],
        [InlineKeyboardButton("⏩ بعدی", callback_data="next_candidate")]
    ]
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

async def candidate_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        action = query.data.split('_')[0]
        target_id = int(query.data.split('_')[1])
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(target_id):
        await query.edit_message_text("❌ کاربر مسدود شده!", reply_markup=main_menu_keyboard())
        return
    
    if action == "like":
        try:
            existing = db.fetchone("SELECT * FROM requests WHERE from_user=? AND to_user=? AND status='pending'", (user_id, target_id))
            
            if not existing:
                db.execute("INSERT INTO requests (from_user, to_user, created_at, expires_at) VALUES (?, ?, ?, ?)", 
                          (user_id, target_id, datetime.now(), datetime.now() + timedelta(days=3)))
                
                # ارسال پیام به طرف مقابل با مشاهده عکس
                try:
                    target_user = get_user_dict(target_id)
                    if target_user:
                        # دریافت عکس کاربر
                        user_photo = get_user_photo(user_id)
                        
                        message_text = (
                            f"📩 **یه نفر به شما علاقه داره!**\n\n"
                            f"👤 {target_user['gender']} {target_user['age']} ساله"
                        )
                        
                        # ارسال عکس اگه وجود داره
                        if user_photo:
                            try:
                                await context.bot.send_photo(
                                    target_id,
                                    photo=user_photo,
                                    caption=message_text,
                                    parse_mode='Markdown',
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("👀 مشاهده پروفایل", callback_data=f"view_{user_id}")],
                                        [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{user_id}")],
                                        [InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}")]
                                    ])
                                )
                            except:
                                # اگر عکس ارسال نشد، پیام متنی بفرست
                                await context.bot.send_message(
                                    target_id,
                                    message_text + "\n\n(عکس قابل ارسال نبود)",
                                    parse_mode='Markdown',
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("👀 مشاهده پروفایل", callback_data=f"view_{user_id}")],
                                        [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{user_id}")],
                                        [InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}")]
                                    ])
                                )
                        else:
                            # بدون عکس
                            await context.bot.send_message(
                                target_id,
                                message_text + "\n\n(بدون عکس)",
                                parse_mode='Markdown',
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("👀 مشاهده پروفایل", callback_data=f"view_{user_id}")],
                                    [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{user_id}")],
                                    [InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}")]
                                ])
                            )
                except Exception as e:
                    logger.error(f"Error sending request notification: {e}")
            
            await query.edit_message_text("✅ درخواست ارسال شد!", reply_markup=main_menu_keyboard())
            
        except Exception as e:
            logger.error(f"Error in like: {e}")
            await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
    
    elif action == "dislike":
        try:
            db.execute("INSERT OR REPLACE INTO rejected (user_id, rejected_user_id, rejected_at) VALUES (?, ?, ?)", 
                      (user_id, target_id, datetime.now()))
            await query.edit_message_text("✅ رد شد!", reply_markup=None)
            if 'candidate_index' in context.user_data:
                context.user_data['candidate_index'] += 1
            await show_candidate(update, context)
        except:
            await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
    
    elif action == "more":
        target_user = get_user_dict(target_id)
        if target_user:
            interests = json.loads(target_user['interests']) if target_user['interests'] else []
            message = f"📋 اطلاعات بیشتر:\n\n🎨 علایق: {', '.join(interests) if interests else '❌'}\n"
            if target_user['description']:
                message += f"\n📝 {target_user['description']}"
            else:
                message += "\n📝 توضیحی ندارد"
            
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data=f"back_{target_id}")]]))

# ============ مشاهده پروفایل با عکس ============
async def view_requester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        requester_id = int(query.data.replace("view_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    if is_admin_blocked(requester_id):
        await query.edit_message_text("❌ کاربر مسدود شده!", reply_markup=main_menu_keyboard())
        return
    
    requester = get_user_dict(requester_id)
    if not requester:
        await query.edit_message_text("❌ کاربر پیدا نشد!", reply_markup=main_menu_keyboard())
        return
    
    message = f"👤 **اطلاعات کاربر**\n\n"
    message += f"جنسیت: {requester['gender']}\n"
    message += f"سن: {requester['age'] if requester['privacy_age'] else '❌'}\n"
    message += f"شهر: {requester['city'] if requester['privacy_city'] else '❌'}\n"
    message += f"هدف: {requester['purpose']}\n"
    message += f"وضعیت: {requester['job_status']}\n"
    
    interests = json.loads(requester['interests']) if requester['interests'] else []
    if interests:
        message += f"🎨 علایق: {', '.join(interests)}"
    
    if requester['description']:
        message += f"\n\n📝 {requester['description']}"
    
    keyboard = [
        [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{requester_id}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"reject_{requester_id}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
    ]
    
    # ارسال عکس اگه وجود داره
    user_photo = get_user_photo(requester_id)
    if user_photo:
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=update.effective_user.id,
                photo=user_photo,
                caption=message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        except:
            pass
    
    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# ============ مدیریت درخواست‌ها ============
async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        action = query.data.split('_')[0]
        user_id = int(query.data.split('_')[1])
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    if is_admin_blocked(user_id) or is_admin_blocked(current_user):
        await query.edit_message_text("❌ کاربر مسدود شده!", reply_markup=main_menu_keyboard())
        return
    
    try:
        request = db.fetchone("SELECT * FROM requests WHERE from_user=? AND to_user=? AND status='pending'", (user_id, current_user))
        
        if not request:
            await query.edit_message_text("❌ درخواست وجود ندارد!", reply_markup=main_menu_keyboard())
            return
        
        if action == "accept":
            db.execute("UPDATE requests SET status='accepted' WHERE from_user=? AND to_user=? AND status='pending'", (user_id, current_user))
            
            db.execute("INSERT INTO chats (user1, user2, match_date, expiry_date, last_message_at) VALUES (?, ?, ?, ?, ?)", 
                      (user_id, current_user, datetime.now(), datetime.now() + timedelta(days=3), datetime.now()))
            
            chat_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # قوانین چت
            chat_rules = (
                "📋 **قوانین چت در بات هم‌نوا**\n\n"
                "🔒 **حریم خصوصی:**\n"
                "• تا زمانی که به فرد مقابل اطمینان کامل پیدا نکردید، از به اشتراک گذاشتن شماره تماس، آیدی تلگرام و سایر اطلاعات شخصی خودداری کنید.\n"
                "• لطفاً در چت از ذکر نام کامل، آدرس محل سکونت و اطلاعات کاری خود بپرهیزید.\n\n"
                "🤝 **ادب و احترام:**\n"
                "• از هرگونه فحاشی، توهین و بی‌ادبی در چت خودداری کنید.\n"
                "• با احترام و ادب با طرف مقابل صحبت کنید.\n\n"
                "🚫 **مزاحمت و آزار:**\n"
                "• در صورت مشاهده هرگونه رفتار نامناسب، مزاحمت، اسپم یا فحاشی، از گزینه **گزارش و بلاک** استفاده کنید.\n"
                "• گزارش‌های شما به ما کمک می‌کند تا محیطی امن برای همه کاربران فراهم کنیم.\n\n"
                "💡 **نکات مهم:**\n"
                "• این چت تا ۳ روز دیگر منقضی می‌شود.\n"
                "• در صورت نیاز می‌توانید چت را بسته یا طرف مقابل را بلاک کنید.\n"
                "• لطفاً با دید باز و بدون پیش‌داوری وارد چت شوید.\n\n"
                "✨ امیدواریم لحظات خوبی را در کنار هم تجربه کنید. ✨"
            )
            
            for user in [user_id, current_user]:
                try:
                    await context.bot.send_message(
                        user,
                        chat_rules,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 شروع چت", callback_data=f"chat_{chat_id}")]])
                    )
                except Exception as e:
                    logger.error(f"Error sending rules to user {user}: {e}")
            
            await query.edit_message_text(
                "🎉 **شما همدیگرو پسندیدین!** 🎉\n\n"
                "📋 قوانین چت براتون ارسال شد.\n"
                "لطفاً قبل از شروع چت، قوانین رو مطالعه کنید.",
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard()
            )
        
        elif action == "reject":
            db.execute("UPDATE requests SET status='rejected' WHERE from_user=? AND to_user=? AND status='pending'", (user_id, current_user))
            
            try:
                await context.bot.send_message(user_id, "😔 طرف مقابل درخواست شما رو رد کرد!")
            except:
                pass
            
            await query.edit_message_text("❌ رد شد!", reply_markup=main_menu_keyboard())
            
    except Exception as e:
        logger.error(f"Error in handle_request: {e}")
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

# ============ مدیریت چت ============
async def chat_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات طرف مقابل در چت"""
    query = update.callback_query
    await query.answer()
    
    try:
        chat_id = int(query.data.replace("chat_info_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    chat = get_chat_info(chat_id)
    if not chat:
        await query.edit_message_text("❌ چت پیدا نشد!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    other_user = chat['user2'] if chat['user1'] == current_user else chat['user1']
    other = get_user_dict(other_user)
    
    if not other:
        await query.edit_message_text("❌ کاربر پیدا نشد!", reply_markup=main_menu_keyboard())
        return
    
    message = f"👤 **اطلاعات هم‌چت**\n\n"
    message += f"جنسیت: {other['gender']}\n"
    message += f"سن: {other['age'] if other['privacy_age'] else '❌'}\n"
    message += f"شهر: {other['city'] if other['privacy_city'] else '❌'}\n"
    message += f"هدف: {other['purpose']}\n"
    message += f"وضعیت: {other['job_status']}\n"
    
    interests = json.loads(other['interests']) if other['interests'] else []
    if interests:
        message += f"🎨 علایق: {', '.join(interests)}"
    
    if other['description']:
        message += f"\n\n📝 {other['description']}"
    
    # ارسال عکس اگه وجود داره
    user_photo = get_user_photo(other_user)
    if user_photo:
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=current_user,
                photo=user_photo,
                caption=message,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 برگشت به چت", callback_data=f"back_chat_{chat_id}")]
                ])
            )
            return
        except:
            pass
    
    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 برگشت به چت", callback_data=f"back_chat_{chat_id}")]
        ])
    )

async def back_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """برگشت به چت از صفحه اطلاعات"""
    query = update.callback_query
    await query.answer()
    
    try:
        chat_id = int(query.data.replace("back_chat_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    chat = get_chat_info(chat_id)
    if not chat or not chat['is_active']:
        await query.edit_message_text("❌ چت فعال نیست!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    other_user = chat['user2'] if chat['user1'] == current_user else chat['user1']
    
    context.user_data['active_chat'] = chat_id
    context.user_data['chat_partner'] = other_user
    
    await query.edit_message_text(
        "💬 برگشت به چت:",
        reply_markup=chat_keyboard(other_user, chat_id)
    )

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        chat_id = int(query.data.replace("chat_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    try:
        chat = get_chat_info(chat_id)
        
        if not chat or not chat['is_active']:
            await query.edit_message_text("❌ چت فعال نیست!", reply_markup=main_menu_keyboard())
            return
        
        current_user = update.effective_user.id
        
        if is_admin_blocked(current_user):
            await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
            return
        
        if chat['blocked_by'] and chat['blocked_by'] != current_user:
            await query.edit_message_text("🚫 بلاک شدید!", reply_markup=main_menu_keyboard())
            return
        
        if current_user not in [chat['user1'], chat['user2']]:
            await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
            return
        
        other_user = chat['user2'] if chat['user1'] == current_user else chat['user1']
        
        if is_admin_blocked(other_user):
            await query.edit_message_text("❌ کاربر مقابل مسدود شده!", reply_markup=main_menu_keyboard())
            return
        
        context.user_data['active_chat'] = chat_id
        context.user_data['chat_partner'] = other_user
        
        await query.message.reply_text(
            "💬 چت شروع شد!",
            reply_markup=chat_keyboard(other_user, chat_id)
        )
        
        try:
            await query.message.delete()
        except:
            pass
            
    except Exception as e:
        logger.error(f"Error in start_chat: {e}")
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

async def show_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    cleanup_expired_chats()
    chats = get_active_chats(user_id)
    
    if not chats:
        await query.edit_message_text("❌ چت فعالی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    keyboard = []
    for chat in chats:
        other_user = chat['user2'] if chat['user1'] == user_id else chat['user1']
        other = get_user_dict(other_user)
        if other and not is_admin_blocked(other_user):
            last_msg = f" - {chat['last_message_at'][:16]}" if chat['last_message_at'] else ""
            keyboard.append([InlineKeyboardButton(f"💬 {other['gender']} {other['age']}ساله{last_msg}", callback_data=f"switch_chat_{chat['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")])
    
    await query.edit_message_text("📋 چت‌های شما:", reply_markup=InlineKeyboardMarkup(keyboard))

async def switch_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        chat_id = int(query.data.replace("switch_chat_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    chat = get_chat_info(chat_id)
    
    if not chat or not chat['is_active']:
        await query.edit_message_text("❌ چت فعال نیست!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    other_user = chat['user2'] if chat['user1'] == current_user else chat['user1']
    
    if is_admin_blocked(other_user):
        await query.edit_message_text("❌ کاربر مقابل مسدود شده!", reply_markup=main_menu_keyboard())
        return
    
    context.user_data['active_chat'] = chat_id
    context.user_data['chat_partner'] = other_user
    
    await query.edit_message_text(
        "✅ چت فعال شد!",
        reply_markup=chat_keyboard(other_user, chat_id)
    )

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر اصلی پیام‌های چت"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # ============ اول: بررسی حالت پشتیبانی ============
    if context.user_data.get('support_mode'):
        await support_message_input(update, context)
        return
    
    # ============ دوم: بررسی بلاک توسط ادمین ============
    if is_admin_blocked(user_id):
        await update.message.reply_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    # ============ سوم: بررسی ثبت‌نام ============
    if user and not user['is_setup_complete']:
        return
    
    # ============ چهارم: بررسی حالت ویرایش ============
    if 'editing_field' in context.user_data:
        return
    
    # ============ پنجم: بررسی چت فعال ============
    if 'active_chat' not in context.user_data:
        if user and user['is_setup_complete']:
            await update.message.reply_text("❌ در چتی نیستی!", reply_markup=main_menu_keyboard())
        return
    
    # ============ ششم: ادامه کد چت ============
    chat_id = context.user_data['active_chat']
    sender_id = user_id
    
    chat = get_chat_info(chat_id)
    
    if not chat or not chat['is_active']:
        await update.message.reply_text("❌ چت فعال نیست!", reply_markup=main_menu_keyboard())
        context.user_data.pop('active_chat', None)
        return
    
    if chat['blocked_by'] and chat['blocked_by'] != sender_id:
        await update.message.reply_text("🚫 بلاک شدید!", reply_markup=main_menu_keyboard())
        context.user_data.pop('active_chat', None)
        return
    
    partner_id = chat['user2'] if chat['user1'] == sender_id else chat['user1']
    
    if is_admin_blocked(partner_id):
        await update.message.reply_text("❌ کاربر مقابل مسدود شده!", reply_markup=main_menu_keyboard())
        context.user_data.pop('active_chat', None)
        return
    
    db.execute("UPDATE chats SET last_message_at=? WHERE id=?", (datetime.now(), chat_id))
    
    # دریافت اطلاعات فرستنده برای نمایش به گیرنده
    sender = get_user_dict(sender_id)
    sender_info = f"{sender['gender']} {sender['age']} ساله" if sender else "کاربر"
    
    try:
        if update.message.photo:
            caption = update.message.caption if update.message.caption else None
            await context.bot.send_photo(
                chat_id=partner_id, 
                photo=update.message.photo[-1].file_id, 
                caption=caption
            )
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.text:
            await context.bot.send_message(
                chat_id=partner_id, 
                text=f"📩 پیام از {sender_info}:\n\n{update.message.text}"
            )
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.sticker:
            await context.bot.send_sticker(partner_id, update.message.sticker.file_id)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.animation:
            caption = update.message.caption if update.message.caption else "🎬 گیف"
            await context.bot.send_animation(partner_id, update.message.animation.file_id, caption=caption)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.video:
            caption = update.message.caption if update.message.caption else "🎥 ویدیو"
            await context.bot.send_video(partner_id, update.message.video.file_id, caption=caption)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.voice:
            await context.bot.send_voice(partner_id, update.message.voice.file_id)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.audio:
            await context.bot.send_audio(partner_id, update.message.audio.file_id)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        elif update.message.document:
            caption = update.message.caption if update.message.caption else "📄 فایل"
            await context.bot.send_document(partner_id, update.message.document.file_id, caption=caption)
            await update.message.reply_text("✅", reply_markup=chat_keyboard(partner_id, chat_id))
        else:
            await update.message.reply_text("❌ این نوع پیام پشتیبانی نمی‌شه!", reply_markup=chat_keyboard(partner_id, chat_id))
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        await update.message.reply_text("❌ ارسال ناموفق!", reply_markup=chat_keyboard(partner_id, chat_id))

# ============ بلاک توسط کاربر ============
async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = int(query.data.replace("bl_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    keyboard = [
        [InlineKeyboardButton("🔞 فحاشی", callback_data=f"br_a_{user_id}")],
        [InlineKeyboardButton("📱 مزاحمت", callback_data=f"br_s_{user_id}")],
        [InlineKeyboardButton("🎭 کلاهبرداری", callback_data=f"br_f_{user_id}")],
        [InlineKeyboardButton("❌ مورد پسندم نبود", callback_data=f"br_n_{user_id}")],
        [InlineKeyboardButton("🔙 انصراف", callback_data="close_chat")]
    ]
    
    await query.edit_message_text("🚫 دلیل بلاک:", reply_markup=InlineKeyboardMarkup(keyboard))

async def block_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        reason = parts[1]
        user_id = int(parts[2])
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    try:
        db.execute("INSERT INTO blocks (blocker_id, blocked_id, reason, created_at) VALUES (?, ?, ?, ?)", 
                  (current_user, user_id, reason, datetime.now()))
        
        if chat_id:
            db.execute("UPDATE chats SET is_active=0, blocked_by=? WHERE id=?", (current_user, chat_id))
        
        reason_text = {"a": "فحاشی", "s": "مزاحمت", "f": "کلاهبرداری", "n": "مورد پسندم نبود"}.get(reason, "نامشخص")
        
        try:
            await context.bot.send_message(user_id, f"🚫 شما بلاک شدید!\nدلیل: {reason_text}")
        except:
            pass
        
        context.user_data.pop('active_chat', None)
        context.user_data.pop('chat_partner', None)
        
        await query.edit_message_text(f"✅ بلاک شد!\nدلیل: {reason_text}", reply_markup=main_menu_keyboard())
        
    except Exception as e:
        logger.error(f"Error in block_reason: {e}")
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

# ============ آنبلاک ============
async def blocked_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    blocked = db.fetchall("SELECT blocked_id, reason, created_at FROM blocks WHERE blocker_id=? ORDER BY created_at DESC", (user_id,))
    
    if not blocked:
        await query.edit_message_text("📋 کسی را بلاک نکرده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    message = "🚫 افراد بلاک شده:\n\n"
    keyboard = []
    
    for item in blocked:
        reason_text = {"a": "فحاشی", "s": "مزاحمت", "f": "کلاهبرداری", "n": "مورد پسندم نبود"}.get(item['reason'], item['reason'])
        message += f"👤 {item['blocked_id']} - {reason_text}\n"
        keyboard.append([InlineKeyboardButton(f"🔓 آنبلاک {item['blocked_id']}", callback_data=f"unblock_{item['blocked_id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = int(query.data.replace("unblock_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    try:
        db.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?", (current_user, user_id))
        db.execute("DELETE FROM rejected WHERE user_id=? AND rejected_user_id=?", (current_user, user_id))
        
        await query.edit_message_text(f"✅ {user_id} آنبلاک شد!", reply_markup=main_menu_keyboard())
        
    except Exception as e:
        logger.error(f"Error in unblock_user: {e}")
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

# ============ گزارش تخلف با ارسال چت به ادمین ============
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = int(query.data.replace("rp_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    keyboard = [
        [InlineKeyboardButton("🔞 فحاشی", callback_data=f"rr_a_{user_id}_{chat_id}")],
        [InlineKeyboardButton("📱 مزاحمت", callback_data=f"rr_s_{user_id}_{chat_id}")],
        [InlineKeyboardButton("🎭 کلاهبرداری", callback_data=f"rr_f_{user_id}_{chat_id}")],
        [InlineKeyboardButton("🔞 محتوای نامناسب", callback_data=f"rr_i_{user_id}_{chat_id}")],
        [InlineKeyboardButton("🔙 انصراف", callback_data="close_chat")]
    ]
    
    await query.edit_message_text("⚠️ دلیل گزارش:", reply_markup=InlineKeyboardMarkup(keyboard))

async def report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        reason = parts[1]
        user_id = int(parts[2])
        chat_id = int(parts[3]) if len(parts) > 3 else None
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    try:
        # ثبت گزارش در دیتابیس با chat_id
        db.execute("""
            INSERT INTO reports (reporter_id, reported_id, reason, created_at, status, chat_id)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (current_user, user_id, reason, datetime.now(), chat_id))
        
        reason_text = {
            "a": "فحاشی و بی‌ادبی",
            "s": "مزاحمت و اسپم",
            "f": "دروغ و کلاهبرداری",
            "i": "محتوای نامناسب"
        }.get(reason, "نامشخص")
        
        # دریافت اطلاعات کاربران
        reporter = get_user_dict(current_user)
        reported = get_user_dict(user_id)
        
        # دریافت تاریخچه چت (آخرین ۱۰ پیام)
        chat_history = ""
        if chat_id:
            messages = db.fetchall(
                "SELECT sender_id, message_text, timestamp FROM messages WHERE chat_id=? ORDER BY timestamp DESC LIMIT 10",
                (chat_id,)
            )
            if messages:
                chat_history = "\n\n📝 **آخرین پیام‌های چت:**\n"
                for msg in reversed(messages):
                    sender = "گزارش‌دهنده" if msg['sender_id'] == current_user else "گزارش‌شونده"
                    chat_history += f"{sender}: {msg['message_text']}\n"
        
        # ارسال گزارش کامل به ادمین
        if ADMIN_ID:
            try:
                admin_msg = (
                    f"⚠️ **گزارش جدید تخلف** ⚠️\n\n"
                    f"👤 **گزارش‌دهنده:**\n"
                    f"   آیدی: `{current_user}`\n"
                    f"   جنسیت: {reporter['gender'] if reporter else 'نامشخص'}\n"
                    f"   سن: {reporter['age'] if reporter else 'نامشخص'}\n\n"
                    f"👤 **گزارش‌شونده:**\n"
                    f"   آیدی: `{user_id}`\n"
                    f"   جنسیت: {reported['gender'] if reported else 'نامشخص'}\n"
                    f"   سن: {reported['age'] if reported else 'نامشخص'}\n\n"
                    f"📌 **دلیل گزارش:** {reason_text}\n"
                    f"📅 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    f"{chat_history}\n\n"
                    f"🔹 **لطفاً بررسی کنید و تصمیم بگیرید:**"
                )
                
                await context.bot.send_message(
                    ADMIN_ID,
                    admin_msg,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ تایید و بلاک", callback_data=f"admin_block_from_report_{user_id}")],
                        [InlineKeyboardButton("❌ رد گزارش", callback_data=f"admin_reject_report_{user_id}")],
                        [InlineKeyboardButton("📋 همه گزارش‌ها", callback_data="admin_reports")]
                    ])
                )
                
                logger.info(f"✅ Report sent to admin: reporter={current_user}, reported={user_id}, reason={reason_text}")
                
            except Exception as e:
                logger.error(f"Error sending report to admin: {e}")
        
        # پاسخ به کاربر
        reply_markup = chat_keyboard(user_id, chat_id) if chat_id else main_menu_keyboard()
        
        await query.edit_message_text(
            f"✅ **گزارش شما ثبت شد!**\n\n"
            f"📌 دلیل: {reason_text}\n"
            f"🆔 کاربر گزارش‌شونده: `{user_id}`\n\n"
            f"مدیریت گزارش شما رو بررسی میکنه.\n"
            f"از کمک شما به ما در حفظ امنیت متشکریم.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in report_reason: {e}")
        await query.edit_message_text(
            "❌ خطا در ثبت گزارش!",
            reply_markup=main_menu_keyboard()
        )

# ============ پشتیبانی ============
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام به پشتیبانی"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    await query.edit_message_text(
        "📞 **پشتیبانی**\n\n"
        "پیام خودت رو بنویس و بعد دکمه **ارسال** رو بزن.\n"
        "مدیریت در اسرع وقت پاسخ میده.\n\n"
        "⚠️ لطفاً مشکل یا سوالت رو به صورت کامل توضیح بده:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
        ])
    )
    context.user_data['support_mode'] = True

async def support_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت پیام پشتیبانی از کاربر"""
    if not context.user_data.get('support_mode'):
        return
    
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if not message_text:
        await update.message.reply_text("❌ لطفاً پیامت رو بنویس!")
        return
    
    # ذخیره در دیتابیس
    db.execute("""
        INSERT INTO support_messages (user_id, message, created_at, status)
        VALUES (?, ?, ?, 'pending')
    """, (user_id, message_text, datetime.now()))
    
    # ارسال به ادمین
    if ADMIN_ID:
        try:
            user = get_user_dict(user_id)
            admin_msg = (
                f"📞 **پیام پشتیبانی جدید**\n\n"
                f"👤 **کاربر:** `{user_id}`\n"
                f"👤 **نام:** {user['gender'] if user else 'نامشخص'} {user['age'] if user else ''} ساله\n"
                f"📅 **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"📝 **پیام:**\n{message_text}"
            )
            
            await context.bot.send_message(
                ADMIN_ID,
                admin_msg,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user_id}")],
                    [InlineKeyboardButton("📋 همه پیام‌ها", callback_data="admin_support")]
                ])
            )
        except Exception as e:
            logger.error(f"Error sending support to admin: {e}")
    
    await update.message.reply_text(
        "✅ **پیام شما ارسال شد!**\n\n"
        "مدیریت در اسرع وقت پاسخ میده.\n"
        "لطفاً صبور باشید.",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    context.user_data.pop('support_mode', None)

# ============ مدیریت پشتیبانی توسط ادمین ============
async def admin_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مشاهده پیام‌های پشتیبانی توسط ادمین"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    messages = db.fetchall(
        "SELECT * FROM support_messages WHERE status='pending' ORDER BY created_at DESC"
    )
    
    if not messages:
        await query.edit_message_text(
            "📋 پیام جدیدی نیست!",
            reply_markup=admin_panel_keyboard()
        )
        return
    
    message = "📞 **پیام‌های پشتیبانی**\n\n"
    keyboard = []
    
    for msg in messages:
        user = get_user_dict(msg['user_id'])
        user_name = f"{user['gender'] if user else ''} {user['age'] if user else ''}" if user else 'نامشخص'
        message += f"🆔 {msg['id']} - کاربر {msg['user_id']} ({user_name})\n"
        message += f"📝 {msg['message'][:50]}...\n"
        message += f"📅 {msg['created_at'][:16]}\n\n"
        keyboard.append([
            InlineKeyboardButton(f"💬 پاسخ", callback_data=f"admin_reply_{msg['user_id']}"),
            InlineKeyboardButton(f"✅ بسته شد", callback_data=f"admin_close_support_{msg['id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_panel")])
    
    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ادمین به کاربر پاسخ میده"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        user_id = int(query.data.replace("admin_reply_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=admin_panel_keyboard())
        return
    
    await query.edit_message_text(
        f"📞 **پاسخ به کاربر `{user_id}`**\n\n"
        "پیام پاسخ رو بنویس و ارسال کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 برگشت", callback_data="admin_support")]
        ])
    )
    context.user_data['admin_reply_to'] = user_id

async def admin_send_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پاسخ ادمین به کاربر"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    user_id = context.user_data.get('admin_reply_to')
    if not user_id:
        await update.message.reply_text("❌ لطفاً از منوی پشتیبانی استفاده کن!", reply_markup=admin_panel_keyboard())
        return
    
    reply_text = update.message.text
    
    try:
        await context.bot.send_message(
            user_id,
            f"📞 **پاسخ پشتیبانی**\n\n{reply_text}\n\n"
            f"اگه سوال دیگه‌ای داری، باز هم میتونی از گزینه پشتیبانی استفاده کنی.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        
        # بستن پیام‌های پشتیبانی این کاربر
        db.execute("UPDATE support_messages SET status='replied' WHERE user_id=? AND status='pending'", (user_id,))
        
        await update.message.reply_text(
            f"✅ پاسخ شما به کاربر `{user_id}` ارسال شد!",
            reply_markup=admin_panel_keyboard()
        )
        context.user_data.pop('admin_reply_to', None)
        
    except Exception as e:
        logger.error(f"Error sending admin reply: {e}")
        await update.message.reply_text(
            f"❌ خطا در ارسال پاسخ به کاربر `{user_id}`!\n"
            f"ممکن است کاربر ربات رو بلاک کرده باشد.",
            reply_markup=admin_panel_keyboard()
        )
        context.user_data.pop('admin_reply_to', None)

async def admin_close_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بستن پیام پشتیبانی توسط ادمین"""
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        msg_id = int(query.data.replace("admin_close_support_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=admin_panel_keyboard())
        return
    
    db.execute("UPDATE support_messages SET status='closed' WHERE id=?", (msg_id,))
    
    await query.edit_message_text(f"✅ پیام {msg_id} بسته شد!", reply_markup=admin_panel_keyboard())

# ============ مدیریت گزارش توسط ادمین ============
async def admin_reject_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        user_id = int(query.data.replace("admin_reject_report_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=admin_panel_keyboard())
        return
    
    db.execute("UPDATE reports SET status='rejected' WHERE reported_id=? AND status='pending'", (user_id,))
    
    reports = db.fetchall("SELECT reporter_id FROM reports WHERE reported_id=? AND status='rejected'", (user_id,))
    for report in reports:
        try:
            await context.bot.send_message(
                report['reporter_id'],
                f"📋 گزارش شما درباره کاربر `{user_id}` توسط مدیریت **رد شد**.",
                parse_mode='Markdown'
            )
        except:
            pass
    
    await query.edit_message_text(f"✅ گزارش‌های {user_id} رد شد!", reply_markup=admin_panel_keyboard())

async def admin_block_from_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        user_id = int(query.data.replace("admin_block_from_report_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=admin_panel_keyboard())
        return
    
    db.execute("INSERT OR REPLACE INTO admin_blocks (admin_id, blocked_user_id, reason, created_at) VALUES (?, ?, ?, ?)", 
              (ADMIN_ID, user_id, "گزارش تخلف", datetime.now()))
    
    db.execute("UPDATE chats SET is_active=0 WHERE user1=? OR user2=?", (user_id, user_id))
    db.execute("UPDATE reports SET status='resolved' WHERE reported_id=? AND status='pending'", (user_id,))
    
    reports = db.fetchall("SELECT reporter_id FROM reports WHERE reported_id=? AND status='resolved'", (user_id,))
    for report in reports:
        try:
            await context.bot.send_message(
                report['reporter_id'],
                f"✅ گزارش شما درباره کاربر `{user_id}` **تایید شد**!\nکاربر بلاک شد.",
                parse_mode='Markdown'
            )
        except:
            pass
    
    try:
        await context.bot.send_message(
            user_id,
            f"🚫 شما توسط مدیریت بلاک شدید!\nدلیل: گزارش تخلف"
        )
    except:
        pass
    
    await query.edit_message_text(f"✅ {user_id} بلاک شد!", reply_markup=admin_panel_keyboard())

# ============ بقیه هندلرها ============
async def request_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        target_id = int(query.data.replace("photo_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    if is_admin_blocked(target_id):
        await query.edit_message_text("❌ کاربر مسدود شده!", reply_markup=main_menu_keyboard())
        return
    
    # دریافت عکس کاربر
    user_photo = get_user_photo(target_id)
    
    if user_photo:
        try:
            await context.bot.send_photo(
                current_user, 
                user_photo, 
                caption="📸 عکس درخواستی:"
            )
            await query.edit_message_text("✅ ارسال شد!", reply_markup=chat_keyboard(target_id, chat_id))
        except:
            await query.edit_message_text("❌ خطا در ارسال عکس!", reply_markup=chat_keyboard(target_id, chat_id))
    else:
        await query.edit_message_text(
            "❌ این کاربر **هیچ عکسی** تنظیم نکرده!",
            reply_markup=chat_keyboard(target_id, chat_id)
        )

async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop('active_chat', None)
    context.user_data.pop('chat_partner', None)
    
    is_admin = (update.effective_user.id == ADMIN_ID)
    await query.edit_message_text("✅ چت بسته شد!", reply_markup=main_menu_keyboard(is_admin))

async def back_to_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_candidate(update, context)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    
    try:
        await query.edit_message_text("🏠 منو:", reply_markup=main_menu_keyboard(is_admin))
    except:
        await query.message.reply_text("🏠 منو:", reply_markup=main_menu_keyboard(is_admin))

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    user = get_user_dict(user_id)
    if not user or not user['is_setup_complete']:
        await query.edit_message_text("❌ ثبت‌نام نکردی!", reply_markup=main_menu_keyboard())
        return
    
    info = f"📝 اطلاعات شما:\n\n"
    info += f"👤 جنسیت: {user['gender']}\n"
    info += f"📅 سن: {user['age']}\n"
    info += f"🎯 هدف: {user['purpose']}\n"
    info += f"🏙️ شهر: {user['city']}\n"
    
    interests = json.loads(user['interests']) if user['interests'] else []
    info += f"🎨 علایق: {', '.join(interests) if interests else '❌'}\n"
    info += f"💼 وضعیت: {user['job_status']}\n"
    
    if user['no_photo'] == 1:
        info += f"📸 عکس: **بدون عکس**\n"
    elif user['photo_file_id']:
        info += f"📸 عکس: ✅ دارد\n"
    else:
        info += f"📸 عکس: ❌ ندارد (عکس تلگرام)\n"
    info += f"\nکدوم بخش رو ویرایش کنی؟"
    
    keyboard = [
        [InlineKeyboardButton("👤 جنسیت", callback_data="edit_gender"), InlineKeyboardButton("📅 سن", callback_data="edit_age")],
        [InlineKeyboardButton("🎯 هدف", callback_data="edit_purpose"), InlineKeyboardButton("🏙️ شهر", callback_data="edit_city")],
        [InlineKeyboardButton("🎨 علایق", callback_data="edit_interests"), InlineKeyboardButton("💼 وضعیت", callback_data="edit_job")],
        [InlineKeyboardButton("📝 توضیحات", callback_data="edit_description")],
        [InlineKeyboardButton("📸 عکس", callback_data="edit_photo")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard))

async def edit_profile_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    field = query.data.replace("edit_", "")
    user = get_user_dict(user_id)
    
    if field == "gender":
        await query.edit_message_text(
            "جنسیت جدید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨 مرد", callback_data="update_gender_male")],
                [InlineKeyboardButton("👩 زن", callback_data="update_gender_female")],
                [InlineKeyboardButton("🧑 سایر", callback_data="update_gender_other")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    elif field == "age":
        await query.edit_message_text(f"سن فعلی: {user['age']}\n\nسن جدید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]]))
        context.user_data['editing_field'] = 'age'
    elif field == "purpose":
        await query.edit_message_text(
            f"هدف فعلی: {user['purpose']}\n\nهدف جدید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💍 ازدواج", callback_data="update_purpose_marriage")],
                [InlineKeyboardButton("💑 دوستی", callback_data="update_purpose_relationship")],
                [InlineKeyboardButton("🎭 رفاقت", callback_data="update_purpose_friendship")],
                [InlineKeyboardButton("🤷 نمیدونم", callback_data="update_purpose_unknown")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    elif field == "city":
        await query.edit_message_text(f"شهر فعلی: {user['city']}\n\nشهر جدید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]]))
        context.user_data['editing_field'] = 'city'
    elif field == "interests":
        await query.edit_message_text("🎨 علایق جدید:", reply_markup=get_interests_keyboard(json.loads(user['interests']) if user['interests'] else []))
        context.user_data['editing_interests'] = json.loads(user['interests']) if user['interests'] else []
        context.user_data['editing_field'] = 'interests'
    elif field == "job":
        await query.edit_message_text(
            f"وضعیت فعلی: {user['job_status']}\n\nوضعیت جدید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 دانشجو", callback_data="update_job_student")],
                [InlineKeyboardButton("💼 شاغل", callback_data="update_job_employed")],
                [InlineKeyboardButton("🔍 جویای کار", callback_data="update_job_seeking")],
                [InlineKeyboardButton("🏠 خانه‌دار", callback_data="update_job_home")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    elif field == "description":
        await query.edit_message_text(f"توضیحات فعلی: {user['description'] or '❌'}\n\nتوضیحات جدید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]]))
        context.user_data['editing_field'] = 'description'
    elif field == "photo":
        await query.edit_message_text(
            "📸 **ویرایش عکس**\n\n"
            "یکی از گزینه‌های زیر رو انتخاب کن:\n\n"
            "📤 **ارسال عکس جدید:** عکس رو بفرست\n"
            "🔄 **عکس تلگرام:** از عکس پروفایل تلگرام استفاده کن\n"
            "🚫 **بدون عکس:** هیچ عکسی برای کسی ارسال نشه",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 عکس تلگرام", callback_data="update_photo_telegram")],
                [InlineKeyboardButton("🚫 بدون عکس", callback_data="update_photo_none")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
        context.user_data['editing_field'] = 'photo'

async def update_profile_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    data = query.data.replace("update_", "")
    
    if data.startswith("gender_"):
        gender = data.replace("gender_", "")
        gender_map = {"male": "مرد", "female": "زن", "other": "سایر"}
        save_user(user_id, {'gender': gender_map[gender]})
        await query.edit_message_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
    elif data.startswith("purpose_"):
        purpose = data.replace("purpose_", "")
        purpose_map = {"marriage": "ازدواج", "relationship": "دوستی", "friendship": "رفاقت", "unknown": "نمیدونم"}
        save_user(user_id, {'purpose': purpose_map[purpose]})
        await query.edit_message_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
    elif data.startswith("job_"):
        job = data.replace("job_", "")
        job_map = {"student": "دانشجو", "employed": "شاغل", "seeking": "جویای کار", "home": "خانه‌دار"}
        save_user(user_id, {'job_status': job_map[job]})
        await query.edit_message_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
    elif data == "photo_telegram":
        save_user(user_id, {'photo_file_id': None, 'no_photo': 0})
        await query.edit_message_text("✅ از عکس پروفایل تلگرام استفاده میشه!", reply_markup=main_menu_keyboard())
    elif data == "photo_none":
        save_user(user_id, {'photo_file_id': None, 'no_photo': 1})
        await query.edit_message_text("✅ تنظیم شد: هیچ عکسی ارسال نمیشه!", reply_markup=main_menu_keyboard())
    elif data.startswith("interest_"):
        interest = data.replace("interest_", "")
        if 'editing_interests' not in context.user_data:
            context.user_data['editing_interests'] = []
        
        if interest in context.user_data['editing_interests']:
            context.user_data['editing_interests'].remove(interest)
        else:
            if len(context.user_data['editing_interests']) >= 5:
                await query.edit_message_text("❌ حداکثر ۵ علاقه!", reply_markup=None)
                return
            context.user_data['editing_interests'].append(interest)
        
        await edit_profile_field(update, context)
    elif data == "interests_done":
        if not context.user_data.get('editing_interests', []):
            await query.edit_message_text("❌ حداقل یک علاقه!", reply_markup=None)
            await edit_profile_field(update, context)
            return
        
        save_user(user_id, {'interests': json.dumps(context.user_data['editing_interests'])})
        context.user_data.pop('editing_interests', None)
        context.user_data.pop('editing_field', None)
        await query.edit_message_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())

async def handle_profile_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await update.message.reply_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    field = context.user_data.get('editing_field')
    
    if field == 'age':
        try:
            age = int(update.message.text)
            if 10 <= age <= 100:
                save_user(user_id, {'age': age})
                await update.message.reply_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
            else:
                await update.message.reply_text("❌ ۱۰ تا ۱۰۰!")
        except ValueError:
            await update.message.reply_text("❌ عدد وارد کن!")
    elif field == 'city':
        save_user(user_id, {'city': update.message.text})
        await update.message.reply_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
    elif field == 'description':
        text = update.message.text
        if len(text) > 200:
            await update.message.reply_text("❌ حداکثر ۲۰۰!")
            return
        save_user(user_id, {'description': text})
        await update.message.reply_text("✅ به‌روز شد!", reply_markup=main_menu_keyboard())
    elif field == 'photo':
        if update.message.photo:
            photo_file = update.message.photo[-1]
            save_user(user_id, {'photo_file_id': photo_file.file_id, 'no_photo': 0})
            await update.message.reply_text("✅ عکس به‌روز شد!", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("❌ عکس بفرست!")
            return
    
    context.user_data.pop('editing_field', None)

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    received = db.fetchall("SELECT from_user, created_at FROM requests WHERE to_user=? AND status='pending' ORDER BY created_at DESC", (user_id,))
    
    if not received:
        await query.edit_message_text("📋 درخواستی نیست!", reply_markup=main_menu_keyboard())
        return
    
    message = "📋 درخواست‌ها:\n\n"
    keyboard = []
    
    for req in received[:5]:
        from_user = get_user_dict(req['from_user'])
        if from_user and not is_admin_blocked(from_user['user_id']):
            message += f"👤 {from_user['age'] if from_user['privacy_age'] else '❌'} - {from_user['city'] if from_user['privacy_city'] else '❌'}\n"
            keyboard.append([InlineKeyboardButton("👀 مشاهده", callback_data=f"view_{from_user['user_id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

async def privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    user = get_user_dict(user_id)
    if not user:
        await query.edit_message_text("❌ ثبت‌نام نکردی!", reply_markup=main_menu_keyboard())
        return
    
    age_status = "✅" if user['privacy_age'] else "❌"
    city_status = "✅" if user['privacy_city'] else "❌"
    vis_text = {'all': '🌍 همه', 'same_city': '🏙️ همشهری', 'none': '❌ هیچکس'}.get(user['privacy_visibility'], '🌍 همه')
    
    keyboard = [
        [InlineKeyboardButton(f"{age_status} سن", callback_data="privacy_toggle_age"),
         InlineKeyboardButton(f"{city_status} شهر", callback_data="privacy_toggle_city")],
        [InlineKeyboardButton(f"🌍 نمایش به: {vis_text}", callback_data="privacy_change_visibility")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text("🔒 حریم خصوصی:", reply_markup=InlineKeyboardMarkup(keyboard))

async def privacy_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    user = get_user_dict(user_id)
    
    if query.data == "privacy_toggle_age":
        save_user(user_id, {'privacy_age': not user['privacy_age']})
    elif query.data == "privacy_toggle_city":
        save_user(user_id, {'privacy_city': not user['privacy_city']})
    elif query.data == "privacy_change_visibility":
        options = ['all', 'same_city', 'none']
        current = user['privacy_visibility']
        next_idx = (options.index(current) + 1) % len(options)
        save_user(user_id, {'privacy_visibility': options[next_idx]})
    
    await privacy_settings(update, context)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    sent = db.fetchone("SELECT COUNT(*) FROM requests WHERE from_user=? AND status='pending'", (user_id,))[0]
    recv = db.fetchone("SELECT COUNT(*) FROM requests WHERE to_user=? AND status='pending'", (user_id,))[0]
    chats = db.fetchone("SELECT COUNT(*) FROM chats WHERE (user1=? OR user2=?) AND is_active=1", (user_id, user_id))[0]
    
    await query.edit_message_text(
        f"📊 آمار شما:\n\n📤 ارسالی: {sent}\n📥 دریافتی: {recv}\n💬 چت: {chats}",
        reply_markup=main_menu_keyboard()
    )

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        save_user(user_id, {'is_setup_complete': 0})
        context.user_data.clear()
        await query.edit_message_text("🔄 ریست شد! /start بزن.", reply_markup=None)
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if is_admin_blocked(user_id):
        await query.edit_message_text("🚫 شما مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    await query.edit_message_text(
        "ℹ️ **راهنما**\n\n"
        "🔍 **جستجو:** پیدا کردن افراد مناسب\n"
        "💬 **چت‌های من:** مدیریت چت‌های فعال\n"
        "📝 **ویرایش پروفایل:** تغییر اطلاعات\n"
        "📋 **درخواست‌ها:** مشاهده درخواست‌های دریافتی\n"
        "🔒 **حریم خصوصی:** تنظیمات نمایش اطلاعات\n"
        "📊 **آمار:** مشاهده آمار فعالیت\n"
        "🚫 **افراد بلاک شده:** مدیریت بلاک‌ها\n"
        "🔄 **ریست:** ریست کردن ربات\n"
        "📞 **پشتیبانی:** ارتباط با مدیریت\n\n"
        "💡 چت‌ها ۳ روز اعتبار دارند.",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )

# ============ پنل مدیریت ============
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    await query.edit_message_text("👑 **پنل مدیریت**", parse_mode='Markdown', reply_markup=admin_panel_keyboard())

async def admin_block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    await query.edit_message_text(
        "🚫 **بلاک کاربر**\n\nآیدی کاربر رو وارد کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="admin_panel")]])
    )
    context.user_data['admin_action'] = 'block'

async def admin_unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    blocked = get_admin_blocked_users()
    
    if not blocked:
        await query.edit_message_text("📋 کسی بلاک نشده!", reply_markup=admin_panel_keyboard())
        return
    
    message = "📋 لیست بلاک‌شده‌ها:\n\n"
    keyboard = []
    
    for user_id in blocked:
        user = get_user_dict(user_id)
        if user:
            message += f"👤 {user_id}\n"
            keyboard.append([InlineKeyboardButton(f"✅ آنبلاک {user_id}", callback_data=f"admin_unblock_{user_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_panel")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_do_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ عدد وارد کن!", reply_markup=admin_panel_keyboard())
        context.user_data.pop('admin_action', None)
        return
    
    user = get_user(user_id)
    if not user:
        await update.message.reply_text(f"❌ {user_id} پیدا نشد!", reply_markup=admin_panel_keyboard())
        context.user_data.pop('admin_action', None)
        return
    
    db.execute("INSERT OR REPLACE INTO admin_blocks (admin_id, blocked_user_id, reason, created_at) VALUES (?, ?, ?, ?)", 
              (ADMIN_ID, user_id, "بلاک توسط ادمین", datetime.now()))
    
    db.execute("UPDATE chats SET is_active=0 WHERE user1=? OR user2=?", (user_id, user_id))
    
    try:
        await context.bot.send_message(user_id, "🚫 شما توسط مدیریت بلاک شدید!")
    except:
        pass
    
    await update.message.reply_text(f"✅ {user_id} بلاک شد!", reply_markup=admin_panel_keyboard())
    context.user_data.pop('admin_action', None)

async def admin_do_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    try:
        user_id = int(query.data.replace("admin_unblock_", ""))
    except:
        await query.edit_message_text("❌ خطا!", reply_markup=admin_panel_keyboard())
        return
    
    db.execute("DELETE FROM admin_blocks WHERE blocked_user_id=?", (user_id,))
    
    try:
        await context.bot.send_message(user_id, "✅ شما توسط مدیریت آنبلاک شدید!")
    except:
        pass
    
    await query.edit_message_text(f"✅ {user_id} آنبلاک شد!", reply_markup=admin_panel_keyboard())

async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    reports = db.fetchall("SELECT * FROM reports WHERE status='pending' ORDER BY created_at DESC LIMIT 10")
    
    if not reports:
        await query.edit_message_text("📋 گزارش جدیدی نیست!", reply_markup=admin_panel_keyboard())
        return
    
    message = "📋 **گزارش‌ها:**\n\n"
    keyboard = []
    
    for r in reports:
        reason_text = {"a": "فحاشی", "s": "مزاحمت", "f": "کلاهبرداری", "i": "محتوای نامناسب"}.get(r['reason'], r['reason'])
        message += f"🆔 {r['id']} - {r['reported_id']} - {reason_text}\n"
        keyboard.append([
            InlineKeyboardButton(f"🚫 بلاک", callback_data=f"admin_block_from_report_{r['reported_id']}"),
            InlineKeyboardButton(f"❌ رد", callback_data=f"admin_reject_report_{r['reported_id']}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_panel")])
    
    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("❌ دسترسی ندارید!", reply_markup=main_menu_keyboard())
        return
    
    total = db.fetchone("SELECT COUNT(*) FROM users")[0]
    active = db.fetchone("SELECT COUNT(*) FROM users WHERE is_setup_complete=1")[0]
    banned = db.fetchone("SELECT COUNT(*) FROM users WHERE is_banned=1")[0]
    admin_b = db.fetchone("SELECT COUNT(*) FROM admin_blocks")[0]
    pending = db.fetchone("SELECT COUNT(*) FROM reports WHERE status='pending'")[0]
    chats = db.fetchone("SELECT COUNT(*) FROM chats WHERE is_active=1")[0]
    support = db.fetchone("SELECT COUNT(*) FROM support_messages WHERE status='pending'")[0]
    
    await query.edit_message_text(
        f"📊 **آمار ربات**\n\n"
        f"👤 کل کاربران: {total}\n"
        f"✅ کاربران فعال: {active}\n"
        f"🚫 کاربران بلاک شده: {banned}\n"
        f"👑 بلاک شده توسط ادمین: {admin_b}\n"
        f"⚠️ گزارش‌های در انتظار: {pending}\n"
        f"💬 چت‌های فعال: {chats}\n"
        f"📞 پیام‌های پشتیبانی: {support}",
        parse_mode='Markdown',
        reply_markup=admin_panel_keyboard()
    )

# ============ پاکسازی خودکار ============
async def scheduled_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)
            cleanup_expired_chats()
            logger.info("🔄 Scheduled cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# ============ تابع اصلی ============
def main():
    try:
        logger.info("🚀 Starting bot...")
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        application = Application.builder().token(TOKEN).build()
        
        # ثبت‌نام
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
                    CallbackQueryHandler(no_photo, pattern='^no_photo$'),
                    CallbackQueryHandler(photo_done, pattern='^photo_done$')
                ],
                PRIVACY: [CallbackQueryHandler(privacy_selection, pattern='^(toggle_age|toggle_city|change_visibility|privacy_done)')],
            },
            fallbacks=[CommandHandler('start', start)]
        )
        application.add_handler(conv_handler)
        
        # منوها
        application.add_handler(CallbackQueryHandler(search, pattern='^search$'))
        application.add_handler(CallbackQueryHandler(edit_profile, pattern='^edit_profile$'))
        application.add_handler(CallbackQueryHandler(my_requests, pattern='^my_requests$'))
        application.add_handler(CallbackQueryHandler(privacy_settings, pattern='^privacy_settings$'))
        application.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
        application.add_handler(CallbackQueryHandler(reset_bot, pattern='^reset_bot$'))
        application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
        application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))
        application.add_handler(CallbackQueryHandler(support, pattern='^support$'))
        
        # بلاک و آنبلاک
        application.add_handler(CallbackQueryHandler(blocked_users_list, pattern='^blocked_users$'))
        application.add_handler(CallbackQueryHandler(unblock_user, pattern='^unblock_'))
        
        # چت‌ها
        application.add_handler(CallbackQueryHandler(show_chats, pattern='^show_chats$'))
        application.add_handler(CallbackQueryHandler(switch_chat, pattern='^switch_chat_'))
        application.add_handler(CallbackQueryHandler(chat_info, pattern='^chat_info_'))
        application.add_handler(CallbackQueryHandler(back_chat, pattern='^back_chat_'))
        
        # ویرایش
        application.add_handler(CallbackQueryHandler(edit_profile_field, pattern='^edit_(gender|age|purpose|city|interests|job|description|photo)$'))
        application.add_handler(CallbackQueryHandler(update_profile_field, pattern='^update_(gender_|purpose_|job_|interest_|interests_done|photo_telegram|photo_none)'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_text_input))
        application.add_handler(MessageHandler(filters.PHOTO, handle_profile_text_input))
        
        # جستجو و درخواست
        application.add_handler(CallbackQueryHandler(candidate_action, pattern='^(like|dislike|more)_'))
        application.add_handler(CallbackQueryHandler(show_candidate, pattern='^next_candidate$'))
        application.add_handler(CallbackQueryHandler(back_to_candidate, pattern='^back_'))
        application.add_handler(CallbackQueryHandler(view_requester, pattern='^view_'))
        application.add_handler(CallbackQueryHandler(handle_request, pattern='^(accept|reject)_'))
        
        # چت
        application.add_handler(CallbackQueryHandler(start_chat, pattern='^chat_'))
        application.add_handler(CallbackQueryHandler(request_photo, pattern='^photo_'))
        application.add_handler(CallbackQueryHandler(block_user, pattern='^bl_'))
        application.add_handler(CallbackQueryHandler(block_reason, pattern='^br_'))
        application.add_handler(CallbackQueryHandler(close_chat, pattern='^close_chat$'))
        
        # گزارش
        application.add_handler(CallbackQueryHandler(report_user, pattern='^rp_'))
        application.add_handler(CallbackQueryHandler(report_reason, pattern='^rr_'))
        
        # مدیریت گزارش
        application.add_handler(CallbackQueryHandler(admin_reject_report, pattern='^admin_reject_report_'))
        application.add_handler(CallbackQueryHandler(admin_block_from_report, pattern='^admin_block_from_report_'))
        
        # پنل مدیریت
        application.add_handler(CallbackQueryHandler(admin_panel, pattern='^admin_panel$'))
        application.add_handler(CallbackQueryHandler(admin_block_user, pattern='^admin_block_user$'))
        application.add_handler(CallbackQueryHandler(admin_unblock_user, pattern='^admin_unblock_user$'))
        application.add_handler(CallbackQueryHandler(admin_do_unblock, pattern='^admin_unblock_'))
        application.add_handler(CallbackQueryHandler(admin_reports, pattern='^admin_reports$'))
        application.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_do_block))
        
        # پشتیبانی
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_input))
        application.add_handler(CallbackQueryHandler(admin_support, pattern='^admin_support$'))
        application.add_handler(CallbackQueryHandler(admin_reply, pattern='^admin_reply_'))
        application.add_handler(CallbackQueryHandler(admin_close_support, pattern='^admin_close_support_'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_reply))
        
        # حریم خصوصی
        application.add_handler(CallbackQueryHandler(privacy_toggle, pattern='^privacy_toggle_(age|city|change_visibility)$'))
        
        # پیام‌ها
        application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_chat_message), group=1)
        
        # پاکسازی
        loop = asyncio.get_event_loop()
        loop.create_task(scheduled_cleanup())
        
        logger.info("✅ Bot started successfully!")
        
        asyncio.run(application.run_polling(
            allowed_updates=['message', 'callback_query'],
            drop_pending_updates=True
        ))
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
