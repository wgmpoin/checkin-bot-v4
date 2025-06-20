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
PORT = int(os.environ.get('PORT', 8000)) # Default port 8000
WEBHOOK_PATH = TELEGRAM_TOKEN
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{WEBHOOK_PATH}"

# updater = Updater(token=TELEGRAM_TOKEN, use_context=True) # Akan diinisialisasi di main()
# dispatcher = updater.dispatcher # Akan diinisialisasi di main()

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
    """Mengambil kredensial dari environment variables."""
    try:
        private_key = os.getenv('GSHEET_PRIVATE_KEY', '').replace('\\n', '\n')
        
        # Validasi format private_key yang lebih ketat
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----') or \
           not private_key.strip().endswith('-----END PRIVATE KEY-----'):
            raise ValueError("GSHEET_PRIVATE_KEY is not in the correct PEM format or missing BEGIN/END markers.")

        creds_dict = {
            "type": "service_account",
            "project_id": os.getenv('GSHEET_PROJECT_ID'),
            "private_key_id": os.getenv('GSHEET_PRIVATE_KEY_ID'),
            "private_key": private_key,
            "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),
            "client_id": os.getenv('GSHEET_CLIENT_ID'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            # Client x509 cert url bisa dibangun dari client email
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GSHEET_CLIENT_EMAIL', '').replace('@', '%40')}"
        }
        
        # Validasi field penting
        for key in ["project_id", "private_key_id", "client_email", "client_id", "token_uri"]:
            if not creds_dict.get(key):
                raise ValueError(f"Missing required credential field: {key}")

        return creds_dict
    except Exception as e:
        logger.error(f"Credential setup failed: {str(e)}")
        raise

def init_gsheet():
    """Menginisialisasi koneksi ke Google Sheet."""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = get_credentials()
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        sheet_url = os.getenv('SHEET_URL')
        if not sheet_url:
            raise ValueError("SHEET_URL environment variable not set. Please provide the full URL of your Google Sheet.")
        
        return client.open_by_url(sheet_url)
    except Exception as e:
        logger.critical(f"Google Sheets init failed: {str(e)}. Pastikan SHEET_URL benar dan Service Account memiliki izin Editor.")
        raise

def load_user_roles_from_gsheet():
    """Memuat peran pengguna dari Google Sheet 'Users' ke cache."""
    global user_roles_cache
    try:
        gsheet = init_gsheet()
        users_sheet = gsheet.worksheet("Users") # Nama sheet harus "Users"
        records = users_sheet.get_all_records()
        
        user_roles_cache = {} # Kosongkan cache lama
        
        for record in records:
            user_id_str = str(record.get('user_id')).strip()
            role = str(record.get('role', 'unauthorized')).strip().lower() # Default 'unauthorized' jika role kosong
            
            if user_id_str and user_id_str.isdigit():
                user_roles_cache[int(user_id_str)] = {
                    'role': role,
                    'first_name': str(record.get('first_name', '')).strip(),
                    'username': str(record.get('username', '')).strip()
                }
        logger.info(f"User roles loaded from Google Sheet. Loaded {len(user_roles_cache)} entries.")
    except gspread.exceptions.WorksheetNotFound:
        logger.critical("Google Sheet 'Users' tab not found. Please ensure your Google Sheet has a tab named 'Users' (case-sensitive).")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        logger.critical("Google Spreadsheet not found. Please ensure the SHEET_URL environment variable is correct and the Service Account has 'Editor' access.")
        raise
    except Exception as e:
        logger.critical(f"Failed to load user roles from Google Sheet: {str(e)}. Please check Google Cloud Console API status and Service Account permissions.")
        raise

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

# ======================
# HANDLER COMMANDS & CONVERSATION
# ======================

def start_command(update: Update, context: CallbackContext):
    """Handler untuk perintah /start."""
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)
    
    msg = "👋 Halo! Saya Bot Check-in Sales Anda.\n"
    if current_role == 'unauthorized':
        msg += "Anda belum terdaftar. Silakan hubungi admin Anda untuk mendapatkan akses."
    else:
        msg += (
            "Gunakan perintah di bawah ini untuk berinteraksi:\n"
            "/checkin - Mulai proses check-in lokasi dan wilayah.\n"
            "/menu - Tampilkan menu perintah."
        )
    update.message.reply_text(msg)

