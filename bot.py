import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

app = Flask(__name__)

# Konfigurasi Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State untuk ConversationHandler
INPUT_NAMA_LOKASI, INPUT_WILAYAH = range(2)

# Inisialisasi Bot
updater = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True)
dispatcher = updater.dispatcher

# Handler Command
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Selamat datang! Ketik /checkin untuk mulai check-in"
    )

def start_checkin(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("🏷️ Mohon masukkan NAMA LOKASI (contoh: TB Makmur Jaya):")
    return INPUT_NAMA_LOKASI

def input_nama_lokasi(update: Update, context: CallbackContext) -> int:
    context.user_data['nama_lokasi'] = update.message.text
    update.message.reply_text("📍 Sekarang masukkan WILAYAH (contoh: Surabaya):")
    return INPUT_WILAYAH

def input_wilayah(update: Update, context: CallbackContext) -> int:
    try:
        # Simpan ke Google Sheets
        sheet = init_gsheet().sheet1
        sheet.append_row([
            str(update.effective_user.id),
            update.effective_user.first_name,
            update.effective_user.username,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            context.user_data['nama_lok
