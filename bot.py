import os
import logging
from datetime import datetime
import pytz # Untuk penyesuaian zona waktu
import gspread
from telegram import Update, BotCommand
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler
)
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request # Digunakan untuk menerima webhook

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
# Mendapatkan token bot Telegram dari environment variable
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
# URL publik Koyeb Anda tanpa 'https://'
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST') 
# Port yang disediakan Koyeb, default 8000
PORT = int(os.environ.get('PORT', 8000))
# Path unik untuk webhook, bisa menggunakan token bot untuk keamanan
WEBHOOK_PATH = TELEGRAM_TOKEN
# URL lengkap yang akan didaftarkan ke Telegram
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{WEBHOOK_PATH}"

# Inisialisasi Updater dan Dispatcher
updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# ======================
# MANAJEMEN PENGGUNA (OWNER, ADMIN, USER)
# ======================
OWNER_ID = int(os.getenv('OWNER_ID', '0')) # ID Owner bot
ADMIN_IDS = [int(uid) for uid in os.getenv('ADMIN_IDS', '').split(',') if uid] # Daftar ID Admin
AUTHORIZED_USER_IDS = [int(uid) for uid in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if uid] # Daftar ID User

# Fungsi untuk memeriksa peran pengguna
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in ADMIN_IDS

def is_authorized_user(user_id: int) -> bool:
    # Semua perintah dasar dilindungi untuk pengguna terotorisasi
    # Jika Anda ingin bot bisa diakses publik (tanpa daftar user),
    # hapus atau ubah logika di sini.
    # Contoh: return True  # untuk semua user bisa akses
    return user_id == OWNER_ID or user_id in ADMIN_IDS or user_id in AUTHORIZED_USER_IDS

