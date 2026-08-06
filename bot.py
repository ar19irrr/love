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
            is_banned BOOLEAN DEFAULT 0
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
            status TEXT DEFAULT 'pending'
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            blocked_user_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP
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
    """بررسی اینکه کاربر توسط ادمین بلاک شده"""
    result = db.fetchone("SELECT * FROM admin_blocks WHERE blocked_user_id=?", (user_id,))
    return result is not None

def get_admin_blocked_users() -> List[int]:
    """دریافت لیست کاربران بلاک شده توسط ادمین"""
    results = db.fetchall("SELECT blocked_user_id FROM admin_blocks")
    return [row['blocked_user_id'] for row in results]

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
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")]
    ]
    if is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def chat_keyboard(other_user: int):
    """کیبورد شیشه‌ای داخل چت - با callback_data کوتاه برای بلاک و ریپورت"""
    return InlineKeyboardMarkup([
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
    """شروع ربات و نمایش خوش‌آمدگویی"""
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # بررسی بلاک بودن کاربر
    if user and user['is_banned']:
        await update.message.reply_text(
            "🚫 شما توسط مدیریت مسدود شده‌اید!\n"
            "در صورت اعتراض با پشتیبانی تماس بگیرید."
        )
        return
    
    # اگر کاربر قبلاً ثبت‌نام کرده
    if user and user['is_setup_complete']:
        is_admin = (user_id == ADMIN_ID)
        await update.message.reply_text(
            f"🌟 به بات هم‌نوا خوش اومدی {update.effective_user.first_name}!\n\n"
            "از طریق منوی زیر می‌تونی به بخش‌های مختلف دسترسی داشته باشی:",
            reply_markup=main_menu_keyboard(is_admin)
        )
        return ConversationHandler.END
    
    # شروع ثبت‌نام جدید
    context.user_data.clear()
    
    await update.message.reply_text(
        "🌟 **به بات هم‌نوا خوش اومدی!** 🌟\n\n"
        "این بات به تو کمک میکنه تا افراد هم‌فکر و هم‌نوا رو پیدا کنی.\n"
        "برای شروع، لطفاً اطلاعات زیر رو وارد کن تا بتونیم بهترین پیشنهادها رو بهت بدیم.\n\n"
        "**مرحله ۱ از ۱۱: انتخاب جنسیت**\n"
        "لطفاً جنسیت خودت رو انتخاب کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨 مرد", callback_data="gender_male")],
            [InlineKeyboardButton("👩 زن", callback_data="gender_female")],
            [InlineKeyboardButton("🧑 سایر", callback_data="gender_other")]
        ])
    )
    return GENDER

async def gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره جنسیت و رفتن به مرحله بعد"""
    query = update.callback_query
    await query.answer()
    
    gender_map = {
        "gender_male": "مرد",
        "gender_female": "زن",
        "gender_other": "سایر"
    }
    context.user_data['gender'] = gender_map[query.data]
    
    await query.edit_message_text(
        "🌸 **مرحله ۲ از ۱۱: سن**\n\n"
        "چند سالت هست؟\n"
        "لطفاً فقط عدد وارد کن (مثلاً: ۲۵)\n\n"
        "⚠️ محدوده سنی مجاز: ۱۰ تا ۱۰۰ سال",
        parse_mode='Markdown',
        reply_markup=None
    )
    return AGE

async def age_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت سن و رفتن به مرحله بعد"""
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text(
                "❌ سن وارد شده معتبر نیست!\n"
                "لطفاً عددی بین ۱۰ تا ۱۰۰ وارد کن:"
            )
            return AGE
        context.user_data['age'] = age
    except ValueError:
        await update.message.reply_text(
            "❌ لطفاً فقط عدد وارد کن!\n"
            "مثلاً: ۲۵"
        )
        return AGE
    
    await update.message.reply_text(
        "🎯 **مرحله ۳ از ۱۱: هدف از حضور**\n\n"
        "هدف شما از عضویت در این بات چیه؟\n"
        "گزینه مورد نظرت رو انتخاب کن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💍 ازدواج", callback_data="purpose_marriage")],
            [InlineKeyboardButton("💑 رابطه دوستی", callback_data="purpose_relationship")],
            [InlineKeyboardButton("🎭 رفاقت ساده", callback_data="purpose_friendship")],
            [InlineKeyboardButton("🤷 هنوز نمیدونم", callback_data="purpose_unknown")]
        ])
    )
    return PURPOSE

