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
    GET_ACCOUNT_NAME, GET_NAME, GET_PHONE, GET_CAPITAL_TMN, GET_CAPITAL_USDT, 
    GET_STOP_LOSS, GET_API, GET_STRATEGIES, GET_GRADES, GET_COINS
) = range(10)

class TradingBotUI:
    def __init__(self, token):
        self.app = ApplicationBuilder().token(token).build()
        self.db = DatabaseHandler()
        self.admin = AdminPanel()

    def get_paginated_keyboard(self, all_items, selected_items, page=0, items_per_page=15, prefix="COIN"):
        keyboard = []
        keyboard.append([
            InlineKeyboardButton("Select All", callback_data="ALL_SELECT"),
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
            nav_row.append(InlineKeyboardButton("Prev", callback_data=f"PAGE_PREV"))
        total_pages = (len(all_items) + items_per_page - 1) // items_per_page
        nav_row.append(InlineKeyboardButton(f"Page {page+1}/{total_pages}", callback_data="NOOP"))
        if end < len(all_items):
            nav_row.append(InlineKeyboardButton("Next", callback_data=f"PAGE_NEXT"))
        keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton("Save Account", callback_data=f"CONFIRM_{prefix}")])
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
        keyboard.append([InlineKeyboardButton("Confirm", callback_data=f"CONFIRM_{prefix}")])
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM users WHERE telegram_id = ?", (user.id,))
        count = cursor.fetchone()[0]
        conn.close()

        if count > 0:
            await self.show_main_menu(update, user)
        else:
            await update.message.reply_text(
                f"Hello {user.first_name}! Welcome to the Trading Bot.\n"
                "You have no accounts. Let's create one.\n"
                "Step 1: Enter a name for this account (e.g., Main):"
            )
            return GET_ACCOUNT_NAME

    async def add_new_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Creating New Account.\nStep 1: Enter account name:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_ACCOUNT_NAME

    async def get_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['account_name'] = update.message.text
        await update.message.reply_text("Name saved. Step 2: Enter your full name:")
        return GET_NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['full_name'] = update.message.text
        btn = KeyboardButton("Share Phone", request_contact=True)
        await update.message.reply_text("Step 3: Share phone number:", reply_markup=ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True))
        return GET_PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.contact:
            context.user_data['phone'] = update.message.contact.phone_number
        else:
            context.user_data['phone'] = update.message.text
        await update.message.reply_text("Step 4: TMN Buy Amount (e.g., 500000):", reply_markup=ReplyKeyboardRemove())
        return GET_CAPITAL_TMN

    async def get_capital_tmn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data['buy_tmn'] = float(update.message.text)
            await update.message.reply_text("Step 5: USDT Buy Amount (e.g., 20):")
            return GET_CAPITAL_USDT
        except:
            await update.message.reply_text("Invalid number.")
            return GET_CAPITAL_TMN

    async def get_capital_usdt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data['buy_usdt'] = float(update.message.text)
            await update.message.reply_text("Step 6: Stop Loss % (e.g., 2):")
            return GET_STOP_LOSS
        except:
            await update.message.reply_text("Invalid number.")
            return GET_CAPITAL_USDT

    async def get_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            context.user_data['stop_loss'] = float(update.message.text)
            await update.message.reply_text("Step 7: Send Wallex API Key:")
            return GET_API
        except:
            await update.message.reply_text("Invalid number.")
            return GET_STOP_LOSS

    async def get_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        api_key = update.message.text.strip()
        await update.message.reply_text("Validating...")
        try:
            url = f"{WALLEX_BASE_URL}/v1/account/balances"
            headers = DEFAULT_HEADERS.copy()
            headers["X-API-Key"] = api_key
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                context.user_data['api_key'] = api_key
                context.user_data['strategies'] = []
                markup = self.get_simple_keyboard(['Internal', 'G1', 'Computiational'], [], "STRAT")
                await update.message.reply_text("API Valid. Step 8: Select Strategies:", reply_markup=markup)
                return GET_STRATEGIES
            else:
                await update.message.reply_text("Invalid API Key.")
                return GET_API
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
            return GET_API

    async def get_strategies_step(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        curr = context.user_data.get('strategies', [])
        if data == "CONFIRM_STRAT":
            if not curr: return GET_STRATEGIES
            context.user_data['grades'] = []
            markup = self.get_simple_keyboard(['Q1', 'Q2', 'Q3', 'Q4'], [], "GRADE")
            await query.message.edit_text("Strategies saved.")
            await query.message.reply_text("Step 9: Select Grades:", reply_markup=markup)
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
            if not curr: return GET_GRADES
            await query.message.edit_text("Fetching coins...")
            client = WallexClient()
            all_coins = client.get_available_coins()
            context.user_data['all_available_coins'] = all_coins
            context.user_data['coins'] = [] 
            context.user_data['page'] = 0   
            markup = self.get_paginated_keyboard(all_coins, [], page=0)
            await query.message.reply_text("Step 10: Select Coins:", reply_markup=markup)
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
            if not selected_coins: return GET_COINS
            await query.message.edit_text("Saving...")
            user_id = update.effective_user.id
            d = context.user_data
            conn = self.db.get_connection()
            try:
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
                await query.message.reply_text("Account created!")
                await self.show_main_menu(update, update.effective_user)
            except Exception as e:
                logging.error(e)
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

    async def show_main_menu(self, update: Update, user):
        target = update.message if update.message else update.callback_query.message
        keyboard = [['Manage Accounts'], ['Add New Account', 'Report']]
        if self.admin.is_admin(user.id): keyboard.append(['Admin Panel'])
        await target.reply_text(f"User: {user.first_name}\nMenu:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

    async def manage_accounts_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        users = cursor.fetchall()
        conn.close()
        if not users:
            await update.message.reply_text("No accounts.")
            return
        for user in users:
            status = "Active" if user['is_active'] else "Inactive"
            toggle = "Stop" if user['is_active'] else "Activate"
            kb = [[InlineKeyboardButton(toggle, callback_data=f"ACC_TOGGLE_{user['id']}"), InlineKeyboardButton("Delete", callback_data=f"ACC_DELETE_{user['id']}")]]
            msg = f"Name: {user['account_name']}\nStatus: {status}"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    async def account_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        parts = data.split("_")
        action = parts[1]
        acc_id = parts[2]
        conn = self.db.get_connection()
        cursor = conn.cursor()
        if action == "TOGGLE":
            cursor.execute("SELECT is_active FROM users WHERE id=?", (acc_id,))
            curr = cursor.fetchone()[0]
            new_s = 0 if curr else 1
            cursor.execute("UPDATE users SET is_active=? WHERE id=?", (new_s, acc_id))
            conn.commit()
            await query.message.edit_text(f"Status changed to {'Active' if new_s else 'Inactive'}")
        elif action == "DELETE":
            cursor.execute("DELETE FROM users WHERE id=?", (acc_id,))
            conn.commit()
            await query.message.edit_text("Deleted.")
        conn.close()

    async def menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if "Manage Accounts" in text: await self.manage_accounts_list(update, context)
        elif "Add New Account" in text: await self.add_new_account(update, context)
        elif "Report" in text: await self.manage_accounts_list(update, context)
        elif "Admin" in text: await self.admin_panel(update, context)

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.admin.is_admin(update.effective_user.id): return
        stats = self.admin.get_quick_stats()
        await update.message.reply_text(stats)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    def run(self):
        conv = ConversationHandler(
            entry_points=[CommandHandler("start", self.start), MessageHandler(filters.Regex('Add New Account'), self.add_new_account)],
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
        self.app.add_handler(CallbackQueryHandler(self.account_action, pattern="^ACC_"))
        self.app.add_handler(MessageHandler(filters.TEXT, self.menu_handler))
        print("Bot Running...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
