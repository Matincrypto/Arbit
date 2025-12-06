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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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
        
        keyboard.append([
            InlineKeyboardButton("✅ انتخاب همه", callback_data="ALL_SELECT"),
            InlineKeyboardButton("❌ حذف همه", callback_data="ALL_DESELECT")
        ])

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
        nav_row.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="NOOP"))
        
        if end < len(all_items):
            nav_row.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"PAGE_NEXT"))
            
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("💾 تایید نهایی و ساخت حساب", callback_data=f"CONFIRM_{prefix}")])
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
    # شروع و ورود
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

    async def restart_wizard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🔄 **ساخت حساب جدید / ویرایش اطلاعات**\n\n"
            "🔹 **مرحله ۱ از ۹:**\n"
            "لطفاً نام خود را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_NAME

    # -------------------------------------------------------------------------
    # بخش مدیریت حساب‌ها (ویژگی جدید)
    # -------------------------------------------------------------------------
    async def manage_accounts_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # دریافت تمام حساب‌های این تلگرام (فعلاً یکی است اما ساختار آماده چندتایی است)
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        users = cursor.fetchall()
        conn.close()

        if not users:
            await update.message.reply_text("❌ شما هیچ حسابی ندارید. لطفاً ابتدا ثبت نام کنید.")
            return

        for user in users:
            status_icon = "🟢 فعال" if user['is_active'] else "🔴 غیرفعال"
            
            # دکمه‌های کنترل برای هر حساب
            toggle_text = "⛔️ توقف" if user['is_active'] else "✅ فعال‌سازی"
            toggle_data = f"ACC_TOGGLE_{user['id']}"
            delete_data = f"ACC_DELETE_{user['id']}"
            
            keyboard = [
                [InlineKeyboardButton(toggle_text, callback_data=toggle_data),
                 InlineKeyboardButton("🗑 حذف حساب", callback_data=delete_data)]
            ]
            
            msg = (
                f"🆔 **شناسه حساب:** `{user['id']}`\n"
                f"👤 **نام:** {user['full_name']}\n"
                f"📱 **موبایل:** {user['phone_number']}\n"
                f"📡 **وضعیت:** {status_icon}\n"
                f"💰 **سرمایه:** {user['buy_amount_tmn']:,} T | {user['buy_amount_usdt']} $\n"
                f"🛑 **حد ضرر:** {user['stop_loss_percent']}%\n"
                "------------------------------"
            )
            
            # ارسال پیام (اگر آپدیت از دکمه باشد یا پیام متنی)
            if update.message:
                await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            else:
                await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def account_action_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        # فرمت دیتا: ACC_ACTION_ID
        parts = data.split("_")
        action = parts[1] # TOGGLE or DELETE
        account_id = parts[2]
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        if action == "TOGGLE":
            # دریافت وضعیت فعلی
            cursor.execute("SELECT is_active FROM users WHERE id = ?", (account_id,))
            current_status = cursor.fetchone()[0]
            new_status = 0 if current_status else 1
            
            # آپدیت وضعیت
            cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, account_id,))
            conn.commit()
            
            new_text = "🟢 فعال" if new_status else "🔴 غیرفعال"
            await query.message.edit_text(f"✅ وضعیت حساب تغییر کرد به: **{new_text}**\n(برای مشاهده تغییرات مجدد گزینه مدیریت حساب را بزنید)", parse_mode='Markdown')
            
        elif action == "DELETE":
            # پرسش اطمینان (با یک دکمه تایید نهایی)
            keyboard = [[
                InlineKeyboardButton("بله، مطمئنم 🗑", callback_data=f"ACC_CONFIRM_{account_id}"),
                InlineKeyboardButton("لغو", callback_data="ACC_CANCEL")
            ]]
            await query.message.edit_text("⚠️ آیا مطمئن هستید که می‌خواهید این حساب را حذف کنید؟", reply_markup=InlineKeyboardMarkup(keyboard))

        elif action == "CONFIRM":
            cursor.execute("DELETE FROM users WHERE id = ?", (account_id,))
            conn.commit()
            await query.message.edit_text("🗑 حساب با موفقیت حذف شد.")
            
        elif action == "CANCEL":
            await query.message.edit_text("عملیات لغو شد.")
            
        conn.close()

    # -------------------------------------------------------------------------
    # فلو ثبت نام (ویزارد) - بدون تغییر نسبت به قبل
    # -------------------------------------------------------------------------
    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        name = update.message.text
        if len(name) < 3:
            await update.message.reply_text("نام کوتاه است. لطفاً کامل بنویسید:")
            return GET_NAME
        context.user_data['full_name'] = name
        btn = KeyboardButton("📱 ارسال شماره موبایل", request_contact=True)
        await update.message.reply_text("✅ نام ثبت شد.\n\n🔹 **مرحله ۲ از ۹:**\nشماره موبایل:", reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True))
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            txt = update.message.text
            if not txt.isdigit() or len(txt) < 10:
                await update.message.reply_text("فرمت نامعتبر. عدد وارد کنید:")
                return GET_PHONE
            context.user_data['phone'] = txt
        await update.message.reply_text("✅ ثبت شد.\n\n🔹 **مرحله ۳ از ۹:**\nمبلغ خرید **تومانی** (مثال: 500000):", reply_markup=ReplyKeyboardRemove())
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 50000:
                await update.message.reply_text("حداقل ۵۰,۰۰۰ تومان. اصلاح کنید:")
                return GET_CAPITAL_TMN
            context.user_data['buy_tmn'] = val
            await update.message.reply_text("🔹 **مرحله ۴ از ۹:**\nمبلغ خرید **تتری** (مثال: 20):")
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            if val < 5:
                await update.message.reply_text("حداقل ۵ تتر. اصلاح کنید:")
                return GET_CAPITAL_USDT
            context.user_data['buy_usdt'] = val
            await update.message.reply_text("🔹 **مرحله ۵ از ۹:**\nدرصد **حد ضرر** (مثال: 2):")
            return GET_STOP_LOSS
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT

    async def get_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['stop_loss'] = val
            await update.message.reply_text("🔹 **مرحله ۶ از ۹:**\nلطفاً **API Key** والکس را ارسال کنید:")
            return GET_API
        except:
            await update.message.reply_text("لطفاً عدد وارد کنید:")
            return GET_STOP_LOSS

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ بررسی اعتبار کلید...")
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
                await update.message.reply_text("🔹 **مرحله ۷ از ۹:**\nاستراتژی‌ها:", reply_markup=markup)
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ کلید نامعتبر. مجدد ارسال کنید:")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"خطا: {e}")
            return GET_API

    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('strategies', [])
        if data == "CONFIRM_STRAT":
            if not curr:
                await query.answer("حداقل یک مورد!", show_alert=True)
                return GET_STRATEGIES
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("✅ استراتژی‌ها ثبت شد.")
            await query.message.reply_text("🔹 **مرحله ۸ از ۹:**\nکیفیت سیگنال (گرید):", reply_markup=markup)
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
                await query.answer("حداقل یک مورد!", show_alert=True)
                return GET_GRADES
            await query.message.edit_text("⏳ دریافت لیست ارزها...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            context.user_data['all_available_coins'] = all_coins
            context.user_data['coins'] = [] 
            context.user_data['page'] = 0   
            markup = self.get_paginated_keyboard(all_coins, [], page=0)
            await query.message.reply_text("🔹 **مرحله ۹ از ۹ (آخر):**\nانتخاب ارزها:", reply_markup=markup)
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

        if data == "ALL_SELECT":
            selected_coins = list(all_coins)
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            await query.answer("✅ همه انتخاب شدند.", show_alert=False)
            return GET_COINS
        elif data == "ALL_DESELECT":
            selected_coins = []
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            await query.answer("❌ همه حذف شدند.", show_alert=False)
            return GET_COINS
        elif data == "PAGE_NEXT":
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
        elif data == "NOOP": return GET_COINS
        elif data == "CONFIRM_COIN":
            if not selected_coins:
                await query.answer("حداقل یک مورد!", show_alert=True)
                return GET_COINS
            await query.message.edit_text("✅ در حال ذخیره...")
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
                await query.message.reply_text("🎉 حساب ساخته شد.")
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
                new_user = cursor.fetchone()
                await self.show_main_menu(update, new_user)
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطا در دیتابیس.")
            finally: conn.close()
            return ConversationHandler.END
        elif data.startswith("COIN_"):
            coin_symbol = data.split("_")[1]
            if coin_symbol in selected_coins: selected_coins.remove(coin_symbol)
            else: selected_coins.append(coin_symbol)
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS

    # -------------------------------------------------------------------------
    # منوی اصلی و هندلرها
    # -------------------------------------------------------------------------
    async def show_main_menu(self, update: Update, user_row):
        target = update.message if update.message else update.callback_query.message
        
        # متن وضعیت کلی (اگر حداقل یک حساب فعال باشد، سیستم روشن است)
        status = "آماده به کار 🟢"
        
        keyboard = [
            ['💼 مدیریت حساب‌ها', '📊 گزارش'],
            ['➕ افزودن حساب جدید / شروع مجدد']
        ]

        if self.admin.is_admin(user_row['telegram_id']):
            keyboard.append(['🛠 پنل مدیریت (Admin)'])

        markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await target.reply_text(
            f"👤 کاربر: **{user_row['full_name']}**\n"
            f"وضعیت کلی: {status}\n\n"
            "از منوی زیر انتخاب کنید:",
            reply_markup=markup,
            parse_mode='Markdown'
        )

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        uid = update.effective_user.id
        
        if "مدیریت حساب" in text:
            await self.manage_accounts_list(update, context)
            
        elif "افزودن حساب" in text or "شروع مجدد" in text:
            await self.restart_wizard(update, context)
            
        elif "گزارش" in text:
            # نمایش گزارش کلی
            conn = self.db.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE telegram_id = ?", (uid,))
            u = cur.fetchone()
            conn.close()
            if u:
                try: coins = json.loads(u['allowed_coins'])
                except: coins = []
                c_len = len(coins)
                coins_str = f"({c_len} ارز)" if c_len > 20 else ", ".join(coins)
                msg = (f"📊 **گزارش:**\n👤 {u['full_name']}\n💰 {u['buy_amount_tmn']:,} T | {u['buy_amount_usdt']} $\n🪙 ارزها: {coins_str}")
                await update.message.reply_text(msg, parse_mode='Markdown')

        elif "پنل مدیریت" in text or "/admin" in text:
            await self.admin_panel(update, context)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self.admin.is_admin(user_id): return 
        stats_msg = self.admin.get_quick_stats()
        keyboard = [[InlineKeyboardButton("📥 دانلود اکسل", callback_data="ADMIN_DOWNLOAD_EXCEL")]]
        if update.message: await update.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else: await update.callback_query.message.reply_text(stats_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        if not self.admin.is_admin(user_id): return
        if query.data == "ADMIN_DOWNLOAD_EXCEL":
            await query.answer("⏳ ...")
            filename = self.admin.generate_excel_report()
            if filename:
                await query.message.reply_document(document=open(filename, 'rb'), caption="📂 گزارش", filename=filename)
                self.admin.clean_up_file(filename)
            else: await query.message.reply_text("خطا.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("لغو شد.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start), 
                MessageHandler(filters.Regex('افزودن حساب|تنظیمات مجدد'), self.restart_wizard)
            ],
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
        self.app.add_handler(CallbackQueryHandler(self.account_action_handler, pattern="^ACC_"))
        self.app.add_handler(CommandHandler("admin", self.admin_panel))
        self.app.add_handler(CallbackQueryHandler(self.admin_actions, pattern="^ADMIN_"))
        self.app.add_handler(MessageHandler(filters.TEXT, self.menu_handler))
        print("🤖 Bot Running (Managed Account Feature)...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
