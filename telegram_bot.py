# telegram_bot.py
import logging
import json
import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
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

# مراحل وضعیت گفتگو (Wizard States)
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

    # -------------------------------------------------------------------------
    # بخش ۱: شروع و بررسی وضعیت ثبت‌نام
    # -------------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # چک میکنیم آیا کاربر قبلا ثبت نام کرده؟
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user.id,))
        db_user = cursor.fetchone()
        conn.close()

        if db_user:
            # اگر ثبت نام کرده بود، منوی اصلی را نشان بده
            await self.show_main_menu(update, db_user)
        else:
            # اگر ثبت نام نکرده بود، وارد پروسه ثبت نام شو
            await update.message.reply_text(
                f"سلام {user.first_name} خوش آمدید! 👋\n\n"
                "برای استفاده از ربات معامله‌گر، نیاز به ایجاد حساب کاربری داریم.\n"
                "ما در چند مرحله کوتاه اطلاعات لازم را از شما می‌گیریم.\n\n"
                "🔹 **مرحله ۱ از ۷:**\n"
                "لطفاً **نام و نام خانوادگی** خود را وارد کنید.\n"
                "_(این نام برای گزارش‌دهی به شما استفاده می‌شود)_"
            )
            return GET_NAME

    # -------------------------------------------------------------------------
    # بخش ۲: فلو ثبت نام (Wizard)
    # -------------------------------------------------------------------------
    
    # دریافت نام
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        
        # درخواست شماره موبایل (با دکمه اشتراک گذاری برای راحتی)
        contact_btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        markup = ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "✅ نام شما ثبت شد.\n\n"
            "🔹 **مرحله ۲ از ۷:**\n"
            "لطفاً **شماره موبایل** خود را وارد کنید یا از دکمه زیر استفاده کنید.\n"
            "_(شماره شما برای اطلاع‌رسانی‌های اضطراری و امنیتی استفاده می‌شود و نزد ما محفوظ است.)_",
            reply_markup=markup
        )
        return GET_PHONE

    # دریافت شماره موبایل
    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # هندل کردن ارسال کانتکت یا متن دستی
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            phone = update.message.text
            
        context.user_data['phone'] = phone
        
        await update.message.reply_text(
            "✅ شماره موبایل ثبت شد.\n\n"
            "🔹 **مرحله ۳ از ۷:**\n"
            "مبلغ سرمایه درگیر برای هر خرید **تومانی** را وارد کنید (به تومان).\n"
            "مثال: `500000` (برای پانصد هزار تومان)\n\n"
            "_(وقتی سیگنال تومان ارسال می‌شود، ربات دقیقاً به این اندازه خرید می‌کند)_",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    # دریافت سرمایه تومانی
    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = float(update.message.text)
            context.user_data['buy_tmn'] = amount
            
            await update.message.reply_text(
                "🔹 **مرحله ۴ از ۷:**\n"
                "مبلغ سرمایه درگیر برای هر خرید **تتری** را وارد کنید (به تتر).\n"
                "مثال: `20` (برای بیست تتر)\n\n"
                "_(برای سیگنال‌های جفت تتر استفاده می‌شود)_"
            )
            return GET_CAPITAL_USDT
        except ValueError:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید (بدون حروف و کاما).")
            return GET_CAPITAL_TMN

    # دریافت سرمایه تتری
    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = float(update.message.text)
            context.user_data['buy_usdt'] = amount
            
            await update.message.reply_text(
                "✅ تنظیمات سرمایه انجام شد.\n\n"
                "🔹 **مرحله ۵ از ۷ (بسیار مهم):**\n"
                "لطفاً **API Key** حساب والکس خود را ارسال کنید.\n\n"
                "ℹ️ **چرا API میگیریم؟**\n"
                "برای اینکه ربات بتواند به جای شما سفارش خرید و فروش بگذارد. ما فقط دسترسی ترید نیاز داریم.\n"
                "_(کلید شما اعتبارسنجی می‌شود)_"
            )
            return GET_API
        except ValueError:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید.")
            return GET_CAPITAL_USDT

    # دریافت و اعتبارسنجی API Key
    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        
        await update.message.reply_text("⏳ در حال اتصال به والکس جهت بررسی اعتبار کلید...")
        
        # اعتبارسنجی با والکس
        url = f"{WALLEX_BASE_URL}/v1/account/balances"
        headers = DEFAULT_HEADERS.copy()
        headers["X-API-Key"] = api_key
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید API معتبر است.")
                
                # آماده‌سازی برای انتخاب استراتژی
                context.user_data['strategies'] = []
                await self.ask_strategies(update)
                return GET_STRATEGIES
                
            elif resp.status_code == 401:
                await update.message.reply_text("⛔️ کلید نامعتبر است (خطای 401). لطفاً کلید صحیح را ارسال کنید.")
                return GET_API
            else:
                await update.message.reply_text(f"⚠️ خطای عجیب از والکس ({resp.status_code}). لطفاً مجدد تلاش کنید.")
                return GET_API
                
        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}. لطفاً مجدد تلاش کنید.")
            return GET_API

    # تابع کمکی برای نمایش دکمه‌های استراتژی
    async def ask_strategies(self, update: Update):
        keyboard = [
            ['Internal', 'G1'],
            ['Computiational'],
            ['✅ تایید و ادامه']
        ]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        selected = ", ".join(context.user_data.get('strategies', []))
        msg = (
            "🔹 **مرحله ۶ از ۷:**\n"
            "کدام **استراتژی‌ها** را می‌خواهید دنبال کنید؟\n"
            "روی گزینه‌ها کلیک کنید. در آخر دکمه تایید را بزنید.\n\n"
            f"✅ انتخاب‌های فعلی: **{selected if selected else '(خالی)'}**\n\n"
            "_(ربات فقط سیگنال‌های این استراتژی‌ها را خرید می‌کند)_"
        )
        # در اولین بار فراخوانی update.message وجود دارد
        if update.message:
            await update.message.reply_text(msg, reply_markup=markup)

    # دریافت انتخاب‌های استراتژی
    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        current_list = context.user_data.get('strategies', [])
        
        if text == '✅ تایید و ادامه':
            if not current_list:
                await update.message.reply_text("⚠️ لطفاً حداقل یک استراتژی انتخاب کنید.")
                return GET_STRATEGIES
            
            # رفتن به مرحله بعد
            context.user_data['grades'] = []
            await self.ask_grades(update, context)
            return GET_GRADES
            
        elif text in ['Internal', 'G1', 'Computiational']:
            if text in current_list:
                current_list.remove(text)
                await update.message.reply_text(f"🗑 حذف شد: {text}")
            else:
                current_list.append(text)
                await update.message.reply_text(f"➕ اضافه شد: {text}")
            
            context.user_data['strategies'] = current_list
            # نمایش مجدد لیست
            selected = ", ".join(current_list)
            await update.message.reply_text(f"لیست فعلی: {selected}")
            return GET_STRATEGIES
        else:
            await update.message.reply_text("لطفاً از دکمه‌های پایین استفاده کنید.")
            return GET_STRATEGIES

    # تابع کمکی برای نمایش دکمه‌های گرید
    async def ask_grades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            ['Q1', 'Q2'],
            ['Q3', 'Q4'],
            ['✅ پایان ثبت نام']
        ]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        selected = ", ".join(context.user_data.get('grades', []))
        msg = (
            "🔹 **مرحله ۷ از ۷ (آخر):**\n"
            "کدام **گریدها** (کیفیت سیگنال) را قبول می‌کنید؟\n"
            "معمولاً Q1 بهترین کیفیت است.\n\n"
            f"✅ انتخاب‌های فعلی: **{selected if selected else '(خالی)'}**"
        )
        await update.message.reply_text(msg, reply_markup=markup)

    # دریافت انتخاب‌های گرید و ذخیره نهایی
    async def get_grades_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        current_list = context.user_data.get('grades', [])
        
        if text == '✅ پایان ثبت نام':
            if not current_list:
                await update.message.reply_text("⚠️ لطفاً حداقل یک گرید انتخاب کنید.")
                return GET_GRADES
            
            # --- ذخیره نهایی در دیتابیس ---
            user_id = update.effective_user.id
            data = context.user_data
            
            conn = self.db.get_connection()
            try:
                conn.execute('''
                    INSERT INTO users (
                        telegram_id, full_name, phone_number, wallex_api_key,
                        buy_amount_tmn, buy_amount_usdt,
                        allowed_strategies, allowed_grades, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (
                    user_id, data['full_name'], data['phone'], data['api_key'],
                    data['buy_tmn'], data['buy_usdt'],
                    json.dumps(data['strategies']), json.dumps(current_list)
                ))
                conn.commit()
                await update.message.reply_text(
                    "🎉 **حساب کاربری شما با موفقیت ایجاد شد!**\n\n"
                    "⚠️ توجه: حساب شما به صورت پیش‌فرض **غیرفعال** است تا زمانی که خودتان آماده باشید.\n"
                    "از منوی زیر گزینه «✅ فعال‌سازی ربات» را بزنید.",
                    reply_markup=ReplyKeyboardRemove()
                )
                
                # نمایش منوی اصلی
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
                
            except Exception as e:
                logging.error(e)
                await update.message.reply_text("❌ خطا در ذخیره اطلاعات. لطفا دوباره تلاش کنید.")
            finally:
                conn.close()
            
            return ConversationHandler.END
            
        elif text in ['Q1', 'Q2', 'Q3', 'Q4']:
            if text in current_list:
                current_list.remove(text)
                await update.message.reply_text(f"🗑 حذف شد: {text}")
            else:
                current_list.append(text)
                await update.message.reply_text(f"➕ اضافه شد: {text}")
            
            context.user_data['grades'] = current_list
            await update.message.reply_text(f"لیست فعلی: {', '.join(current_list)}")
            return GET_GRADES
        else:
            await update.message.reply_text("لطفاً از دکمه‌ها استفاده کنید.")
            return GET_GRADES

    # -------------------------------------------------------------------------
    # بخش ۳: منوی اصلی و مدیریت حساب (بعد از لاگین)
    # -------------------------------------------------------------------------
    async def show_main_menu(self, update: Update, user_row):
        is_active = user_row['is_active']
        status_icon = "🟢" if is_active else "🔴"
        status_text = "روشن" if is_active else "خاموش"
        
        toggle_btn = "❌ توقف ربات" if is_active else "✅ فعال‌سازی ربات"
        
        keyboard = [
            [toggle_btn],
            ['📊 گزارش وضعیت', '⚙️ تنظیمات مجدد']
        ]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"👤 کاربر: {user_row['full_name']}\n"
            f"وضعیت ربات: {status_icon} **{status_text}**\n\n"
            "یکی از گزینه‌ها را انتخاب کنید:",
            reply_markup=markup
        )

    async def toggle_activation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = update.message.text
        
        new_status = 1 if "فعال‌سازی" in text else 0
        
        conn = self.db.get_connection()
        conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (new_status, user_id))
        conn.commit()
        
        # رفرش کردن اطلاعات کاربر برای نمایش منو
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        user_row = cursor.fetchone()
        conn.close()
        
        msg = "🚀 ربات فعال شد و آماده انجام معامله است." if new_status else "💤 ربات متوقف شد."
        await update.message.reply_text(msg)
        await self.show_main_menu(update, user_row)

    async def status_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        u = cursor.fetchone()
        conn.close()
        
        if u:
            strategies = json.loads(u['allowed_strategies'])
            grades = json.loads(u['allowed_grades'])
            
            report = (
                f"📋 **مشخصات حساب:**\n"
                f"نام: {u['full_name']}\n"
                f"موبایل: {u['phone_number']}\n"
                f"----------------\n"
                f"💰 خرید تومانی: {u['buy_amount_tmn']:,} T\n"
                f"💰 خرید تتری: {u['buy_amount_usdt']} $\n"
                f"----------------\n"
                f"🎯 استراتژی‌ها: {', '.join(strategies)}\n"
                f"💎 گریدها: {', '.join(grades)}\n"
            )
            await update.message.reply_text(report)
            await self.show_main_menu(update, u)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ عملیات لغو شد.")
        return ConversationHandler.END

    def run(self):
        # هندلر مکالمه ثبت نام
        reg_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                GET_NAME: [MessageHandler(filters.TEXT, self.get_name)],
                GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, self.get_phone)],
                GET_CAPITAL_TMN: [MessageHandler(filters.TEXT, self.get_capital_tmn)],
                GET_CAPITAL_USDT: [MessageHandler(filters.TEXT, self.get_capital_usdt)],
                GET_API: [MessageHandler(filters.TEXT, self.get_api)],
                GET_STRATEGIES: [MessageHandler(filters.TEXT, self.get_strategies_step)],
                GET_GRADES: [MessageHandler(filters.TEXT, self.get_grades_step)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.app.add_handler(reg_handler)
        self.app.add_handler(MessageHandler(filters.Regex('فعال‌سازی|توقف'), self.toggle_activation))
        self.app.add_handler(MessageHandler(filters.Regex('گزارش وضعیت'), self.status_report))
        
        print("🤖 Wizard Bot Started...")
        self.app.run_polling()

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or "YOUR_" in TELEGRAM_BOT_TOKEN:
        print("❌ خطا: توکن ربات را در فایل config.py تنظیم کنید.")
    else:
        bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
        bot.run()