def restricted(func):
    """Decorator untuk membatasi akses ke fungsi hanya untuk pengguna terotorisasi."""
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_authorized_user(user_id):
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def admin_restricted(func):
    """Decorator untuk membatasi akses ke fungsi hanya untuk Admin dan Owner."""
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            logger.warning(f"Admin restricted command attempt by user {user_id}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin Admin untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def owner_restricted(func):
    """Decorator untuk membatasi akses ke fungsi hanya untuk Owner."""
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
    """Load and validate Google Sheets credentials"""
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
    """Initialize Google Sheets connection and return client"""
    try:
        # Menyesuaikan scope untuk gspread
        # "https://www.googleapis.com/auth/drive.readonly" diperlukan jika sheet di drive yang tidak publicly shared
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
    """Mendapatkan timestamp lokal sesuai zona waktu"""
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
    update.message.reply_text("🏷️ Baik, mari kita mulai check-in Anda!\n"
                              "Mohon masukkan *Nama Lokasi* (contoh: TB Makmur Jaya):",
                              parse_mode='Markdown')
    context.user_data['temp_chat_id'] = update.effective_chat.id # Simpan chat ID untuk digunakan nanti
    return INPUT_NAMA_LOKASI

@restricted
def checkin_nama_lokasi(update: Update, context: CallbackContext) -> int:
    """Menerima nama lokasi dan meminta wilayah."""
    nama_lokasi = update.message.text
    if not nama_lokasi:
        update.message.reply_text("Nama lokasi tidak boleh kosong. Silakan coba lagi.")
        return INPUT_NAMA_LOKASI
    context.user_data['nama_lokasi'] = nama_lokasi
    update.message.reply_text(f"📍 Nama Lokasi: *{nama_lokasi}*\n"
                              f"Sekarang, mohon masukkan *Wilayah* (contoh: Surabaya, Denpasar, Duren Sawit):",
                              parse_mode='Markdown')
    return INPUT_WILAYAH

@restricted
def checkin_wilayah(update: Update, context: CallbackContext) -> int:
    """Menerima wilayah dan meminta lokasi (koordinat)."""
    wilayah = update.message.text
    if not wilayah:
        update.message.reply_text("Wilayah tidak boleh kosong. Silakan coba lagi.")
        return INPUT_WILAYAH
    context.user_data['wilayah'] = wilayah
    update.message.reply_text(f"🌍 Wilayah: *{wilayah}*\n"
                              f"Terakhir, mohon *kirim lokasi* Anda saat ini (melalui fitur 'Attach' -> 'Location' di Telegram):",
                              parse_mode='Markdown')
    return INPUT_LOCATION

@restricted
def checkin_location(update: Update, context: CallbackContext) -> int:
    """Menerima lokasi dan menyimpan semua data."""
    if not update.message.location:
        update.message.reply_text("Mohon kirimkan lokasi Anda yang valid melalui fitur lokasi Telegram. Jika tidak, ketik /cancel untuk membatalkan.")
        return INPUT_LOCATION

    user = update.effective_user
    location = update.message.location
    latitude = location.latitude
    longitude = location.longitude
    
    # Konversi koordinat menjadi link Google Maps
    # URL ini adalah "share link" yang universal dan berfungsi baik
    Maps_link = f"https://maps.app.goo.gl/?link=https://maps.google.com/maps/search/{latitude},{longitude}"

    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')
    wilayah = context.user_data.get('wilayah', 'N/A')
    timestamp_lokal = get_local_timestamp() # Menggunakan fungsi timestamp lokal

    # Data yang akan ditulis ke Google Sheet
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
        # Inisialisasi Google Sheet dan tambahkan baris
        gsheet_client = init_gsheet()
        sheet = gsheet_client.sheet1 # Pastikan Anda ingin menulis ke sheet pertama
        sheet.append_row(row_data)
        logger.info(f"Check-in recorded for {user.id} at {timestamp_lokal} - {nama_lokasi}, {wilayah}")
        
        # Konfirmasi ke pengguna
        update.message.reply_text(
            "✅ Data check-in berhasil dicatat!\n\n"
            f"👤 User ID: `{user.id}`\n"
            f"🧑‍💻 Nama: `{user.first_name or 'N/A'}`\n" # Handle None for first_name
            f"📧 Username: `@{user.username}`\n"
            f"⏰ Waktu: `{timestamp_lokal}`\n"
            f"🏷️ Nama Lokasi: *{nama_lokasi}*\n"
            f"🌍 Wilayah: *{wilayah}*\n"
            f"📍 Lokasi Google Maps: [Link Lokasi]({Maps_link})\n\n"
            "Terima kasih!",
            parse_mode='Markdown',
            disable_web_page_preview=True # Untuk mencegah preview link Google Maps
        )
    except Exception as e:
        logger.error(f"Gagal mencatat data check-in: {str(e)}")
        update.message.reply_text("❌ Gagal mencatat data. Mohon coba lagi nanti.")

    # Akhiri percakapan
    return ConversationHandler.END

def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Membatalkan percakapan check-in."""
    update.message.reply_text("Proses check-in dibatalkan.")
    return ConversationHandler.END

# ======================
# MENU BOT (set_my_commands)
# ======================
# Hapus 'async' karena python-telegram-bot 13.x tidak menggunakan async untuk set_my_commands
def set_bot_commands_sync(dispatcher):
    """Menyetel perintah bot untuk ditampilkan di menu secara sinkron."""
    commands = [
        BotCommand("start", "Mulai bot dan lihat sambutan"),
        BotCommand("checkin", "Mulai proses check-in lokasi dan wilayah."),
        BotCommand("menu", "Tampilkan daftar perintah bot ini"),
        BotCommand("myid", "Lihat ID Telegram Anda"),
        BotCommand("help", "Bantuan dan informasi bot"),
        # Perintah admin/owner (hanya terlihat di menu jika ada user yang berinteraksi)
        BotCommand("add_user", "Admin: Tambah pengguna terotorisasi"),
        BotCommand("remove_user", "Admin: Hapus pengguna terotorisasi"),
        BotCommand("list_users", "Admin: Daftar pengguna terotorisasi"),
        BotCommand("add_admin", "Owner: Tambah admin"),
        BotCommand("remove_admin", "Owner: Hapus admin"),
        BotCommand("list_admins", "Owner: Daftar admin")
    ]
    
    # Panggil metode set_my_commands secara sinkron (tanpa 'await')
    try:
        success = dispatcher.bot.set_my_commands(commands)
        if success:
            logger.info("Bot commands have been set successfully.")
        else:
            logger.warning("Failed to set bot commands. Telegram API might return False.")
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")
    # Tidak perlu mengembalikan apapun

@restricted
def show_menu(update: Update, context: CallbackContext):
    """Menampilkan menu perintah."""
    msg = (
        "Berikut adalah perintah yang bisa Anda gunakan:\n"
        "/start - Memulai bot dan sambutan\n"
        "/checkin
