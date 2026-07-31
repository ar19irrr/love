import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
import asyncio

# تنظیمات اولیه
TOKEN = "8733726486:AAFYttHp2F0mK_rjNeDlOk9oKte5CbPoJMc"
PORT = int(os.environ.get('PORT', 8443))

# فعال کردن logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# دیتابیس
def init_db():
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    # جدول کاربران
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
        photo TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP,
        last_active TIMESTAMP,
        is_setup_complete BOOLEAN DEFAULT 0
    )''')
    
    # جدول درخواست‌ها
    c.execute('''CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (from_user) REFERENCES users(user_id),
        FOREIGN KEY (to_user) REFERENCES users(user_id)
    )''')
    
    # جدول چت‌ها
    c.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER,
        user2 INTEGER,
        match_date TIMESTAMP,
        expiry_date TIMESTAMP,
        is_active BOOLEAN DEFAULT 1,
        blocked_by INTEGER DEFAULT NULL,
        FOREIGN KEY (user1) REFERENCES users(user_id),
        FOREIGN KEY (user2) REFERENCES users(user_id)
    )''')
    
    # جدول پیام‌ها
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        sender_id INTEGER,
        message_text TEXT,
        photo_path TEXT,
        timestamp TIMESTAMP,
        is_read BOOLEAN DEFAULT 0,
        FOREIGN KEY (chat_id) REFERENCES chats(id),
        FOREIGN KEY (sender_id) REFERENCES users(user_id)
    )''')
    
    # جدول ردها (برای جلوگیری از نمایش مجدد)
    c.execute('''CREATE TABLE IF NOT EXISTS rejected (
        user_id INTEGER,
        rejected_user_id INTEGER,
        rejected_at TIMESTAMP,
        PRIMARY KEY (user_id, rejected_user_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (rejected_user_id) REFERENCES users(user_id)
    )''')
    
    # جدول درخواست عکس
    c.execute('''CREATE TABLE IF NOT EXISTS photo_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER,
        target_id INTEGER,
        chat_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP,
        FOREIGN KEY (requester_id) REFERENCES users(user_id),
        FOREIGN KEY (target_id) REFERENCES users(user_id),
        FOREIGN KEY (chat_id) REFERENCES chats(id)
    )''')
    
    conn.commit()
    conn.close()

# Helper functions
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
               'privacy_visibility', 'photo', 'is_active', 'created_at', 'last_active', 'is_setup_complete']
    return dict(zip(columns, user))

def save_user(user_id, data):
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    # Check if user exists
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    exists = c.fetchone()
    
    if exists:
        # Update
        set_clause = ", ".join([f"{k}=?" for k in data.keys()])
        values = list(data.values()) + [user_id]
        c.execute(f"UPDATE users SET {set_clause} WHERE user_id=?", values)
    else:
        # Insert
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = list(data.values())
        c.execute(f"INSERT INTO users ({columns}) VALUES ({placeholders})", values)
    
    conn.commit()
    conn.close()

# مرحله‌های ثبت‌نام
GENDER, AGE, PURPOSE, CITY, AGE_MIN, AGE_MAX, INTERESTS, JOB_STATUS, DESCRIPTION, PRIVACY = range(10)

# دکمه‌های اصلی
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 جستجو", callback_data="search")],
        [InlineKeyboardButton("📝 ویرایش پروفایل", callback_data="edit_profile")],
        [InlineKeyboardButton("📋 درخواست‌های من", callback_data="my_requests")],
        [InlineKeyboardButton("🔒 حریم خصوصی", callback_data="privacy")],
        [InlineKeyboardButton("📊 آمار من", callback_data="stats")],
        [InlineKeyboardButton("🔄 ریست ربات", callback_data="reset_bot")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

# شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    # ریست کردن context
    context.user_data.clear()
    
    if user and user[17]:  # is_setup_complete
        await update.message.reply_text(
            f"🌟 به بات هم‌نوا خوش اومدی {update.effective_user.first_name}!\n\n"
            "از منوی زیر استفاده کن:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    
    # شروع ثبت‌نام
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

async def gender_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    gender_map = {
        "gender_male": "مرد",
        "gender_female": "زن",
        "gender_other": "سایر"
    }
    context.user_data['gender'] = gender_map[query.data]
    
    await query.edit_message_text(
        "🌸 چند بهار رو پشت سر گذاشتی؟\n"
        "(فقط عدد وارد کن)",
        reply_markup=None
    )
    return AGE

async def age_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            await update.message.reply_text("❌ لطفاً سن معتبر وارد کن (۱۰ تا ۱۰۰):")
            return AGE
        context.user_data['age'] = age
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کن:")
        return AGE
    
    await update.message.reply_text(
        "🎯 هدف شما از حضور در این بات چیه؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💍 ازدواج", callback_data="purpose_marriage")],
            [InlineKeyboardButton("💑 رابطه دوستی", callback_data="purpose_relationship")],
            [InlineKeyboardButton("🎭 رفاقت ساده", callback_data="purpose_friendship")],
            [InlineKeyboardButton("🤷 هنوز نمیدونم", callback_data="purpose_unknown")]
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
        "🏙️ کدوم شهر زندگی می‌کنی؟",
        reply_markup=None
    )
    return CITY

async def city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['city'] = update.message.text
    
    await update.message.reply_text(
        "📏 طرف مقابلت چند ساله باشه؟\n"
        "از چند سال (حداقل):",
        reply_markup=None
    )
    return AGE_MIN

async def age_min_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age_min = int(update.message.text)
        if age_min < 10 or age_min > 100:
            await update.message.reply_text("❌ لطفاً عدد معتبر وارد کن (۱۰ تا ۱۰۰):")
            return AGE_MIN
        context.user_data['age_min'] = age_min
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کن:")
        return AGE_MIN
    
    await update.message.reply_text(
        "تا چند سال (حداکثر):",
        reply_markup=None
    )
    return AGE_MAX

async def age_max_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age_max = int(update.message.text)
        if age_max < context.user_data['age_min'] or age_max > 100:
            await update.message.reply_text(f"❌ باید بین {context.user_data['age_min']} تا ۱۰۰ باشه:")
            return AGE_MAX
        context.user_data['age_max'] = age_max
    except ValueError:
        await update.message.reply_text("❌ لطفاً فقط عدد وارد کن:")
        return AGE_MAX
    
    # علایق
    interests = [
        ["🎬 فیلم", "📚 کتاب", "🎵 موسیقی"],
        ["🏋️ ورزش", "🍳 آشپزی", "🎮 بازی"],
        ["🧳 سفر", "🌿 طبیعت", "✏️ نقاشی"],
        ["💻 تکنولوژی", "🧘 مدیتیشن", "🐱 حیوانات"]
    ]
    
    keyboard = []
    for row in interests:
        keyboard.append([InlineKeyboardButton(item, callback_data=f"interest_{item}") for item in row])
    keyboard.append([InlineKeyboardButton("✅ تموم شد", callback_data="interests_done")])
    
    await update.message.reply_text(
        "🎨 چه چیزهایی رو دوست داری؟\n"
        "چند تا انتخاب کن و بعد روی 'تموم شد' بزن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INTERESTS

async def interests_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    if query.data == "interests_done":
        if not context.user_data['interests']:
            await query.edit_message_text(
                "❌ حداقل یک علاقه انتخاب کن!",
                reply_markup=None
            )
            return INTERESTS
        
        await query.edit_message_text(
            "💼 وضعیت شغلی/تحصیلیت چیه؟",
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
        await query.edit_message_text(
            f"❌ {interest} حذف شد!",
            reply_markup=None
        )
    else:
        if len(context.user_data['interests']) >= 5:
            await query.edit_message_text(
                "❌ حداکثر ۵ علاقه می‌تونی انتخاب کنی!",
                reply_markup=None
            )
            return INTERESTS
        context.user_data['interests'].append(interest)
        await query.edit_message_text(
            f"✅ {interest} اضافه شد!",
            reply_markup=None
        )
    
    # نمایش مجدد دکمه‌ها
    interests = [
        ["🎬 فیلم", "📚 کتاب", "🎵 موسیقی"],
        ["🏋️ ورزش", "🍳 آشپزی", "🎮 بازی"],
        ["🧳 سفر", "🌿 طبیعت", "✏️ نقاشی"],
        ["💻 تکنولوژی", "🧘 مدیتیشن", "🐱 حیوانات"]
    ]
    
    keyboard = []
    for row in interests:
        keyboard.append([InlineKeyboardButton(item, callback_data=f"interest_{item}") for item in row])
    keyboard.append([InlineKeyboardButton("✅ تموم شد", callback_data="interests_done")])
    
    await query.message.reply_text(
        f"علایق فعلی: {', '.join(context.user_data['interests'])}\n\n"
        "می‌تونی اضافه یا حذف کنی:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INTERESTS

async def job_status_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "📝 یه توضیح کوتاه از خودت بنویس (حداکثر ۲۰۰ کاراکتر)\n"
        "اگه دوست نداری، 'رد شدن' رو بزن:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="description_skip")]
        ])
    )
    return DESCRIPTION

async def description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if len(text) > 200:
        await update.message.reply_text("❌ حداکثر ۲۰۰ کاراکتر! کوتاه‌تر بنویس:")
        return DESCRIPTION
    context.user_data['description'] = text
    
    await show_privacy_settings(update, context)
    return PRIVACY

async def description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['description'] = ""
    
    await show_privacy_settings(update, context)
    return PRIVACY

async def show_privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            "🔒 تنظیمات حریم خصوصی:\n\n"
            "این تنظیمات رو هر وقت بخوای می‌تونی تغییر بدی.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 نمایش سن", callback_data="privacy_show_age"),
                 InlineKeyboardButton("🙈 مخفی کردن سن", callback_data="privacy_hide_age")],
                [InlineKeyboardButton("🏙️ نمایش شهر", callback_data="privacy_show_city"),
                 InlineKeyboardButton("🙈 مخفی کردن شهر", callback_data="privacy_hide_city")],
                [InlineKeyboardButton("🌍 همه ببینن", callback_data="privacy_all"),
                 InlineKeyboardButton("🏙️ فقط همشهری‌ها", callback_data="privacy_same_city"),
                 InlineKeyboardButton("❌ هیچکس نبینه", callback_data="privacy_none")],
                [InlineKeyboardButton("✅ ثبت نهایی", callback_data="privacy_done")]
            ])
        )
    else:
        await update.message.reply_text(
            "🔒 تنظیمات حریم خصوصی:\n\n"
            "این تنظیمات رو هر وقت بخوای می‌تونی تغییر بدی.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 نمایش سن", callback_data="privacy_show_age"),
                 InlineKeyboardButton("🙈 مخفی کردن سن", callback_data="privacy_hide_age")],
                [InlineKeyboardButton("🏙️ نمایش شهر", callback_data="privacy_show_city"),
                 InlineKeyboardButton("🙈 مخفی کردن شهر", callback_data="privacy_hide_city")],
                [InlineKeyboardButton("🌍 همه ببینن", callback_data="privacy_all"),
                 InlineKeyboardButton("🏙️ فقط همشهری‌ها", callback_data="privacy_same_city"),
                 InlineKeyboardButton("❌ هیچکس نبینه", callback_data="privacy_none")],
                [InlineKeyboardButton("✅ ثبت نهایی", callback_data="privacy_done")]
            ])
        )

async def privacy_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if 'privacy' not in context.user_data:
        context.user_data['privacy'] = {
            'show_age': True,
            'show_city': True,
            'visibility': 'all'
        }
    
    if query.data == "privacy_show_age":
        context.user_data['privacy']['show_age'] = True
        await query.edit_message_text("✅ سن شما نمایش داده میشه")
    elif query.data == "privacy_hide_age":
        context.user_data['privacy']['show_age'] = False
        await query.edit_message_text("✅ سن شما مخفی میشه")
    elif query.data == "privacy_show_city":
        context.user_data['privacy']['show_city'] = True
        await query.edit_message_text("✅ شهر شما نمایش داده میشه")
    elif query.data == "privacy_hide_city":
        context.user_data['privacy']['show_city'] = False
        await query.edit_message_text("✅ شهر شما مخفی میشه")
    elif query.data == "privacy_all":
        context.user_data['privacy']['visibility'] = 'all'
        await query.edit_message_text("✅ همه می‌تونن شما رو ببینن")
    elif query.data == "privacy_same_city":
        context.user_data['privacy']['visibility'] = 'same_city'
        await query.edit_message_text("✅ فقط همشهری‌ها شما رو می‌بینن")
    elif query.data == "privacy_none":
        context.user_data['privacy']['visibility'] = 'none'
        await query.edit_message_text("✅ شما در حالت مخفی قرار گرفتید")
    elif query.data == "privacy_done":
        # ذخیره نهایی کاربر
        user_data = {
            'user_id': update.effective_user.id,
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
            'is_active': 1,
            'created_at': datetime.now(),
            'last_active': datetime.now(),
            'is_setup_complete': 1
        }
        save_user(update.effective_user.id, user_data)
        
        await query.edit_message_text(
            "🎉 ثبت‌نام شما کامل شد!\n\n"
            "حالا می‌تونی از امکانات ربات استفاده کنی:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

# جستجو
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = get_user_dict(user_id)
    
    if not user or not user['is_setup_complete']:
        await query.edit_message_text(
            "❌ اول باید ثبت‌نام کامل کنی!",
            reply_markup=main_menu_keyboard()
        )
        return
    
    # پیدا کردن کاندیداها
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    # دریافت لیست ردها
    c.execute("SELECT rejected_user_id FROM rejected WHERE user_id=?", (user_id,))
    rejected = [row[0] for row in c.fetchall()]
    
    # دریافت لیست چت‌های فعال
    c.execute("SELECT user2 FROM chats WHERE user1=? AND is_active=1", (user_id,))
    c.execute("SELECT user1 FROM chats WHERE user2=? AND is_active=1", (user_id,))
    active_chats = [row[0] for row in c.fetchall()]
    
    # ساخت کوئری
    query_str = """
        SELECT * FROM users 
        WHERE user_id != ? 
        AND is_active = 1 
        AND is_setup_complete = 1
        AND age BETWEEN ? AND ?
        AND purpose = ?
    """
    params = [user_id, user['age_min'], user['age_max'], user['purpose']]
    
    # فیلتر شهر
    if user['privacy_visibility'] == 'same_city':
        query_str += " AND city = ?"
        params.append(user['city'])
    
    # حذف ردها و چت‌های فعال
    if rejected:
        query_str += f" AND user_id NOT IN ({','.join(['?']*len(rejected))})"
        params.extend(rejected)
    if active_chats:
        query_str += f" AND user_id NOT IN ({','.join(['?']*len(active_chats))})"
        params.extend(active_chats)
    
    c.execute(query_str, params)
    candidates = c.fetchall()
    conn.close()
    
    if not candidates:
        await query.edit_message_text(
            "😔 متاسفانه کسی با معیارهای شما پیدا نشد!\n"
            "سعی کن فیلترها رو عوض کنی یا بعداً دوباره امتحان کن.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    # ذخیره کاندیداها در context
    context.user_data['candidates'] = candidates
    context.user_data['candidate_index'] = 0
    
    await show_candidate(update, context)

async def show_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    candidates = context.user_data.get('candidates', [])
    index = context.user_data.get('candidate_index', 0)
    
    if index >= len(candidates):
        await query.edit_message_text(
            "🎯 جستجو به پایان رسید!\n"
            "می‌تونی دوباره جستجو کنی.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    candidate = candidates[index]
    user_dict = get_user_dict(candidate[0])
    
    # ساخت پیام
    message = f"👤 {user_dict['user_id']}\n"
    message += f"سن: {user_dict['age'] if user_dict['privacy_age'] else '❌ مخفی'}\n"
    message += f"شهر: {user_dict['city'] if user_dict['privacy_city'] else '❌ مخفی'}\n"
    message += f"هدف: {user_dict['purpose']}\n"
    message += f"وضعیت: {user_dict['job_status']}\n"
    message += f"تعداد: {index+1} از {len(candidates)}"
    
    keyboard = [
        [InlineKeyboardButton("👍 علاقه‌مندم", callback_data=f"like_{user_dict['user_id']}"),
         InlineKeyboardButton("👎 رد کردن", callback_data=f"dislike_{user_dict['user_id']}")],
        [InlineKeyboardButton("❓ اطلاعات بیشتر", callback_data=f"more_info_{user_dict['user_id']}")],
        [InlineKeyboardButton("⏩ بعدی", callback_data="next_candidate")]
    ]
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def candidate_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, target_id = query.data.split('_')
    target_id = int(target_id)
    user_id = update.effective_user.id
    
    if action == "like":
        # ثبت درخواست
        conn = sqlite3.connect('matchbot.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO requests (from_user, to_user, created_at, expires_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, target_id, datetime.now(), datetime.now() + timedelta(days=3)))
        conn.commit()
        conn.close()
        
        # اطلاع به طرف مقابل
        try:
            await context.bot.send_message(
                target_id,
                f"📩 یه نفر به شما علاقه نشان داد!\n"
                f"می‌خواید پروفایلش رو ببینید؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👀 مشاهده پروفایل", callback_data=f"view_requester_{user_id}")],
                    [InlineKeyboardButton("🙅 رد کردن", callback_data=f"reject_request_{user_id}")]
                ])
            )
        except:
            pass
        
        await query.edit_message_text(
            "✅ درخواست شما ارسال شد!\n"
            "منتظر پاسخ طرف مقابل می‌مونیم... ⏳",
            reply_markup=main_menu_keyboard()
        )
    
    elif action == "dislike":
        # ثبت در ردها
        conn = sqlite3.connect('matchbot.db')
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO rejected (user_id, rejected_user_id, rejected_at)
            VALUES (?, ?, ?)
        """, (user_id, target_id, datetime.now()))
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            "✅ رد شد!",
            reply_markup=None
        )
        
        # رفتن به کاندیدای بعدی
        context.user_data['candidate_index'] += 1
        await show_candidate(update, context)
    
    elif action == "more_info":
        target_user = get_user_dict(target_id)
        if target_user:
            interests = json.loads(target_user['interests'])
            message = f"📋 اطلاعات بیشتر:\n\n"
            message += f"علایق: {', '.join(interests)}\n"
            if target_user['description']:
                message += f"\nتوضیحات: {target_user['description']}"
            else:
                message += f"\nتوضیحات: ❌ ندارد"
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 برگشت", callback_data=f"back_to_candidate_{target_id}")]
                ])
            )

async def view_requester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    _, requester_id = query.data.split('_')
    requester_id = int(requester_id)
    user_id = update.effective_user.id
    
    requester = get_user_dict(requester_id)
    if not requester:
        await query.edit_message_text("❌ کاربر پیدا نشد!")
        return
    
    message = f"👤 اطلاعات درخواست‌دهنده:\n\n"
    message += f"سن: {requester['age'] if requester['privacy_age'] else '❌ مخفی'}\n"
    message += f"شهر: {requester['city'] if requester['privacy_city'] else '❌ مخفی'}\n"
    message += f"هدف: {requester['purpose']}\n"
    message += f"وضعیت: {requester['job_status']}"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول کردن", callback_data=f"accept_request_{requester_id}")],
            [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_request_{requester_id}")]
        ])
    )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, user_id = query.data.split('_')
    user_id = int(user_id)
    current_user = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    if action == "accept_request":
        # بروزرسانی وضعیت درخواست
        c.execute("""
            UPDATE requests SET status='accepted' 
            WHERE from_user=? AND to_user=? AND status='pending'
        """, (user_id, current_user))
        
        # ایجاد چت جدید
        c.execute("""
            INSERT INTO chats (user1, user2, match_date, expiry_date)
            VALUES (?, ?, ?, ?)
        """, (user_id, current_user, datetime.now(), datetime.now() + timedelta(days=3)))
        
        chat_id = c.lastrowid
        conn.commit()
        
        # اطلاع به هر دو طرف
        await context.bot.send_message(
            user_id,
            f"🎉 طرف مقابل درخواست شما رو قبول کرد!\n"
            f"حالا می‌تونید با هم چت کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 شروع چت", callback_data=f"start_chat_{chat_id}")]
            ])
        )
        
        await query.edit_message_text(
            "🎉 هورا! شما همدیگرو پسندیدین!\n"
            "چت شما فعال شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 شروع چت", callback_data=f"start_chat_{chat_id}")]
            ])
        )
    
    elif action == "reject_request":
        c.execute("""
            UPDATE requests SET status='rejected' 
            WHERE from_user=? AND to_user=? AND status='pending'
        """, (user_id, current_user))
        conn.commit()
        
        await query.edit_message_text(
            "🙅 درخواست رد شد!",
            reply_markup=main_menu_keyboard()
        )
    
    conn.close()

# چت
async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = int(query.data.split('_')[2])
    
    # بررسی مالکیت چت
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT user1, user2, is_active FROM chats WHERE id=?", (chat_id,))
    chat = c.fetchone()
    conn.close()
    
    if not chat or not chat[2]:
        await query.edit_message_text("❌ این چت فعال نیست!")
        return
    
    if update.effective_user.id not in [chat[0], chat[1]]:
        await query.edit_message_text("❌ شما دسترسی به این چت ندارید!")
        return
    
    other_user = chat[1] if chat[0] == update.effective_user.id else chat[0]
    
    context.user_data['active_chat'] = chat_id
    context.user_data['chat_partner'] = other_user
    
    # نمایش پیام‌های قبلی
    messages = get_chat_messages(chat_id)
    if messages:
        for msg in messages:
            await query.message.reply_text(
                f"{'شما' if msg[1] == update.effective_user.id else 'طرف مقابل'}:\n{msg[2]}"
            )
    else:
        await query.edit_message_text(
            "💬 چت شروع شد!\n"
            "پیام خودت رو بفرست...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 درخواست عکس", callback_data=f"request_photo_{other_user}")],
                [InlineKeyboardButton("🚫 بستن چت", callback_data="close_chat")],
                [InlineKeyboardButton("🚫 بلاک کردن", callback_data=f"block_{other_user}")]
            ])
        )

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'active_chat' not in context.user_data:
        await update.message.reply_text(
            "❌ شما در هیچ چتی نیستی!\n"
            "از منوی اصلی استفاده کن.",
            reply_markup=main_menu_keyboard()
        )
        return
    
    chat_id = context.user_data['active_chat']
    sender_id = update.effective_user.id
    text = update.message.text
    
    # ذخیره پیام
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (chat_id, sender_id, message_text, timestamp)
        VALUES (?, ?, ?, ?)
    """, (chat_id, sender_id, text, datetime.now()))
    conn.commit()
    conn.close()
    
    # ارسال به طرف مقابل
    partner_id = context.user_data['chat_partner']
    try:
        await context.bot.send_message(
            partner_id,
            f"📩 پیام جدید از طرف مقابل:\n\n{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 پاسخ", callback_data=f"reply_chat_{chat_id}")]
            ])
        )
        await update.message.reply_text("✅ پیام ارسال شد!")
    except:
        await update.message.reply_text("❌ ارسال پیام ناموفق!")

async def request_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    _, target_id = query.data.split('_')
    target_id = int(target_id)
    requester_id = update.effective_user.id
    chat_id = context.user_data['active_chat']
    
    # ثبت درخواست عکس
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO photo_requests (requester_id, target_id, chat_id, created_at)
        VALUES (?, ?, ?, ?)
    """, (requester_id, target_id, chat_id, datetime.now()))
    conn.commit()
    conn.close()
    
    # ارسال درخواست به طرف مقابل
    try:
        await context.bot.send_message(
            target_id,
            f"📸 {requester_id} درخواست عکس شما رو کرده!\n"
            "آیا اجازه می‌دی عکس شما رو ببینه؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ بله", callback_data=f"accept_photo_{requester_id}")],
                [InlineKeyboardButton("❌ نه", callback_data=f"reject_photo_{requester_id}")]
            ])
        )
        await query.edit_message_text("✅ درخواست عکس ارسال شد!")
    except:
        await query.edit_message_text("❌ ارسال درخواست ناموفق!")

async def handle_photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, requester_id = query.data.split('_')
    requester_id = int(requester_id)
    target_id = update.effective_user.id
    
    if action == "accept_photo":
        # دریافت عکس کاربر
        user = get_user_dict(target_id)
        if user and user['photo']:
            try:
                with open(user['photo'], 'rb') as photo:
                    await context.bot.send_photo(
                        requester_id,
                        photo,
                        caption="📸 عکس درخواستی:"
                    )
                await query.edit_message_text("✅ عکس ارسال شد!")
            except:
                await query.edit_message_text("❌ خطا در ارسال عکس!")
        else:
            await query.edit_message_text("❌ شما عکسی ندارید!")
    
    elif action == "reject_photo":
        try:
            await context.bot.send_message(
                requester_id,
                "❌ طرف مقابل اجازه ارسال عکس نداد!"
            )
            await query.edit_message_text("🙅 درخواست رد شد!")
        except:
            await query.edit_message_text("🙅 درخواست رد شد!")

# ویرایش پروفایل
async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📝 چه چیزی رو می‌خوای ویرایش کنی؟",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 جنسیت", callback_data="edit_gender")],
            [InlineKeyboardButton("📅 سن", callback_data="edit_age")],
            [InlineKeyboardButton("🎯 هدف", callback_data="edit_purpose")],
            [InlineKeyboardButton("🏙️ شهر", callback_data="edit_city")],
            [InlineKeyboardButton("🎨 علایق", callback_data="edit_interests")],
            [InlineKeyboardButton("💼 وضعیت شغلی", callback_data="edit_job")],
            [InlineKeyboardButton("📝 توضیحات", callback_data="edit_description")],
            [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
        ])
    )

# آمار
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    # تعداد درخواست‌های ارسالی
    c.execute("SELECT COUNT(*) FROM requests WHERE from_user=? AND status='pending'", (user_id,))
    sent_requests = c.fetchone()[0]
    
    # تعداد درخواست‌های دریافتی
    c.execute("SELECT COUNT(*) FROM requests WHERE to_user=? AND status='pending'", (user_id,))
    received_requests = c.fetchone()[0]
    
    # تعداد چت‌های فعال
    c.execute("SELECT COUNT(*) FROM chats WHERE (user1=? OR user2=?) AND is_active=1", (user_id, user_id))
    active_chats = c.fetchone()[0]
    
    conn.close()
    
    await query.edit_message_text(
        f"📊 آمار شما:\n\n"
        f"📤 درخواست‌های ارسالی: {sent_requests}\n"
        f"📥 درخواست‌های دریافتی: {received_requests}\n"
        f"💬 چت‌های فعال: {active_chats}",
        reply_markup=main_menu_keyboard()
    )

# ریست ربات
async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # فقط علامت setup_complete رو false کن
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET is_setup_complete=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(
        "🔄 ربات ریست شد!\n"
        "لطفاً دوباره /start رو بزن تا ثبت‌نام مجدد انجام بشه.",
        reply_markup=None
    )

# راهنما
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "ℹ️ راهنمای استفاده از بات هم‌نوا:\n\n"
        "🔍 جستجو: پیدا کردن افراد مناسب\n"
        "📝 ویرایش پروفایل: تغییر اطلاعات\n"
        "📋 درخواست‌های من: مشاهده درخواست‌ها\n"
        "🔒 حریم خصوصی: تنظیمات نمایش اطلاعات\n"
        "📊 آمار: مشاهده آمار شما\n"
        "🔄 ریست: ریست کردن ربات\n\n"
        "💡 نکات:\n"
        "- هر چت ۳ روز اعتبار داره\n"
        "- می‌تونی حداکثر ۳ چت همزمان داشته باشی\n"
        "- افراد رد شده تا ۱ هفته نمایش داده نمیشن",
        reply_markup=main_menu_keyboard()
    )

# تابع اصلی
def main():
    # مقداردهی دیتابیس
    init_db()
    
    # ساخت اپلیکیشن
    application = Application.builder().token(TOKEN).build()
    
    # هندلرهای مکالمه (ثبت‌نام)
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
            PRIVACY: [CallbackQueryHandler(privacy_selection, pattern='^privacy_')],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    application.add_handler(conv_handler)
    
    # هندلرهای دکمه‌های منو
    application.add_handler(CallbackQueryHandler(search, pattern='^search$'))
    application.add_handler(CallbackQueryHandler(edit_profile, pattern='^edit_profile$'))
    application.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
    application.add_handler(CallbackQueryHandler(reset_bot, pattern='^reset_bot$'))
    application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    
    # هندلرهای جستجو
    application.add_handler(CallbackQueryHandler(candidate_action, pattern='^(like|dislike|more_info)_'))
    application.add_handler(CallbackQueryHandler(show_candidate, pattern='^next_candidate$'))
    application.add_handler(CallbackQueryHandler(view_requester, pattern='^view_requester_'))
    application.add_handler(CallbackQueryHandler(handle_request, pattern='^(accept|reject)_request_'))
    
    # هندلرهای چت
    application.add_handler(CallbackQueryHandler(start_chat, pattern='^start_chat_'))
    application.add_handler(CallbackQueryHandler(request_photo, pattern='^request_photo_'))
    application.add_handler(CallbackQueryHandler(handle_photo_request, pattern='^(accept|reject)_photo_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))
    
    # هندلرهای برگشت
    application.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.edit_message_text(
        "🏠 بازگشت به منوی اصلی",
        reply_markup=main_menu_keyboard()
    ), pattern='^back_to_menu$'))
    
    # اجرا
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
