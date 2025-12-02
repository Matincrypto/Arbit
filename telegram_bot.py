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

(
    GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(8)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()

    # --- تابع جدید برای ساخت کیبورد صفحه‌بندی شده ---
    def get_paginated_keyboard(self, all_items, selected_items, page=0, items_per_page=15, prefix="COIN"):
        keyboard = []
        
        # محاسبه آیتم‌های این صفحه
        start = page * items_per_page
        end = start + items_per_page
        current_page_items = all_items[start:end]
        
        # ساخت دکمه‌های ارزها (3 تایی در هر ردیف)
        row = []
        for item in current_page_items:
            text = f"✅ {item}" if item in selected_items else item
            row.append(InlineKeyboardButton(text, callback_data=f"{prefix}_{item}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        # دکمه‌های نویگیشن (بعدی/قبلی)
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"PAGE_PREV"))
        
        # نمایش شماره صفحه
        total_pages = (len(all_items) + items_per_page - 1) // items_per_page
        nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="NOOP"))
        
        if end < len(all_items):
            nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"PAGE_NEXT"))
            
        keyboard.append(nav_row)
        
        # دکمه پایان
        keyboard.append([InlineKeyboardButton("تایید نهایی و ساخت حساب 🏁", callback_data=f"CONFIRM_{prefix}")])
        
        return InlineKeyboardMarkup(keyboard)

    # --- کیبورد ساده برای استراتژی و گرید ---
    def get_simple_keyboard(self, options, selected_list, prefix):
        keyboard = []
        row = []
        for opt in options:
            text = f"✅ {opt}" if opt in selected_list else opt
            row.append(InlineKeyboardButton(text, callback_data=f"{prefix}_{opt}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("تایید و ادامه ➡️", callback_data=f"CONFIRM_{prefix}")])
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------------------
    # بخش شروع و ویزارد ثبت نام
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
                f"سلام {user.first_name} خوش آمدید! 👋\n\n"
                "برای استفاده از ربات معامله‌گر، نیاز به ساخت حساب کاربری دارید.\n"
                "مرحله 1 از 8:\n"
                "لطفاً نام خود را وارد کنید:"
            )
            return GET_NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        await update.message.reply_text(
            "مرحله 2 از 8:\nشماره موبایل خود را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            txt = update.message.text
            if not txt.isdigit() or len(txt) < 10:
                await update.message.reply_text("فرمت نامعتبر. لطفاً فقط عدد وارد کنید:")
                return GET_PHONE
            context.user_data['phone'] = txt

        await update.message.reply_text("مرحله 3 از 8:\nمبلغ خرید تومانی (مثال: 500000):", reply_markup=ReplyKeyboardRemove())
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 50000:
                await update.message.reply_text("حداقل مبلغ ۵۰,۰۰۰ تومان است. مجدد وارد کنید:")
                return GET_CAPITAL_TMN
            context.user_data['buy_tmn'] = val
            await update.message.reply_text("مرحله 4 از 8:\nمبلغ خرید تتری (مثال: 20):")
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 5:
                await update.message.reply_text("حداقل مبلغ ۵ تتر است. مجدد وارد کنید:")
                return GET_CAPITAL_USDT
            context.user_data['buy_usdt'] = val
            await update.message.reply_text("مرحله 5 از 8:\nلطفاً API Key والکس را ارسال کنید:")
            return GET_API
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ در حال اعتبارسنجی...")
        
        try:
            url = f"{WALLEX_BASE_URL}/v1/account/balances"
            headers = DEFAULT_HEADERS.copy()
            headers["X-API-Key"] = api_key
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید تایید شد.")
                
                context.user_data['strategies'] = []
                markup = self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], [], "STRAT")
                await update.message.reply_text("مرحله 6 از 8:\nاستراتژی‌ها را انتخاب کنید:", reply_markup=markup)
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ کلید نامعتبر است. مجدد تلاش کنید:")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"خطای شبکه: {e}")
            return GET_API

    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('strategies', [])

        if data == "CONFIRM_STRAT":
            if not curr:
                await query.answer("حداقل یک مورد انتخاب کنید!", show_alert=True)
                return GET_STRATEGIES
            
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text("مرحله 7 از 8:\nگریدها را انتخاب کنید:", reply_markup=markup)
            return GET_GRADES
        
        elif data.startswith("STRAT_"):
            val = data.split("_")[1]
            if val in curr: curr.remove(val)
            else: curr.append(val)
            context.user_data['strategies'] = curr
            await query.edit_message_reply_markup(self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], curr, "STRAT"))
            return GET_STRATEGIES

    async def get_grades_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('grades', [])

        if data == "CONFIRM_GRADE":
            if not curr:
                await query.answer("حداقل یک مورد انتخاب کنید!", show_alert=True)
                return GET_GRADES
            
            # دریافت لیست کامل ارزها برای صفحه‌بندی
            await query.message.edit_text("⏳ در حال دریافت لیست کامل ارزها از والکس...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            
            # ذخیره لیست کل در context
            context.user_data['all_available_coins'] = all_coins
            context.user_data['coins'] = [] # لیست انتخاب شده‌های کاربر
            context.user_data['page'] = 0   # صفحه فعلی
            
            markup = self.get_paginated_keyboard(all_coins, [], page=0)
            
            await query.message.reply_text(
                "مرحله 8 از 8 (انتخاب ارزها):\n"
                "ارزهایی که می‌خواهید معامله شوند را تیک بزنید.\n"
                "از دکمه‌های «بعدی» و «قبلی» برای دیدن بقیه ارزها استفاده کنید.",
                reply_markup=markup
            )
            return GET_COINS
            
        elif data.startswith("GRADE_"):
            val = data.split("_")[1]
            if val in curr: curr.remove(val)
            else: curr.append(val)
            context.user_data['grades'] = curr
            await query.edit_message_reply_markup(self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], curr, "GRADE"))
            return GET_GRADES

    # --- هندلر انتخاب کوین (با صفحه‌بندی) ---
    async def get_coins_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        # هندل کردن دکمه‌های صفحه بندی که فقط دکمه را میزنند و نباید لودینگ بماند
        try: await query.answer()
        except: pass
        
        data = query.data
        
        selected_coins = context.user_data.get('coins', [])
        all_coins = context.user_data.get('all_available_coins', [])
        current_page = context.user_data.get('page', 0)

        # 1. تغییر صفحه
        if data == "PAGE_NEXT":
            current_page += 1
            context.user_data['page'] = current_page
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS
            
        elif data == "PAGE_PREV":
            current_page -= 1
            context.user_data['page'] = current_page
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS
            
        elif data == "NOOP":
            # دکمه شماره صفحه که کاری نمیکند
            return GET_COINS

        # 2. پایان انتخاب
        elif data == "CONFIRM_COIN":
            if not selected_coins:
                await query.answer("لطفاً حداقل یک ارز انتخاب کنید!", show_alert=True)
                return GET_COINS
            
            await query.message.edit_text("✅ در حال ساخت حساب...")
            
            # ذخیره نهایی
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
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
                    json.dumps(d['strategies']), json.dumps(d['grades']), json.dumps(selected_coins)
                ))
                conn.commit()
                await query.message.reply_text("🎉 حساب شما با موفقیت ساخته شد.")
                
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
                
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطا در ذخیره دیتابیس.")
            finally:
                conn.close()
            return ConversationHandler.END

        # 3. انتخاب/حذف ارز
        elif data.startswith("COIN_"):
            coin_symbol = data.split("_")[1]
            if coin_symbol in selected_coins:
                selected_coins.remove(coin_symbol)
            else:
                selected_coins.append(coin_symbol)
            
            context.user_data['coins'] = selected_coins
            # بازسازی صفحه فعلی با تیک‌های جدید
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS

    # --- منوی اصلی ---
    async def show_main_menu(self, update: Update, user_row):
        target = update.message if update.message else update.callback_query.message
        status = "روشن 🟢" if user_row['is_active'] else "خاموش 🔴"
        btn = "❌ توقف ربات" if user_row['is_active'] else "✅ فعال‌سازی ربات"
        
        kb = [[btn], ['📊 گزارش', '🗑 حذف حساب'], ['➕ ویرایش']]
        await target.reply_text(
            f"کاربر: {user_row['full_name']}\nوضعیت: {status}\nگزینه مورد نظر را انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        uid = update.effective_user.id
        
        if "فعال‌سازی" in text or "توقف" in text:
            new_s = 1 if "فعال‌سازی" in text else 0
            conn = self.db.get_connection()
            conn.execute("UPDATE users SET is_active = ? WHERE telegram_id = ?", (new_s, uid))
            conn.commit()
            
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (uid,))
            u = cursor.fetchone()
            conn.close()
            await update.message.reply_text(f"وضعیت تغییر کرد: {'فعال' if new_s else 'غیرفعال'}")
            await self.show_main_menu(update, u)
            
        elif "حذف حساب" in text:
            kb = [[InlineKeyboardButton("بله حذف شود", callback_data="DEL_YES"), InlineKeyboardButton("خیر", callback_data="DEL_NO")]]
            await update.message.reply_text("آیا مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(kb))
            
        elif "ویرایش" in text:
            await update.message.reply_text("شروع ویرایش...")
            return await self.get_name(update, context)
            
        elif "گزارش" in text:
            conn = self.db.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE telegram_id = ?", (uid,))
            u = cur.fetchone()
            conn.close()
            if u:
                try: coins = ", ".join(json.loads(u['allowed_coins']))
                except: coins = "همه"
                msg = f"نام: {u['full_name']}\nموبایل: {u['phone_number']}\nارزها: {coins}"
                await update.message.reply_text(msg)

    async def confirm_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == "DEL_YES":
            conn = self.db.get_connection()
            conn.execute("DELETE FROM users WHERE telegram_id = ?", (update.effective_user.id,))
            conn.commit()
            conn.close()
            await q.message.edit_text("حساب حذف شد. /start")
        else:
            await q.message.edit_text("لغو شد.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("لغو شد.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.start), MessageHandler(filters.Regex('ویرایش'), self.start)],
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
        self.app.add_handler(conv)
        self.app.add_handler(CallbackQueryHandler(self.confirm_delete, pattern="^DEL_"))
        self.app.add_handler(MessageHandler(filters.TEXT, self.menu_handler))
        print("Bot Running...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
