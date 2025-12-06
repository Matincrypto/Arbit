# telegram_bot.py
import logging
import json
import requests
import os
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
from admin_panel import AdminPanel
from config import TELEGRAM_BOT_TOKEN, WALLEX_BASE_URL, DEFAULT_HEADERS

# تنظیمات لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# مراحل گفتگو
(
    GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_STOP_LOSS, GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(9)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()
        self.admin = AdminPanel()

    # --- توابع کمکی ---
    def get_paginated_keyboard(self, all_items, selected_items, page=0, items_per_page=15, prefix="COIN"):
        keyboard = []
        start = page * items_per_page
        end = start + items_per_page
        current_page_items = all_items[start:end]
        
        row = []
        for item in current_page_items:
            text = f"✅ {item}" if item in selected_items else item
            row.append(InlineKeyboardButton(text, callback_data=f"{prefix}_{item}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"PAGE_PREV"))
        
        total_pages = (len(all_items) + items_per_page - 1) // items_per_page
        nav_row.append(InlineKeyboardButton(f"صفحه {page+1}/{total_pages}", callback_data="NOOP"))
        
        if end < len(all_items):
            nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"PAGE_NEXT"))
            
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("تایید نهایی و ساخت حساب 🏁", callback_data=f"CONFIRM_{prefix}")])
        return InlineKeyboardMarkup(keyboard)

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
    # شروع و منوی اصلی
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
                f"سلام {user.first_name} عزیز! 👋\n\n"
                "به ربات معامله‌گر هوشمند خوش آمدید.\n"
                "برای شروع اتوماتیک‌سازی معاملات، لطفاً ثبت‌نام کنید.\n\n"
                "🔹 **مرحله ۱ از ۹:**\n"
                "لطفاً نام خود را وارد کنید:"
            )
            return GET_NAME

    async def show_main_menu(self, update: Update, user_row):
        target = update.message if update.message else update.callback_query.message
        
        status = "روشن 🟢" if user_row['is_active'] else "خاموش 🔴"
        btn_toggle = "❌ توقف ربات" if user_row['is_active'] else "✅ فعال‌سازی ربات"
        
        keyboard = [
            [btn_toggle],
            ['📊 گزارش حساب', '🗑 حذف حساب'],
            ['➕ ویرایش / شروع مجدد']
        ]

        # اگر ادمین بود، دکمه پنل مدیریت را اضافه کن
        if self.admin.is_admin(user_row['telegram_id']):
            keyboard.append(['🛠 پنل مدیریت (Admin)'])

        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await target.reply_text(
            f"👤 کاربر: **{user_row['full_name']}**\n"
            f"وضعیت ربات: {status}\n\n"
            "چه کاری انجام دهم؟ 👇",
            reply_markup=markup,
            parse_mode='Markdown'
        )

    # -------------------------------------------------------------------------
    # فلو ثبت نام (ویزارد)
    # -------------------------------------------------------------------------
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text
        if len(name) < 3:
            await update.message.reply_text("نام خیلی کوتاه است. لطفاً کامل وارد کنید:")
            return GET_NAME

        context.user_data['full_name'] = name
        btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        
        await update.message.reply_text(
            "✅ نام شما ثبت شد.\n\n"
            "🔹 **مرحله ۲ از ۹:**\n"
            "برای امنیت حساب، لطفاً شماره موبایل خود را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            txt = update.message.text
            if not txt.isdigit() or len(txt) < 10:
                await update.message.reply_text("فرمت شماره صحیح نیست. لطفاً فقط عدد وارد کنید:")
                return GET_PHONE
            context.user_data['phone'] = txt

        await update.message.reply_text(
            "✅ شماره ثبت شد.\n\n"
            "🔹 **مرحله ۳ از ۹ (مدیریت سرمایه):**\n"
            "برای سیگنال‌های تومانی (TMN) چقدر خرید انجام شود؟\n"
            "عدد را به تومان وارد کنید (مثال: 500000):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 50000:
                await update.message.reply_text("حداقل خرید ۵۰,۰۰۰ تومان است. لطفاً اصلاح کنید:")
                return GET_CAPITAL_TMN
            context.user_data['buy_tmn'] = val
            await update.message.reply_text(
                "🔹 **مرحله ۴ از ۹:**\n"
                "برای سیگنال‌های تتری (USDT) چقدر خرید انجام شود؟\n"
                "عدد را به تتر وارد کنید (مثال: 20):"
            )
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 5:
                await update.message.reply_text("حداقل خرید ۵ تتر است. لطفاً اصلاح کنید:")
                return GET_CAPITAL_USDT
            context.user_data['buy_usdt'] = val
            await update.message.reply_text(
                "🔹 **مرحله ۵ از ۹ (مدیریت ریسک):**\n"
                "لطفاً درصد **حد ضرر (Stop Loss)** را وارد کنید.\n"
                "مثال: اگر `2` وارد کنید، با ۲ درصد ضرر ربات می‌فروشد.\n"
                "(عدد 0 یعنی بدون حد ضرر):"
            )
            return GET_STOP_LOSS
        except:
            await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT

    async def get_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['stop_loss'] = val
            await update.message.reply_text(
                "✅ حد ضرر ثبت شد.\n\n"
                "🔹 **مرحله ۶ از ۹ (اتصال صرافی):**\n"
                "لطفاً **API Key** حساب والکس خود را ارسال کنید.\n"
                "_(ما فقط دسترسی ترید نیاز داریم و کلید شما رمزنگاری می‌شود)_"
            )
            return GET_API
        except:
            await update.message.reply_text("لطفاً عدد وارد کنید:")
            return GET_STOP_LOSS

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ در حال اعتبارسنجی کلید با والکس...")
        
        try:
            url = f"{WALLEX_BASE_URL}/v1/account/balances"
            headers = DEFAULT_HEADERS.copy()
            headers["X-API-Key"] = api_key
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ کلید API معتبر است.")
                
                context.user_data['strategies'] = []
                markup = self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], [], "STRAT")
                await update.message.reply_text(
                    "🔹 **مرحله ۷ از ۹:**\n"
                    "استراتژی‌های مورد نظر را انتخاب کنید:",
                    reply_markup=markup
                )
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ کلید نامعتبر است (خطای 401). لطفاً کلید صحیح را بفرستید:")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"❌ خطای شبکه: {e}")
            return GET_API

    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('strategies', [])

        if data == "CONFIRM_STRAT":
            if not curr:
                await query.answer("حداقل یک استراتژی انتخاب کنید!", show_alert=True)
                return GET_STRATEGIES
            
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text("🔹 **مرحله ۸ از ۹:**\nکیفیت (گرید) سیگنال‌ها را انتخاب کنید:", reply_markup=markup)
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
                await query.answer("حداقل یک گرید انتخاب کنید!", show_alert=True)
                return GET_GRADES
            
            await query.message.edit_text("⏳ در حال دریافت لیست ارزها از والکس...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            
            context.user_data['all_available_coins'] = all_coins
            context.user_data['coins'] = [] 
            context.user_data['page'] = 0   
            
            markup = self.get_paginated_keyboard(all_coins, [], page=0)
            await query.message.reply_text(
                "🔹 **مرحله ۹ از ۹ (آخر):**\n"
                "ارزهایی که می‌خواهید معامله شوند را تیک بزنید (صفحه‌بندی شده):",
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

    async def get_coins_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        try: await query.answer()
        except: pass
        
        data = query.data
        selected_coins = context.user_data.get('coins', [])
        all_coins = context.user_data.get('all_available_coins', [])
        current_page = context.user_data.get('page', 0)

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
            return GET_COINS

        elif data == "CONFIRM_COIN":
            if not selected_coins:
                await query.answer("حداقل یک ارز انتخاب کنید!", show_alert=True)
                return GET_COINS
            
            await query.message.edit_text("✅ تنظیمات نهایی شد. در حال ذخیره...")
            
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
                conn.execute("DELETE FROM users WHERE telegram_id = ?", (user_id,))
                conn.execute('''
                    INSERT INTO users (
                        telegram_id, full_name, phone_number, wallex_api_key,
                        buy_amount_tmn, buy_amount_usdt, stop_loss_percent,
                        allowed_strategies, allowed_grades, allowed_coins, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (
                    user_id, d['full_name'], d['phone'], d['api_key'],
                    d['buy_tmn'], d['buy_usdt'], d['stop_loss'],
                    json.dumps(d['strategies']), json.dumps(d['grades']), json.dumps(selected_coins)
                ))
                conn.commit()
                await query.message.reply_text("🎉 تبریک! حساب شما ساخته شد.\nاکنون می‌توانید ربات را فعال کنید.")
                
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
            
        elif data.startswith("COIN_"):
            coin_symbol = data.split("_")[1]
            if coin_symbol in selected_coins:
                selected_coins.remove(coin_symbol)
            else:
                selected_coins.append(coin_symbol)
            
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS

    # -------------------------------------------------------------------------
    # هندلرهای منو و ادمین
    # -------------------------------------------------------------------------
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
            msg = "🚀 ربات فعال شد و آماده ترید است." if new_s else "💤 ربات متوقف شد."
            await update.message.reply_text(msg)
            await self.show_main_menu(update, u)
            
        elif "حذف حساب" in text:
            kb = [[InlineKeyboardButton("بله حذف شود", callback_data="DEL_YES"), InlineKeyboardButton("لغو", callback_data="DEL_NO")]]
            await update.message.reply_text("⚠️ آیا مطمئن هستید؟ تمام اطلاعات پاک می‌شود.", reply_markup=InlineKeyboardMarkup(kb))
            
        elif "ویرایش" in text:
            await update.message.reply_text("🔄 بازگشت به تنظیمات اولیه...")
            return await self.get_name(update, context)
            
        elif "گزارش" in text:
            conn = self.db.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE telegram_id = ?", (uid,))
            u = cur.fetchone()
            conn.close()
            if u:
                try: coins = json.loads(u['allowed_coins'])
                except: coins = []
                
                # نمایش زیبا و خلاصه ارزها
                if len(coins) > 10:
                    coins_str = f"{', '.join(coins[:10])} و {len(coins)-10} ارز دیگر..."
                else:
                    coins_str = ", ".join(coins)

                msg = (
                    f"📊 **گزارش وضعیت حساب:**\n\n"
                    f"👤 **نام:** {u['full_name']}\n"
                    f"📱 **موبایل:** {u['phone_number']}\n"
                    f"------------------------------\n"
                    f"💰 **خرید تومانی:** {u['buy_amount_tmn']:,} T\n"
                    f"💰 **خرید تتری:** {u['buy_amount_usdt']} $\n"
                    f"🛑 **حد ضرر:** {u['stop_loss_percent']}%\n"
                    f"------------------------------\n"
                    f"🪙 **ارزهای مجاز:**\n{coins_str}"
                )
                await update.message.reply_text(msg, parse_mode='Markdown')

        elif "پنل مدیریت" in text or "/admin" in text:
            await self.admin_panel(update, context)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.admin.is_admin(user_id):
            return 

        stats_msg = self.admin.get_quick_stats()
        keyboard = [[InlineKeyboardButton("📥 دانلود فایل اکسل کامل", callback_data="ADMIN_DOWNLOAD_EXCEL")]]
        
        # اگر از دکمه منو آمده باشد message دارد، اگر نه کامند است
        if update.message:
            await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        
        if not self.admin.is_admin(user_id):
            return

        if query.data == "ADMIN_DOWNLOAD_EXCEL":
            await query.answer("⏳ در حال تولید فایل اکسل...")
            filename = self.admin.generate_excel_report()
            if filename:
                await query.message.reply_document(
                    document=open(filename, 'rb'),
                    caption="📂 گزارش کامل سیستم",
                    filename=filename
                )
                self.admin.clean_up_file(filename)
            else:
                await query.message.reply_text("❌ خطا در ساخت فایل اکسل.")

    async def confirm_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == "DEL_YES":
            conn = self.db.get_connection()
            conn.execute("DELETE FROM users WHERE telegram_id = ?", (update.effective_user.id,))
            conn.commit()
            conn.close()
            await q.message.edit_text("🗑 حساب حذف شد. برای شروع مجدد /start بزنید.")
        else:
            await q.message.edit_text("عملیات لغو شد.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ لغو شد.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.start), MessageHandler(filters.Regex('ویرایش'), self.start)],
            states={
                GET_NAME: [MessageHandler(filters.TEXT, self.get_name)],
                GET_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, self.get_phone)],
                GET_CAPITAL_TMN: [MessageHandler(filters.TEXT, self.get_capital_tmn)],
                GET_CAPITAL_USDT: [MessageHandler(filters.TEXT, self.get_capital_usdt)],
                GET_STOP_LOSS: [MessageHandler(filters.TEXT, self.get_stop_loss)],
                GET_API: [MessageHandler(filters.TEXT, self.get_api)],
                GET_STRATEGIES: [CallbackQueryHandler(self.get_strategies_step)],
                GET_GRADES: [CallbackQueryHandler(self.get_grades_step)],
                GET_COINS: [CallbackQueryHandler(self.get_coins_step)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )
        self.app.add_handler(conv)
        self.app.add_handler(CallbackQueryHandler(self.confirm_delete, pattern="^DEL_"))
        
        # هندلر ادمین (هم کامند هم دکمه شیشه‌ای)
        self.app.add_handler(CommandHandler("admin", self.admin_panel))
        self.app.add_handler(CallbackQueryHandler(self.admin_actions, pattern="^ADMIN_"))
        
        self.app.add_handler(MessageHandler(filters.TEXT, self.menu_handler))
        print("🤖 Final Bot Running...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