async def purpose_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره هدف و رفتن به مرحله بعد"""
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
        "نام شهر رو وارد کن (مثلاً: تهران، اصفهان، مشهد):",
        parse_mode='Markdown',
        reply_markup=None
    )
    return CITY

async def city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شهر و رفتن به مرحله بعد"""
    context.user_data['city'] = update.message.text
    
    await update.message.reply_text(
        "📏 **مرحله ۵ از ۱۱: محدوده سنی طرف مقابل**\n\n"
        "طرف مقابلت چند ساله باشه؟\n"
        "**حداقل سن** رو وارد کن:",
        parse_mode='Markdown',
        reply_markup=None
    )
    return AGE_MIN

async def age_min_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت حداقل سن و رفتن به مرحله بعد"""
    try:
        age_min = int(update.message.text)
        if age_min < 10 or age_min > 100:
            await update.message.reply_text(
                "❌ عدد معتبر نیست!\n"
                "لطفاً عددی بین ۱۰ تا ۱۰۰ وارد کن:"
            )
            return AGE_MIN
        context.user_data['age_min'] = age_min
    except ValueError:
        await update.message.reply_text(
            "❌ لطفاً فقط عدد وارد کن!"
        )
        return AGE_MIN
    
    await update.message.reply_text(
        "📏 **مرحله ۶ از ۱۱: حداکثر سن**\n\n"
        "طرف مقابلت تا چند ساله باشه؟\n"
        "**حداکثر سن** رو وارد کن:",
        parse_mode='Markdown',
        reply_markup=None
    )
    return AGE_MAX

async def age_max_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت حداکثر سن و رفتن به مرحله بعد"""
    try:
        age_max = int(update.message.text)
        if age_max < context.user_data['age_min'] or age_max > 100:
            await update.message.reply_text(
                f"❌ باید بین {context.user_data['age_min']} تا ۱۰۰ باشه!\n"
                f"لطفاً مجدد وارد کن:"
            )
            return AGE_MAX
        context.user_data['age_max'] = age_max
    except ValueError:
        await update.message.reply_text(
            "❌ لطفاً فقط عدد وارد کن!"
        )
        return AGE_MAX
    
    await show_interests(update, context)
    return INTERESTS

