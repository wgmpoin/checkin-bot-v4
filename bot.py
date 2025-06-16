import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

app = Flask(__name__)

# ===== KONFIGURASI =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State untuk Conversation
INPUT_LOKASI, INPUT_WILAYAH = range(2)

# ===== INISIALISASI BOT =====
updater = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True)
dp = updater.dispatcher

# ===== FUNGSI UTAMA =====
def start_checkin(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("🏷️ MASUKKAN NAMA LOKASI:")
    return INPUT_LOKASI

def input_lokasi(update: Update, context: CallbackContext) -> int:
    context.user_data['lokasi'] = update.message.text
    update.message.reply_text("📍 MASUKKAN WILAYAH:")
    return INPUT_WILAYAH

def input_wilayah(update: Update, context: CallbackContext) -> int:
    try:
        # 1. Persiapan Data
        user = update.effective_user
        data = [
            str(user.id),
            user.first_name or '-',
            f"@{user.username}" if user.username else '-',
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            context.user_data['lokasi'],
            update.message.text,
            context.user_data.get('maps_link', '-')
        ]
        
        # 2. Simpan ke Google Sheet
        sheet = get_gsheet()
        sheet.append_row(data)
        
        # 3. Konfirmasi ke User
        update.message.reply_text(
            "✅ DATA TERSIMPAN\n"
            f"Lokasi: {data[4]}\n"
            f"Wilayah: {data[5]}\n"
            f"Waktu: {data[3][11:16]}"
        )
        
    except Exception as e:
        logger.error(f"GAGAL SIMPAN: {str(e)}", exc_info=True)
        update.message.reply_text(
            "❌ GAGAL MENYIMPAN\n"
            "Silakan coba beberapa saat lagi\n"
            "Atau hubungi admin jika masalah berlanjut"
        )
    finally:
        context.user_data.clear()
        return ConversationHandler.END

# ===== GOOGLE SHEETS SERVICE =====
def get_gsheet():
    """Mengembalikan sheet dengan error handling"""
    try:
        creds = {
            "type": "service_account",
            "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
            "client_email": os.getenv('GSHEET_CLIENT_EMAIL')
        }
        
        scope = ["https://spreadsheets.google.com/feeds"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds, scope)
        client = gspread.authorize(credentials)
        
        # Cek koneksi
        spreadsheet = client.open_by_url(os.getenv('SHEET_URL'))
        spreadsheet.listworksheets()  # Test koneksi
        return spreadsheet.sheet1
        
    except Exception as e:
        logger.critical(f"ERROR SHEET: {str(e)}", exc_info=True)
        raise Exception("Terjadi masalah dengan Google Sheets")

# ===== SETUP HANDLER =====
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('checkin', start_checkin)],
    states={
        INPUT_LOKASI: [MessageHandler(Filters.text & ~Filters.command, input_lokasi)],
        INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, input_wilayah)]
    },
    fallbacks=[]
)

dp.add_handler(conv_handler)
dp.add_handler(MessageHandler(Filters.location, lambda u,c: c.user_data.update({'maps_link': f"https://maps.app.goo.gl/?q={u.message.location.latitude},{u.message.location.longitude}"}))

# ===== WEBHOOK =====
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), updater.bot)
    dp.process_update(update)
    return 'OK', 200

if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