def show_menu(update: Update, context: CallbackContext):
    """Menampilkan menu perintah yang relevan berdasarkan peran pengguna."""
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)

    msg = "Berikut adalah perintah yang bisa Anda gunakan:\n\n"
    
    # Perintah umum untuk semua pengguna terdaftar
    if current_role in ['owner', 'admin', 'authorized_user']:
        msg += "*/start* - Memulai bot dan sambutan\n"
        msg += "*/checkin* - Memulai proses check-in lokasi dan wilayah\n"
        msg += "*/menu* - Menampilkan menu perintah ini\n"
        msg += "*/myid* - Melihat ID Telegram Anda\n"
        msg += "*/kontak* - Menampilkan informasi kontak penting\n"
        msg += "*/help* - Bantuan dan informasi bot\n\n"
    
    # Perintah untuk Admin dan Owner
    if is_admin(user_id):
        msg += (
            "--- Perintah Admin ---\n"
            "*/add_user <id>* - Tambah pengguna terotorisasi\n"
            "*/remove_user <id>* - Hapus pengguna terotorisasi\n"
            "*/list_users* - Daftar pengguna terotorisasi (termasuk admin/owner)\n"
        )
    
    # Perintah untuk Owner saja
    if is_owner(user_id):
        msg += (
            "--- Perintah Owner ---\n"
            "*/add_admin <id>* - Tambah admin\n"
            "*/remove_admin <id>* - Hapus admin\n"
            "*/list_admins* - Daftar admin (termasuk owner)\n"
        )
    
    if current_role == 'unauthorized':
        msg = "Maaf, Anda belum terdaftar. Silakan hubungi admin Anda untuk mendapatkan akses."

    update.message.reply_text(msg, parse_mode='Markdown')

def my_id(update: Update, context: CallbackContext):
    """Menampilkan ID Telegram dan peran pengguna."""
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)
    update.message.reply_text(f"ID Telegram Anda adalah: `{user_id}`\nPeran Anda: `{current_role.capitalize()}`", parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext):
    """Menampilkan pesan bantuan."""
    update.message.reply_text(
        "Bot ini dirancang untuk memudahkan proses check-in sales dengan mencatat nama lokasi, wilayah, dan lokasi geografis ke Google Sheets.\n\n"
        "Untuk memulai, ketik /checkin di private chat dengan bot ini. Lokasi harus dikirim melalui fitur lampiran (📎 Lokasi) Telegram.\n"
        "Untuk melihat perintah yang tersedia sesuai peran Anda, ketik /menu."
    )

def contact(update: Update, context: CallbackContext) -> None:
    """Displays important contact information."""
    msg = "*Perintah:* /kontak\n\n"
    msg += "*Hotline Bebas Pulsa:* [08001119999](tel:+628001119999)\n"
    # Menggunakan link tel: atau teks biasa untuk nomor Telegram karena ID belum tersedia
    msg += "*Hotline:* [+6281231447777](tel:+6281231447777) (Kontak Telegram)\n" 
    msg += "*Email Support:* [support@mpoin.com](mailto:support@mpoin.com)\n\n"
    
    msg += "*PELAPORAN PELANGGARAN*\n"
    msg += "Laporkan kepada Internal Audit secara jelas & lengkap melalui:\n"
    # Menggunakan link tel: atau teks biasa untuk nomor Telegram karena ID belum tersedia
    msg += "[+62 812 3445 0505](tel:+6281234450505) | " 
    msg += "[+62 822 2909 3495](tel:+6282229093495) | "
    msg += "[+62 822 2930 9341](tel:+6282229309341)\n"
    msg += "*Email Pengaduan:* [pengaduanmpoin@gmail.com](mailto:pengaduanmpoin@gmail.com)\n\n"

    msg += "*HRD*\n"
    # Menggunakan link tel: atau teks biasa untuk nomor Telegram karena ID belum tersedia
    msg += "[+6281228328631](tel:+6281228328631)\n"
    msg += "*Email HRD:* [hrdepartment@mpoin.com](mailto:hrdepartment@mpoin.com)\n\n"

    msg += "*Sosial Media:*\n"
    msg += "Tiktok: @mpoin.id\n"
    msg += "IG: [@mpoinpipaku.id](https://www.instagram.com/mpoinpipaku.id)\n"
    msg += "FB: Mpoinpipakuid\n"
    msg += "Website: [www.mpoin.com](https://mpoin.com)"

    update.message.reply_text(msg, parse_mode='Markdown')