async def show_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش صفحه انتخاب علایق"""
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    text = (
        "🎨 **مرحله ۷ از ۱۱: علایق**\n\n"
        "چه چیزهایی رو دوست داری؟\n"
        f"**انتخاب شده:** {', '.join(context.user_data['interests']) if context.user_data['interests'] else 'هیچ'}\n\n"
        "💡 روی هر گزینه بزن تا انتخاب یا حذف بشه.\n"
        "⚠️ **حداکثر ۵ علاقه** می‌تونی انتخاب کنی.\n\n"
        "وقتی تموم شد، دکمه **✅ تموم شد** رو بزن."
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
    """انتخاب یا حذف علایق"""
    query = update.callback_query
    await query.answer()
    
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    if query.data == "interests_done":
        if not context.user_data['interests']:
            await query.edit_message_text(
                "❌ حداقل **یک علاقه** باید انتخاب کنی!\n"
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
    
    # حذف "interest_" از ابتدای داده
    interest = query.data.replace("interest_", "")
    
    if interest in context.user_data['interests']:
        context.user_data['interests'].remove(interest)
        await query.answer(f"❌ {interest} حذف شد!")
    else:
        if len(context.user_data['interests']) >= 5:
            await query.edit_message_text(
                "❌ **حداکثر ۵ علاقه** می‌تونی انتخاب کنی!\n"
                "برای انتخاب جدید، اول یکی از علایق رو حذف کن.",
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
    """ذخیره وضعیت شغلی و رفتن به مرحله بعد"""
    query = update.callback_query
    await query.answer()
    
    job_map = {
        "job_student": "دانشجو",
        "job_employed": "شاغل",
        "job_seeking": "جویای کار",
        "job_home": "خانه‌دار"
    }
    context.user_data['job_status'] = job_map[query.data]
    
    await query.edit_message_text(
        "📝 **مرحله ۹ از ۱۱: توضیحات**\n\n"
        "یه توضیح کوتاه از خودت بنویس.\n"
        "این توضیحات به طرف مقابل کمک میکنه تا بیشتر باهات آشنا بشه.\n\n"
        "⚠️ **حداکثر ۲۰۰ کاراکتر**\n\n"
        "اگه دوست نداری توضیح بدی، دکمه **⏭️ رد شدن** رو بزن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="description_skip")]
        ])
    )
    return DESCRIPTION

async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت توضیحات و رفتن به مرحله بعد"""
    text = update.message.text
    if len(text) > 200:
        await update.message.reply_text(
            f"❌ توضیحات شما {len(text)} کاراکتر داره!\n"
            "حداکثر **۲۰۰ کاراکتر** مجاز است.\n"
            "لطفاً کوتاه‌تر بنویس:"
        )
        return DESCRIPTION
    context.user_data['description'] = text
    
    await update.message.reply_text(
        "📸 **مرحله ۱۰ از ۱۱: عکس پروفایل**\n\n"
        "حالا عکس پروفایل خودت رو بفرست.\n\n"
        "📌 این عکس وقتی کسی درخواست عکس بده، براش ارسال میشه.\n"
        "📌 اگه عکس نفرستی، **عکس پروفایل تلگرامت** استفاده میشه.\n\n"
        "📤 عکس رو بفرست یا دکمه **⏭️ رد شدن** رو بزن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
        ])
    )
    return PHOTO

async def description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد شدن از توضیحات"""
    query = update.callback_query
    await query.answer()
    context.user_data['description'] = ""
    
    await query.edit_message_text(
        "📸 **مرحله ۱۰ از ۱۱: عکس پروفایل**\n\n"
        "حالا عکس پروفایل خودت رو بفرست.\n\n"
        "📌 این عکس وقتی کسی درخواست عکس بده، براش ارسال میشه.\n"
        "📌 اگه عکس نفرستی، **عکس پروفایل تلگرامت** استفاده میشه.\n\n"
        "📤 عکس رو بفرست یا دکمه **⏭️ رد شدن** رو بزن:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
        ])
    )
    return PHOTO

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره عکس آپلود شده"""
    if update.message.photo:
        photo_file = update.message.photo[-1]
        file_id = photo_file.file_id
        context.user_data['photo'] = file_id
        
        await update.message.reply_text(
            "✅ عکس شما با موفقیت ذخیره شد!\n\n"
            "برای ادامه، دکمه **✅ ادامه** رو بزن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ادامه", callback_data="photo_done")]
            ])
        )
        return PHOTO
    else:
        await update.message.reply_text(
            "❌ لطفاً یک عکس بفرست!\n"
            "یا دکمه **⏭️ رد شدن** رو بزن.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
            ])
        )
        return PHOTO

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد شدن از عکس"""
    query = update.callback_query
    await query.answer()
    context.user_data['photo'] = None
    
    await show_privacy_settings(update, context)
    return PRIVACY

async def photo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید عکس و رفتن به تنظیمات حریم خصوصی"""
    query = update.callback_query
    await query.answer()
    
    await show_privacy_settings(update, context)
    return PRIVACY

