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
    """Menerima lokasi dan menyimpan semua data, lalu membalas di chat asal."""
    user = update.effective_user
    location = update.message.location
    original_chat_id = context.user_data.get('original_chat_id', update.effective_chat.id)

    if not location:
        context.bot.send_message(
            chat_id=original_chat_id,
            text="Mohon kirimkan lokasi Anda yang valid melalui fitur lokasi Telegram (bukan teks atau foto). Ketik /cancel untuk membatalkan."
        )
        return INPUT_LOCATION

    latitude = location.latitude
    longitude = location.longitude
    
    # Perbaikan link Google Maps untuk kompatibilitas yang lebih baik
    Maps_link = f"http://maps.google.com/maps?q={latitude},{longitude}" 

    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')
    wilayah = context.user_data.get('wilayah', 'N/A')
    timestamp_lokal = get_local_timestamp()

    # Data untuk sheet log check-in (bukan sheet user roles)
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
        # Mengambil sheet PERTAMA (index 0) dari spreadsheet untuk data check-in
        # PASTIKAN SHEET PERTAMA ANDA ADALAH UNTUK CHECK-IN DATA, bukan sheet "Users"
        sheet_checkin_data = gsheet_client.get_worksheet(0) 
        sheet_checkin_data.append_row(row_data)
        logger.info(f"Check-in recorded for {user.id} at {timestamp_lokal} - {nama_lokasi}, {wilayah}")
        
        context.bot.send_message(
            chat_id=original_chat_id,
            text=(
                "✅ Data check-in berhasil dicatat!\n\n"
                f"👤 User: `{user.first_name or 'N/A'}` (`@{user.username}`)\n"
                f"⏰ Waktu: `{timestamp_lokal}`\n"
                f"🏷️ Nama Lokasi: *{nama_lokasi}*\n"
                f"🌍 Wilayah: *{wilayah}*\n"
                f"📍 Lokasi Google Maps: [Link Lokasi]({Maps_link})\n\n"
                "Terima kasih!"
            ),
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Gagal mencatat data check-in: {str(e)}")
        context.bot.send_message(
            chat_id=original_chat_id,
            text="❌ Gagal mencatat data. Mohon coba lagi nanti. Detail error ada di log bot."
        )

    context.user_data.clear() 
    return ConversationHandler.END

def cancel_conversation(update: Update, context: CallbackContext) -> int:
    """Membatalkan percakapan check-in."""
    original_chat_id = context.user_data.get('original_chat_id', update.effective_chat.id)
    context.bot.send_message(chat_id=original_chat_id, text="Proses check-in dibatalkan.")
    context.user_data.clear()
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
            "/list_users - Daftar pengguna terotorisasi (termasuk admin/owner)\n" # Perbarui deskripsi
        )
    if is_owner(user_id):
        msg += (
            "--- Perintah Owner ---\n"
            "/add_admin <id> - Tambah admin\n"
            "/remove_admin <id> - Hapus admin\n"
            "/list_admins - Daftar admin (termasuk owner)\n" # Perbarui deskripsi
        )
    update.message.reply_text(msg, parse_mode='Markdown')

@restricted
def my_id(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)
    update.message.reply_text(f"ID Telegram Anda adalah: `{user_id}`\nPeran Anda: `{current_role.capitalize()}`", parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Bot ini dirancang untuk memudahkan proses check-in sales dengan mencatat nama lokasi, wilayah, dan lokasi geografis ke Google Sheets.\n\n"
        "Untuk memulai, ketik /checkin di grup atau private chat.\n"
        "Saat diminta lokasi, kirimkan lokasi Anda secara manual dari fitur lampiran (📎 Lokasi).\n"
        "Jika ada masalah, pastikan bot memiliki akses ke Google Sheets dan semua variabel lingkungan sudah diatur dengan benar."
    )

# ======================
# COMMANDS UNTUK MANAJEMEN USER (ADMIN/OWNER ONLY) VIA GOOGLE SHEETS
# ======================