# ======================
# CONVERSATION HANDLERS
# ======================

def checkin_start(update: Update, context: CallbackContext) -> int:
    """Memulai percakapan check-in."""
    if not is_authorized_user(update.effective_user.id):
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk memulai check-in. Silakan hubungi admin Anda.")
        return ConversationHandler.END

    logger.info(f"Checkin started by user {update.effective_user.id}")
    context.user_data['original_chat_id'] = update.effective_chat.id # Simpan chat ID asal
    update.message.reply_text("🏷️ Baik, mari kita mulai check-in Anda!\n"
                              "Mohon masukkan *Nama Lokasi*:",
                              parse_mode='Markdown')
    return INPUT_NAMA_LOKASI

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

def checkin_location(update: Update, context: CallbackContext) -> int:
    """Menerima lokasi geografis dan menyimpan data check-in."""
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
    Maps_link = f"http://maps.google.com/maps?q={latitude},{longitude}" 

    nama_lokasi = context.user_data.get('nama_lokasi', 'N/A')
    wilayah = context.user_data.get('wilayah', 'N/A')
    timestamp_lokal = get_local_timestamp()

    # Data untuk sheet 'Check-in Data' (tab pertama)
    row_data = [
        str(user.id),                  # USER ID
        user.first_name or '',         # NAMA
        user.username or '',           # USERNAME
        timestamp_lokal,               # TIMESTAMP
        nama_lokasi,                   # NAMA LOKASI
        wilayah,                       # WILAYAH
        Maps_link                      # GOOGLE MAP
    ]

    try:
        gsheet_client = init_gsheet()
        checkin_sheet = gsheet_client.get_worksheet(0) # Mengambil sheet PERTAMA (index 0)
        checkin_sheet.append_row(row_data)
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
# COMMANDS UNTUK MANAJEMEN USER (ADMIN/OWNER ONLY) VIA GOOGLE SHEETS
# ======================

