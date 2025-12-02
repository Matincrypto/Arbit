# telegram_bot.py
import logging
import json
import requests
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
from wallex_client import WallexClient
from config import TELEGRAM_BOT_TOKEN, WALLEX_BASE_URL, DEFAULT_HEADERS

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# مراحل گفتگو
(
    GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(8)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()

    # --- توابع سازنده کیبورد ---
    def get_simple_keyboard(self, options, selected_list, prefix):
        keyboard = []
        row = []
        for opt in options:
            text = f"✅ {opt}" if opt in selected_list else opt
            row.append(InlineKeyboardButton(text, callback_data=f"{prefix}_{opt}"))
            if len(row) == 2: # دو ستونه
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        # دکمه تایید
        confirm_text = "تایید و ادامه ➡️" if prefix != "COIN" else "پایان و ساخت حساب 🏁"
        callback = f"CONFIRM_{prefix}"
        keyboard.append([InlineKeyboardButton(confirm_text, callback_data=callback)])
        return InlineKeyboardMarkup(keyboard)

    # --- شروع ---
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
                "برای ساخت حساب جدید، لطفاً **نام** خود را وارد کنید:"
            )
            return GET_NAME

    # --- فلو ثبت نام ---
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        contact_btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        await update.message.reply_text(
            "✅ نام ثبت شد. لطفاً **شماره موبایل** خود را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([[contact_btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            text = update.message.text
            if not text.isdigit() or len(text) < 10:
                await update.message.reply_text("❌ فرمت شماره غلط است. لطفاً فقط عدد وارد کنید:")
                return GET_PHONE
            context.user_data['phone'] = text

        await update.message.reply_text(
            "💰 مبلغ خرید **تومانی** (مثال: 500000):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['buy_tmn'] = val
            await update.message.reply_text("💰 مبلغ خرید **تتری** (مثال: 20):")
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("❌ فقط عدد وارد کنید:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data['buy_usdt'] = float(update.message.text)
            await update.message.reply_text("🔑 لطفاً **API Key** والکس را ارسال کنید:")
            return GET_API
        except:
            await update.message.reply_text("❌ فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ اعتبارسنجی...")
        
        url = f"{WALLEX_BASE_URL}/v1/account/balances"
        headers = DEFAULT_HEADERS.copy()
        headers["X-API-Key"] = api_key
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید تایید شد.")
                
                # مرحله استراتژی
                context.user_data['strategies'] = []
                markup = self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], [], "STRAT")
                await update.message.reply_text("🎯 استراتژی‌ها را انتخاب کنید:", reply_markup=markup)
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ کلید نامعتبر است.")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}")
            return GET_API

    # --- هندلر استراتژی ---
    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('strategies', [])

        if data == "CONFIRM_STRAT":
            if not current: return GET_STRATEGIES
            
            # مرحله گرید
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text("💎 گریدها را انتخاب کنید:", reply_markup=markup)
            return GET_GRADES
            
        elif data.startswith("STRAT_"):
            val = data.split("_")[1]
            if val in current: current.remove(val)
            else: current.append(val)
            context.user_data['strategies'] = current
            await query.edit_message_reply_markup(self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], current, "STRAT"))
            return GET_STRATEGIES

    # --- هندلر گرید ---
    async def get_grades_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('grades', [])

        if data == "CONFIRM_GRADE":
            if not current: return GET_GRADES
            
            # دریافت لیست ارزها از والکس
            await query.message.edit_text("⏳ در حال دریافت لیست ارزها از والکس...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            
            # برای جلوگیری از شلوغی، فقط 20 تای اول محبوب یا همه را لود میکنیم
            # اینجا 30 تای اول را میگیریم
            display_coins = all_coins[:30] if all_coins else ['BTC', 'ETH', 'USDT', 'SHIB', 'DOGE']
            context.user_data['available_coins_list'] = display_coins # ذخیره برای استفاده در کیبورد
            
            context.user_data['coins'] = []
            markup = self.get_simple_keyboard(display_coins, [], "COIN")
            
            await query.message.reply_text(
                "🪙 **انتخاب ارزها:**\n"
                "کدام ارزها را معامله کنیم؟ (لیست از مارکت والکس گرفته شده)", 
                reply_markup=markup
            )
            return GET_COINS
            
        elif data.startswith("GRADE_"):
            val = data.split("_")[1]
            if val in current: current.remove(val)
            else: current.append(val)
            context.user_data['grades'] = current
            await query.edit_message_reply_markup(self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], current, "GRADE"))
            return GET_GRADES

    # --- هندلر انتخاب کوین ---
    async def get_coins_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        current = context.user_data.get('coins', [])
        display_coins = context.user_data.get('available_coins_list', [])

        if data == "CONFIRM_COIN":
            if not current:
                await query.answer("حداقل یک ارز انتخاب کنید!", show_alert=True)
                return GET_COINS
            
            # ذخیره نهایی
            await query.message.edit_text("✅ در حال ساخت حساب...")
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
                # حذف احتمالی حساب قبلی (برای حالت ویرایش)
                conn.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))
                
                conn.execute('''
                    INSERT INTO users (
                        telegram_id, full_name, phone_number, wallex_api_key,
                        buy_amount_tmn, buy_amount_usdt,
                        allowed_strategies, allowed_grades, allowed_coins, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (
                    user_id, d['full_name'], d['phone'], d['api_key'],
                    d['buy_tmn'], d['buy_usdt'],
                    json.dumps(d['strategies']), json.dumps(d['grades']), json.dumps(current)
                ))
                conn.commit()
                
                await query.message.reply_text("🎉 حساب شما ساخته و بروزرسانی شد.")
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
                
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطا در دیتابیس.")
            finally:
                conn.close()
            return ConversationHandler.END
            
        elif data.startswith("COIN_"):
            val = data.split("_")[1]
            if val in current: current.remove(val)
            else: current.append(val)
            context.user_data['coins'] = current
            await query.edit_message_reply_markup(self.get_simple_keyboard(display_coins, current, "COIN"))
            return GET_COINS

    # --- مدیریت منوی اصلی ---
    async def show_main_menu(self, update: Update, user_row):
        target = update.message if update.message else update.callback_query.message
        
        status = "🟢 روشن" if user_row['is_active'] else "🔴 خاموش"
        toggle_btn = "❌ توقف ربات" if user_row['is_active'] else "✅ فعال‌سازی ربات"
        
        keyboard = [
            [toggle_btn],
            ['📊 گزارش', '🗑 حذف حساب'],
            ['➕ ویرایش / ساخت مجدد']
        ]
        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await target.reply_text(
            f"👤 {user_row['full_name']}\nوضعیت: {status}",
            reply_markup=markup
        )

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        user_id = update.effective_user.id
        
        if "فعال‌سازی" in text or "توقف" in text:
            status = 1 if "فعال‌سازی" in text else 0
            conn = self.db.get_connection()
            conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (status, user_id))
            conn.commit()
            
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
            u = cursor.fetchone()
            conn.close()
            
            await update.message.reply_text("✅ انجام شد.")
            await self.show_main_menu(update, u)
            
        elif "حذف حساب" in text:
            # تاییدیه حذف
            keyboard = [[InlineKeyboardButton("بله، حذف کن 🗑", callback_data="DELETE_YES"), 
                         InlineKeyboardButton("خیر", callback_data="DELETE_NO")]]
            await update.message.reply_text("⚠️ آیا مطمئن هستید؟ تمام تنظیمات شما پاک می‌شود.", 
                                            reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif "ویرایش" in text:
            await update.message.reply_text("🔄 شروع فرآیند ثبت نام مجدد...")
            return await self.get_name(update, context) # پرش به مرحله اول ویزارد
            
        elif "گزارش" in text:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
            u = cursor.fetchone()
            conn.close()
            if u:
                coins = ", ".join(json.loads(u['allowed_coins']))
                msg = f"👤 {u['full_name']}\n💎 ارزهای مجاز:\n{coins}"
                await update.message.reply_text(msg)

    async def delete_account_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if query.data == "DELETE_YES":
            conn = self.db.get_connection()
            conn.execute("DELETE FROM users WHERE telegram_id = ?", (update.effective_user.id,))
            conn.commit()
            conn.close()
            await query.message.edit_text("🗑 حساب شما با موفقیت حذف شد. برای شروع مجدد /start بزنید.")
        else:
            await query.message.edit_text("❌ عملیات لغو شد.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    def run(self):
        # تعریف هندلر مکالمه
        reg_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start), 
                          MessageHandler(filters.Regex('ویرایش'), self.start)], # ویرایش هم استارت را صدا می‌زند
            states={
                GET_NAME: [MessageHandler(filters.TEXT, self.get_name)],
                GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, self.get_phone)],
                GET_CAPITAL_TMN: [MessageHandler(filters.TEXT, self.get_capital_tmn)],
                GET_CAPITAL_USDT: [MessageHandler(filters.TEXT, self.get_capital_usdt)],
                GET_API: [MessageHandler(filters.TEXT, self.get_api)],
                GET_STRATEGIES: [CallbackQueryHandler(self.get_strategies_step)],
                GET_GRADES: [CallbackQueryHandler(self.get_grades_step)],
                GET_COINS: [CallbackQueryHandler(self.get_coins_step)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.app.add_handler(reg_handler)
        self.app.add_handler(CallbackQueryHandler(self.delete_account_confirm, pattern="^DELETE_"))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.menu_handler))
        
        print("🤖 Bot with Delete/Add & Coin Filter Started...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