def manage_user_role(update: Update, context: CallbackContext, target_role: str, action: str):
    if not context.args:
        update.message.reply_text(f"Penggunaan: /{action}_{target_role} <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
        gsheet = init_gsheet()
        users_sheet = gsheet.worksheet("Users")
        
        # Cari baris user
        # Pastikan kita mendapatkan header terlebih dahulu untuk mapping kolom
        headers = users_sheet.row_values(1) 
        user_id_col_idx = headers.index('user_id') + 1 # Kolom 'user_id'
        role_col_idx = headers.index('role') + 1 # Kolom 'role'
        first_name_col_idx = headers.index('first_name') + 1 if 'first_name' in headers else None
        username_col_idx = headers.index('username') + 1 if 'username' in headers else None
        added_by_id_col_idx = headers.index('added_by_id') + 1 if 'added_by_id' in headers else None
        added_by_name_col_idx = headers.index('added_by_name') + 1 if 'added_by_name' in headers else None
        added_date_col_idx = headers.index('added_date') + 1 if 'added_date' in headers else None


        user_cell = users_sheet.find(str(target_user_id), in_column=user_id_col_idx) # Cari user_id di kolom 'user_id'
        
        current_user = update.effective_user
        current_timestamp = get_local_timestamp()

        if action == 'add':
            if user_cell: # User ditemukan
                current_role = user_roles_cache.get(target_user_id, {}).get('role', 'unauthorized')
                if current_role == 'owner':
                    update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak perlu ditambahkan sebagai {target_role.capitalize()}.")
                    return
                elif current_role == target_role:
                    update.message.reply_text(f"User ID {target_user_id} sudah menjadi {target_role.capitalize()}.")
                    return
                elif target_role == 'admin' and current_role == 'authorized_user':
                    # Tingkatkan dari authorized_user ke admin
                    users_sheet.update_cell(user_cell.row, role_col_idx, target_role)
                    if added_by_id_col_idx: users_sheet.update_cell(user_cell.row, added_by_id_col_idx, str(current_user.id))
                    if added_by_name_col_idx: users_sheet.update_cell(user_cell.row, added_by_name_col_idx, f"{current_user.first_name} (@{current_user.username})")
                    if added_date_col_idx: users_sheet.update_cell(user_cell.row, added_date_col_idx, current_timestamp)
                    update.message.reply_text(f"User ID {target_user_id} berhasil ditingkatkan menjadi {target_role.capitalize()}.")
                elif target_role == 'authorized_user' and current_role in ['owner', 'admin']:
                    update.message.reply_text(f"User ID {target_user_id} adalah {current_role.capitalize()}, sudah otomatis terotorisasi.")
                    return
                else:
                    # Update peran yang ada
                    users_sheet.update_cell(user_cell.row, role_col_idx, target_role)
                    if added_by_id_col_idx: users_sheet.update_cell(user_cell.row, added_by_id_col_idx, str(current_user.id))
                    if added_by_name_col_idx: users_sheet.update_cell(user_cell.row, added_by_name_col_idx, f"{current_user.first_name} (@{current_user.username})")
                    if added_date_col_idx: users_sheet.update_cell(user_cell.row, added_date_col_idx, current_timestamp)
                    update.message.reply_text(f"Peran User ID {target_user_id} berhasil diupdate menjadi {target_role.capitalize()}.")
            else: # User belum ada, tambahkan baris baru
                if target_user_id == OWNER_ID: # Jika mencoba menambah owner ID yang sudah ada di ENV
                    update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak perlu ditambahkan secara manual.")
                    return
                
                new_row_values = [""] * len(headers) # Inisialisasi baris kosong
                new_row_values[user_id_col_idx - 1] = str(target_user_id)
                new_row_values[role_col_idx - 1] = target_role
                
                try:
                    chat_member = context.bot.get_chat_member(chat_id=target_user_id, user_id=target_user_id).user
                    if first_name_col_idx: new_row_values[first_name_col_idx - 1] = chat_member.first_name or ''
                    if username_col_idx: new_row_values[username_col_idx - 1] = chat_member.username or ''
                except Exception as e:
                    logger.warning(f"Could not fetch user info for {target_user_id}: {e}")
                    # Biarkan kosong jika tidak bisa diambil

                if added_by_id_col_idx: new_row_values[added_by_id_col_idx - 1] = str(current_user.id)
                if added_by_name_col_idx: new_row_values[added_by_name_col_idx - 1] = f"{current_user.first_name} (@{current_user.username})"
                if added_date_col_idx: new_row_values[added_date_col_idx - 1] = current_timestamp

                users_sheet.append_row(new_row_values)
                update.message.reply_text(f"User ID {target_user_id} berhasil ditambahkan sebagai {target_role.capitalize()}.")
            
        elif action == 'remove':
            if not user_cell:
                update.message.reply_text(f"User ID {target_user_id} tidak ditemukan dalam daftar peran pengguna.")
                return
            
            # Jika user_id yang ingin dihapus adalah OWNER_ID yang ada di ENV
            if target_user_id == OWNER_ID:
                update.message.reply_text(f"Owner tidak bisa dihapus dari daftar peran.")
                return

            current_role = user_roles_cache.get(target_user_id, {}).get('role', 'unauthorized')
            
            # Verifikasi apakah peran yang ingin dihapus sesuai
            if current_role == target_role:
                users_sheet.delete_rows(user_cell.row)
                update.message.reply_text(f"User ID {target_user_id} berhasil dihapus dari daftar {target_role.capitalize()}.")
            elif target_role == 'admin' and current_role == 'owner':
                update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak bisa dihapus dari daftar Admin.")
            elif target_role == 'authorized_user' and current_role in ['owner', 'admin']:
                 update.message.reply_text(f"User ID {target_user_id} adalah {current_role.capitalize()}, tidak bisa dihapus dari daftar Pengguna Terotorisasi secara langsung. Gunakan /remove_admin jika dia admin.")
            else:
                update.message.reply_text(f"User ID {target_user_id} memiliki peran '{current_role.capitalize()}', bukan '{target_role.capitalize()}'.")
        
        # Setelah perubahan, muat ulang cache
        load_user_roles_from_gsheet()
        logger.info(f"{action.capitalize()} {target_role} completed for {target_user_id}. Cache reloaded.")

    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")
    except Exception as e:
        logger.error(f"Error managing user role: {str(e)}")
        update.message.reply_text(f"Terjadi kesalahan saat mencoba {action} {target_role}. Mohon coba lagi. Detail: {e}")

@owner_restricted
def add_admin(update: Update, context: CallbackContext):
    manage_user_role(update, context, 'admin', 'add')

@owner_restricted
def remove_admin(update: Update, context: CallbackContext):
    manage_user_role(update, context, 'admin', 'remove')

@admin_restricted
def add_user(update: Update, context: CallbackContext):
    manage_user_role(update, context, 'authorized_user', 'add')

@admin_restricted
def remove_user(update: Update, context: CallbackContext):
    manage_user_role(update, context, 'authorized_user', 'remove')

@admin_restricted
def list_users(update: Update, context: CallbackContext):
    # Mengambil dari cache yang sudah dimuat
    msg = "Daftar Semua Pengguna Bot (termasuk Owner & Admin):\n"
    if not user_roles_cache:
        msg += "Tidak ada pengguna terdaftar (atau gagal memuat dari Google Sheet)."
    else:
        # Urutkan berdasarkan peran: owner -> admin -> authorized_user -> unauthorized
        sorted_users = sorted(user_roles_cache.items(), 
                              key=lambda item: (
                                  0 if item[1].get('role') == 'owner' else
                                  1 if item[1].get('role') == 'admin' else
                                  2 if item[1].get('role') == 'authorized_user' else 3
                              ))
        for uid, data in sorted_users:
            role = data.get('role', 'unknown')
            first_name = data.get('first_name', 'N/A')
            username = data.get('username', 'N/A')
            msg += f"- `{uid}` | *{role.capitalize()}* | {first_name} (`@{username}`)\n"
    update.message.reply_text(msg, parse_mode='Markdown')


@owner_restricted
def list_admins(update: Update, context: CallbackContext):
    msg = "Daftar Admin dan Owner:\n"
    found_admins = False
    
    # Tambahkan owner dari ENV (dan pastikan ada di cache) terlebih dahulu
    owner_info = user_roles_cache.get(OWNER_ID, {})
    owner_name = owner_info.get('first_name', 'N/A')
    owner_username = owner_info.get('username', 'N/A')
    # Pastikan owner_id ini selalu ada dalam daftar jika OWNER_ID di ENV valid
    if OWNER_ID != 0: # Cek jika OWNER_ID sudah diset
        msg += f"- `{OWNER_ID}` | *Owner* | {owner_name} (`@{owner_username}`)\n"
        found_admins = True

    # Tambahkan admin dari cache
    for uid, data in user_roles_cache.items():
        if data.get('role') == 'admin': # Hanya tampilkan admin (owner sudah di atas)
            first_name = data.get('first_name', 'N/A')
            username = data.get('username', 'N/A')
            msg += f"- `{uid}` | *Admin* | {first_name} (`@{username}`)\n"
            found_admins = True
    
    if not found_admins and OWNER_ID == 0: # Hanya jika tidak ada admin dan OWNER_ID tidak diset
        msg += "Tidak ada admin atau owner yang terdaftar."
    elif not found_admins: # Hanya jika tidak ada admin dan OWNER_ID diset
        msg += "Tidak ada admin yang terdaftar selain owner."
    
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
        
        # Inisialisasi Google Sheets dan muat peran pengguna saat bot start
        load_user_roles_from_gsheet()
        
        set_bot_commands_sync(dispatcher)

        dispatcher.add_handler(CommandHandler("start", start_command))
        dispatcher.add_handler(CommandHandler("menu", show_menu))
        dispatcher.add_handler(CommandHandler("myid", my_id))
        dispatcher.add_handler(CommandHandler("help", help_command))

        dispatcher.add_handler(CommandHandler("add_admin", add_admin))
        dispatcher.add_handler(CommandHandler("remove_admin", remove_admin))
        dispatcher.add_handler(CommandHandler("list_admins", list_admins))
        dispatcher.add_handler(CommandHandler("add_user", add_user))
        dispatcher.add_handler(CommandHandler("remove_user", remove_user))
        dispatcher.add_handler(CommandHandler("list_users", list_users))
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('checkin', checkin_start)],
            states={
                INPUT_NAMA_LOKASI: [MessageHandler(Filters.text & ~Filters.command, checkin_nama_lokasi)],
                INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, checkin_wilayah)],
                INPUT_LOCATION: [MessageHandler(Filters.location & ~Filters.command, checkin_location)], 
            },
            fallbacks=[CommandHandler('cancel', cancel_conversation)],
            allow_reentry=True
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
    # Coba inisialisasi gsheet untuk memastikan koneksi ke gsheet berjalan
    try:
        gsheet = init_gsheet()
        # Coba baca sheet agar yakin koneksi end-to-end
        # Ambil nama sheet pertama sebagai dummy read
        sheet_name = gsheet.sheet1.title 
        logger.info(f"Health check: Google Sheet '{sheet_name}' accessible.")
        return "OK", 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return f"Health check failed: {e}", 500

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
