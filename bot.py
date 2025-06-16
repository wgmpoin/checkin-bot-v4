import os
import logging
from datetime import datetime
import pytz
import gspread
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# ======================
# SETUP FLASK UNTUK WEBHOOK
# ======================
app = Flask(__name__)

# ======================
# SETUP LOGGING
# ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======================
# STATE UNTUK CONVERSATIONHANDLER
# ======================
INPUT_NAMA_LOKASI, INPUT_WILAYAH, INPUT_LOCATION, FINAL_CHECKIN = range(4)

# ======================
# KONFIGURASI BOT
# ======================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST') 
PORT = int(os.environ.get('PORT', 8000))
WEBHOOK_PATH = TELEGRAM_TOKEN
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{WEBHOOK_PATH}"

updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# ======================
# MANAJEMEN PENGGUNA (OWNER, ADMIN, USER)
# ======================
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
ADMIN_IDS = [int(uid) for uid in os.getenv('ADMIN_IDS', '').split(',') if uid]
AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if uid]

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS

def is_authorized_user(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS or user_id in AUTHORIZED_USER_IDS

def restricted(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not update.effective_chat:
            logger.warning(f"No effective chat for restricted command. Update type: {update.update_id}")
            return
        user_id = update.effective_user.id
        if not is_authorized_user(user_id):
            logger.warning(f"Unauthorized access attempt by user {user_id} for command {update.message.text if update.message else 'unknown'}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def admin_restricted(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            logger.warning(f"Admin restricted command attempt by user {user_id}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin Admin untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def owner_restricted(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_owner(user_id):
            logger.warning(f"Owner restricted command attempt by user {user_id}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin Owner untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

# ======================
# KONFIGURASI GOOGLE SHEETS
# ======================
def get_credentials():
    try:
        private_key = os.getenv('GSHEET_PRIVATE_KEY', '').replace('\\n', '\n')
        
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            raise ValueError("Invalid private key format")

        return {
            "type": "service_account",
            "project_id": os.getenv('GSHEET_PROJECT_ID'),
            "private_key_id": os.getenv('GSHEET_PRIVATE_KEY_ID'),
            "private_key": private_key,
            "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),
            "client_id": os.getenv('GSHEET_CLIENT_ID'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GSHEET_CLIENT_EMAIL', '').replace('@', '%40')}"
        }
    except Exception as e:
        logger.error(f"Credential setup failed: {str(e)}")
        raise

def init_gsheet():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]
        creds_dict = get_credentials()
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet_url = os.getenv('SHEET_URL')
        if not sheet_url:
            raise ValueError("SHEET_URL environment variable not set")
        
        return client.open_by_url(sheet_url)
    except Exception as e:
        logger.error(f"Google Sheets init failed: {str(e)}")
        raise

# ======================
# HELPER FUNCTIONS
# ======================
def get_local_timestamp(tz_name: str = 'Asia/Jakarta') -> str:
    """Mendapatkan timestamp lokal sesuai zona waktu (standar GMT+7 / Asia/Jakarta)."""
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S")
    except pytz.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: {tz_name}. Falling back to UTC.")
        return datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

# ======================
# HANDLER COMMANDS & CONVERSATION
# ======================

@restricted
def start_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Halo! Saya Bot Check-in Sales Anda.\n"
        "Gunakan perintah di bawah ini untuk berinteraksi:\n"
        "/checkin - Mulai proses check-in lokasi dan wilayah.\n"
        "/menu - Tampilkan menu perintah."
    )

@restricted
def checkin_start(update: Update, context: CallbackContext) -> int:
    """Memulai percakapan check-in."""
    logger.info(f"Checkin started by user {update.effective_user.id}")
    update.message.reply_text("🏷️ Baik, mari kita mulai check-in Anda!\n"
                              "Mohon masukkan *Nama Lokasi*:",
                              parse_mode='Markdown')
    context.user_data['temp_chat_id'] = update.effective_chat.id
    return INPUT_NAMA_LOKASI

@restricted
def checkin_nama_lokasi(update: Update, context: CallbackContext) -> int:
    """Menerima nama lokasi dan meminta wilayah."""
    nama_lokasi = update.message.text
    if not nama_lokasi:
        update.message.reply_text("Nama lokasi tidak boleh kosong. Silakan coba lagi.")
        return INPUT_NAMA_LOKASI
    context.user_data['nama_lokasi'] = nama_lokasi
    logger.info(f"User {update.effective_user.id} entered Nama Lokasi: {nama_lokasi}")
    update.message.reply_text(f"Sekarang, mohon masukkan *Wilayah*:",
                              parse_mode='Markdown')
    return INPUT_WILAYAH

@restricted
def checkin_wilayah(update: Update, context: CallbackContext) -> int:
    """Menerima wilayah, menampilkan ringkasan, dan meminta lokasi dengan tombol."""
    wilayah = update.message.text
    if not wilayah:
        update.message.reply_text("Wilayah tidak boleh kosong. Silakan coba lagi.")
        return INPUT_WILAYAH
    context.user_data['wilayah'] = wilayah
    logger.info(f"User {update.effective_user.id} entered Wilayah: {wilayah}")
    
    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')

    keyboard = [[KeyboardButton("📍 Share Lokasi Saya", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    update.message.reply_text(
        f"✅ Lokasi: *{nama_lokasi}*\n"
        f"🌍 Wilayah: *{wilayah}*\n\n"
        f"Terakhir, mohon kirim lokasi Anda saat ini dengan menekan tombol di bawah ini:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return INPUT_LOCATION

@restricted
def checkin_location(update: Update, context: CallbackContext) -> int:
    """Menerima lokasi dan menyimpan semua data."""
    if not update.message.location:
        update.message.reply_text("Mohon kirimkan lokasi Anda yang valid melalui fitur lokasi Telegram (tombol 'Share Lokasi Saya'). Jika tidak, ketik /cancel untuk membatalkan.")
        return INPUT_LOCATION

    user = update.effective_user
    location = update.message.location
    latitude = location.latitude
    longitude = location.longitude
    
    Maps_link = f"http://maps.google.com/maps?q={latitude},{longitude}" # Revisi link maps

    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')
    wilayah = context.user_data.get('wilayah', 'N/A')
    timestamp_lokal = get_local_timestamp()

    row_data = [
        str(user.id),
        user.first_name or '',
        user.username or '',
        timestamp_lokal,
        nama_lokasi,
        wilayah,
        Maps_link
    ]

    try:
        gsheet_client = init_gsheet()
        sheet = gsheet_client.sheet1
        sheet.append_row(row_data)
        logger.info(f"Check-in recorded for {user.id} at {timestamp_lokal} - {nama_lokasi}, {wilayah}")
        
        update.message.reply_text(
            "✅ Data check-in berhasil dicatat!\n\n"
            f"👤 User ID: `{user.id}`\n"
            f"🧑‍💻 Nama: `{user.first_name or 'N/A'}`\n"
            f"📧 Username: `@{user.username}`\n"
            f"⏰ Waktu: `{timestamp_lokal}`\n"
            f"🏷️ Nama Lokasi: *{nama_lokasi}*\n"
            f"🌍 Wilayah: *{wilayah}*\n"
            f"📍 Lokasi Google Maps: [Link Lokasi]({Maps_link})\n\n"
            "Terima kasih!",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Gagal mencatat data check-in: {str(e)}")
        update.message.reply_text("❌ Gagal mencatat data. Mohon coba lagi nanti.")

    return ConversationHandler.END

def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Membatalkan percakapan check-in."""
    update.message.reply_text("Proses check-in dibatalkan.")
    return ConversationHandler.END

# ======================
# MENU BOT (set_my_commands)
# ======================
def set_bot_commands_sync(dispatcher):
    commands = [
        BotCommand("start", "Mulai bot dan lihat sambutan"),
        BotCommand("checkin", "Mulai proses check-in lokasi dan wilayah."),
        BotCommand("menu", "Tampilkan daftar perintah bot ini"),
        BotCommand("myid", "Lihat ID Telegram Anda"),
        BotCommand("help", "Bantuan dan informasi bot"),
        BotCommand("add_user", "Admin: Tambah pengguna terotorisasi"),
        BotCommand("remove_user", "Admin: Hapus pengguna terotorisasi"),
        BotCommand("list_users", "Admin: Daftar pengguna terotorisasi"),
        BotCommand("add_admin", "Owner: Tambah admin"),
        BotCommand("remove_admin", "Owner: Hapus admin"),
        BotCommand("list_admins", "Owner: Daftar admin")
    ]
    
    try:
        success = dispatcher.bot.set_my_commands(commands)
        if success:
            logger.info("Bot commands have been set successfully.")
        else:
            logger.warning("Failed to set bot commands. Telegram API might return False.")
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")

@restricted
def show_menu(update: Update, context: CallbackContext):
    msg = (
        "Berikut adalah perintah yang bisa Anda gunakan:\n"
        "/start - Memulai bot dan sambutan\n"
        "/checkin - Memulai proses check-in lokasi dan wilayah\n"
        "/menu - Menampilkan menu perintah ini\n"
        "/myid - Melihat ID Telegram Anda\n"
        "/help - Bantuan dan informasi bot\n\n"
    )
    user_id = update.effective_user.id
    if is_admin(user_id):
        msg += (
            "--- Perintah Admin ---\n"
            "/add_user <id> - Tambah pengguna terotorisasi\n"
            "/remove_user <id> - Hapus pengguna terotorisasi\n"
            "/list_users - Daftar pengguna terotorisasi\n"
        )
    if is_owner(user_id):
        msg += (
            "--- Perintah Owner ---\n"
            "/add_admin <id> - Tambah admin\n"
            "/remove_admin <id> - Hapus admin\n"
            "/list_admins - Daftar admin\n"
        )
    update.message.reply_text(msg)

@restricted
def my_id(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(f"ID Telegram Anda adalah: `{user_id}`", parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Bot ini dirancang untuk memudahkan proses check-in sales dengan mencatat nama lokasi, wilayah, dan lokasi geografis ke Google Sheets.\n\n"
        "Untuk memulai, ketik /checkin.\n"
        "Jika ada masalah, pastikan bot memiliki akses ke Google Sheets dan semua variabel lingkungan sudah diatur dengan benar."
    )

# ======================
# COMMANDS UNTUK MANAJEMEN USER (ADMIN/OWNER ONLY)
# ======================

@owner_restricted
def add_admin(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Penggunaan: /add_admin <user_id>")
        return
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id == OWNER_ID:
            update.message.reply_text(f"User ID {new_admin_id} adalah Owner, tidak perlu ditambahkan sebagai Admin.")
        elif new_admin_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin_id)
            update.message.reply_text(f"User ID {new_admin_id} berhasil ditambahkan sebagai Admin.")
            logger.info(f"User {new_admin_id} added as Admin by {update.effective_user.id}")
        else:
            update.message.reply_text(f"User ID {new_admin_id} sudah menjadi Admin.")
    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")

@owner_restricted
def remove_admin(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Penggunaan: /remove_admin <user_id>")
        return
    try:
        admin_to_remove = int(context.args[0])
        if admin_to_remove == OWNER_ID:
             update.message.reply_text(f"Owner tidak bisa dihapus dari daftar Admin.")
        elif admin_to_remove in ADMIN_IDS:
            ADMIN_IDS.remove(admin_to_remove)
            update.message.reply_text(f"User ID {admin_to_remove} berhasil dihapus dari daftar Admin.")
            logger.info(f"User {admin_to_remove} removed from Admin by {update.effective_user.id}")
        else:
            update.message.reply_text(f"User ID {admin_to_remove} bukan Admin.")
    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")

@admin_restricted
def add_user(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Penggunaan: /add_user <user_id>")
        return
    try:
        new_user_id = int(context.args[0])
        if is_admin(new_user_id):
            update.message.reply_text(f"User ID {new_user_id} adalah Admin/Owner, sudah otomatis terotorisasi.")
        elif new_user_id not in AUTHORIZED_USER_IDS:
            AUTHORIZED_USER_IDS.append(new_user_id)
            update.message.reply_text(f"User ID {new_user_id} berhasil ditambahkan sebagai Pengguna Terotorisasi.")
            logger.info(f"User {new_user_id} added as Authorized User by {update.effective_user.id}")
        else:
            update.message.reply_text(f"User ID {new_user_id} sudah menjadi Pengguna Terotorisasi.")
    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")

@admin_restricted
def remove_user(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Penggunaan: /remove_user <user_id>")
        return
    try:
        user_to_remove = int(context.args[0])
        if is_admin(user_to_remove):
            update.message.reply_text(f"User ID {user_to_remove} adalah Admin/Owner, tidak bisa dihapus dari daftar pengguna terotorisasi secara langsung.")
        elif user_to_remove in AUTHORIZED_USER_IDS:
            AUTHORIZED_USER_IDS.remove(user_to_remove)
            update.message.reply_text(f"User ID {user_to_remove} berhasil dihapus dari daftar Pengguna Terotorisasi.")
            logger.info(f"User {user_to_remove} removed from Authorized User by {update.effective_user.id}")
        else:
            update.message.reply_text(f"User ID {user_to_remove} bukan Pengguna Terotorisasi.")
    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")

@admin_restricted
def list_users(update: Update, context: CallbackContext):
    msg = "Daftar User Terotorisasi (Diluar Owner/Admin):\n"
    if AUTHORIZED_USER_IDS:
        for uid in AUTHORIZED_USER_IDS:
            msg += f"- `{uid}`\n"
    else:
        msg += "Tidak ada user terotorisasi yang ditambahkan secara manual."
    update.message.reply_text(msg, parse_mode='Markdown')

@owner_restricted
def list_admins(update: Update, context: CallbackContext):
    msg = "Daftar Admin (Diluar Owner):\n"
    if ADMIN_IDS:
        for uid in ADMIN_IDS:
            msg += f"- `{uid}`\n"
    else:
        msg += "Tidak ada admin yang ditambahkan secara manual."
    update.message.reply_text(msg, parse_mode='Markdown')


# ======================
# MAIN APPLICATION LOGIC
# ======================
def main():
    try:
        logger.info("Starting bot initialization...")
        
        required_vars = [
            'TELEGRAM_TOKEN', 'GSHEET_PRIVATE_KEY', 'GSHEET_CLIENT_EMAIL',
            'SHEET_URL', 'WEBHOOK_HOST', 'OWNER_ID'
        ]
        
        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Missing required environment variable: {var}")
        
        set_bot_commands_sync(dispatcher)

        dispatcher.add_handler(CommandHandler("start", start_command))
        dispatcher.add_handler(CommandHandler("menu", show_menu))
        dispatcher.add_handler(CommandHandler("myid", my_id))
        dispatcher.add_handler(CommandHandler("help", help_command))

        dispatcher.add_handler(CommandHandler("add_admin", add_admin))
        dispatcher.add_handler(CommandHandler("remove_admin", remove_admin))
        dispatcher.add_handler(CommandHandler("add_user", add_user))
        dispatcher.add_handler(CommandHandler("remove_user", remove_user))
        dispatcher.add_handler(CommandHandler("list_users", list_users))
        dispatcher.add_handler(CommandHandler("list_admins", list_admins))

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('checkin', checkin_start)],
            states={
                INPUT_NAMA_LOKASI: [MessageHandler(Filters.text & ~Filters.command, checkin_nama_lokasi)],
                INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, checkin_wilayah)],
                INPUT_LOCATION: [MessageHandler(Filters.location & ~Filters.command, checkin_location)],
            },
            fallbacks=[CommandHandler('cancel', cancel_conversation)],
        )
        dispatcher.add_handler(conv_handler)
        
        logger.info(f"Bot configured for webhook. Listening on {WEBHOOK_HOST}:{PORT}/{WEBHOOK_PATH}")

    except Exception as e:
        logger.critical(f"Bot crashed during initialization: {str(e)}")
        raise

# ======================
# ROUTE FLASK UNTUK MENERIMA WEBHOOK
# ======================
@app.route(f'/{WEBHOOK_PATH}', methods=['POST'])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), dispatcher.bot)
        dispatcher.process_update(update)
    return "ok"

# ======================
# HEALTH CHECK ENDPOINT UNTUK KOYEB
# ======================
@app.route('/healthz', methods=['GET'])
def health_check():
    return "OK", 200

# ======================
# START FLASK SERVER
# ======================
if __name__ == '__main__':
    main()
    logger.info(f"Starting Flask server on host 0.0.0.0, port {PORT}") 
    try:
        app.run(host="0.0.0.0", port=PORT)
    except Exception as e:
        logger.critical(f"Flask server crashed: {e}")