def manage_user_role(update: Update, context: CallbackContext, target_role: str, action: str):
    """Fungsi pembantu untuk menambah/menghapus peran pengguna."""
    user_id_caller = update.effective_user.id
    if not is_admin(user_id_caller) and not (action == 'add' and target_role == 'admin' and is_owner(user_id_caller)):
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk melakukan tindakan ini.")
        return

    if not context.args:
        update.message.reply_text(f"Penggunaan: /{action}_{target_role.replace('authorized_user', 'user')} <user_id>")
        return

    try:
        target_user_id = int(context.args[0])
        gsheet = init_gsheet()
        users_sheet = gsheet.worksheet("Users")
        
        headers = users_sheet.row_values(1) 
        user_id_col_idx = headers.index('user_id') + 1 
        role_col_idx = headers.index('role') + 1 
        first_name_col_idx = headers.index('first_name') + 1 if 'first_name' in headers else None
        username_col_idx = headers.index('username') + 1 if 'username' in headers else None
        added_by_id_col_idx = headers.index('added_by_id') + 1 if 'added_by_id' in headers else None
        added_by_name_col_idx = headers.index('added_by_name') + 1 if 'added_by_name' in headers else None
        added_date_col_idx = headers.index('added_date') + 1 if 'added_date' in headers else None


        user_cell = None
        all_users = users_sheet.get_all_records()
        for i, record in enumerate(all_users):
            if str(record.get('user_id')) == str(target_user_id):
                user_cell = users_sheet.cell(i + 2, user_id_col_idx) # +2 karena header dan 0-index
                break
        
        current_user = update.effective_user
        current_timestamp = get_local_timestamp()

        if action == 'add':
            if user_cell: # User ditemukan
                current_role_in_sheet = users_sheet.cell(user_cell.row, role_col_idx).value.lower()
                
                if current_role_in_sheet == 'owner':
                    update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak perlu ditambahkan sebagai {target_role.replace('authorized_user', 'user').capitalize()}.")
                    return
                elif current_role_in_sheet == target_role:
                    update.message.reply_text(f"User ID {target_user_id} sudah menjadi {target_role.replace('authorized_user', 'user').capitalize()}.")
                    return
                elif target_role == 'admin' and current_role_in_sheet == 'authorized_user':
                    users_sheet.update_cell(user_cell.row, role_col_idx, target_role)
                    if added_by_id_col_idx: users_sheet.update_cell(user_cell.row, added_by_id_col_idx, str(current_user.id))
                    if added_by_name_col_idx: users_sheet.update_cell(user_cell.row, added_by_name_col_idx, f"{current_user.first_name} (@{current_user.username})")
                    if added_date_col_idx: users_sheet.update_cell(user_cell.row, added_date_col_idx, current_timestamp)
                    update.message.reply_text(f"User ID {target_user_id} berhasil ditingkatkan menjadi {target_role.capitalize()}.")
                elif target_role == 'authorized_user' and current_role_in_sheet in ['owner', 'admin']:
                    update.message.reply_text(f"User ID {target_user_id} adalah {current_role_in_sheet.capitalize()}, sudah otomatis terotorisasi.")
                    return
                else: # Update peran yang ada (misal dari admin ke user, atau sebaliknya jika diizinkan)
                    users_sheet.update_cell(user_cell.row, role_col_idx, target_role)
                    if added_by_id_col_idx: users_sheet.update_cell(user_cell.row, added_by_id_col_idx, str(current_user.id))
                    if added_by_name_col_idx: users_sheet.update_cell(user_cell.row, added_by_name_col_idx, f"{current_user.first_name} (@{current_user.username})")
                    if added_date_col_idx: users_sheet.update_cell(user_cell.row, added_date_col_idx, current_timestamp)
                    update.message.reply_text(f"Peran User ID {target_user_id} berhasil diupdate menjadi {target_role.replace('authorized_user', 'user').capitalize()}.")
            else: # User belum ada, tambahkan baris baru
                if target_user_id == OWNER_ID:
                    update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak perlu ditambahkan secara manual.")
                    return
                
                new_row_values = [""] * len(headers) 
                new_row_values[user_id_col_idx - 1] = str(target_user_id)
                new_row_values[role_col_idx - 1] = target_role
                
                try:
                    chat_member = context.bot.get_chat_member(chat_id=target_user_id, user_id=target_user_id).user
                    if first_name_col_idx: new_row_values[first_name_col_idx - 1] = chat_member.first_name or ''
                    if username_col_idx: new_row_values[username_col_idx - 1] = chat_member.username or ''
                except Exception as e:
                    logger.warning(f"Could not fetch user info for {target_user_id}: {e}")

                if added_by_id_col_idx: new_row_values[added_by_id_col_idx - 1] = str(current_user.id)
                if added_by_name_col_idx: new_row_values[added_by_name_col_idx - 1] = f"{current_user.first_name} (@{current_user.username})"
                if added_date_col_idx: new_row_values[added_date_col_idx - 1] = current_timestamp

                users_sheet.append_row(new_row_values)
                update.message.reply_text(f"User ID {target_user_id} berhasil ditambahkan sebagai {target_role.replace('authorized_user', 'user').capitalize()}.")
            
        elif action == 'remove':
            if not user_cell:
                update.message.reply_text(f"User ID {target_user_id} tidak ditemukan dalam daftar peran pengguna.")
                return
            
            if target_user_id == OWNER_ID:
                update.message.reply_text(f"Owner tidak bisa dihapus dari daftar peran.")
                return

            current_role_in_sheet = users_sheet.cell(user_cell.row, role_col_idx).value.lower()
            
            if current_role_in_sheet == target_role:
                users_sheet.delete_rows(user_cell.row)
                update.message.reply_text(f"User ID {target_user_id} berhasil dihapus dari daftar {target_role.replace('authorized_user', 'user').capitalize()}.")
            elif target_role == 'admin' and current_role_in_sheet == 'owner':
                update.message.reply_text(f"User ID {target_user_id} adalah Owner, tidak bisa dihapus dari daftar Admin.")
            elif target_role == 'authorized_user' and current_role_in_sheet in ['owner', 'admin']:
                 update.message.reply_text(f"User ID {target_user_id} adalah {current_role_in_sheet.capitalize()}, tidak bisa dihapus dari daftar Pengguna Terotorisasi secara langsung. Gunakan /remove_admin jika dia admin.")
            else:
                update.message.reply_text(f"User ID {target_user_id} memiliki peran '{current_role_in_sheet.capitalize()}', bukan '{target_role.replace('authorized_user', 'user').capitalize()}'.")
        
        load_user_roles_from_gsheet()
        logger.info(f"{action.capitalize()} {target_role.replace('authorized_user', 'user')} completed for {target_user_id}. Cache reloaded.")

    except ValueError:
        update.message.reply_text("User ID harus berupa angka.")
    except Exception as e:
        logger.error(f"Error managing user role for {target_user_id}: {str(e)}")
        update.message.reply_text(f"Terjadi kesalahan saat mencoba {action} {target_role.replace('authorized_user', 'user')}. Mohon coba lagi. Detail: {e}")

