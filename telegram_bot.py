# telegram_bot.py
import logging
import json
import requests
import re  # برای بررسی الگوی شماره موبایل
from telegram import (
    Update, 
    ReplyKeyboardMarkup, 
    ReplyKeyboardRemove, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
)
from database import DatabaseHandler
from config import TELEGRAM_BOT_TOKEN, WALLEX_BASE_URL, DEFAULT_HEADERS

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# تعریف مراحل
(
    GET_NAME,
    GET_PHONE,
    GET_CAPITAL_TMN,
    GET_CAPITAL_USDT,
    GET_API,
    GET_STRATEGIES,
    GET_GRADES
) = range(7)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()

    # --- توابع کمکی کیبورد شیشه‌ای ---
    def get_strategy_keyboard(self, selected_list):
        options = ['Internal', 'G1', 'Computiational']
        keyboard = []
        for opt in options:
            # اگر انتخاب شده بود، تیک کنارش بذار
            text = f"✅ {opt}" if opt in selected_list else opt
            keyboard.append([InlineKeyboardButton(text, callback_data=f"STRAT_{opt}")])
        
        # دکمه تایید نهایی
        keyboard.append([InlineKeyboardButton("تایید و ادامه ➡️", callback_data="CONFIRM_STRAT")])
        return InlineKeyboardMarkup(keyboard)

    def get_grade_keyboard(self, selected_list):
        options = ['Q1', 'Q2', 'Q3', 'Q4']
        keyboard = []
        row = []
        for opt in options:
            text = f"✅ {opt}" if opt in selected_list else opt
            row.append(InlineKeyboardButton(text, callback_data=f"GRADE_{opt}"))
            # چیدمان دو تایی
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("پایان ثبت نام 🏁", callback_data="CONFIRM_GRADE")])
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------------------
    # بخش ۱: شروع و بررسی حساب کاربری
    # -------------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # جستجو در دیتابیس بر اساس آیدی تلگرام
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user.id,))
        db_user = cursor.fetchone()
        conn.close()

        if db_user:
            # اگر کاربر وجود داشت -> نمایش منوی اصلی
            await update.message.reply_text(f"سلام {user.first_name}، خوش برگشتی! 🌹")
            await self.show_main_menu(update, db_user)
        else:
            # اگر کاربر جدید بود -> شروع ثبت نام
            await update.message.reply_text(
                f"سلام {user.first_name} خوش آمدید! 👋\n"
                "برای استفاده از ربات، لطفاً ثبت‌نام کنید.\n\n"
                "🔹 **مرحله ۱ از ۷:**\n"
                "لطفاً **نام و نام خانوادگی** خود را تایپ کنید:"
            )
            return GET_NAME

    # -------------------------------------------------------------------------
    # بخش ۲: فلو ثبت نام (Wizard) با اعتبارسنجی
    # -------------------------------------------------------------------------
    
    # دریافت نام
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text
        if len(name) < 3:
            await update.message.reply_text("❌ نام خیلی کوتاه است. لطفاً نام کامل خود را وارد کنید:")
            return GET_NAME # تکرار مرحله

        context.user_data['full_name'] = name
        
        contact_btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        markup = ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "✅ نام شما ثبت شد.\n\n"
            "🔹 **مرحله ۲ از ۷:**\n"
            "لطفاً شماره موبایل خود را با دکمه زیر ارسال کنید (یا تایپ کنید):",
            reply_markup=markup
        )
        return GET_PHONE

    # دریافت موبایل
    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone = ""
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            text = update.message.text
            # اعتبارسنجی ساده شماره (فقط عدد و حداقل ۱۰ رقم)
            if not text.isdigit() or len(text) < 10:
                await update.message.reply_text("❌ شماره نامعتبر است. لطفاً فقط عدد وارد کنید (مثال: 0912...):")
                return GET_PHONE # تکرار مرحله
            phone = text

        context.user_data['phone'] = phone
        await update.message.reply_text(
            "✅ شماره ثبت شد.\n\n"
            "🔹 **مرحله ۳ از ۷:**\n"
            "مبلغ سرمایه درگیر برای خرید **تومانی** را به عدد وارد کنید (مثال: 500000):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    # دریافت سرمایه تومانی
    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 50000: # حداقل ۵۰ هزار تومان
                await update.message.reply_text("❌ مبلغ خیلی کم است (حداقل ۵۰,۰۰۰ تومان). لطفاً اصلاح کنید:")
                return GET_CAPITAL_TMN
            
            context.user_data['buy_tmn'] = val
            await update.message.reply_text(
                "🔹 **مرحله ۴ از ۷:**\n"
                "مبلغ سرمایه درگیر برای خرید **تتری** را به عدد وارد کنید (مثال: 20):"
            )
            return GET_CAPITAL_USDT
        except ValueError:
            await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید:")
            return GET_CAPITAL_TMN

    # دریافت سرمایه تتری
    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 5: # حداقل ۵ تتر
                await update.message.reply_text("❌ مبلغ خیلی کم است (حداقل ۵ تتر). لطفاً اصلاح کنید:")
                return GET_CAPITAL_USDT

            context.user_data['buy_usdt'] = val
            await update.message.reply_text(
                "🔹 **مرحله ۵ از ۷ (مهم):**\n"
                "لطفاً **API Key** حساب والکس خود را ارسال کنید.\n"
                "_(ما اعتبار این کلید را همین الان چک می‌کنیم)_"
            )
            return GET_API
        except ValueError:
            await update.message.reply_text("❌ لطفاً فقط عدد انگلیسی وارد کنید:")
            return GET_CAPITAL_USDT

    # دریافت و چک کردن API
    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ در حال اعتبارسنجی کلید با سرور والکس...")
        
        # تست اتصال واقعی
        url = f"{WALLEX_BASE_URL}/v1/account/balances"
        headers = DEFAULT_HEADERS.copy()
        headers["X-API-Key"] = api_key
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید تایید شد.")
                
                # نمایش انتخاب استراتژی (شیشه‌ای)
                context.user_data['strategies'] = []
                markup = self.get_strategy_keyboard([])
                await update.message.reply_text(
                    "🔹 **مرحله ۶ از ۷:**\n"
                    "استراتژی‌هایی که می‌خواهید دنبال کنید را انتخاب کنید (چند انتخابی):",
                    reply_markup=markup
                )
                return GET_STRATEGIES
            else:
                await update.message.reply_text(f"⛔️ کلید نامعتبر است (کد {resp.status_code}). لطفاً کلید صحیح را بفرستید:")
                return GET_API # تکرار مرحله
        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}. لطفاً دوباره تلاش کنید:")
            return GET_API

    # --- هندلر دکمه‌های شیشه‌ای استراتژی ---
    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('strategies', [])

        if data == "CONFIRM_STRAT":
            # اعتبارسنجی: لیست خالی نباشد
            if not current:
                await query.answer("⚠️ حداقل یک استراتژی را انتخاب کنید!", show_alert=True)
                return GET_STRATEGIES
            
            # رفتن به مرحله بعد
            context.user_data['grades'] = []
            markup = self.get_grade_keyboard([])
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text(
                "🔹 **مرحله ۷ از ۷ (آخر):**\n"
                "گریدهای سیگنال (کیفیت) را انتخاب کنید:", 
                reply_markup=markup
            )
            return GET_GRADES
            
        elif data.startswith("STRAT_"):
            strat = data.split("_")[1]
            if strat in current: current.remove(strat)
            else: current.append(strat)
            
            context.user_data['strategies'] = current
            # آپدیت کیبورد برای نشان دادن تیک‌ها
            await query.edit_message_reply_markup(reply_markup=self.get_strategy_keyboard(current))
            return GET_STRATEGIES

    # --- هندلر دکمه‌های شیشه‌ای گرید ---
    async def get_grades_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('grades', [])

        if data == "CONFIRM_GRADE":
            # اعتبارسنجی: لیست خالی نباشد
            if not current:
                await query.answer("⚠️ حداقل یک گرید را انتخاب کنید!", show_alert=True)
                return GET_GRADES
            
            # --- پایان ثبت نام و ذخیره ---
            await query.message.edit_text("✅ گریدها ثبت شد. در حال ساخت حساب...")
            
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
                # ذخیره در دیتابیس
                conn.execute('''
                    INSERT INTO users (
                        telegram_id, full_name, phone_number, wallex_api_key,
                        buy_amount_tmn, buy_amount_usdt,
                        allowed_strategies, allowed_grades, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (
                    user_id, d['full_name'], d['phone'], d['api_key'],
                    d['buy_tmn'], d['buy_usdt'],
                    json.dumps(d['strategies']), json.dumps(current)
                ))
                conn.commit()
                
                await query.message.reply_text(
                    "🎉 **تبریک! حساب شما ساخته شد.**\n"
                    "⚠️ حساب شما فعلاً **غیرفعال** است. برای شروع ترید دکمه فعال‌سازی را بزنید."
                )
                
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
                
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطا در ذخیره اطلاعات. لطفاً با پشتیبانی تماس بگیرید.")
            finally:
                conn.close()
            return ConversationHandler.END
            
        elif data.startswith("GRADE_"):
            grade = data.split("_")[1]
            if grade in current: current.remove(grade)
            else: current.append(grade)
            
            context.user_data['grades'] = current
            await query.edit_message_reply_markup(reply_markup=self.get_grade_keyboard(current))
            return GET_GRADES

    # -------------------------------------------------------------------------
    # بخش ۳: منوی اصلی
    # -------------------------------------------------------------------------
    async def show_main_menu(self, update: Update, user_row):
        # تشخیص اینکه آپدیت از پیام است یا دکمه شیشه‌ای
        target = update.message if update.message else update.callback_query.message
        
        status = "🟢 روشن" if user_row['is_active'] else "🔴 خاموش"
        btn_action = "❌ توقف ربات" if user_row['is_active'] else "✅ فعال‌سازی ربات"
        
        keyboard = [[btn_action], ['📊 گزارش وضعیت', '⚙️ تنظیمات مجدد']]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await target.reply_text(
            f"👤 کاربر: {user_row['full_name']}\n"
            f"وضعیت ربات: {status}\n\n"
            "یکی از گزینه‌ها را انتخاب کنید:",
            reply_markup=markup
        )

    async def toggle_activation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # تشخیص وضعیت جدید بر اساس متن دکمه
        new_status = 1 if "فعال‌سازی" in update.message.text else 0
        
        conn = self.db.get_connection()
        conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (new_status, user_id))
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        u = cursor.fetchone()
        conn.close()
        
        msg = "🚀 ربات فعال شد و آماده شکار است!" if new_status else "💤 ربات متوقف شد."
        await update.message.reply_text(msg)
        await self.show_main_menu(update, u)

    async def status_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        u = cursor.fetchone()
        conn.close()
        
        if u:
            # نمایش زیبای لیست‌ها
            try:
                st = ", ".join(json.loads(u['allowed_strategies']))
                gr = ", ".join(json.loads(u['allowed_grades']))
            except:
                st = "-"
                gr = "-"

            report = (
                f"📊 **گزارش وضعیت حساب**\n"
                f"--------------------------\n"
                f"👤 نام: {u['full_name']}\n"
                f"📱 موبایل: {u['phone_number']}\n"
                f"--------------------------\n"
                f"💰 خرید تومانی: {u['buy_amount_tmn']:,} T\n"
                f"💰 خرید تتری: {u['buy_amount_usdt']} $\n"
                f"--------------------------\n"
                f"🎯 استراتژی‌ها: {st}\n"
                f"💎 گریدها: {gr}"
            )
            await update.message.reply_text(report)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    def run(self):
        # تعریف هندلر مکالمه (Wizard)
        reg_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT & ~filters.COMMAND, self.get_phone)],
                GET_CAPITAL_TMN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_capital_tmn)],
                GET_CAPITAL_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_capital_usdt)],
                GET_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_api)],
                GET_STRATEGIES: [CallbackQueryHandler(self.get_strategies_step)],
                GET_GRADES: [CallbackQueryHandler(self.get_grades_step)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.app.add_handler(reg_handler)
        self.app.add_handler(MessageHandler(filters.Regex('فعال‌سازی|توقف'), self.toggle_activation))
        self.app.add_handler(MessageHandler(filters.Regex('گزارش وضعیت'), self.status_report))
        
        print("🤖 Advanced Bot Started...")
        self.app.run_polling()

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or "YOUR_" in TELEGRAM_BOT_TOKEN:
        print("❌ خطا: توکن ربات تنظیم نشده است.")
    else:
        bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
        bot.run()
