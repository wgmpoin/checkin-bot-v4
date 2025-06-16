import os
import logging
from datetime import datetime
from typing import Optional
import gspread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, CallbackQueryHandler, Dispatcher,
    ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

app = Flask(__name__)

# ======================
# KONFIGURASI AWAL
# ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State untuk ConversationHandler
LOCATION_NAME, AREA = range(2)

# ======================
# INISIALISASI BOT
# ======================
bot = Updater(os.getenv('TELEGRAM_TOKEN'), use_context=True).bot
dispatcher = Dispatcher(bot, None, workers=1)

# ======================
# HANDLER CHECK-IN 2 TAHAP
# ======================
def start_checkin(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("🏷️ Masukkan NAMA LOKASI (contoh: TB Makmur Jaya):")
    return LOCATION_NAME

def get_location_name(update: Update, context: CallbackContext) -> int:
    context.user_data['location_name'] = update.message.text
    update.message.reply_text("📍 Masukkan WILAYAH (contoh: Surabaya, Jl. Sudirman No. 5):")
    return AREA

def get_area_and_save(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    sheet = init_gsheet().sheet1
    sheet.append_row([
        str(user.id),
        user.first_name or '',
        user.username or '',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        context.user_data['location_name'],
        update.message.text,
        f"https://maps.google.com/?q={context.user_data.get('lat', '')},{context.user_data.get('lon', '')}"
    ])
    
    update.message.reply_text(f"""
✅ CHECK-IN BERHASIL
🏠 Lokasi: {context.user_data['location_name']}
📍 Wilayah: {update.message.text}
🕒 Waktu: {datetime.now().strftime("%H:%M:%S")}
""")
    return ConversationHandler.END

# ======================
# SETUP HANDLER
# ======================
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('checkin', start_checkin)],
    states={
        LOCATION_NAME: [MessageHandler(Filters.text & ~Filters.command, get_location_name)],
        AREA: [MessageHandler(Filters.text & ~Filters.command, get_area_and_save)]
    },
    fallbacks=[]
)

dispatcher.add_handler(conv_handler)

# [Bagian lainnya tetap sama...]
