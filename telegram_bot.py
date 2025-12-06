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

# Conversation States (Added GET_ACCOUNT_NAME)
(
    GET_ACCOUNT_NAME, GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_STOP_LOSS, GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(10)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()
        self.admin = AdminPanel()

    # --- Helper: Paginated Keyboard with Select All ---
    def get_paginated_keyboard(self, all_items, selected_items, page=0, items_per_page=15, prefix="COIN"):
        keyboard = []
        
        # Select All / Deselect All Buttons
        keyboard.append([
            InlineKeyboardButton("Select All Coins", callback_data="ALL_SELECT"),
            InlineKeyboardButton("Deselect All", callback_data="ALL_DESELECT")
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
            nav_row.append(InlineKeyboardButton("Previous", callback_data=f"PAGE_PREV"))
        
        total_pages = (len(all_items) + items_per_page - 1) // items_per_page
        nav_row.append(InlineKeyboardButton(f"Page {page+1}/{total_pages}", callback_data="NOOP"))
        
        if end < len(all_items):
            nav_row.append(InlineKeyboardButton("Next", callback_data=f"PAGE_NEXT"))
            
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("Save and Create Account", callback_data=f"CONFIRM_{prefix}")])
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
        keyboard.append([InlineKeyboardButton("Confirm and Continue", callback_data=f"CONFIRM_{prefix}")])
        return InlineKeyboardMarkup(keyboard)

    # -------------------------------------------------------------------------
    # Start & Menu
    # -------------------------------------------------------------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Check if user has ANY account
        cursor.execute("SELECT count(*) FROM users WHERE telegram_id = ?", (user.id,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            await self.show_main_menu(update, user)
        else:
            await update.message.reply_text(
                f"Hello {user.first_name}! Welcome to the Smart Trading Bot.\n\n"
                "I am here to help you automate your trades.\n"
                "You don't have any accounts yet. Let's create your first profile.\n\n"
                "Step 1 of 10:\n"
                "Please choose a name for this account (e.g., Main Account, Risk Account):"
            )
            return GET_ACCOUNT_NAME

    async def add_new_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Creating a New Account\n\n"
            "Step 1 of 10:\n"
            "Please enter a name for this new account (e.g., Savings, High Risk):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_ACCOUNT_NAME

    # -------------------------------------------------------------------------
    # Registration Flow (Wizard) - Educational & No Asterisks
    # -------------------------------------------------------------------------
    async def get_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        acc_name = update.message.text
        context.user_data['account_name'] = acc_name
        
        await update.message.reply_text(
            f"Account name '{acc_name}' saved.\n\n"
            "Step 2 of 10:\n"
            "Please enter your full name:"
        )
        return GET_NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        btn = KeyboardButton("Share Phone Number", request_contact=True)
        await update.message.reply_text(
            "Step 3 of 10:\n"
            "For account security, we need your phone number.\n"
            "Please use the button below:",
            reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
        )
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            context.user_data['phone'] = update.message.text
        
        await update.message.reply_text(
            "Phone number saved.\n\n"
            "Step 4 of 10 (Capital Management):\n"
            "How much should the bot buy for each TMN (Toman) signal?\n"
            "Enter the amount in Tomans (e.g., 500000):",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['buy_tmn'] = val
            await update.message.reply_text(
                "Step 5 of 10:\n"
                "How much should the bot buy for each USDT (Tether) signal?\n"
                "Enter the amount in USDT (e.g., 20):"
            )
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("Please enter a valid number:")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['buy_usdt'] = val
            await update.message.reply_text(
                "Step 6 of 10 (Risk Management):\n"
                "What is your Stop Loss percentage?\n"
                "Example: Enter 2 for 2 percent loss.\n"
                "Enter 0 to disable Stop Loss:"
            )
            return GET_STOP_LOSS
        except:
            await update.message.reply_text("Please enter a valid number:")
            return GET_CAPITAL_USDT

    async def get_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = float(update.message.text)
            context.user_data['stop_loss'] = val
            await update.message.reply_text(
                "Stop Loss saved.\n\n"
                "Step 7 of 10 (Exchange Connection):\n"
                "To place orders, we need your Wallex API Key.\n"
                "We only require 'Trade' permission.\n"
                "Please send your API Key:"
            )
            return GET_API
        except:
            await update.message.reply_text("Please enter a valid number:")
            return GET_STOP_LOSS

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("⏳ Validating API Key...")
        try:
            url = f"{WALLEX_BASE_URL}/v1/account/balances"
            headers = DEFAULT_HEADERS.copy()
            headers["X-API-Key"] = api_key
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200 and resp.json().get('success'):
                context.user_data['api_key'] = api_key
                await update.message.reply_text("✅ API Key Validated.")
                context.user_data['strategies'] = []
                markup = self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], [], "STRAT")
                await update.message.reply_text(
                    "Step 8 of 10:\n"
                    "Select Strategies:",
                    reply_markup=markup
                )
                return GET_STRATEGIES
            else:
                await update.message.reply_text("⛔️ Invalid Key. Please try again:")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"Network Error: {e}")
            return GET_API

    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('strategies', [])
        if data == "CONFIRM_STRAT":
            if not curr:
                await query.answer("Select at least one!", show_alert=True)
                return GET_STRATEGIES
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("✅ Strategies Saved.")
            await query.message.reply_text("Step 9 of 10:\nSelect Signal Grades:", reply_markup=markup)
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
                await query.answer("Select at least one!", show_alert=True)
                return GET_GRADES
            await query.message.edit_text("⏳ Fetching coin list from Wallex...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            context.user_data['all_available_coins'] = all_coins
            context.user_data['coins'] = [] 
            context.user_data['page'] = 0   
            markup = self.get_paginated_keyboard(all_coins, [], page=0)
            await query.message.reply_text(
                "Step 10 of 10 (Last Step):\n"
                "Select coins to trade.\n"
                "You can select ALL:",
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

        # --- Select All Logic ---
        if data == "ALL_SELECT":
            selected_coins = list(all_coins)
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            await query.answer("All coins selected.", show_alert=False)
            return GET_COINS
        elif data == "ALL_DESELECT":
            selected_coins = []
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            await query.answer("All coins removed.", show_alert=False)
            return GET_COINS

        # --- Pagination ---
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
        
        # --- Final Save ---
        elif data == "CONFIRM_COIN":
            if not selected_coins:
                await query.answer("Select at least one coin!", show_alert=True)
                return GET_COINS
            
            await query.message.edit_text("✅ Saving Account...")
            user_id = update.effective_user.id
            d = context.user_data
            
            conn = self.db.get_connection()
            try:
                # INSERT new row (Do not delete previous accounts)
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
                await query.message.reply_text("🎉 Account successfully added.")
                await self.show_main_menu(update, update.effective_user)
            except Exception as e:
                logging.error(e)
                await query.message.reply_text("❌ Database Error.")
            finally:
                conn.close()
            return ConversationHandler.END
            
        # --- Single Selection ---
        elif data.startswith("COIN_"):
            coin_symbol = data.split("_")[1]
            if coin_symbol in selected_coins: selected_coins.remove(coin_symbol)
            else: selected_coins.append(coin_symbol)
            context.user_data['coins'] = selected_coins
            markup = self.get_paginated_keyboard(all_coins, selected_coins, page=current_page)
            await query.edit_message_reply_markup(reply_markup=markup)
            return GET_COINS

    # -------------------------------------------------------------------------
    # Account Management & Menu
    # -------------------------------------------------------------------------
    async def show_main_menu(self, update: Update, user):
        target = update.message if update.message else update.callback_query.message
        
        keyboard = [
            ['Manage Accounts'],
            ['Add New Account', 'Report']
        ]
        if self.admin.is_admin(user.id):
            keyboard.append(['Admin Panel'])

        await target.reply_text(
            f"User: {user.first_name}\n"
            "Select an option:",
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
            await update.message.reply_text("No accounts found.")
            return

        await update.message.reply_text(f"📋 You have {len(users)} accounts:")

        for user in users:
            status_txt = "Active 🟢" if user['is_active'] else "Inactive 🔴"
            toggle_txt = "Stop" if user['is_active'] else "Activate"
            
            keyboard = [[
                InlineKeyboardButton(toggle_txt, callback_data=f"ACC_TOGGLE_{user['id']}"),
                InlineKeyboardButton("Delete", callback_data=f"ACC_DELETE_{user['id']}")
            ]]
            
            acc_name = user['account_name'] if user['account_name'] else f"Account {user['id']}"
            
            msg = (
                f"🔖 Name: {acc_name}\n"
                f"Status: {status_txt}\n"
                f"Capital: {user['buy_amount_tmn']:,} T | {user['buy_amount_usdt']} $\n"
                f"Stop Loss: {user['stop_loss_percent']}%\n"
            )
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

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
                new_icon = "Active 🟢" if new_s else "Inactive 🔴"
                await query.message.edit_text(f"Account status changed: {new_icon}")
        
        elif action == "DELETE":
            kb = [[
                InlineKeyboardButton("Confirm Delete", callback_data=f"ACC_CONFIRM_{account_id}"),
                InlineKeyboardButton("Cancel", callback_data="ACC_CANCEL")
            ]]
            await query.message.edit_text("Are you sure you want to delete this account?", reply_markup=InlineKeyboardMarkup(kb))

        elif action == "CONFIRM":
            cursor.execute("DELETE FROM users WHERE id = ?", (account_id,))
            conn.commit()
            await query.message.edit_text("Account deleted.")
            
        elif action == "CANCEL":
            await query.message.edit_text("Cancelled.")
            
        conn.close()

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if "Manage Accounts" in text:
            await self.manage_accounts_list(update, context)
        elif "Add New Account" in text:
            await self.add_new_account(update, context)
        elif "Report" in text:
            await self.manage_accounts_list(update, context)
        elif "Admin Panel" in text or "/admin" in text:
            await self.admin_panel(update, context)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.admin.is_admin(update.effective_user.id): return
        stats = self.admin.get_quick_stats()
        kb = [[InlineKeyboardButton("Download Excel", callback_data="ADMIN_DOWNLOAD_EXCEL")]]
        await update.message.reply_text(stats, reply_markup=InlineKeyboardMarkup(kb))

    async def admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.admin.is_admin(update.effective_user.id): return
        query = update.callback_query
        if query.data == "ADMIN_DOWNLOAD_EXCEL":
            await query.answer("Generating...")
            fname = self.admin.generate_excel_report()
            if fname:
                await query.message.reply_document(open(fname, 'rb'), caption="Report", filename=fname)
                self.admin.clean_up_file(fname)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start), 
                MessageHandler(filters.Regex('Add New Account'), self.add_new_account)
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
