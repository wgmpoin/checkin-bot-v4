import os
import logging
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton # Bot ditambahkan di sini
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from datetime import datetime # datetime diimpor di sini

# --- Konfigurasi Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
SHEET_URL = os.getenv('SHEET_URL')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')

# Konversi OWNER_ID dan PORT ke integer dengan penanganan error
try:
    OWNER_ID = int(os.getenv('OWNER_ID'))
except (ValueError, TypeError):
    logger.critical("Bot berhenti: Variabel lingkungan OWNER_ID tidak ada atau bukan bilangan bulat.")
    exit(1) # Keluar jika OWNER_ID tidak valid

try:
    PORT = int(os.getenv('PORT', 8080)) # Default ke 8080 jika tidak ada atau tidak valid
except (ValueError, TypeError):
    logger.warning("Variabel lingkungan PORT bukan bilangan bulat. Menggunakan port default 8080.")
    PORT = 8080

# Cek keberadaan semua environment variables penting
if not all([TELEGRAM_TOKEN, WEBHOOK_HOST, SHEET_URL, GOOGLE_CREDENTIALS_JSON]):
    logger.critical("Bot berhenti: Hilang satu atau lebih variabel lingkungan yang diperlukan (TELEGRAM_TOKEN, WEBHOOK_HOST, SHEET_URL, GOOGLE_CREDENTIALS_JSON).")
    exit(1)

# --- Google Sheets Initialization ---
gsheet_client = None
admin_ids = set() # Set untuk menyimpan ID admin
user_ids = set()  # Set untuk menyimpan ID semua pengguna terdaftar (role 'user', 'admin', 'owner')

def get_google_sheet_client():
    global gsheet_client
    if gsheet_client:
        return gsheet_client # Return existing client if already initialized

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gsheet_client = gspread.authorize(creds)
        logger.info("Klien Google Sheet berhasil diinisialisasi.")
        return gsheet_client
    except json.JSONDecodeError as e:
        logger.critical(f"Inisialisasi Google Sheets gagal: Kesalahan parsing kredensial JSON. Pastikan GOOGLE_APPLICATION_CREDENTIALS_JSON adalah JSON yang valid. Error: {e}")
        raise # Re-raise for bot to crash, as this is critical
    except Exception as e:
        logger.critical(f"Inisialisasi Google Sheets gagal: {e}. Pastikan SHEET_URL benar dan Akun Layanan memiliki izin Editor.")
        raise # Re-raise for bot to crash, as this is critical

def load_user_roles():
    """Memuat peran pengguna dari Google Sheet 'Users'."""
    global admin_ids, user_ids
    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)

        try:
            worksheet_names = [ws.title for ws in spreadsheet.worksheets()]
            logger.info(f"Berhasil terhubung ke spreadsheet. Ditemukan lembar kerja: {worksheet_names}")
            if "Users" not in worksheet_names:
                logger.critical(f"Lembar kerja 'Users' TIDAK DITEMUKAN di spreadsheet. Lembar kerja yang tersedia: {worksheet_names}")
                raise ValueError("Lembar kerja 'Users' tidak ditemukan.") # Raise an error to stop initialization
        except Exception as e:
            logger.critical(f"Kesalahan daftar lembar kerja di spreadsheet. Harap periksa izin. Error: {e}")
            raise # Re-raise jika tidak bisa membaca daftar worksheet

        worksheet = spreadsheet.worksheet("Users")
        all_data = worksheet.get_all_values()

        admin_ids.clear()
        user_ids.clear()

        # OWNER_ID selalu admin dan user
        admin_ids.add(OWNER_ID)
        user_ids.add(OWNER_ID)

        if not all_data:
            logger.warning("Lembar 'Users' kosong.")
            return

        # Loop melalui baris data, mulai dari baris kedua (index 1)
        for i, row in enumerate(all_data[1:]): # Melewati header (all_data[0])
            row_num = i + 2 # Nomor baris di sheet Google (mulai dari 2)
            try:
                # user_id ada di kolom A (index 0)
                user_id_str = row[0] if len(row) > 0 else None
                if not user_id_str:
                    logger.warning(f"Melewati baris {row_num} di 'Users' karena 'user_id' di kolom A hilang.")
                    continue
                user_id = int(user_id_str.strip()) # Pastikan user_id bisa diubah ke integer

                # role ada di kolom B (index 1)
                role_str = row[1] if len(row) > 1 else None
                if not role_str:
                    logger.warning(f"Melewati baris {row_num} di 'Users' karena 'role' di kolom B hilang.")
                    continue
                role = str(role_str).strip().lower() # Normalisasi role

                # Tambahkan ke set user_ids jika valid
                user_ids.add(user_id)

                # Tambahkan ke set admin_ids jika peran adalah 'admin' atau 'owner'
                if role == 'admin' or user_id == OWNER_ID: # Owner juga dianggap admin
                    admin_ids.add(user_id)
            except (ValueError, TypeError) as e:
                logger.warning(f"Melewati baris {row_num} di lembar 'Users' karena data tidak valid di kolom A (user_id) atau B (role). Data: {row}. Error: {e}")
            except Exception as e:
                logger.error(f"Kesalahan tak terduga saat memproses baris {row_num} di lembar 'Users'. Data: {row}. Error: {e}")

        logger.info(f"Peran pengguna dimuat. Admin: {sorted(list(admin_ids))}. Total Pengguna Terdaftar: {sorted(list(user_ids))}")

    except Exception as e:
        logger.critical(f"Gagal memuat peran pengguna dari Google Sheet (Users). Harap periksa status API Google Cloud Console, izin Akun Layanan, dan akses sheet. Error: {e}")
        raise # Re-raise for bot to crash if user roles cannot be loaded

