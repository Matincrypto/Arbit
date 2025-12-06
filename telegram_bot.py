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

# اضافه شدن مرحله GET_ACCOUNT_NAME
(
    GET_ACCOUNT_NAME, GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_STOP_LOSS, GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(10)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()
        self.admin = AdminPanel()

    # --- توابع کمکی ---
    def get_paginated_keyboard(self, all_items, selected_items, page=0, items_per_page=15, prefix="COIN"):
        keyboard = []
        keyboard.append([
            InlineKeyboardButton("انتخاب همه", callback_data="ALL_SELECT"),
            InlineKeyboardButton("حذف همه", callback_data="ALL_DESELECT")
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
        if page > 0: nav_row.append(InlineKeyboardButton("قبلی", callback_data=f"PAGE_PREV"))
        total_pages = (len(all_items) + items_per_page - 1) // items_per_page
        nav_row.append(InlineKeyboardButton(f"صفحه {page+1}/{total_pages}", callback_data="NOOP"))
        if end < len(all_items): nav_row.append(InlineKeyboardButton("بعدی", callback_data=f"PAGE_NEXT"))
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("تایید نهایی و ساخت حساب", callback_data=f"CONFIRM_{prefix}")])
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
        keyboard.append([InlineKeyboardButton("تایید و ادامه", callback_data=f"CONFIRM_{prefix}")])
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------------------
    # شروع
    # -------------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # بررسی اینکه آیا کاربر حداقل یک حساب دارد؟
        cursor.execute("SELECT count(*) FROM users WHERE telegram_id = ?", (user.id,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            await self.show_main_menu(update, user)
        else:
            await update.message.reply_text(
                f"سلام {user.first_name} عزیز! 👋\n\n"
                "به ربات مدیریت سرمایه خوش آمدید.\n"
                "شما هنوز هیچ حسابی نساخته‌اید.\n\n"
                "مرحله 1 از 10 (نام‌گذاری حساب):\n"
                "لطفاً یک نام برای این حساب انتخاب کنید (مثلاً: حساب اصلی، حساب پس‌انداز):"
            )
            return GET_ACCOUNT_NAME

    async def add_new_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "➕ **ساخت حساب جدید**\n\n"
            "مرحله 1 از 10:\n"
            "یک نام برای این حساب جدید وارد کنید (مثلاً: حساب ریسک بالا):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_ACCOUNT_NAME

    # -------------------------------------------------------------------------
    # فلو ثبت نام (ویزارد)
    # -------------------------------------------------------------------------
    async def get_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        acc_name = update.message.text
        context.user_data['account_name'] = acc_name
        
        await update.message.reply_text(
            f"نام حساب '{acc_name}' ثبت شد.\n\n"
            "مرحله 2 از 10:\n"
            "نام و نام خانوادگی خود را وارد کنید:"
        )
        return GET_NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        btn = KeyboardButton("ارسال شماره موبایل", request_contact=True)
        await update.message.reply_text(
            "مرحله 3 از 10:\nبرای امنیت حساب، شماره موبایل را ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            context.user_data['phone'] = update.message.text
        await update.message.reply_text("مرحله 4 از 10:\nسرمایه خرید تومانی (مثال: 500000):", reply_markup=ReplyKeyboardRemove())
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['buy_tmn'] = val
            await update.message.reply_text("مرحله 5 از 10:\nسرمایه خرید تتری (مثال: 20):")
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['buy_usdt'] = val
            await update.message.reply_text("مرحله 6 از 10:\nدرصد حد ضرر (مثال: 2):")
            return GET_STOP_LOSS
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
            return GET_CAPITAL_USDT

    async def get_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['stop_loss'] = val
            await update.message.reply_text("مرحله 7 از 10:\nلطفاً API Key والکس را ارسال کنید:")
            return GET_API
        except:
            await update.message.reply_text("فقط عدد وارد کنید:")
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
                await update.message.reply_text("مرحله 8 از 10:\nاستراتژی‌ها:", reply_markup=markup)
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
            await query.message.reply_text("مرحله 9 از 10:\nکیفیت سیگنال (گرید):", reply_markup=markup)
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
            await query.message.reply_text("مرحله 10 از 10 (آخر):\nانتخاب ارزها:", reply_markup=markup)
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
            return GET_COINS
        elif data == "ALL_DESELECT":
            selected_coins = []
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
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
                await query.answer("حداقل یک ارز انتخاب کنید!", show_alert=True)
                return GET_COINS
            
            await query.message.edit_text("✅ در حال ساخت حساب جدید...")
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
                # نکته مهم: اینجا دیگر DELETE نداریم تا حساب‌های قبلی پاک نشوند
                conn.execute('''
                    INSERT INTO users (
                        telegram_id, account_name, full_name, phone_number, wallex_api_key,
                        buy_amount_tmn, buy_amount_usdt, stop_loss_percent,
                        allowed_strategies, allowed_grades, allowed_coins, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (
                    user_id, d['account_name'], d['full_name'], d['phone'], d['api_key'],
                    d['buy_tmn'], d['buy_usdt'], d['stop_loss'],
                    json.dumps(d['strategies']), json.dumps(d['grades']), json.dumps(selected_coins)
                ))
                conn.commit()
                await query.message.reply_text("🎉 حساب جدید با موفقیت اضافه شد.")
                await self.show_main_menu(update, update.effective_user)
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ خطا در ذخیره حساب.")
            finally:
                conn.close()
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
    # مدیریت حساب‌ها (نمایش لیست و کنترل)
    # -------------------------------------------------------------------------
    async def show_main_menu(self, update: Update, user):
        target = update.message if update.message else update.callback_query.message
        
        keyboard = [
            ['💼 مدیریت حساب‌ها'],
            ['➕ افزودن حساب جدید', '📊 گزارش کلی']
        ]
        if self.admin.is_admin(user.id):
            keyboard.append(['🛠 پنل ادمین'])

        await target.reply_text(
            f"👤 کاربر: {user.first_name}\n"
            "از منوی زیر استفاده کنید:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    async def manage_accounts_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        users = cursor.fetchall()
        conn.close()

        if not users:
            await update.message.reply_text("هیچ حسابی یافت نشد.")
            return

        await update.message.reply_text(f"📋 شما {len(users)} حساب متصل دارید:")

        for user in users:
            status_txt = "🟢 فعال" if user['is_active'] else "🔴 غیرفعال"
            toggle_txt = "⛔️ توقف" if user['is_active'] else "✅ روشن کردن"
            
            # کلیدهای عملیاتی برای هر حساب با ID مشخص
            keyboard = [[
                InlineKeyboardButton(toggle_txt, callback_data=f"ACC_TOGGLE_{user['id']}"),
                InlineKeyboardButton("🗑 حذف", callback_data=f"ACC_DELETE_{user['id']}")
            ]]
            
            # اگر نام حساب نداشت، یک نام پیش‌فرض بگذار
            acc_name = user['account_name'] if user['account_name'] else f"حساب {user['id']}"
            
            msg = (
                f"🔖 **{acc_name}**\n"
                f"وضعیت: {status_txt}\n"
                f"سرمایه: {user['buy_amount_tmn']:,} T | {user['buy_amount_usdt']} $\n"
                f"حد ضرر: {user['stop_loss_percent']}%\n"
            )
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def account_action_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split("_")
        action = parts[1]
        account_id = parts[2]
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        if action == "TOGGLE":
            cursor.execute("SELECT is_active FROM users WHERE id = ?", (account_id,))
            res = cursor.fetchone()
            if res:
                new_s = 0 if res[0] else 1
                cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_s, account_id,))
                conn.commit()
                # رفرش کردن پیام
                new_icon = "🟢 فعال" if new_s else "🔴 غیرفعال"
                await query.message.reply_text(f"وضعیت حساب تغییر کرد: {new_icon}")
                # کاربر باید دوباره لیست را ببیند تا دکمه آپدیت شود (محدودیت تلگرام در ادیت اینلاین‌کیبورد پیچیده)
        
        elif action == "DELETE":
            # درخواست تایید
            kb = [[
                InlineKeyboardButton("بله حذف شود", callback_data=f"ACC_CONFIRM_{account_id}"),
                InlineKeyboardButton("لغو", callback_data="ACC_CANCEL")
            ]]
            await query.message.edit_text("آیا مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(kb))

        elif action == "CONFIRM":
            cursor.execute("DELETE FROM users WHERE id = ?", (account_id,))
            conn.commit()
            await query.message.edit_text("حساب حذف شد.")
            
        elif action == "CANCEL":
            await query.message.edit_text("لغو شد.")
            
        conn.close()

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if "مدیریت حساب" in text:
            await self.manage_accounts_list(update, context)
        elif "افزودن حساب" in text:
            await self.add_new_account(update, context)
        elif "گزارش" in text:
            await self.manage_accounts_list(update, context) # گزارش همون لیست حساب هاست
        elif "پنل ادمین" in text or "/admin" in text:
            await self.admin_panel(update, context)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.admin.is_admin(update.effective_user.id): return
        stats = self.admin.get_quick_stats()
        kb = [[InlineKeyboardButton("دانلود اکسل", callback_data="ADMIN_DOWNLOAD_EXCEL")]]
        await update.message.reply_text(stats, reply_markup=InlineKeyboardMarkup(kb))

    async def admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.admin.is_admin(update.effective_user.id): return
        query = update.callback_query
        if query.data == "ADMIN_DOWNLOAD_EXCEL":
            await query.answer("تولید فایل...")
            fname = self.admin.generate_excel_report()
            if fname:
                await query.message.reply_document(open(fname, 'rb'), caption="گزارش", filename=fname)
                self.admin.clean_up_file(fname)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("لغو شد.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start), 
                MessageHandler(filters.Regex('افزودن حساب'), self.add_new_account)
            ],
            states={
                GET_ACCOUNT_NAME: [MessageHandler(filters.TEXT, self.get_account_name)],
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
        print("🤖 Multi-Account Bot Running...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
