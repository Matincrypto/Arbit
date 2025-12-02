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
from admin_panel import AdminPanel  # <--- ایمپورت فایل جدید
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
        self.admin = AdminPanel() # <--- نمونه‌سازی از کلاس ادمین

    # ... (تمام توابع قبلی مثل start, get_name و غیره سر جای خودشان باشند و تغییری ندهید) ...
    # برای کوتاه شدن پاسخ، توابع قبلی را تکرار نمیکنم، فقط بخش‌های جدید را اضافه میکنم.
    
    # ---------------------------------------------------------
    # بخش جدید: دستورات ادمین
    # ---------------------------------------------------------
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # چک کردن دسترسی ادمین از فایل config
        if not self.admin.is_admin(user_id):
            # اگر ادمین نبود، اصلا واکنشی نشان نده یا بگو دستور نامعتبر
            return 

        # دریافت آمار
        stats_msg = self.admin.get_quick_stats()
        
        # دکمه دانلود اکسل
        keyboard = [[InlineKeyboardButton("📥 دانلود فایل اکسل کامل", callback_data="ADMIN_DOWNLOAD_EXCEL")]]
        markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(stats_msg, reply_markup=markup)

    async def admin_actions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        
        if not self.admin.is_admin(user_id):
            return

        if query.data == "ADMIN_DOWNLOAD_EXCEL":
            await query.answer("⏳ در حال تولید فایل اکسل...")
            
            # تولید فایل
            filename = self.admin.generate_excel_report()
            
            if filename:
                await query.message.reply_document(
                    document=open(filename, 'rb'),
                    caption="📂 گزارش کامل کاربران و معاملات (شامل لاگ خطاها)",
                    filename=filename
                )
                # حذف فایل از روی سرور بعد از ارسال
                self.admin.clean_up_file(filename)
            else:
                await query.message.reply_text("❌ خطا در ساخت فایل اکسل.")

    # ... (بقیه توابع منو و ... سر جای خودشان) ...

    def run(self):
        conv = ConversationHandler(
            # ... (همان تنظیمات قبلی) ...
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
        
        # --- هندلر جدید ادمین ---
        self.app.add_handler(CommandHandler("admin", self.admin_panel))
        self.app.add_handler(CallbackQueryHandler(self.admin_actions, pattern="^ADMIN_"))
        
        self.app.add_handler(MessageHandler(filters.TEXT, self.menu_handler))
        
        print("🤖 Bot Running with Admin Panel...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradingBotUI(TELEGRAM_BOT_TOKEN)
    bot.run()
