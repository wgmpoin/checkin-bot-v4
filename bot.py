import os
import logging
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

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
    global admin_ids
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

        if not all_data:
            logger.warning("Lembar 'Users' kosong.")
            return

        admin_ids.clear()
        admin_ids.add(OWNER_ID)

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

                if role == 'admin':
                    admin_ids.add(user_id)
            except (ValueError, TypeError) as e:
                logger.warning(f"Melewati baris {row_num} di lembar 'Users' karena data tidak valid di kolom A (user_id) atau B (role). Data: {row}. Error: {e}")
            except Exception as e:
                logger.error(f"Kesalahan tak terduga saat memproses baris {row_num} di lembar 'Users'. Data: {row}. Error: {e}")

        logger.info(f"Peran pengguna dimuat. Admin saat ini: {sorted(list(admin_ids))}")

    except Exception as e:
        logger.critical(f"Gagal memuat peran pengguna dari Google Sheet (Users). Harap periksa status API Google Cloud Console, izin Akun Layanan, dan akses sheet. Error: {e}")
        raise # Re-raise for bot to crash if user roles cannot be loaded

# --- Decorator untuk Admin Command ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in admin_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk admin.")
            logger.warning(f"Upaya akses tidak sah oleh {update.effective_user.id} ({update.effective_user.username}) ke {func.__name__} (perintah: {update.message.text})")
    return wrapper

# --- States for Conversation Handler ---
GET_LOCATION_NAME, GET_REGION, GET_LOCATION_PHOTO = range(3)

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya bot Sales Check-in Anda. Gunakan /help untuk melihat perintah.")
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) memulai bot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Daftar perintah:\n"
        "/start - Memulai bot\n"
        "/help - Menampilkan pesan bantuan ini\n"
        "/checkin - Untuk memulai proses check-in lokasi\n"
        "/kontak - Menampilkan informasi kontak\n"
    )
    if update.effective_user.id in admin_ids: # Keep for /reloadroles for now, though showadmins is removed
        help_text += "\n--- Perintah Admin ---\n"
        help_text += "/reloadroles - Memuat ulang peran pengguna dari Google Sheet\n"
    await update.message.reply_text(help_text)
    logger.info(f"Pengguna {update.effective_user.id} ({update.effective_user.username}) meminta bantuan.")

@admin_only
async def reload_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        load_user_roles()
        await update.message.reply_text("Peran pengguna berhasil dimuat ulang.")
        logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) memuat ulang peran pengguna.")
    except Exception as e:
        await update.message.reply_text(f"Gagal memuat ulang peran: {e}")
        logger.error(f"Admin {update.effective_user.id} ({update.effective_user.username}) gagal memuat ulang peran: {e}")

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
    await update.message.reply_text(f"Baik, lokasi Anda: **{location_name}**.\nSekarang, mohon berikan **Wilayah**:")
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
        Maps_link = f"http://maps.google.com/?q={latitude},{longitude}" # Corrected Google Maps link format

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

    # Add conversation handler
    application.add_handler(checkin_conversation_handler)

    # Other Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reloadroles", reload_roles))
    application.add_handler(CommandHandler("kontak", kontak)) # New kontak command
    
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
