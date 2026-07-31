import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

TOKEN = os.environ.get('TOKEN', "YOUR_BOT_TOKEN_HERE")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== دیتابیس ====================

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
        photo_path TEXT,
        timestamp TIMESTAMP,
        is_read BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS rejected (
        user_id INTEGER,
        rejected_user_id INTEGER,
        rejected_at TIMESTAMP,
        PRIMARY KEY (user_id, rejected_user_id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS photo_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER,
        target_id INTEGER,
        chat_id INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP
    )''')
    
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

# ==================== مراحل ثبت‌نام ====================

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

# ==================== شروع و ثبت‌نام ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    context.user_data.clear()
    
    if user and user[17]:
        await update.message.reply_text(
            f"🌟 به بات هم‌نوا خوش اومدی {update.effective_user.first_name}!\n\n"
            "از منوی زیر استفاده کن:",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END
    
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
        "🌸 چند سالت هست؟\n"
        "(مثلاً: ۲۵)\n"
        "فقط عدد وارد کن:",
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
    
    await show_interests(update, context)
    return INTERESTS

# ==================== علایق ====================

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

async def show_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'interests' not in context.user_data:
        context.user_data['interests'] = []
    
    text = "🎨 چه چیزهایی رو دوست داری؟\n"
    text += f"انتخاب شده: {', '.join(context.user_data['interests']) if context.user_data['interests'] else 'هیچ'}\n\n"
    text += "روی هر گزینه بزن تا انتخاب یا حذف بشه (حداکثر ۵ تا):"
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            reply_markup=get_interests_keyboard(context.user_data['interests'])
        )
    else:
        await update.message.reply_text(
            text,
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
                "❌ حداقل یک علاقه انتخاب کن!",
                reply_markup=None
            )
            await show_interests(update, context)
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
    else:
        if len(context.user_data['interests']) >= 5:
            await query.edit_message_text(
                "❌ حداکثر ۵ علاقه می‌تونی انتخاب کنی!",
                reply_markup=None
            )
            await show_interests(update, context)
            return INTERESTS
        context.user_data['interests'].append(interest)
    
    await show_interests(update, context)
    return INTERESTS

# ==================== وضعیت شغلی ====================

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
    
    await update.message.reply_text(
        "📸 حالا عکس پروفایل خودت رو بفرست.\n\n"
        "این عکس وقتی کسی درخواست عکس بده، براش ارسال میشه.\n"
        "اگه عکس نفرستی، عکس پروفایل تلگرامت استفاده میشه.\n\n"
        "📤 عکس رو بفرست یا دکمه 'رد شدن' رو بزن:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
        ])
    )
    return PHOTO

async def description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['description'] = ""
    
    await query.edit_message_text(
        "📸 حالا عکس پروفایل خودت رو بفرست.\n\n"
        "این عکس وقتی کسی درخواست عکس بده، براش ارسال میشه.\n"
        "اگه عکس نفرستی، عکس پروفایل تلگرامت استفاده میشه.\n\n"
        "📤 عکس رو بفرست یا دکمه 'رد شدن' رو بزن:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
        ])
    )
    return PHOTO

# ==================== عکس ====================

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_file = update.message.photo[-1]
        file_id = photo_file.file_id
        
        context.user_data['photo'] = file_id
        
        await update.message.reply_text(
            "✅ عکس شما با موفقیت ذخیره شد!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ادامه", callback_data="photo_done")]
            ])
        )
        return PHOTO
    else:
        await update.message.reply_text(
            "❌ لطفاً یک عکس بفرست!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭️ رد شدن", callback_data="skip_photo")]
            ])
        )
        return PHOTO

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['photo'] = None
    
    await show_privacy_settings(update, context)
    return PRIVACY

async def photo_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await show_privacy_settings(update, context)
    return PRIVACY

# ==================== حریم خصوصی ====================

async def show_privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            "🔒 تنظیمات حریم خصوصی:\n\n"
            "روی هر گزینه بزن تا تغییر کنه:\n"
            "✅ = نمایش داده میشه\n"
            "❌ = نمایش داده نمیشه",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "🔒 تنظیمات حریم خصوصی:\n\n"
            "روی هر گزینه بزن تا تغییر کنه:\n"
            "✅ = نمایش داده میشه\n"
            "❌ = نمایش داده نمیشه",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

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
        visibility_options = ['all', 'same_city', 'none']
        current = context.user_data['privacy']['visibility']
        next_index = (visibility_options.index(current) + 1) % len(visibility_options)
        context.user_data['privacy']['visibility'] = visibility_options[next_index]
        await show_privacy_settings(update, context)
    
    elif query.data == "privacy_done":
        await finish_registration(update, context)
        return PRIVACY

async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
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
        'is_setup_complete': 1
    }
    save_user(user_id, user_data)
    
    if isinstance(update, Update) and update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            "🎉 ثبت‌نام شما کامل شد!\n\n"
            "حالا می‌تونی از امکانات ربات استفاده کنی:",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "🎉 ثبت‌نام شما کامل شد!\n\n"
            "حالا می‌تونی از امکانات ربات استفاده کنی:",
            reply_markup=main_menu_keyboard()
        )
    return ConversationHandler.END

# ==================== جستجو ====================

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
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    week_ago = datetime.now() - timedelta(days=7)
    c.execute("SELECT rejected_user_id FROM rejected WHERE user_id=? AND rejected_at > ?", (user_id, week_ago))
    rejected = [row[0] for row in c.fetchall()]
    
    c.execute("SELECT user2 FROM chats WHERE user1=? AND is_active=1", (user_id,))
    active_chats1 = [row[0] for row in c.fetchall()]
    c.execute("SELECT user1 FROM chats WHERE user2=? AND is_active=1", (user_id,))
    active_chats2 = [row[0] for row in c.fetchall()]
    active_chats = active_chats1 + active_chats2
    
    query_str = """
        SELECT * FROM users 
        WHERE user_id != ? 
        AND is_active = 1 
        AND is_setup_complete = 1
        AND age BETWEEN ? AND ?
        AND purpose = ?
    """
    params = [user_id, user['age_min'], user['age_max'], user['purpose']]
    
    if user['privacy_visibility'] == 'same_city':
        query_str += " AND city = ?"
        params.append(user['city'])
    
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
    
    message = f"👤 کاربر {index+1} از {len(candidates)}\n\n"
    message += f"سن: {user_dict['age'] if user_dict['privacy_age'] else '❌ مخفی'}\n"
    message += f"شهر: {user_dict['city'] if user_dict['privacy_city'] else '❌ مخفی'}\n"
    message += f"هدف: {user_dict['purpose']}\n"
    message += f"وضعیت: {user_dict['job_status']}"
    
    keyboard = [
        [InlineKeyboardButton("👍 علاقه‌مندم", callback_data=f"like_{user_dict['user_id']}")],
        [InlineKeyboardButton("👎 رد کردن", callback_data=f"dislike_{user_dict['user_id']}")],
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
    
    try:
        parts = query.data.split('_', 1)
        if len(parts) != 2:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        action = parts[0]
        target_id = int(parts[1])
    except Exception as e:
        logger.error(f"Error in candidate_action: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    user_id = update.effective_user.id
    
    if action == "like":
        conn = sqlite3.connect('matchbot.db')
        c = conn.cursor()
        
        c.execute("SELECT * FROM requests WHERE from_user=? AND to_user=? AND status='pending'", (user_id, target_id))
        if not c.fetchone():
            c.execute("""
                INSERT INTO requests (from_user, to_user, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, target_id, datetime.now(), datetime.now() + timedelta(days=3)))
            conn.commit()
            
            try:
                target_user = get_user_dict(target_id)
                if target_user:
                    await context.bot.send_message(
                        target_id,
                        f"📩 یه نفر به شما علاقه نشان داد!\n"
                        f"می‌خواید پروفایلش رو ببینید؟",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("👀 مشاهده پروفایل", callback_data=f"view_requester_{user_id}")],
                            [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{user_id}")],
                            [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_{user_id}")]
                        ])
                    )
            except Exception as e:
                logger.error(f"Error sending request: {e}")
        
        conn.close()
        
        await query.edit_message_text(
            "✅ درخواست شما ارسال شد!\n"
            "منتظر پاسخ طرف مقابل می‌مونیم... ⏳",
            reply_markup=main_menu_keyboard()
        )
    
    elif action == "dislike":
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
        
        if 'candidate_index' in context.user_data:
            context.user_data['candidate_index'] += 1
        await show_candidate(update, context)
    
    elif action == "more_info":
        target_user = get_user_dict(target_id)
        if target_user:
            interests = json.loads(target_user['interests']) if target_user['interests'] else []
            message = f"📋 اطلاعات بیشتر:\n\n"
            message += f"علایق: {', '.join(interests) if interests else '❌ ندارد'}\n"
            if target_user['description']:
                message += f"\n📝 توضیحات: {target_user['description']}"
            else:
                message += f"\n📝 توضیحات: ❌ ندارد"
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 برگشت به پروفایل", callback_data=f"back_to_candidate_{target_id}")]
                ])
            )

async def back_to_candidate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_candidate(update, context)

# ==================== مشاهده پروفایل و مدیریت درخواست‌ها ====================

async def view_requester(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        if len(parts) != 3:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        requester_id = int(parts[2])
    except Exception as e:
        logger.error(f"Error in view_requester: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    requester = get_user_dict(requester_id)
    if not requester:
        await query.edit_message_text("❌ کاربر پیدا نشد!", reply_markup=main_menu_keyboard())
        return
    
    message = f"👤 اطلاعات درخواست‌دهنده:\n\n"
    message += f"جنسیت: {requester['gender']}\n"
    message += f"سن: {requester['age'] if requester['privacy_age'] else '❌ مخفی'}\n"
    message += f"شهر: {requester['city'] if requester['privacy_city'] else '❌ مخفی'}\n"
    message += f"هدف: {requester['purpose']}\n"
    message += f"وضعیت: {requester['job_status']}\n\n"
    
    interests = json.loads(requester['interests']) if requester['interests'] else []
    message += f"🎨 علایق: {', '.join(interests) if interests else '❌ ندارد'}\n"
    
    if requester['description']:
        message += f"\n📝 توضیحات: {requester['description']}"
    
    keyboard = [
        [InlineKeyboardButton("✅ تایید", callback_data=f"accept_{requester_id}")],
        [InlineKeyboardButton("❌ رد کردن", callback_data=f"reject_{requester_id}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="back_to_menu")]
    ]
    
    if requester.get('photo_file_id'):
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=update.effective_user.id,
                photo=requester['photo_file_id'],
                caption=message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        if len(parts) != 2:
            await query.edit_message_text("❌ خطا در پردازش! فرمت: accept_123", reply_markup=main_menu_keyboard())
            return
        action = parts[0]
        user_id = int(parts[1])
    except Exception as e:
        logger.error(f"Error in handle_request: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM requests WHERE from_user=? AND to_user=? AND status='pending'", (user_id, current_user))
    request_exists = c.fetchone()
    
    if not request_exists:
        await query.edit_message_text("❌ این درخواست وجود ندارد یا قبلاً پاسخ داده شده!", reply_markup=main_menu_keyboard())
        conn.close()
        return
    
    if action == "accept":
        c.execute("""
            UPDATE requests SET status='accepted' 
            WHERE from_user=? AND to_user=? AND status='pending'
        """, (user_id, current_user))
        
        c.execute("""
            INSERT INTO chats (user1, user2, match_date, expiry_date)
            VALUES (?, ?, ?, ?)
        """, (user_id, current_user, datetime.now(), datetime.now() + timedelta(days=3)))
        
        chat_id = c.lastrowid
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(
                user_id,
                f"🎉 طرف مقابل درخواست شما رو قبول کرد!\n"
                f"حالا می‌تونید با هم چت کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 شروع چت", callback_data=f"start_chat_{chat_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Error notifying requester: {e}")
        
        await query.edit_message_text(
            "🎉 هورا! شما همدیگرو پسندیدین!\n"
            "چت شما فعال شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 شروع چت", callback_data=f"start_chat_{chat_id}")]
            ])
        )
    
    elif action == "reject":
        c.execute("""
            UPDATE requests SET status='rejected' 
            WHERE from_user=? AND to_user=? AND status='pending'
        """, (user_id, current_user))
        conn.commit()
        conn.close()
        
        try:
            await context.bot.send_message(
                user_id,
                "😔 متاسفانه طرف مقابل درخواست شما رو رد کرد!",
                reply_markup=main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Error notifying rejection: {e}")
        
        await query.edit_message_text(
            "🙅 درخواست رد شد!",
            reply_markup=main_menu_keyboard()
        )

# ==================== چت ====================

async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_')
        if len(parts) != 3:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        chat_id = int(parts[2])
    except Exception as e:
        logger.error(f"Error in start_chat: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("SELECT user1, user2, is_active FROM chats WHERE id=?", (chat_id,))
    chat = c.fetchone()
    conn.close()
    
    if not chat or not chat[2]:
        await query.edit_message_text("❌ این چت فعال نیست!", reply_markup=main_menu_keyboard())
        return
    
    if update.effective_user.id not in [chat[0], chat[1]]:
        await query.edit_message_text("❌ شما دسترسی به این چت ندارید!", reply_markup=main_menu_keyboard())
        return
    
    other_user = chat[1] if chat[0] == update.effective_user.id else chat[0]
    
    context.user_data['active_chat'] = chat_id
    context.user_data['chat_partner'] = other_user
    
    await query.edit_message_text(
        "💬 چت شروع شد!\n"
        "پیام خودت رو بفرست...\n\n"
        "📌 برای بستن چت از دکمه زیر استفاده کن.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 درخواست عکس", callback_data=f"request_photo_{other_user}")],
            [InlineKeyboardButton("❌ بستن چت", callback_data="close_chat")],
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
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (chat_id, sender_id, message_text, timestamp)
        VALUES (?, ?, ?, ?)
    """, (chat_id, sender_id, text, datetime.now()))
    conn.commit()
    conn.close()
    
    partner_id = context.user_data['chat_partner']
    try:
        await context.bot.send_message(
            partner_id,
            f"📩 پیام جدید:\n\n{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 پاسخ", callback_data=f"reply_chat_{chat_id}")]
            ])
        )
        await update.message.reply_text("✅ پیام ارسال شد!")
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        await update.message.reply_text("❌ ارسال پیام ناموفق!")

async def request_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_', 1)
        if len(parts) != 2:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        target_id = int(parts[1])
    except Exception as e:
        logger.error(f"Error in request_photo: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    requester_id = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    if not chat_id:
        await query.edit_message_text("❌ شما در هیچ چتی نیستی!", reply_markup=main_menu_keyboard())
        return
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO photo_requests (requester_id, target_id, chat_id, created_at)
        VALUES (?, ?, ?, ?)
    """, (requester_id, target_id, chat_id, datetime.now()))
    conn.commit()
    conn.close()
    
    try:
        user = get_user_dict(target_id)
        if user and user['photo_file_id']:
            await context.bot.send_message(
                target_id,
                f"📸 کاربری درخواست عکس شما رو کرده!\n"
                "آیا اجازه می‌دی عکس شما رو ببینه؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بله", callback_data=f"accept_photo_{requester_id}")],
                    [InlineKeyboardButton("❌ نه", callback_data=f"reject_photo_{requester_id}")]
                ])
            )
            await query.edit_message_text("✅ درخواست عکس ارسال شد!")
        else:
            await query.edit_message_text("❌ کاربر مورد نظر عکسی ندارد!")
    except Exception as e:
        logger.error(f"Error requesting photo: {e}")
        await query.edit_message_text("❌ ارسال درخواست ناموفق!")

async def handle_photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_', 1)
        if len(parts) != 2:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        action = parts[0]
        requester_id = int(parts[1])
    except Exception as e:
        logger.error(f"Error in handle_photo_request: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    target_id = update.effective_user.id
    
    if action == "accept_photo":
        user = get_user_dict(target_id)
        if user and user['photo_file_id']:
            try:
                await context.bot.send_photo(
                    requester_id,
                    user['photo_file_id'],
                    caption="📸 عکس درخواستی:"
                )
                await query.edit_message_text("✅ عکس ارسال شد!")
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
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
        except Exception as e:
            logger.error(f"Error rejecting photo: {e}")
            await query.edit_message_text("🙅 درخواست رد شد!")

async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop('active_chat', None)
    context.user_data.pop('chat_partner', None)
    
    await query.edit_message_text(
        "✅ چت بسته شد!",
        reply_markup=main_menu_keyboard()
    )

async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split('_', 1)
        if len(parts) != 2:
            await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
            return
        user_id = int(parts[1])
    except Exception as e:
        logger.error(f"Error in block_user: {e}")
        await query.edit_message_text("❌ خطا در پردازش!", reply_markup=main_menu_keyboard())
        return
    
    current_user = update.effective_user.id
    chat_id = context.user_data.get('active_chat')
    
    if chat_id:
        conn = sqlite3.connect('matchbot.db')
        c = conn.cursor()
        c.execute("UPDATE chats SET is_active=0, blocked_by=? WHERE id=?", (current_user, chat_id))
        conn.commit()
        conn.close()
    
    context.user_data.pop('active_chat', None)
    context.user_data.pop('chat_partner', None)
    
    await query.edit_message_text(
        f"🚫 کاربر بلاک شد!",
        reply_markup=main_menu_keyboard()
    )

# ==================== ویرایش پروفایل ====================

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user_dict(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ شما ثبت‌نام نکردی!", reply_markup=main_menu_keyboard())
        return
    
    info_text = f"📝 اطلاعات فعلی شما:\n\n"
    info_text += f"👤 جنسیت: {user['gender']}\n"
    info_text += f"📅 سن: {user['age']}\n"
    info_text += f"🎯 هدف: {user['purpose']}\n"
    info_text += f"🏙️ شهر: {user['city']}\n"
    info_text += f"🎨 علایق: {', '.join(json.loads(user['interests']) if user['interests'] else [])}\n"
    info_text += f"💼 وضعیت: {user['job_status']}\n"
    info_text += f"📝 توضیحات: {user['description'][:30] + '...' if user['description'] and len(user['description']) > 30 else user['description'] or '❌ ندارد'}\n"
    info_text += f"📸 عکس: {'✅ دارد' if user['photo_file_id'] else '❌ ندارد'}\n\n"
    info_text += "کدوم بخش رو می‌خوای ویرایش کنی؟"
    
    keyboard = [
        [InlineKeyboardButton("👤 جنسیت", callback_data="edit_gender"),
         InlineKeyboardButton("📅 سن", callback_data="edit_age")],
        [InlineKeyboardButton("🎯 هدف", callback_data="edit_purpose"),
         InlineKeyboardButton("🏙️ شهر", callback_data="edit_city")],
        [InlineKeyboardButton("🎨 علایق", callback_data="edit_interests"),
         InlineKeyboardButton("💼 وضعیت شغلی", callback_data="edit_job")],
        [InlineKeyboardButton("📝 توضیحات", callback_data="edit_description")],
        [InlineKeyboardButton("📸 عکس پروفایل", callback_data="edit_photo")],
        [InlineKeyboardButton("🔙 برگشت به منو", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def edit_profile_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    field = query.data.replace("edit_", "")
    user = get_user_dict(update.effective_user.id)
    
    if field == "gender":
        await query.edit_message_text(
            "جنسیت جدید رو انتخاب کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👨 مرد", callback_data="update_gender_male")],
                [InlineKeyboardButton("👩 زن", callback_data="update_gender_female")],
                [InlineKeyboardButton("🧑 سایر", callback_data="update_gender_other")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    
    elif field == "age":
        await query.edit_message_text(
            f"سن فعلی: {user['age']}\n\nسن جدید رو وارد کن (فقط عدد):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
        context.user_data['editing_field'] = 'age'
    
    elif field == "purpose":
        await query.edit_message_text(
            f"هدف فعلی: {user['purpose']}\n\nهدف جدید رو انتخاب کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💍 ازدواج", callback_data="update_purpose_marriage")],
                [InlineKeyboardButton("💑 دوستی", callback_data="update_purpose_relationship")],
                [InlineKeyboardButton("🎭 رفاقت", callback_data="update_purpose_friendship")],
                [InlineKeyboardButton("🤷 نمیدونم", callback_data="update_purpose_unknown")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    
    elif field == "city":
        await query.edit_message_text(
            f"شهر فعلی: {user['city']}\n\nشهر جدید رو وارد کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
        context.user_data['editing_field'] = 'city'
    
    elif field == "interests":
        await query.edit_message_text(
            "🎨 علایق جدید رو انتخاب کن (حداکثر ۵ تا):",
            reply_markup=get_interests_keyboard(
                json.loads(user['interests']) if user['interests'] else []
            )
        )
        context.user_data['editing_interests'] = json.loads(user['interests']) if user['interests'] else []
        context.user_data['editing_field'] = 'interests'
    
    elif field == "job":
        await query.edit_message_text(
            f"وضعیت فعلی: {user['job_status']}\n\nوضعیت جدید رو انتخاب کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 دانشجو", callback_data="update_job_student")],
                [InlineKeyboardButton("💼 شاغل", callback_data="update_job_employed")],
                [InlineKeyboardButton("🔍 جویای کار", callback_data="update_job_seeking")],
                [InlineKeyboardButton("🏠 خانه‌دار", callback_data="update_job_home")],
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
    
    elif field == "description":
        await query.edit_message_text(
            f"توضیحات فعلی: {user['description'] if user['description'] else '❌ ندارد'}\n\n"
            "توضیحات جدید رو وارد کن (حداکثر ۲۰۰ کاراکتر):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
        context.user_data['editing_field'] = 'description'
    
    elif field == "photo":
        await query.edit_message_text(
            "📸 عکس جدید رو بفرست.\n\n"
            "این عکس وقتی کسی درخواست عکس بده، براش ارسال میشه.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 برگشت", callback_data="edit_profile")]
            ])
        )
        context.user_data['editing_field'] = 'photo'

async def update_profile_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data.replace("update_", "")
    
    if data.startswith("gender_"):
        gender = data.replace("gender_", "")
        gender_map = {"male": "مرد", "female": "زن", "other": "سایر"}
        save_user(user_id, {'gender': gender_map[gender]})
        await query.edit_message_text("✅ جنسیت به‌روز شد!", reply_markup=main_menu_keyboard())
    
    elif data.startswith("purpose_"):
        purpose = data.replace("purpose_", "")
        purpose_map = {"marriage": "ازدواج", "relationship": "دوستی", "friendship": "رفاقت", "unknown": "نمیدونم"}
        save_user(user_id, {'purpose': purpose_map[purpose]})
        await query.edit_message_text("✅ هدف به‌روز شد!", reply_markup=main_menu_keyboard())
    
    elif data.startswith("job_"):
        job = data.replace("job_", "")
        job_map = {"student": "دانشجو", "employed": "شاغل", "seeking": "جویای کار", "home": "خانه‌دار"}
        save_user(user_id, {'job_status': job_map[job]})
        await query.edit_message_text("✅ وضعیت شغلی به‌روز شد!", reply_markup=main_menu_keyboard())
    
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
            await query.edit_message_text("❌ حداقل یک علاقه انتخاب کن!", reply_markup=None)
            await edit_profile_field(update, context)
            return
        
        save_user(user_id, {'interests': json.dumps(context.user_data['editing_interests'])})
        context.user_data.pop('editing_interests', None)
        context.user_data.pop('editing_field', None)
        await query.edit_message_text("✅ علایق به‌روز شد!", reply_markup=main_menu_keyboard())

async def handle_profile_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    field = context.user_data.get('editing_field')
    
    if field == 'age':
        try:
            age = int(update.message.text)
            if 10 <= age <= 100:
                save_user(user_id, {'age': age})
                await update.message.reply_text("✅ سن به‌روز شد!", reply_markup=main_menu_keyboard())
            else:
                await update.message.reply_text("❌ سن باید بین ۱۰ تا ۱۰۰ باشه!")
        except ValueError:
            await update.message.reply_text("❌ لطفاً عدد وارد کن!")
    
    elif field == 'city':
        save_user(user_id, {'city': update.message.text})
        await update.message.reply_text("✅ شهر به‌روز شد!", reply_markup=main_menu_keyboard())
    
    elif field == 'description':
        text = update.message.text
        if len(text) > 200:
            await update.message.reply_text("❌ حداکثر ۲۰۰ کاراکتر!")
            return
        save_user(user_id, {'description': text})
        await update.message.reply_text("✅ توضیحات به‌روز شد!", reply_markup=main_menu_keyboard())
    
    elif field == 'photo':
        if update.message.photo:
            photo_file = update.message.photo[-1]
            save_user(user_id, {'photo_file_id': photo_file.file_id})
            await update.message.reply_text("✅ عکس به‌روز شد!", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("❌ لطفاً یک عکس بفرست!")
            return
    
    context.user_data.pop('editing_field', None)

# ==================== حریم خصوصی ====================

async def privacy_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = get_user_dict(update.effective_user.id)
    if not user:
        await query.edit_message_text("❌ شما ثبت‌نام نکردی!", reply_markup=main_menu_keyboard())
        return
    
    age_status = "✅" if user['privacy_age'] else "❌"
    city_status = "✅" if user['privacy_city'] else "❌"
    
    visibility_text = {
        'all': '🌍 همه',
        'same_city': '🏙️ همشهری‌ها',
        'none': '❌ هیچکس'
    }.get(user['privacy_visibility'], '🌍 همه')
    
    keyboard = [
        [InlineKeyboardButton(f"{age_status} نمایش سن", callback_data="privacy_toggle_age")],
        [InlineKeyboardButton(f"{city_status} نمایش شهر", callback_data="privacy_toggle_city")],
        [InlineKeyboardButton(f"🌍 نمایش به: {visibility_text}", callback_data="privacy_change_visibility")],
        [InlineKeyboardButton("🔙 برگشت به منو", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text(
        "🔒 تنظیمات حریم خصوصی:\n\n"
        f"وضعیت فعلی:\n"
        f"سن: {'نمایش داده میشه' if user['privacy_age'] else 'مخفی'}\n"
        f"شهر: {'نمایش داده میشه' if user['privacy_city'] else 'مخفی'}\n"
        f"نمایش به: {visibility_text}\n\n"
        "✅ = نمایش داده میشه\n"
        "❌ = نمایش داده نمیشه\n\n"
        "روی هر گزینه بزن تا تغییر کنه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def privacy_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = get_user_dict(user_id)
    
    if query.data == "privacy_toggle_age":
        new_value = not user['privacy_age']
        save_user(user_id, {'privacy_age': new_value})
    
    elif query.data == "privacy_toggle_city":
        new_value = not user['privacy_city']
        save_user(user_id, {'privacy_city': new_value})
    
    elif query.data == "privacy_change_visibility":
        visibility_options = ['all', 'same_city', 'none']
        current = user['privacy_visibility']
        next_index = (visibility_options.index(current) + 1) % len(visibility_options)
        save_user(user_id, {'privacy_visibility': visibility_options[next_index]})
    
    await privacy_settings(update, context)

# ==================== درخواست‌های من ====================

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT from_user, created_at FROM requests 
        WHERE to_user=? AND status='pending'
        ORDER BY created_at DESC
    """, (user_id,))
    received = c.fetchall()
    
    conn.close()
    
    if not received:
        await query.edit_message_text(
            "📋 هیچ درخواست جدیدی ندارید!",
            reply_markup=main_menu_keyboard()
        )
        return
    
    message = "📋 درخواست‌های دریافتی:\n\n"
    keyboard = []
    
    for req in received[:5]:
        from_user = get_user_dict(req[0])
        if from_user:
            message += f"👤 سن: {from_user['age'] if from_user['privacy_age'] else '❌'}\n"
            message += f"📍 شهر: {from_user['city'] if from_user['privacy_city'] else '❌'}\n"
            message += f"🎯 هدف: {from_user['purpose']}\n\n"
            keyboard.append([InlineKeyboardButton(
                f"👀 مشاهده و پاسخ",
                callback_data=f"view_requester_{from_user['user_id']}"
            )])
    
    keyboard.append([InlineKeyboardButton("🔙 برگشت به منو", callback_data="back_to_menu")])
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==================== آمار ====================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('matchbot.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM requests WHERE from_user=? AND status='pending'", (user_id,))
    sent_requests = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM requests WHERE to_user=? AND status='pending'", (user_id,))
    received_requests = c.fetchone()[0]
    
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

# ==================== ریست ====================

async def reset_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
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

# ==================== راهنما ====================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "ℹ️ راهنمای استفاده از بات هم‌نوا:\n\n"
        "🔍 جستجو: پیدا کردن افراد مناسب بر اساس مشخصات شما\n"
        "📝 ویرایش پروفایل: تغییر اطلاعات ثبت‌نامی\n"
        "📋 درخواست‌های من: مشاهده درخواست‌های دریافتی\n"
        "🔒 حریم خصوصی: تنظیمات نمایش اطلاعات شما\n"
        "📊 آمار: مشاهده آمار فعالیت شما\n"
        "🔄 ریست: ریست کردن ربات (بدون پاک کردن اطلاعات)\n\n"
        "💡 نکات مهم:\n"
        "- هر چت ۳ روز اعتبار داره\n"
        "- حداکثر ۳ چت همزمان فعال میتونی داشته باشی\n"
        "- افراد رد شده تا ۱ هفته دوباره نمایش داده نمیشن\n"
        "- برای تغییر اطلاعات از بخش ویرایش پروفایل استفاده کن\n"
        "- عکس پروفایل رو میتونی در مرحله ثبت‌نام یا ویرایش پروفایل آپلود کنی",
        reply_markup=main_menu_keyboard()
    )

# ==================== برگشت به منو ====================

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard()
    )

# ==================== تابع اصلی ====================

def main():
    init_db()
    
    application = Application.builder().token(TOKEN).build()
    
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
    
    # منوی اصلی
    application.add_handler(CallbackQueryHandler(search, pattern='^search$'))
    application.add_handler(CallbackQueryHandler(edit_profile, pattern='^edit_profile$'))
    application.add_handler(CallbackQueryHandler(my_requests, pattern='^my_requests$'))
    application.add_handler(CallbackQueryHandler(privacy_settings, pattern='^privacy_settings$'))
    application.add_handler(CallbackQueryHandler(stats, pattern='^stats$'))
    application.add_handler(CallbackQueryHandler(reset_bot, pattern='^reset_bot$'))
    application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back_to_menu$'))
    
    # ویرایش پروفایل
    application.add_handler(CallbackQueryHandler(edit_profile_field, pattern='^edit_(gender|age|purpose|city|interests|job|description|photo)$'))
    application.add_handler(CallbackQueryHandler(update_profile_field, pattern='^update_(gender_|purpose_|job_|interest_|interests_done)'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_text_input))
    application.add_handler(MessageHandler(filters.PHOTO, handle_profile_text_input))
    
    # جستجو
    application.add_handler(CallbackQueryHandler(candidate_action, pattern='^(like|dislike|more_info)_'))
    application.add_handler(CallbackQueryHandler(show_candidate, pattern='^next_candidate$'))
    application.add_handler(CallbackQueryHandler(back_to_candidate, pattern='^back_to_candidate_'))
    
    # درخواست‌ها
    application.add_handler(CallbackQueryHandler(view_requester, pattern='^view_requester_'))
    application.add_handler(CallbackQueryHandler(handle_request, pattern='^(accept|reject)_'))
    
    # چت
    application.add_handler(CallbackQueryHandler(start_chat, pattern='^start_chat_'))
    application.add_handler(CallbackQueryHandler(request_photo, pattern='^request_photo_'))
    application.add_handler(CallbackQueryHandler(handle_photo_request, pattern='^(accept|reject)_photo_'))
    application.add_handler(CallbackQueryHandler(close_chat, pattern='^close_chat$'))
    application.add_handler(CallbackQueryHandler(block_user, pattern='^block_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))
    
    # حریم خصوصی
    application.add_handler(CallbackQueryHandler(privacy_toggle, pattern='^privacy_toggle_(age|city|change_visibility)$'))
    
    logger.info("Bot started with Polling!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
