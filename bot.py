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

# Data Admin & Owner
OWNER_ID = 12345678  # Ganti dengan ID Telegram Anda
ADMINS = [87654321]  # Ganti dengan ID Admin lain

# ===== INISIALISASI BOT =====
updater = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True)
dp = updater.dispatcher

# ===== FUNGSI UTAMA =====
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    if user.id == OWNER_ID:
        update.message.reply_text(
            "👑 MODE OWNER\n"
            "• /add_admin - Tambah admin\n"
            "• /remove_admin - Hapus admin\n"
            "• /checkin - Check-in"
        )
    elif user.id in ADMINS:
        update.message.reply_text(
            "🛠️ MODE ADMIN\n"
            "• /checkin - Check-in\n"
            "• /list_data - Lihat data"
        )
    else:
        update.message.reply_text(
            "📍 KETIK /checkin UNTUK MULAI",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("/checkin", request_location=True)]],
                resize_keyboard=True
            )
        )

def start_checkin(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("🏷️ MASUKKAN NAMA LOKASI (Contoh: TB Makmur Jaya):")
    return INPUT_LOKASI

def input_lokasi(update: Update, context: CallbackContext) -> int:
    context.user_data['lokasi'] = update.message.text
    update.message.reply_text("📍 MASUKKAN WILAYAH (Contoh: Surabaya, Jl. Sudirman):")
    return INPUT_WILAYAH

def input_wilayah(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    lokasi = context.user_data['lokasi']
    wilayah = update.message.text
    
    # Simpan ke Google Sheet
    try:
        sheet = init_gsheet().sheet1
        sheet.append_row([
            str(user.id),
            user.first_name,
            f"@{user.username}" if user.username else "-",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lokasi,
            wilayah,
            context.user_data.get('maps_link', '-')
        ])
        
        # Konfirmasi ke user
        update.message.reply_text(
            f"✅ CHECK-IN BERHASIL\n\n"
            f"🏠 Nama Lokasi: {lokasi}\n"
            f"📍 Wilayah: {wilayah}\n"
            f"🕒 Waktu: {datetime.now().strftime('%H:%M')}\n"
            f"🗺️ Maps: {context.user_data.get('maps_link', 'Tidak ada')}"
        )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        update.message.reply_text("❌ Gagal menyimpan data")
    
    return ConversationHandler.END

def handle_location(update: Update, context: CallbackContext):
    loc = update.message.location
    maps_link = f"https://maps.app.goo.gl/?q={loc.latitude},{loc.longitude}"
    context.user_data['maps_link'] = maps_link
    update.message.reply_text("📍 Lokasi diterima! Sekarang ketik /checkin")

# ===== ADMIN TOOLS =====
def add_admin(update: Update, context: CallbackContext):
    if update.effective_user.id == OWNER_ID:
        try:
            new_admin = int(context.args[0])
            ADMINS.append(new_admin)
            update.message.reply_text(f"✅ Admin {new_admin} ditambahkan")
        except:
            update.message.reply_text("❌ Format salah. Contoh: /add_admin 123456")

# ===== GOOGLE SHEETS =====
def init_gsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_dict({
        "type": "service_account",
        "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
        "client_email": os.getenv('GSHEET_CLIENT_EMAIL')
    }, ["https://spreadsheets.google.com/feeds"])
    return gspread.authorize(creds).open_by_url(os.getenv('SHEET_URL'))

# ===== SETUP HANDLER =====
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('checkin', start_checkin)],
    states={
        INPUT_LOKASI: [MessageHandler(Filters.text & ~Filters.command, input_lokasi)],
        INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, input_wilayah)]
    },
    fallbacks=[]
)

dp.add_handler(CommandHandler('start', start))
dp.add_handler(CommandHandler('add_admin', add_admin))
dp.add_handler(MessageHandler(Filters.location, handle_location))
dp.add_handler(conv_handler)

# ===== WEBHOOK =====
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), updater.bot)
    dp.process_update(update)
    return 'OK', 200

if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