# Fungsi helper untuk wrapper permission
def _check_permission(update: Update, context: CallbackContext, required_role: str) -> bool:
    if not update.effective_user:
        logger.warning(f"No effective user for permission check. Update: {update.update_id}")
        return False
    user_id = update.effective_user.id
    current_role = get_user_role(user_id)

    if required_role == 'authorized_user' and not is_authorized_user(user_id):
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk menggunakan perintah ini. Silakan hubungi admin bot untuk akses.")
        return False
    elif required_role == 'admin' and not is_admin(user_id):
        update.message.reply_text("Maaf, Anda tidak memiliki izin Admin untuk menggunakan perintah ini.")
        return False
    elif required_role == 'owner' and not is_owner(user_id):
        update.message.reply_text("Maaf, Anda tidak memiliki izin Owner untuk menggunakan perintah ini.")
        return False
    return True

def add_admin(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'owner'):
        manage_user_role(update, context, 'admin', 'add')

def remove_admin(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'owner'):
        manage_user_role(update, context, 'admin', 'remove')

def add_user(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'admin'):
        manage_user_role(update, context, 'authorized_user', 'add')

def remove_user(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'admin'):
        manage_user_role(update, context, 'authorized_user', 'remove')

def list_users(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'admin'):
        msg = "Daftar Semua Pengguna Bot (termasuk Owner & Admin):\n"
        if not user_roles_cache:
            msg += "Tidak ada pengguna terdaftar (atau gagal memuat dari Google Sheet)."
        else:
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

def list_admins(update: Update, context: CallbackContext):
    if _check_permission(update, context, 'owner'):
        msg = "Daftar Admin dan Owner:\n"
        found_admins = False
        
        owner_info = user_roles_cache.get(OWNER_ID, {})
        owner_name = owner_info.get('first_name', 'N/A')
        owner_username = owner_info.get('username', 'N/A')
        
        if OWNER_ID != 0 and is_owner(OWNER_ID): # Cek jika OWNER_ID diset dan memang owner
            msg += f"- `{OWNER_ID}` | *Owner* | {owner_name} (`@{owner_username}`)\n"
            found_admins = True

        for uid, data in user_roles_cache.items():
            if data.get('role') == 'admin':
                first_name = data.get('first_name', 'N/A')
                username = data.get('username', 'N/A')
                msg += f"- `{uid}` | *Admin* | {first_name} (`@{username}`)\n"
                found_admins = True
        
        if not found_admins and OWNER_ID == 0:
            msg += "Tidak ada admin atau owner yang terdaftar."
        elif not found_admins:
            msg += "Tidak ada admin yang terdaftar selain owner."
        
        update.message.reply_text(msg, parse_mode='Markdown')