async def show_privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش تنظیمات حریم خصوصی"""
    if 'privacy' not in context.user_data:
        context.user_data['privacy'] = {
            'show_age': True,
            'show_city': True,
            'visibility': 'all'
        }
    
    age_status = "✅" if context.user_data['privacy']['show_age'] else "❌"
    city_status = "✅" if context.user_data['privacy']['show_city'] else "❌"
    
    visibility_text = {
        'all': '🌍 همه',
        'same_city': '🏙️ همشهری‌ها',
        'none': '❌ هیچکس'
    }[context.user_data['privacy']['visibility']]
    
    keyboard = [
        [InlineKeyboardButton(f"{age_status} نمایش سن", callback_data="toggle_age")],
        [InlineKeyboardButton(f"{city_status} نمایش شهر", callback_data="toggle_city")],
        [InlineKeyboardButton(f"🌍 نمایش به: {visibility_text}", callback_data="change_visibility")],
        [InlineKeyboardButton("✅ تایید و پایان", callback_data="privacy_done")]
    ]
    
    text = (
        "🔒 **مرحله ۱۱ از ۱۱: حریم خصوصی**\n\n"
        "تنظیمات حریم خصوصی خودت رو مشخص کن:\n\n"
        "✅ = نمایش داده میشه\n"
        "❌ = نمایش داده نمیشه\n\n"
        "🔹 **نمایش سن:** آیا سن شما در جستجو نمایش داده بشه؟\n"
        "🔹 **نمایش شهر:** آیا شهر شما در جستجو نمایش داده بشه؟\n"
        "🔹 **نمایش به:** چه کسانی پروفایل شما رو ببینن؟\n\n"
        "روی هر گزینه بزن تا تغییر کنه:"
    )
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def privacy_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغییر تنظیمات حریم خصوصی"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "toggle_age":
        context.user_data['privacy']['show_age'] = not context.user_data['privacy']['show_age']
        await show_privacy_settings(update, context)
    
    elif query.data == "toggle_city":
        context.user_data['privacy']['show_city'] = not context.user_data['privacy']['show_city']
        await show_privacy_settings(update, context)
    
    elif query.data == "change_visibility":
        visibility_options = ['all', 'same_city', 'none']
        current = context.user_data['privacy']['visibility']
        next_index = (visibility_options.index(current) + 1) % len(visibility_options)
        context.user_data['privacy']['visibility'] = visibility_options[next_index]
        await show_privacy_settings(update, context)
    
    elif query.data == "privacy_done":
        await finish_registration(update, context)
        return PRIVACY

async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پایان ثبت‌نام و ذخیره اطلاعات"""
    user_id = update.effective_user.id
    
    # دریافت عکس از تلگرام اگر آپلود نشده
    if 'photo' not in context.user_data or not context.user_data['photo']:
        try:
            user_photos = await context.bot.get_user_profile_photos(user_id, limit=1)
            if user_photos.total_count > 0:
                photo_file_id = user_photos.photos[0][-1].file_id
                context.user_data['photo'] = photo_file_id
        except:
            context.user_data['photo'] = None
    
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
        'photo_file_id': context.user_data.get('photo'),
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
        
        text = (
            "🎉 **ثبت‌نام شما کامل شد!** 🎉\n\n"
            "حالا می‌تونی از امکانات ربات استفاده کنی:\n\n"
            "🔍 با **جستجو** افراد هم‌نوا رو پیدا کن\n"
            "💬 با **چت‌های من** پیام‌هات رو مدیریت کن\n"
            "📝 با **ویرایش پروفایل** اطلاعاتت رو به‌روز کن\n"
            "🔒 با **حریم خصوصی** کنترل کن چه کسی چی ببینه\n\n"
            "🌟 **موفق باشی!**"
        )
        
        if isinstance(update, Update) and update.callback_query:
            query = update.callback_query
            await query.edit_message_text(
                text,
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard(is_admin)
            )
        else:
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard(is_admin)
            )
    else:
        await update.message.reply_text(
            "❌ **خطا در ذخیره اطلاعات!**\n"
            "لطفاً دوباره تلاش کن یا با پشتیبانی تماس بگیر.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
    
    return ConversationHandler.END

# ============ بقیه هندلرها (با توضیحات کامل) ============
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جستجوی کاربران مناسب"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = get_user_dict(user_id)
    
    if not user or not user['is_setup_complete']:
        await query.edit_message_text(
            "❌ **اول باید ثبت‌نام کامل کنی!**\n"
            "برای شروع، دستور /start رو بزن.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return
    
    if user['is_banned']:
        await query.edit_message_text(
            "🚫 **شما توسط مدیریت مسدود شده‌اید!**\n"
            "در صورت اعتراض با پشتیبانی تماس بگیرید.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return
    
    # پاکسازی چت‌های منقضی شده
    cleanup_expired_chats()
    
    try:
        week_ago = datetime.now() - timedelta(days=7)
        rejected = db.fetchall(
            "SELECT rejected_user_id FROM rejected WHERE user_id=? AND rejected_at > ?",
            (user_id, week_ago)
        )
        rejected_ids = [row['rejected_user_id'] for row in rejected]
        
        active_chats = db.fetchall(
            "SELECT user2 FROM chats WHERE user1=? AND is_active=1 UNION SELECT user1 FROM chats WHERE user2=? AND is_active=1",
            (user_id, user_id)
        )
        active_ids = [row[0] for row in active_chats]
        
        blocked = db.fetchall(
            "SELECT blocked_id FROM blocks WHERE blocker_id=? UNION SELECT blocker_id FROM blocks WHERE blocked_id=?",
            (user_id, user_id)
        )
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
            await query.edit_message_text(
                "😔 **متاسفانه کسی با معیارهای شما پیدا نشد!**\n\n"
                "💡 پیشنهادات:\n"
                "• محدوده سنی رو گسترده‌تر کن\n"
                "• هدف خودت رو تغییر بده\n"
                "• بعداً دوباره امتحان کن\n\n"
                "🔍 می‌تونی از **ویرایش پروفایل** فیلترها رو عوض کنی.",
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard()
            )
            return
        
        context.user_data['candidates'] = candidates
        context.user_data['candidate_index'] = 0
        
        await show_candidate(update, context)
        
    except Exception as e:
        logger.error(f"Error in search: {e}")
        await query.edit_message_text(
            "❌ **خطا در جستجو!**\n"
            "لطفاً دوباره تلاش کن.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )

async def show_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش یک کاندید"""
    query = update.callback_query
    await query.answer()
    
    candidates = context.user_data.get('candidates', [])
    index = context.user_data.get('candidate_index', 0)
    
    if index >= len(candidates):
        await query.edit_message_text(
            "🎯 **جستجو به پایان رسید!**\n\n"
            "می‌تونی دوباره جستجو کنی یا فیلترها رو عوض کنی.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return
    
    candidate = candidates[index]
    user_dict = dict(candidate)
    
    message = f"👤 **کاربر {index+1} از {len(candidates)}**\n\n"
    message += f"📅 سن: {user_dict['age'] if user_dict['privacy_age'] else '❌ مخفی'}\n"
    message += f"🏙️ شهر: {user_dict['city'] if user_dict['privacy_city'] else '❌ مخفی'}\n"
    message += f"🎯 هدف: {user_dict['purpose']}\n"
    message += f"💼 وضعیت: {user_dict['job_status']}\n"
    
    interests = json.loads(user_dict['interests']) if user_dict['interests'] else []
    if interests:
        message += f"\n🎨 علایق: {', '.join(interests[:3])}"
        if len(interests) > 3:
            message += f" +{len(interests)-3} مورد دیگر"
    
    if user_dict['description']:
        message += f"\n\n📝 {user_dict['description'][:50]}..."
    
    keyboard = [
        [InlineKeyboardButton("👍 علاقه‌مندم", callback_data=f"like_{user_dict['user_id']}")],
        [InlineKeyboardButton("👎 رد کردن", callback_data=f"dislike_{user_dict['user_id']}")],
        [InlineKeyboardButton("❓ اطلاعات بیشتر", callback_data=f"more_{user_dict['user_id']}")],
        [InlineKeyboardButton("⏩ بعدی", callback_data="next_candidate")]
    ]
    
    await query.edit_message_text(
        message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ============ بقیه کدها (با توضیحات کامل و callback_data کوتاه برای بلاک/ریپورت) ============

# برای بلاک و ریپورت از callback_data کوتاه استفاده میکنیم:
# bl_123456789  -> بلاک
# br_a_123456789 -> بلاک با دلیل (abuse)
# rp_123456789  -> گزارش
# rr_a_123456789 -> گزارش با دلیل (abuse)

async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بلاک کردن کاربر"""
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = int(query.data.replace("bl_", ""))
    except:
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما توسط مدیریت مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    keyboard = [
        [InlineKeyboardButton("🔞 فحاشی و بی‌ادبی", callback_data=f"br_a_{user_id}")],
        [InlineKeyboardButton("📱 مزاحمت و اسپم", callback_data=f"br_s_{user_id}")],
        [InlineKeyboardButton("🎭 دروغ و کلاهبرداری", callback_data=f"br_f_{user_id}")],
        [InlineKeyboardButton("❌ مورد پسندم نبود", callback_data=f"br_n_{user_id}")],
        [InlineKeyboardButton("🔙 انصراف", callback_data="close_chat")]
    ]
    
    await query.edit_message_text(
        "🚫 **بلاک کردن کاربر**\n\n"
        "لطفاً دلیل بلاک کردن رو انتخاب کن:\n\n"
        "🔞 فحاشی و بی‌ادبی\n"
        "📱 مزاحمت و اسپم\n"
        "🎭 دروغ و کلاهبرداری\n"
        "❌ مورد پسندم نبود\n\n"
        "⚠️ بعد از بلاک، این کاربر دیگه در جستجو به شما نمایش داده نمیشه.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def block_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت دلیل بلاک"""
    query = update.callback_query
    await query.answer()
    
    try:
        # format: br_a_123456789
        parts = query.data.split('_')
        reason = parts[1]
        user_id = int(parts[2])
    except:
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    try:
        db.execute("""
            INSERT INTO blocks (blocker_id, blocked_id, reason, created_at)
            VALUES (?, ?, ?, ?)
        """, (current_user, user_id, reason, datetime.now()))
        
        if chat_id:
            db.execute("UPDATE chats SET is_active=0, blocked_by=? WHERE id=?", (current_user, chat_id))
        
        reason_text = {
            "a": "فحاشی و بی‌ادبی",
            "s": "مزاحمت و اسپم",
            "f": "دروغ و کلاهبرداری",
            "n": "مورد پسندم نبود"
        }.get(reason, "نامشخص")
        
        try:
            await context.bot.send_message(
                user_id,
                f"🚫 شما توسط یک کاربر بلاک شدید!\nدلیل: {reason_text}\n\nلطفاً در رفتار خودت تجدید نظر کن.",
                reply_markup=main_menu_keyboard()
            )
        except:
            pass
        
        context.user_data.pop('active_chat', None)
        context.user_data.pop('chat_partner', None)
        
        await query.edit_message_text(
            f"✅ **کاربر با موفقیت بلاک شد!**\n\n"
            f"📌 دلیل: {reason_text}\n\n"
            f"از اینکه به ما در حفظ امنیت کمک کردی متشکریم.",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in block_reason: {e}")
        await query.edit_message_text(
            "❌ خطا در بلاک کردن!",
            reply_markup=main_menu_keyboard()
        )

async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """گزارش تخلف کاربر"""
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = int(query.data.replace("rp_", ""))
    except:
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    if is_admin_blocked(current_user):
        await query.edit_message_text("🚫 شما توسط مدیریت مسدود شده‌اید!", reply_markup=main_menu_keyboard())
        return
    
    keyboard = [
        [InlineKeyboardButton("🔞 فحاشی و بی‌ادبی", callback_data=f"rr_a_{user_id}")],
        [InlineKeyboardButton("📱 مزاحمت و اسپم", callback_data=f"rr_s_{user_id}")],
        [InlineKeyboardButton("🎭 دروغ و کلاهبرداری", callback_data=f"rr_f_{user_id}")],
        [InlineKeyboardButton("🔞 محتوای نامناسب", callback_data=f"rr_i_{user_id}")],
        [InlineKeyboardButton("🔙 انصراف", callback_data="close_chat")]
    ]
    
    await query.edit_message_text(
        "⚠️ **گزارش تخلف**\n\n"
        "لطفاً دلیل گزارش رو انتخاب کن:\n\n"
        "🔞 فحاشی و بی‌ادبی\n"
        "📱 مزاحمت و اسپم\n"
        "🎭 دروغ و کلاهبرداری\n"
        "🔞 محتوای نامناسب\n\n"
        "📌 گزارش شما به مدیریت ارسال میشه و بررسی خواهد شد.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ثبت دلیل گزارش"""
    query = update.callback_query
    await query.answer()
    
    try:
        # format: rr_a_123456789
        parts = query.data.split('_')
        reason = parts[1]
        user_id = int(parts[2])
    except:
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    try:
        db.execute("""
            INSERT INTO reports (reporter_id, reported_id, reason, created_at, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (current_user, user_id, reason, datetime.now()))
        
        reason_text = {
            "a": "فحاشی و بی‌ادبی",
            "s": "مزاحمت و اسپم",
            "f": "دروغ و کلاهبرداری",
            "i": "محتوای نامناسب"
        }.get(reason, "نامشخص")
        
        if ADMIN_ID:
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"⚠️ **گزارش جدید تخلف**\n\n"
                    f"👤 گزارش‌دهنده: {current_user}\n"
                    f"👤 گزارش‌شونده: {user_id}\n"
                    f"📌 دلیل: {reason_text}\n"
                    f"📅 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"برای مدیریت کاربر از پنل استفاده کنید.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚫 بلاک کاربر", callback_data=f"admin_block_{user_id}")],
                        [InlineKeyboardButton("📋 گزارش‌ها", callback_data="admin_reports")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error sending report to admin: {e}")
        
        reply_markup = chat_keyboard(user_id) if chat_id else main_menu_keyboard()
        
        await query.edit_message_text(
            f"✅ **گزارش شما ثبت شد!**\n\n"
            f"📌 دلیل: {reason_text}\n\n"
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

# ============ ادامه سایر هندلرها (با توضیحات کامل) ============

# ... (بقیه هندلرها مثل قبل با توضیحات کامل)

# ============ تابع اصلی ============
async def scheduled_cleanup():
    while True:
        try:
            await asyncio.sleep(3600)
            cleanup_expired_chats()
            logger.info("🔄 Scheduled cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

def main():
    try:
        logger.info("🚀 Starting bot...")
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        application = Application.builder().token(TOKEN).build()
        
        # ============ هندلر ثبت‌نام ============
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                GENDER: [CallbackQueryHandler(gender_selection, pattern='^gender_')],
                AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_input)],
                PURPOSE: [CallbackQueryHandler(purpose_selection, pattern='^purpose_')],
                CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city_input)],
                AGE_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_min_input)],
                AGE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, age_max_input)],
                INTERESTS: [CallbackQueryHandler(interests_selection, pattern='^interest_')],
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
        
        # ============ منوهای اصلی ============
        application.add_handler(CallbackQueryHandler(search, pattern='^search$'))
        application.add_handler(CallbackQueryHandler(edit_profile, pattern='^edit_profile$'))
        application.add_handler(CallbackQueryHandler(my_requests, pattern='^my_requests$'))
        application.add_handler(CallbackQueryHandler(privacy_settings, pattern='^privacy_settings$'))
        application.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
        application.add_handler(CallbackQueryHandler(reset_bot, pattern='^reset_bot$'))
        application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
        application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))
        
        # ============ افراد بلاک شده ============
        application.add_handler(CallbackQueryHandler(blocked_users_list, pattern='^blocked_users$'))
        application.add_handler(CallbackQueryHandler(unblock_user, pattern='^unblock_'))
        
        # ============ چت‌ها ============
        application.add_handler(CallbackQueryHandler(show_chats, pattern='^show_chats$'))
        application.add_handler(CallbackQueryHandler(switch_chat, pattern='^switch_chat_'))
        
        # ============ ویرایش پروفایل ============
        application.add_handler(CallbackQueryHandler(edit_profile_field, pattern='^edit_(gender|age|purpose|city|interests|job|description|photo)$'))
        application.add_handler(CallbackQueryHandler(update_profile_field, pattern='^update_(gender_|purpose_|job_|interest_|interests_done)'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_text_input))
        application.add_handler(MessageHandler(filters.PHOTO, handle_profile_text_input))
        
        # ============ جستجو و درخواست‌ها ============
        application.add_handler(CallbackQueryHandler(candidate_action, pattern='^(like|dislike|more)_'))
        application.add_handler(CallbackQueryHandler(show_candidate, pattern='^next_candidate$'))
        application.add_handler(CallbackQueryHandler(back_to_candidate, pattern='^back_'))
        application.add_handler(CallbackQueryHandler(view_requester, pattern='^view_'))
        application.add_handler(CallbackQueryHandler(handle_request, pattern='^(accept|reject)_'))
        
        # ============ چت ============
        application.add_handler(CallbackQueryHandler(start_chat, pattern='^chat_'))
        application.add_handler(CallbackQueryHandler(request_photo, pattern='^photo_'))
        
        # بلاک با callback_data کوتاه
        application.add_handler(CallbackQueryHandler(block_user, pattern='^bl_'))
        application.add_handler(CallbackQueryHandler(block_reason, pattern='^br_'))
        
        application.add_handler(CallbackQueryHandler(close_chat, pattern='^close_chat$'))
        
        # ============ گزارش ============
        application.add_handler(CallbackQueryHandler(report_user, pattern='^rp_'))
        application.add_handler(CallbackQueryHandler(report_reason, pattern='^rr_'))
        
        # ============ پنل مدیریت ============
        application.add_handler(CallbackQueryHandler(admin_panel, pattern='^admin_panel$'))
        application.add_handler(CallbackQueryHandler(admin_block_user, pattern='^admin_block_user$'))
        application.add_handler(CallbackQueryHandler(admin_unblock_user, pattern='^admin_unblock_user$'))
        application.add_handler(CallbackQueryHandler(admin_do_unblock, pattern='^admin_unblock_'))
        application.add_handler(CallbackQueryHandler(admin_reports, pattern='^admin_reports$'))
        application.add_handler(CallbackQueryHandler(admin_block_from_report, pattern='^admin_block_from_report_'))
        application.add_handler(CallbackQueryHandler(admin_close_report, pattern='^admin_close_report_'))
        application.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$'))
        
        # ============ حریم خصوصی ============
        application.add_handler(CallbackQueryHandler(privacy_toggle, pattern='^privacy_toggle_(age|city|change_visibility)$'))
        
        # ============ هندلر اصلی پیام‌ها ============
        application.add_handler(
            MessageHandler(filters.ALL & ~filters.COMMAND, handle_chat_message),
            group=1
        )
        
        # ============ پاکسازی خودکار ============
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
