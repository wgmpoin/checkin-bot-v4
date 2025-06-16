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

# ===== INISIALISASI =====
app = Flask(__name__)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== KONFIGURASI =====
INPUT_LOKASI, INPUT_WILAYAH = range(2)
updater = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True)
dp = updater.dispatcher

# ===== FUNGSI UTAMA =====
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "📍 KETIK /checkin UNTUK MULAI",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("/checkin", request_location=True)]],
            resize_keyboard=True
        )
    )

def start_checkin(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("🏷️ MASUKKAN NAMA LOKASI:")
    return INPUT_LOKASI

def input_lokasi(update: Update, context: CallbackContext) -> int:
    context.user_data['lokasi'] = update.message.text
    update.message.reply_text("📍 MASUKKAN WILAYAH:")
    return INPUT_WILAYAH

def input_wilayah(update: Update, context: CallbackContext) -> int:
    try:
        sheet = get_gsheet()
        sheet.append_row([
            str(update.effective_user.id),
            update.effective_user.first_name or '-',
            f"@{update.effective_user.username}" if update.effective_user.username else '-',
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            context.user_data['lokasi'],
            update.message.text,
            context.user_data.get('maps_link', '-')
        ])
        update.message.reply_text("✅ DATA TERSIMPAN")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        update.message.reply_text("❌ GAGAL MENYIMPAN")
    finally:
        return ConversationHandler.END

# ===== GOOGLE SHEETS =====
def get_gsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_dict({
        "type": "service_account",
        "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
        "client_email": os.getenv('GSHEET_CLIENT_EMAIL')
    }, ["https://spreadsheets.google.com/feeds"])
    return gspread.authorize(creds).open_by_url(os.getenv('SHEET_URL')).sheet1

# ===== WEBHOOK =====
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), updater.bot)
    dp.process_update(update)
    return 'OK', 200

# ===== HANDLER =====
dp.add_handler(CommandHandler('start', start))
dp.add_handler(ConversationHandler(
    entry_points=[CommandHandler('checkin', start_checkin)],
    states={
        INPUT_LOKASI: [MessageHandler(Filters.text & ~Filters.command, input_lokasi)],
        INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, input_wilayah)]
    },
    fallbacks=[]
))
dp.add_handler(MessageHandler(Filters.location, 
    lambda u,c: c.user_data.update({
        'maps_link': f"https://maps.app.goo.gl/?q={u.message.location.latitude},{u.message.location.longitude}"
    })
))

# ===== MAIN =====
if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
