import os
import logging
from datetime import datetime
import pytz
import gspread
from telegram import Update, BotCommand, ReplyKeyboardRemove, KeyboardButton
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
INPUT_NAMA_LOKASI, INPUT_WILAYAH, INPUT_LOCATION = range(3)

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
# MANAJEMEN PENGGUNA (OWNER, ADMIN, USER) - SEKARANG DARI GOOGLE SHEETS
# ======================
OWNER_ID = int(os.getenv('OWNER_ID', '0')) # Owner_ID masih dari ENV
user_roles_cache = {} # Cache untuk menyimpan user roles dari Google Sheet

def get_local_timestamp(tz_name: str = 'Asia/Jakarta') -> str:
    """Mendapatkan timestamp lokal sesuai zona waktu (standar GMT+7 / Asia/Jakarta)."""
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S")
    except pytz.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: {tz_name}. Falling back to UTC.")
        return datetime.now(pytz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def get_credentials():
    try:
        private_key = os.getenv('GSHEET_PRIVATE_KEY', '').replace('\\n', '\n')
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----') or \
           not private_key.strip().endswith('-----END PRIVATE KEY-----'):
            raise ValueError("Invalid private key format or missing BEGIN/END markers")

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
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
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

def load_user_roles_from_gsheet():
    global user_roles_cache
    try:
        gsheet = init_gsheet()
        users_sheet = gsheet.worksheet("Users") # Nama sheet harus "Users"
        records = users_sheet.get_all_records() # Mendapatkan semua baris sebagai list of dict
        
        # Kosongkan cache lama
        user_roles_cache = {}
        
        for record in records:
            user_id_str = str(record.get('user_id')).strip()
            role = str(record.get('role')).strip().lower()
            
            if user_id_str and user_id_str.isdigit():
                user_id = int(user_id_str)
                user_roles_cache[user_id] = {
                    'role': role,
                    'first_name': record.get('first_name', ''),
                    'username': record.get('username', '')
                }
        logger.info(f"User roles loaded from Google Sheet. Loaded {len(user_roles_cache)} entries.")
        # DEBUG: Menampilkan isi cache (HATI-HATI JIKA DAFTARNYA SANGAT BESAR)
        # logger.info(f"DEBUG: user_roles_cache: {user_roles_cache}")
    except gspread.exceptions.SpreadsheetNotFound:
        logger.critical("Google Sheet 'Users' not found. Please ensure the SHEET_URL is correct and the sheet named 'Users' exists.")
        # Jika sheet tidak ditemukan, kita tidak bisa melanjutkan, bot mungkin akan crash atau tidak berfungsi
        # Mungkin tambahkan logika untuk membalas ke owner bot
    except Exception as e:
        logger.critical(f"Failed to load user roles from Google Sheet: {str(e)}")
        # Jika ada error, bot mungkin tidak bisa memverifikasi izin
        # Mungkin tambahkan logika untuk membalas ke owner bot

def get_user_role(user_id: int) -> str:
    """Mendapatkan peran pengguna dari cache."""
    if user_id == OWNER_ID:
        return 'owner'
    return user_roles_cache.get(user_id, {}).get('role', 'unauthorized')

def is_owner(user_id: int) -> bool:
    return get_user_role(user_id) == 'owner'

def is_admin(user_id: int) -> bool:
    role = get_user_role(user_id)
    return role in ['owner', 'admin']

def is_authorized_user(user_id: int) -> bool:
    role = get_user_role(user_id)
    return role in ['owner', 'admin', 'authorized_user']

def restricted(func):
    """Decorator untuk membatasi akses ke pengguna terotorisasi (owner, admin, authorized_user)."""
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not update.effective_chat or not update.effective_user:
            logger.warning(f"No effective chat or user for restricted command. Update: {update.update_id}")
            return
        user_id = update.effective_user.id
        if not is_authorized_user(user_id):
            logger.warning(f"Unauthorized access attempt by user {user_id} ({update.effective_user.username}) for command {update.message.text if update.message else 'unknown'}")
            update.message.reply_text("Maaf, Anda tidak memiliki izin untuk menggunakan perintah ini. Silakan hubungi admin bot untuk akses.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def admin_restricted(func):
    """Decorator untuk membatasi akses ke admin dan owner."""
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not update.effective_user:
            logger.warning(f"No effective user for admin restricted command. Update: {update.update_id}")
            return
        user_id = update.effective_user.id
        if not is_admin(user_id):
            logger.warning(f"Admin restricted command attempt by user {user_id} ({update.effective_user.username})")
            update.message.reply_text("Maaf, Anda tidak memiliki izin Admin untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

def owner_restricted(func):
    """Decorator untuk membatasi akses ke owner saja."""
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not update.effective_user:
            logger.warning(f"No effective user for owner restricted command. Update: {update.update_id}")
            return
        user_id = update.effective_user.id
        if not is_owner(user_id):
            logger.warning(f"Owner restricted command attempt by user {user_id} ({update.effective_user.username})")
            update.message.reply_text("Maaf, Anda tidak memiliki izin Owner untuk menggunakan perintah ini.")
            return
        return func(update, context, *args, **kwargs)
    return wrapper

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
    context.user_data['original_chat_id'] = update.effective_chat.id
    update.message.reply_text("🏷️ Baik, mari kita mulai check-in Anda!\n"
                              "Mohon masukkan *Nama Lokasi*:",
                              parse_mode='Markdown')
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
    """Menerima wilayah dan meminta lokasi dengan instruksi manual."""
    wilayah = update.message.text
    if not wilayah:
        update.message.reply_text("Wilayah tidak boleh kosong. Silakan coba lagi.")
        return INPUT_WILAYAH
    context.user_data['wilayah'] = wilayah
    logger.info(f"User {update.effective_user.id} entered Wilayah: {wilayah}")
    
    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')

    update.message.reply_text(
        f"✅ Lokasi: *{nama_lokasi}*\n"
        f"🌍 Wilayah: *{wilayah}*\n\n"
        f"Terakhir, mohon kirim lokasi Anda saat ini dengan menekan tombol lampiran (📎) lalu pilih *Lokasi* dan *'Kirim lokasi saya saat ini'*. Tidak perlu mengirimkan tombol.",
        parse_mode='Markdown'
    )
    return INPUT_LOCATION

@restricted
def checkin_location(update: Update, context: CallbackContext) -> int:
    """Menerima lokasi dan menyimpan
