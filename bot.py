import os
import logging
from datetime import datetime
import pytz
import gspread
from telegram import Update, BotCommand
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
        #