# --- Dekorator untuk Akses Perintah ---
def admin_only(func):
    """Membatasi akses perintah hanya untuk admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in admin_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk admin.")
            logger.warning(f"Upaya akses tidak sah oleh {update.effective_user.id} ({update.effective_user.username}) ke {func.__name__} (perintah: {update.message.text})")
    return wrapper

def owner_only(func):
    """Membatasi akses perintah hanya untuk pemilik bot."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id == OWNER_ID:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk pemilik bot.")
            logger.warning(f"Upaya akses tidak sah oleh {update.effective_user.id} ({update.effective_user.username}) ke {func.__name__} (perintah: {update.message.text})")
    return wrapper

def registered_user_only(func):
    """Membatasi akses perintah hanya untuk pengguna yang terdaftar di sheet 'Users'."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in user_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, Anda tidak memiliki akses untuk perintah ini. Silakan hubungi admin bot untuk mendaftar.")
            logger.warning(f"Upaya akses tidak sah oleh {update.effective_user.id} ({update.effective_user.username}) ke {func.__name__} (perintah: {update.message.text}). Tidak terdaftar.")
    return wrapper

# --- States for Conversation Handler ---
GET_LOCATION_NAME, GET_REGION, GET_LOCATION_PHOTO = range(3)
ADD_ADMIN_ID, REMOVE_ADMIN_ID, ADD_USER_ID, REMOVE_USER_ID = range(3, 7) # New states for user management

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya bot Sales Check-in Anda. Gunakan /help untuk melihat perintah.")
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) memulai bot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    help_text = (
        "**Perintah yang tersedia:**\n"
        "/start - Memulai bot\n"
        "/help - Menampilkan bantuan ini\n"
        "/checkin - Memulai check-in lokasi\n"
        "/kontak - Menampilkan informasi kontak\n"
        "/myid - Melihat ID Telegram Anda\n"
        "/cancel - Membatalkan proses yang sedang berjalan (misal: check-in)\n"
    )
    if user_id in admin_ids:
        help_text += (
            "\n\n**--- Perintah Admin ---**\n"
            "/reloadroles - Memuat ulang peran pengguna dari Google Sheet\n"
            "/listuser - Melihat ID seluruh pengguna terdaftar (termasuk admin/owner)\n"
            "/listadmins - Melihat ID admin yang terdaftar\n"
        )
    if user_id == OWNER_ID:
        help_text += (
            "\n\n**--- Perintah Owner ---**\n"
            "/addadmin - Menambah user sebagai admin\n"
            "/removeadmin - Menghapus admin\n"
            "/adduser - Menambah user baru\n"
            "/removeuser - Menghapus user\n"
        )
    await update.message.reply_text(help_text, parse_mode='Markdown')
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) meminta bantuan.")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID Telegram Anda: `{update.effective_user.id}`", parse_mode='Markdown')
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) meminta ID-nya.")

@admin_only
async def reload_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        load_user_roles()
        await update.message.reply_text("Peran pengguna berhasil dimuat ulang.")
        logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) memuat ulang peran pengguna.")
    except Exception as e:
        await update.message.reply_text(f"Gagal memuat ulang peran: {e}")
        logger.error(f"Admin {update.effective_user.id} ({update.effective_user.username}) gagal memuat ulang peran: {e}")

@admin_only
async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin_ids:
        await update.message.reply_text("Tidak ada admin yang terdaftar selain pemilik bot.")
        return
    admin_list = "\n".join(map(str, sorted(list(admin_ids))))
    await update.message.reply_text(f"Daftar Admin ID:\n`{admin_list}`", parse_mode='Markdown')
    logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) meminta daftar admin.")

@admin_only
async def listuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not user_ids:
        await update.message.reply_text("Tidak ada pengguna terdaftar.")
        return
    user_list = "\n".join(map(str, sorted(list(user_ids))))
    await update.message.reply_text(f"Daftar Pengguna Terdaftar ID:\n`{user_list}`", parse_mode='Markdown')
    logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) meminta daftar pengguna terdaftar.")

async def kontak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_info = (
        "**HOTLINE**\n"
        "0800-111-9999\n"
        "08123 144 7777\n\n"
        "**PENGADUAN PELANGGARAN**\n"
        "0812 3445 0505\n"
        "0822 2909 3495\n"
        "0822 2930 9341\n\n"
        "IG mpoin.id\n"
        "TikTok mpoin.id\n"
        "FB mpoin.id\n\n"
        "mpoin.com"
    )
    await update.message.reply_text(contact_info, parse_mode='Markdown')
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) meminta informasi kontak.")

@registered_user_only # Hanya pengguna terdaftar yang bisa checkin
async def checkin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai percakapan check-in dan meminta nama lokasi."""
    await update.message.reply_text("Baik, mari kita mulai proses check-in.\nMohon berikan **Nama tempat/lokasi** Anda:")
    context.user_data['checkin_data'] = {} # Inisialisasi user_data untuk check-in ini
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) memulai checkin.")
    return GET_LOCATION_NAME

