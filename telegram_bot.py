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
            text = f"✅ {opt}" if opt in selected_list else opt
            keyboard.append([InlineKeyboardButton(text, callback_data=f"STRAT_{opt}")])
        keyboard.append([InlineKeyboardButton("تایید و ادامه ➡️", callback_data="CONFIRM_STRAT")])
        return InlineKeyboardMarkup(keyboard)

    def get_grade_keyboard(self, selected_list):
        options = ['Q1', 'Q2', 'Q3', 'Q4']
        keyboard = []
        row = []
        for opt in options:
            text = f"✅ {opt}" if opt in selected_list else opt
            row.append(InlineKeyboardButton(text, callback_data=f"GRADE_{opt}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("پایان ثبت نام 🏁", callback_data="CONFIRM_GRADE")])
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------------------
    # شروع
    # -------------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user.id,))
        db_user = cursor.fetchone()
        conn.close()

        if db_user:
            await self.show_main_menu(update, db_user)
        else:
            await update.message.reply_text(
                f"سلام {user.first_name} 👋\n"
                "🔹 **مرحله ۱ از ۷:**\nلطفاً **نام و نام خانوادگی** خود را بنویسید."
            )
            return GET_NAME

    # -------------------------------------------------------------------------
    # فلو ثبت نام (با اعتبارسنجی دقیق)
    # -------------------------------------------------------------------------
    
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text
        if len(name) < 3:
            await update.message.reply_text("❌ نام خیلی کوتاه است. لطفاً نام کامل خود را وارد کنید:")
            return GET_NAME # تکرار مرحله

        context.user_data['full_name'] = name
        
        contact_btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        markup = ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "✅ نام ثبت شد.\n\n🔹 **مرحله ۲ از ۷:**\nشماره موبایل خود را دکمه زیر ارسال کنید (یا تایپ کنید):",
            reply_markup=markup
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone = ""
        # حالت ۱: ارسال کانتکت
        if update.message.contact:
            phone = update.message.contact.phone_number
        # حالت ۲: تایپ دستی
        else:
            text = update.message.text
            # اعتبارسنجی: باید فقط عدد باشد و حداقل ۱۰ رقم
            if not text.isdigit() or len(text) < 10:
                await update.message.reply_text("❌ فرمت شماره اشتباه است. لطفاً فقط عدد وارد کنید (مثلاً 0912...):")
                return GET_PHONE # تکرار مرحله
            phone = text

        context.user_data['phone'] = phone
        await update.message.reply_text(
            "✅ شماره ثبت شد.\n\n🔹 **مرحله ۳ از ۷:**\nمبلغ خرید **تومانی** را به عدد وارد کنید (مثلاً 500000):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 50000: # حداقل مبلغ مثلا ۵۰ هزار تومان
                await update.message.reply_text("❌ مبلغ خیلی کم است (حداقل ۵۰,۰۰۰). لطفاً مبلغ صحیح را وارد کنید:")
                return GET_CAPITAL_TMN # تکرار مرحله
            
            context.user_data['buy_tmn'] = val
            await update.message.reply_text("🔹 **مرحله ۴ از ۷:**\nمبلغ خرید **تتری** را به عدد وارد کنید (مثلاً 20):")
            return GET_CAPITAL_USDT
        except ValueError:
            await update.message.reply_text("❌ لطفاً فقط عدد (بدون حروف) وارد کنید:")
            return GET_CAPITAL_TMN # تکرار مرحله

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 5: # حداقل ۵ تتر
                await update.message.reply_text("❌ مبلغ خیلی کم است (حداقل ۵ تتر). لطفاً مبلغ صحیح را وارد کنید:")
                return GET_CAPITAL_USDT # تکرار مرحله

            context.user_data['buy_usdt'] = val
            await update.message.reply_text(
                "🔹 **مرحله ۵ از ۷:**\nلطفاً **API Key** حساب والکس خود را ارسال کنید."
            )
            return GET_API
        except ValueError:
            await update.message.reply_text("❌ لطفاً فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT # تکرار مرحله

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ در حال اعتبارسنجی کلید...")
        
        # تست اتصال
        url = f"{WALLEX_BASE_URL}/v1/account/balances"
        headers = DEFAULT_HEADERS.copy()
        headers["X-API-Key"] = api_key
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید تایید شد.")
                
                # شروع انتخاب استراتژی
                context.user_data['strategies'] = []
                markup = self.get_strategy_keyboard([])
                await update.message.reply_text(
                    "🔹 **مرحله ۶ از ۷:**\nاستراتژی‌ها را انتخاب کنید و سپس دکمه تایید را بزنید:",
                    reply_markup=markup
                )
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ کلید نامعتبر است (خطای دسترسی). لطفاً کلید صحیح را بفرستید:")
                return GET_API # تکرار مرحله تا زمانی که کلید درست بدهد
        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}. لطفاً دوباره تلاش کنید:")
            return GET_API # تکرار مرحله

    # --- هندلر استراتژی (شیشه‌ای) ---
    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('strategies', [])

        if data == "CONFIRM_STRAT":
            # اعتبارسنجی: اگر لیست خالی باشد رد نمیشود
            if not current:
                await query.answer("⚠️ باید حداقل یک استراتژی انتخاب کنید!", show_alert=True)
                return GET_STRATEGIES # ماندن در مرحله
            
            # رفتن به مرحله بعد
            context.user_data['grades'] = []
            markup = self.get_grade_keyboard([])
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text(
                "🔹 **مرحله ۷ از ۷:**\nگریدها (کیفیت سیگنال) را انتخاب کنید:", 
                reply_markup=markup
            )
            return GET_GRADES
            
        elif data.startswith("STRAT_"):
            strat = data.split("_")[1]
            if strat in current: current.remove(strat)
            else: current.append(strat)
            
            context.user_data['strategies'] = current
            await query.edit_message_reply_markup(reply_markup=self.get_strategy_keyboard(current))
            return GET_STRATEGIES

    # --- هندلر گرید (شیشه‌ای) ---
    async def get_grades_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('grades', [])

        if data == "CONFIRM_GRADE":
            # اعتبارسنجی: لیست نباید خالی باشد
            if not current:
                await query.answer("⚠️ باید حداقل یک گرید انتخاب کنید!", show_alert=True)
                return GET_GRADES # ماندن در مرحله
            
            # ذخیره نهایی
            await query.message.edit_text("✅ در حال ساخت حساب...")
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
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
                
                await query.message.reply_text("🎉 **حساب شما ساخته شد!**\nبرای شروع، از منوی زیر دکمه فعال‌سازی را بزنید.")
                
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
                
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطای دیتابیس.")
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

    # --- منوی اصلی ---
    async def show_main_menu(self, update: Update, user_row):
        target = update.message if update.message else update.callback_query.message
        
        status = "🟢 روشن" if user_row['is_active'] else "🔴 خاموش"
        btn = "❌ توقف ربات" if user_row['is_active'] else "✅ فعال‌سازی ربات"
        
        keyboard = [[btn], ['📊 گزارش وضعیت', '⚙️ تنظیمات مجدد']]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await target.reply_text(
            f"👤 {user_row['full_name']}\nوضعیت: {status}",
            reply_markup=markup
        )

    async def toggle_activation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        new_status = 1 if "فعال‌سازی" in update.message.text else 0
        
        conn = self.db.get_connection()
        conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (new_status, user_id))
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        u = cursor.fetchone()
        conn.close()
        
        await update.message.reply_text("✅ انجام شد.")
        await self.show_main_menu(update, u)

    async def status_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (update.effective_user.id,))
        u = cursor.fetchone()
        conn.close()
        
        if u:
            st = ", ".join(json.loads(u['allowed_strategies']))
            gr = ", ".join(json.loads(u['allowed_grades']))
            await update.message.reply_text(
                f"📊 **گزارش**\n👤 {u['full_name']}\n📱 {u['phone_number']}\n"
                f"💰 TMN: {u['buy_amount_tmn']:,}\n💰 USDT: {u['buy_amount_usdt']}\n"
                f"🎯 {st}\n💎 {gr}"
            )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    def run(self):
        reg_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                GET_NAME: [MessageHandler(filters.TEXT, self.get_name)],
                GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, self.get_phone)],
                GET_CAPITAL_TMN: [MessageHandler(filters.TEXT, self.get_capital_tmn)],
                GET_CAPITAL_USDT: [MessageHandler(filters.TEXT, self.get_capital_usdt)],
                GET_API: [MessageHandler(filters.TEXT, self.get_api)],
                GET_STRATEGIES: [CallbackQueryHandler(self.get_strategies_step)],
                GET_GRADES: [CallbackQueryHandler(self.get_grades_step)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.app.add_handler(reg_handler)
        self.app.add_handler(MessageHandler(filters.Regex('فعال‌سازی|توقف'), self.toggle_activation))
        self.app.add_handler(MessageHandler(filters.Regex('گزارش وضعیت'), self.status_report))
        
        print("🤖 Strict Validation Bot Started...")
        self.app.run_polling()

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or "YOUR_" in TELEGRAM_BOT_TOKEN:
        print("❌ توکن را تنظیم کنید.")
    else:
        bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
        bot.run()