# ======================
# MAIN APPLICATION LOGIC
# ======================
def main():
    try:
        logger.info("Starting bot initialization...")
        
        # Pastikan semua ENV vars yang dibutuhkan ada
        required_vars = [
            'TELEGRAM_TOKEN', 'WEBHOOK_HOST', 'OWNER_ID', 'SHEET_URL',
            'GSHEET_PRIVATE_KEY', 'GSHEET_PROJECT_ID', 'GSHEET_PRIVATE_KEY_ID',
            'GSHEET_CLIENT_EMAIL', 'GSHEET_CLIENT_ID'
        ]
        
        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Missing required environment variable: {var}")
        
        # Inisialisasi Updater dan Dispatcher di sini
        updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
        dispatcher = updater.dispatcher

        # Inisialisasi Google Sheets dan muat peran pengguna saat bot start
        load_user_roles_from_gsheet()
        
        # Set commands for Telegram clients
        set_bot_commands_sync(dispatcher)

        # Register command handlers
        dispatcher.add_handler(CommandHandler("start", start_command))
        dispatcher.add_handler(CommandHandler("menu", show_menu))
        dispatcher.add_handler(CommandHandler("myid", my_id))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("kontak", contact)) # New contact command
        
        dispatcher.add_handler(CommandHandler("add_admin", add_admin))
        dispatcher.add_handler(CommandHandler("remove_admin", remove_admin))
        dispatcher.add_handler(CommandHandler("list_admins", list_admins))
        dispatcher.add_handler(CommandHandler("add_user", add_user))
        dispatcher.add_handler(CommandHandler("remove_user", remove_user))
        dispatcher.add_handler(CommandHandler("list_users", list_users))
        
        # Register conversation handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('checkin', checkin_start)],
            states={
                INPUT_NAMA_LOKASI: [MessageHandler(Filters.text & ~Filters.command, checkin_nama_lokasi)],
                INPUT_WILAYAH: [MessageHandler(Filters.text & ~Filters.command, checkin_wilayah)],
                INPUT_LOCATION: [MessageHandler(Filters.location, checkin_location)], 
            },
            fallbacks=[CommandHandler('cancel', cancel_conversation)],
            allow_reentry=True
        )
        dispatcher.add_handler(conv_handler)
        
        # Register error handler
        dispatcher.add_error_handler(error_handler)

        logger.info(f"Bot configured for webhook. Listening on {WEBHOOK_HOST}:{PORT}/{WEBHOOK_PATH}")

    except Exception as e:
        logger.critical(f"Bot crashed during initialization: {str(e)}")
        raise

# ======================
# FLASK WEBHOOK & HEALTH CHECK ENDPOINTS
# ======================
@app.route(f'/{WEBHOOK_PATH}', methods=['POST'])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), updater.bot) # Menggunakan updater.bot
        dispatcher.process_update(update)
    return "ok"

@app.route('/healthz', methods=['GET'])
def health_check():
    try:
        gsheet = init_gsheet()
        # Coba akses sheet pertama
        sheet_name = gsheet.get_worksheet(0).title 
        logger.info(f"Health check: Google Sheet '{sheet_name}' accessible.")
        return "OK", 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return f"Health check failed: {e}", 500

# ======================
# START FLASK SERVER
# ======================
if __name__ == '__main__':
    # Initialize main components (updater, dispatcher) only once
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    main() # Call main function for bot setup

    logger.info(f"Starting Flask server on host 0.0.0.0, port {PORT}") 
    try:
        app.run(host="0.0.0.0", port=PORT)
    except Exception as e:
        logger.critical(f"Flask server crashed: {e}")