async def get_location_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menerima nama lokasi dan meminta wilayah."""
    location_name = update.message.text
    context.user_data['checkin_data']['nama_lokasi'] = location_name
    await update.message.reply_text(f"Baik, lokasi Anda: **{location_name}**.\nSekarang, mohon berikan **Wilayah** (misal: Jakarta Pusat, Surabaya, dll.):")
    logger.info(f"Pengguna {update.effective_user.id} memberikan nama lokasi: {location_name}")
    return GET_REGION

async def get_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menerima wilayah dan meminta lokasi."""
    region = update.message.text
    context.user_data['checkin_data']['wilayah'] = region

    # Membuat keyboard kustom dengan tombol "Bagikan Lokasi"
    keyboard = [[KeyboardButton("Bagikan Lokasi Saya", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"Terima kasih. Wilayah Anda: **{region}**.\n"
        "Terakhir, mohon **bagikan lokasi Google Maps Anda** melalui fitur lampiran di Telegram.\n"
        "Anda bisa menekan tombol di bawah atau ikon klip kertas (attachment) lalu pilih 'Lokasi'.",
        reply_markup=reply_markup
    )
    logger.info(f"Pengguna {update.effective_user.id} memberikan wilayah: {region}. Meminta lokasi.")
    return GET_LOCATION_PHOTO

async def get_location_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menerima data lokasi dan menyimpan ke Google Sheet."""
    if update.message.location:
        location = update.message.location
        latitude = location.latitude
        longitude = location.longitude
        # Menggunakan format link Google Maps yang lebih umum dan disarankan
        Maps_link = f"http://maps.google.com/maps?q={latitude},{longitude}" # Perbaikan link Google Maps

        context.user_data['checkin_data']['link_google_map'] = Maps_link

        user_id = update.effective_user.id
        first_name = update.effective_user.first_name if update.effective_user.first_name else ''
        username = update.effective_user.username if update.effective_user.username else ''
        timestamp = update.message.date.strftime("%Y-%m-%d %H:%M:%S")

        nama_lokasi = context.user_data['checkin_data'].get('nama_lokasi', 'N/A')
        wilayah = context.user_data['checkin_data'].get('wilayah', 'N/A')

        try:
            client = get_google_sheet_client()
            spreadsheet = client.open_by_url(SHEET_URL)
            # Pastikan nama sheet yang benar "Check-in Data"
            worksheet = spreadsheet.worksheet("Check-in Data")

            # Data yang akan dimasukkan, cocok dengan kolom sheet:
            # A User id, B nama, C username, D timestamp, E nama lokasi, F wilayah, G link google map
            row_data = [
                str(user_id),
                first_name,
                username,
                timestamp,
                nama_lokasi,
                wilayah,
                Maps_link
            ]

            worksheet.append_row(row_data) # Menambahkan ke baris kosong pertama

            response_message = (
                "Check-in berhasil dicatat!\n\n"
                f"**Nama Tempat:** {nama_lokasi}\n"
                f"**Wilayah:** {wilayah}\n"
                f"**Link Google Maps:** {Maps_link}"
            )
            await update.message.reply_text(response_message)
            logger.info(f"Check-in oleh {user_id} ({username}): Lokasi={nama_lokasi}, Wilayah={wilayah}, Peta={Maps_link}")

        except Exception as e:
            await update.message.reply_text(f"Terjadi kesalahan saat mencatat check-in ke Google Sheet: {e}. Mohon coba lagi nanti.")
            logger.error(f"Kesalahan selama check-in untuk {user_id} ({username}): {e}")

        # Bersihkan user_data dan akhiri percakapan
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Itu bukan lokasi yang valid. Mohon **bagikan lokasi Anda** dengan menekan ikon klip kertas (lampiran) lalu pilih 'Lokasi'."
        )
        logger.warning(f"Pengguna {update.effective_user.id} mengirim pesan non-lokasi selama langkah lokasi.")
        return GET_LOCATION_PHOTO # Tetap di status yang sama sampai lokasi diterima

async def cancel_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Membatalkan percakapan check-in."""
    if 'checkin_data' in context.user_data:
        context.user_data.clear()
        await update.message.reply_text("Proses check-in dibatalkan.")
        logger.info(f"Pengguna {update.effective_user.id} membatalkan check-in.")
    else:
        await update.message.reply_text("Tidak ada proses check-in yang sedang berjalan untuk dibatalkan.")
        logger.info(f"Pengguna {update.effective_user.id} mencoba membatalkan, tetapi tidak ada check-in yang aktif.")
    return ConversationHandler.END

# --- Owner-only User Management Commands ---

async def manage_user_in_sheet(user_id: int, role: str, add_or_remove: str, initiator_id: int, initiator_name: str, bot_obj: Bot = None):
    """
    Fungsi bantu untuk menambah/menghapus/memperbarui peran pengguna di Google Sheet.
    Args:
        user_id (int): ID pengguna yang akan dikelola.
        role (str): Peran yang akan diberikan ('admin' atau 'user').
        add_or_remove (str): 'add', 'remove_admin', 'remove_user'.
        initiator_id (int): ID pengguna yang memulai aksi.
        initiator_name (str): Nama pengguna yang memulai aksi.
        bot_obj (Bot): Objek bot, opsional untuk mengirim notifikasi ke user_id yang diubah.
    Returns:
        tuple: (bool success, str message)
    """
    try:
        client = get_google_sheet_client()
        sheet = client.open_by_url(SHEET_URL).worksheet("Users")

        # Dapatkan semua data untuk mencari ID pengguna
        data = sheet.get_all_values()
        header = data[0] if data else []
        rows = data[1:]

        # Pastikan kolom yang diperlukan ada di header
        required_headers = ['user_id', 'role', 'first_name', 'username', 'added_by_id', 'added_by_name', 'added_date']
        for h in required_headers:
            if h not in header:
                # Jika header tidak ada, tambahkan ke sheet
                # Ini akan terjadi jika sheet baru atau header belum lengkap
                # Namun, lebih baik sheet disiapkan manual dengan header lengkap
                logger.warning(f"Header '{h}' tidak ditemukan di sheet 'Users'. Pastikan header sudah lengkap.")
                # Untuk menghindari IndexError, kita bisa buat indeks default
                # Atau minta user untuk melengkapi header
                return False, f"Kesalahan: Kolom '{h}' tidak ditemukan di sheet 'Users'. Harap lengkapi header sheet."

        user_id_col_idx = header.index('user_id')
        role_col_idx = header.index('role')
        first_name_col_idx = header.index('first_name')
        username_col_idx = header.index('username')
        added_by_id_col_idx = header.index('added_by_id')
        added_by_name_col_idx = header.index('added_by_name')
        added_date_col_idx = header.index('added_date')

        # Cari baris dengan user_id yang cocok
        target_row_idx = -1
        for i, row in enumerate(rows):
            try:
                # Pastikan baris cukup panjang dan user_id_col_idx valid
                if len(row) > user_id_col_idx and int(row[user_id_col_idx]) == user_id:
                    target_row_idx = i + 2 # +2 karena header dan 0-indexed list
                    break
            except (ValueError, IndexError):
                continue # Skip invalid rows or rows that are too short

        if add_or_remove == 'add':
            if target_row_idx != -1:
                # User sudah ada, perbarui perannya
                current_role = sheet.cell(target_row_idx, role_col_idx + 1).value
                if current_role and current_role.lower() == role:
                    return False, f"Pengguna ID `{user_id}` sudah terdaftar sebagai **{role}**."
                sheet.update_cell(target_row_idx, role_col_idx + 1, role)
                logger.info(f"Memperbarui peran pengguna {user_id} menjadi {role}.")
                if bot_obj:
                    try:
                        await bot_obj.send_message(user_id, f"Peran Anda di bot telah diperbarui menjadi **{role.upper()}** oleh admin.")
                    except Exception as e:
                        logger.warning(f"Gagal mengirim notifikasi ke user {user_id}: {e}")
                return True, f"Berhasil memperbarui peran pengguna ID `{user_id}` menjadi **{role}**."
            else:
                # User belum ada, tambahkan baris baru
                # Pastikan ukuran baris cukup besar untuk semua kolom yang diperlukan
                new_row = [''] * (max(user_id_col_idx, role_col_idx, first_name_col_idx, username_col_idx, added_by_id_col_idx, added_by_name_col_idx, added_date_col_idx) + 1)
                new_row[user_id_col_idx] = str(user_id)
                new_row[role_col_idx] = role
                # Ambil info user jika memungkinkan
                user_info = None
                try:
                    # fetch_chat_member lebih tepat untuk mendapatkan info user dari ID
                    member = await bot_obj.get_chat_member(user_id, user_id) if bot_obj else None
                    if member and member.user:
                        user_info = member.user
                except Exception:
                    logger.warning(f"Tidak dapat mengambil info chat_member untuk ID {user_id} saat menambahkan.")

                new_row[first_name_col_idx] = user_info.first_name if user_info and user_info.first_name else 'N/A'
                new_row[username_col_idx] = user_info.username if user_info and user_info.username else 'N/A'
                new_row[added_by_id_col_idx] = str(initiator_id)
                new_row[added_by_name_col_idx] = initiator_name
                new_row[added_date_col_idx] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                sheet.append_row(new_row)
                logger.info(f"Menambahkan pengguna {user_id} dengan peran {role}.")
                if bot_obj:
                    try:
                        await bot_obj.send_message(user_id, f"Anda telah ditambahkan ke bot dengan peran **{role.upper()}** oleh admin.")
                    except Exception as e:
                        logger.warning(f"Gagal mengirim notifikasi ke user {user_id}: {e}")
                return True, f"Berhasil menambahkan pengguna ID `{user_id}` sebagai **{role}**."

        elif add_or_remove == 'remove_admin':
            if target_row_idx != -1:
                current_role = sheet.cell(target_row_idx, role_col_idx + 1).value
                if not current_role or current_role.lower() != 'admin':
                    return False, f"Pengguna ID `{user_id}` bukan seorang admin."
                if user_id == OWNER_ID:
                    return False, "Anda tidak dapat menghapus pemilik bot dari peran admin."

                # Perbarui peran menjadi 'user' biasa
                sheet.update_cell(target_row_idx, role_col_idx + 1, 'user')
                logger.info(f"Menghapus pengguna {user_id} dari peran admin.")
                if bot_obj:
                    try:
                        await bot_obj.send_message(user_id, "Peran admin Anda di bot telah dihapus.")
                    except Exception as e:
                        logger.warning(f"Gagal mengirim notifikasi ke user {user_id}: {e}")
                return True, f"Berhasil menghapus pengguna ID `{user_id}` dari peran admin."
            else:
                return False, f"Pengguna ID `{user_id}` tidak ditemukan dalam daftar pengguna."

        elif add_or_remove == 'remove_user':
            if target_row_idx != -1:
                if user_id == OWNER_ID:
                    return False, "Anda tidak dapat menghapus pemilik bot."
                sheet.delete_rows(target_row_idx)
                logger.info(f"Menghapus pengguna {user_id} sepenuhnya dari sheet.")
                if bot_obj:
                    try:
                        await bot_obj.send_message(user_id, "Anda telah dihapus sepenuhnya dari bot.")
                    except Exception as e:
                        logger.warning(f"Gagal mengirim notifikasi ke user {user_id}: {e}")
                return True, f"Berhasil menghapus pengguna ID `{user_id}` sepenuhnya dari daftar."
            else:
                return False, f"Pengguna ID `{user_id}` tidak ditemukan dalam daftar pengguna."

    except Exception as e:
        logger.error(f"Kesalahan saat mengelola pengguna ID {user_id} ({add_or_remove} {role}): {e}")
        return False, f"Terjadi kesalahan: {e}"

@owner_only
async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memulai proses penambahan admin."""
    await update.message.reply_text("Silakan kirim ID Telegram pengguna yang ingin Anda jadikan admin:")
    return ADD_ADMIN_ID

async def addadmin_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memproses ID untuk menambah admin."""
    try:
        target_user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("ID tidak valid. Harap masukkan ID Telegram yang berupa angka.")
        return ADD_ADMIN_ID # Tetap di state ini

    initiator_id = update.effective_user.id
    initiator_name = update.effective_user.first_name if update.effective_user.first_name else update.effective_user.username

    success, message = await manage_user_in_sheet(target_user_id, 'admin', 'add', initiator_id, initiator_name, context.bot)
    await update.message.reply_text(message, parse_mode='Markdown')
    if success:
        load_user_roles() # Muat ulang peran setelah perubahan
    return ConversationHandler.END

@owner_only
async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memulai proses penghapusan admin."""
    await update.message.reply_text("Silakan kirim ID Telegram admin yang ingin Anda hapus dari peran admin:")
    return REMOVE_ADMIN_ID

async def removeadmin_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memproses ID untuk menghapus admin."""
    try:
        target_user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("ID tidak valid. Harap masukkan ID Telegram yang berupa angka.")
        return REMOVE_ADMIN_ID # Tetap di state ini

    initiator_id = update.effective_user.id
    initiator_name = update.effective_user.first_name if update.effective_user.first_name else update.effective_user.username

    success, message = await manage_user_in_sheet(target_user_id, 'admin', 'remove_admin', initiator_id, initiator_name, context.bot)
    await update.message.reply_text(message, parse_mode='Markdown')
    if success:
        load_user_roles() # Muat ulang peran setelah perubahan
    return ConversationHandler.END

@owner_only
async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memulai proses penambahan user."""
    await update.message.reply_text("Silakan kirim ID Telegram pengguna yang ingin Anda tambahkan sebagai user biasa:")
    return ADD_USER_ID

async def adduser_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memproses ID untuk menambah user."""
    try:
        target_user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("ID tidak valid. Harap masukkan ID Telegram yang berupa angka.")
        return ADD_USER_ID # Tetap di state ini

    initiator_id = update.effective_user.id
    initiator_name = update.effective_user.first_name if update.effective_user.first_name else update.effective_user.username

    success, message = await manage_user_in_sheet(target_user_id, 'user', 'add', initiator_id, initiator_name, context.bot)
    await update.message.reply_text(message, parse_mode='Markdown')
    if success:
        load_user_roles() # Muat ulang peran setelah perubahan
    return ConversationHandler.END

@owner_only
async def removeuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memulai proses penghapusan user."""
    await update.message.reply_text("Silakan kirim ID Telegram pengguna yang ingin Anda hapus sepenuhnya dari daftar:")
    return REMOVE_USER_ID

async def removeuser_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Owner: Memproses ID untuk menghapus user."""
    try:
        target_user_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("ID tidak valid. Harap masukkan ID Telegram yang berupa angka.")
        return REMOVE_USER_ID # Tetap di state ini

    if target_user_id == OWNER_ID:
        await update.message.reply_text("Anda tidak dapat menghapus pemilik bot.")
        return ConversationHandler.END

    initiator_id = update.effective_user.id
    initiator_name = update.effective_user.first_name if update.effective_user.first_name else update.effective_user.username

    success, message = await manage_user_in_sheet(target_user_id, '', 'remove_user', initiator_id, initiator_name, context.bot)
    await update.message.reply_text(message, parse_mode='Markdown')
    if success:
        load_user_roles() # Muat ulang peran setelah perubahan
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Maaf, perintah tersebut tidak saya kenali. Gunakan /help untuk melihat daftar perintah.")
    logger.info(f"Perintah tidak dikenal diterima dari {update.effective_user.id} ({update.effective_user.username}): {update.message.text}")

# --- Main Function ---
def main():
    logger.info("Memulai inisialisasi bot...")

    try:
        get_google_sheet_client()
        load_user_roles() # Ini akan memuat peran pengguna
    except Exception:
        logger.critical("Inisialisasi bot gagal. Keluar.")
        exit(1)

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Conversation Handler for check-in process
    checkin_conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("checkin", checkin_start)],
        states={
            GET_LOCATION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location_name)],
            GET_REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_region)],
            GET_LOCATION_PHOTO: [MessageHandler(filters.LOCATION, get_location_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)], # Fallback to cancel command
        allow_reentry=True # Allow users to start /checkin again if they get stuck
    )
    application.add_handler(checkin_conversation_handler)

    # Conversation Handlers for Owner-only User Management
    add_admin_handler = ConversationHandler(
        entry_points=[CommandHandler("addadmin", addadmin_command)],
        states={
            ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, addadmin_process)],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)],
        allow_reentry=True
    )
    application.add_handler(add_admin_handler)

    remove_admin_handler = ConversationHandler(
        entry_points=[CommandHandler("removeadmin", removeadmin_command)],
        states={
            REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, removeadmin_process)],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)],
        allow_reentry=True
    )
    application.add_handler(remove_admin_handler)

    add_user_handler = ConversationHandler(
        entry_points=[CommandHandler("adduser", adduser_command)],
        states={
            ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, adduser_process)],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)],
        allow_reentry=True
    )
    application.add_handler(add_user_handler)

    remove_user_handler = ConversationHandler(
        entry_points=[CommandHandler("removeuser", removeuser_command)],
        states={
            REMOVE_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, removeuser_process)],
        },
        fallbacks=[CommandHandler("cancel", cancel_checkin)],
        allow_reentry=True
    )
    application.add_handler(remove_user_handler)


    # Other Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("reloadroles", reload_roles))
    application.add_handler(CommandHandler("listadmins", listadmins))
    application.add_handler(CommandHandler("listuser", listuser))
    application.add_handler(CommandHandler("kontak", kontak))

    # Message Handler for unknown commands (should be after specific command handlers)
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # --- Webhook setup for Render ---
    logger.info(f"Menyiapkan webhook: https://{WEBHOOK_HOST}/{TELEGRAM_TOKEN} pada port {PORT}")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"https://{WEBHOOK_HOST}/{TELEGRAM_TOKEN}"
    )
    logger.info("Bot berjalan melalui webhook.")

if __name__ == '__main__':
    main()
