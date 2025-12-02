import logging
import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

# تنظیمات لاگ (برای دیدن خطاها در ترمینال)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# تعریف مراحل گفتگو (States)
(
    GET_API,
    SET_BUY_TMN,
    SET_BUY_USDT,
    SET_STOP_LOSS,
    SET_MAX_FROZEN_TMN,
    SET_MAX_FROZEN_USDT
) = range(6)

# کیبورد اصلی منو
MAIN_MENU_KEYBOARD = [
    ['🔑 ثبت API Key', '💰 تنظیمات مبلغ خرید'],
    ['🛑 مدیریت ریسک', '📊 گزارش حساب'],
    ['✅ فعال‌سازی ربات', '❌ توقف ربات']
]


class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()

    # --- دستور Start و منوی اصلی ---
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # ثبت کاربر در دیتابیس اگر وجود نداشت
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user.id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (telegram_id) VALUES (?)", (user.id,))
            conn.commit()
            await update.message.reply_text(f"سلام {user.first_name} 👋\nحساب کاربری شما ایجاد شد.")
        else:
            await update.message.reply_text(f"سلام مجدد {user.first_name} 🌹")

        conn.close()
        await self.show_menu(update)

    async def show_menu(self, update: Update):
        markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await update.message.reply_text("چه کاری انجام دهم؟ 👇", reply_markup=markup)

    # --- بخش ۱: ثبت و اعتبارسنجی API ---
    async def start_api_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "لطفاً API Key خود را از پنل کاربری والکس کپی کرده و ارسال کنید:\n"
            "(برای انصراف /cancel را بزنید)",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_API

    async def verify_and_save_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        user_id = update.effective_user.id

        await update.message.reply_text("⏳ در حال بررسی اعتبار کلید با سرور والکس...")

        # اعتبارسنجی واقعی: درخواست گرفتن موجودی کیف پول
        # /v1/account/balances
        url = f"{WALLEX_BASE_URL}/v1/account/balances"
        headers = DEFAULT_HEADERS.copy()
        headers["X-API-Key"] = api_key

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200 and response.json().get('success'):
                # کلید معتبر است -> ذخیره در دیتابیس
                conn = self.db.get_connection()
                conn.execute("UPDATE users SET wallex_api_key = ? WHERE telegram_id = ?", (api_key, user_id))
                conn.commit()
                conn.close()

                await update.message.reply_text("✅ API Key تایید و ذخیره شد.")
            elif response.status_code == 401:
                await update.message.reply_text("⛔️ کلید نامعتبر است (خطای 401). لطفاً دوباره تلاش کنید.")
                return ConversationHandler.END  # یا میتوانیم اجازه دهیم دوباره بفرستد
            else:
                await update.message.reply_text(f"⚠️ خطا در ارتباط با والکس: {response.status_code}")

        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}")

        await self.show_menu(update)
        return ConversationHandler.END

    # --- بخش ۲: تنظیمات مبلغ خرید (Capital) ---
    async def start_capital_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "💵 لطفاً مبلغ خرید برای هر پله **تومانی** را به تومان وارد کنید:\n"
            "(مثلاً: 500000)",
            reply_markup=ReplyKeyboardRemove()
        )
        return SET_BUY_TMN

    async def set_buy_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = float(update.message.text)
            context.user_data['buy_tmn'] = amount
            await update.message.reply_text("💵 حالا مبلغ خرید برای بازارهای **تتری** را وارد کنید (مثلاً: 10):")
            return SET_BUY_USDT
        except ValueError:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید.")
            return SET_BUY_TMN

    async def set_buy_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = float(update.message.text)
            user_id = update.effective_user.id
            buy_tmn = context.user_data['buy_tmn']

            conn = self.db.get_connection()
            conn.execute(
                "UPDATE users SET buy_amount_tmn = ?, buy_amount_usdt = ? WHERE telegram_id = ?",
                (buy_tmn, amount, user_id)
            )
            conn.commit()
            conn.close()

            await update.message.reply_text(f"✅ تنظیمات ذخیره شد:\nخرید تومانی: {buy_tmn:,}\nخرید تتری: {amount}")
            await self.show_menu(update)
            return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید.")
            return SET_BUY_USDT

    # --- بخش ۳: مدیریت ریسک (Risk Management) ---
    async def start_risk_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🛑 درصد **حد ضرر شناور** را وارد کنید (مثلاً 2 برای 2%):\n(عدد 0 یعنی غیرفعال)",
            reply_markup=ReplyKeyboardRemove()
        )
        return SET_STOP_LOSS

    async def set_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            sl = float(update.message.text)
            context.user_data['sl'] = sl
            await update.message.reply_text(
                "🔒 **سقف مجاز دارایی فریز شده تومانی** چقدر باشد؟\n(اگر بیشتر از این مبلغ سفارش باز داشته باشید، خرید جدید انجام نمی‌شود)")
            return SET_MAX_FROZEN_TMN
        except ValueError:
            await update.message.reply_text("لطفاً عدد وارد کنید.")
            return SET_STOP_LOSS

    async def set_max_frozen_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = float(update.message.text)
            context.user_data['max_frozen_tmn'] = amount
            await update.message.reply_text("🔒 **سقف مجاز دارایی فریز شده تتری** چقدر باشد؟")
            return SET_MAX_FROZEN_USDT
        except ValueError:
            await update.message.reply_text("لطفاً عدد وارد کنید.")
            return SET_MAX_FROZEN_TMN

    async def set_max_frozen_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            max_usdt = float(update.message.text)
            user_id = update.effective_user.id
            sl = context.user_data['sl']
            max_tmn = context.user_data['max_frozen_tmn']

            conn = self.db.get_connection()
            conn.execute(
                '''UPDATE users SET 
                   stop_loss_percent = ?, max_frozen_tmn = ?, max_frozen_usdt = ? 
                   WHERE telegram_id = ?''',
                (sl, max_tmn, max_usdt, user_id)
            )
            conn.commit()
            conn.close()

            await update.message.reply_text("✅ تنظیمات ریسک بروزرسانی شد.")
            await self.show_menu(update)
            return ConversationHandler.END
        except ValueError:
            await update.message.reply_text("لطفاً عدد وارد کنید.")
            return SET_MAX_FROZEN_USDT

    # --- فعال/غیرفعال سازی و گزارش ---
    async def toggle_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        is_active = 1 if 'فعال' in text else 0
        user_id = update.effective_user.id

        conn = self.db.get_connection()
        conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (is_active, user_id))
        conn.commit()
        conn.close()

        status_msg = "🟢 ربات فعال شد و آماده شکار سیگنال است." if is_active else "🔴 ربات متوقف شد."
        await update.message.reply_text(status_msg)

    async def status_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # اطلاعات کاربر
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        u = cursor.fetchone()

        # آمار معاملات امروز
        cursor.execute(
            "SELECT COUNT(*), SUM(buy_amount) FROM trades WHERE user_id = ? AND date(created_at) = date('now')",
            (u['id'],))
        stats = cursor.fetchone()

        conn.close()

        if u:
            active_icon = "✅" if u['is_active'] else "❌"
            msg = (
                f"📊 **گزارش وضعیت حساب**\n"
                f"--------------------------\n"
                f"وضعیت کلی: {active_icon}\n"
                f"حد ضرر: {u['stop_loss_percent']}%\n"
                f"خرید (TMN): {u['buy_amount_tmn']:,}\n"
                f"خرید (USDT): {u['buy_amount_usdt']}\n"
                f"سقف فریز (TMN): {u['max_frozen_tmn']:,}\n"
                f"--------------------------\n"
                f"تعداد ترید امروز: {stats[0]}\n"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("عملیات لغو شد.",
                                        reply_markup=ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True))
        return ConversationHandler.END

    def run(self):
        # 1. هندلر API
        api_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^🔑'), self.start_api_flow)],
            states={GET_API: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verify_and_save_api)]},
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        # 2. هندلر مبلغ خرید
        capital_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^💰'), self.start_capital_flow)],
            states={
                SET_BUY_TMN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_buy_tmn)],
                SET_BUY_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_buy_usdt)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        # 3. هندلر ریسک
        risk_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex('^🛑'), self.start_risk_flow)],
            states={
                SET_STOP_LOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_stop_loss)],
                SET_MAX_FROZEN_TMN: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_max_frozen_tmn)],
                SET_MAX_FROZEN_USDT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_max_frozen_usdt)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(api_conv)
        self.app.add_handler(capital_conv)
        self.app.add_handler(risk_conv)
        self.app.add_handler(MessageHandler(filters.Regex('فعال‌سازی|توقف'), self.toggle_bot))
        self.app.add_handler(MessageHandler(filters.Regex('^📊'), self.status_report))

        print("🤖 بات تلگرام آماده و در حال اجراست...")
        self.app.run_polling()


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or "YOUR_TOKEN" in TELEGRAM_BOT_TOKEN:
        print("❌ خطا: لطفاً ابتدا توکن ربات را در فایل config.py وارد کنید.")
    else:
        bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
        bot.run()