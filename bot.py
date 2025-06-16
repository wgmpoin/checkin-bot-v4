import os
from telegram import Bot, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CommandHandler, MessageHandler, Filters, CallbackContext, Dispatcher
from flask import Flask, request

app = Flask(__name__)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = Bot(token=TOKEN)

# Handler perintah /checkin
def checkin(update: Update, context: CallbackContext):
    button = KeyboardButton("📍 Share Location", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=True)
    update.message.reply_text("Silakan share lokasi Anda:", reply_markup=reply_markup)

# Handler lokasi yang dikirim
def handle_location(update: Update, context: CallbackContext):
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    update.message.reply_text(f"Lokasi diterima: {lat}, {lon}\nMenyimpan ke database...")
    
    # Simpan ke database (sederhana)
    try:
        # Ganti dengan kode penyimpanan sebenarnya
        print(f"DEBUG: Menyimpan lokasi - Lat: {lat}, Lon: {lon}")
        update.message.reply_text("✅ Lokasi berhasil disimpan!")
    except Exception as e:
        update.message.reply_text(f"❌ Gagal menyimpan: {str(e)}")

# Webhook untuk Koyeb
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), bot)
    dispatcher.process_update(update)
    return 'OK'

# Inisialisasi
dispatcher = Dispatcher(bot, None, use_context=True)
dispatcher.add_handler(CommandHandler("checkin", checkin))
dispatcher.add_handler(MessageHandler(Filters.location, handle_location))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
