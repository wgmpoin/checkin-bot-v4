import os
import logging
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# --- Konfigurasi Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
# Inisialisasi variabel dengan None atau default untuk penanganan error yang lebih baik
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
SHEET_URL = os.getenv('SHEET_URL')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')

OWNER_ID = None
PORT = 8080 # Default port

try:
    OWNER_ID = int(os.getenv('OWNER_ID'))
except (ValueError, TypeError):
    logger.critical("Bot crashed during initialization: OWNER_ID environment variable is missing or not an integer.")
    exit(1) # Keluar jika OWNER_ID tidak valid

try:
    PORT = int(os.getenv('PORT', 8080)) # Default ke 8080 jika tidak ada atau tidak valid
except (ValueError, TypeError):
    logger.warning("PORT environment variable is not an integer. Using default port 8080.")
    PORT = 8080

# Cek keberadaan semua environment variables penting
if not all([TELEGRAM_TOKEN, WEBHOOK_HOST, SHEET_URL, GOOGLE_CREDENTIALS_JSON]):
    logger.critical("Bot crashed during initialization: Missing one or more required environment variables (TELEGRAM_TOKEN, WEBHOOK_HOST, SHEET_URL, GOOGLE_CREDENTIALS_JSON).")
    exit(1)

# --- Google Sheets Initialization ---
gsheet_client = None
admin_ids = set() # Set untuk menyimpan ID admin

def get_google_sheet_client():
    """Menginisialisasi dan mengembalikan klien Google Sheets."""
    global gsheet_client
    if gsheet_client:
        return gsheet_client # Return existing client if already initialized

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gsheet_client = gspread.authorize(creds)
        logger.info("Google Sheet client initialized successfully.")
        return gsheet_client
    except json.JSONDecodeError as e:
        logger.critical(f"Google Sheets init failed: JSON credentials parse error. Ensure GOOGLE_APPLICATION_CREDENTIALS_JSON is valid JSON. Error: {e}")
        raise # Re-raise for bot to crash, as this is critical
    except Exception as e:
        logger.critical(f"Google Sheets init failed: {e}. Make sure SHEET_URL is correct and Service Account has Editor permissions.")
        raise # Re-raise for bot to crash, as this is critical

def load_user_roles():
    """Memuat peran pengguna (admin) dari Google Sheet 'Users'."""
    global admin_ids
    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)

        # Diagnosa awal keberadaan worksheet "Users"
        try:
            worksheet_names = [ws.title for ws in spreadsheet.worksheets()]
            logger.info(f"Successfully connected to spreadsheet. Found worksheets: {worksheet_names}")
            if "Users" not in worksheet_names:
                logger.critical(f"Worksheet 'Users' NOT FOUND in spreadsheet. Available worksheets: {worksheet_names}")
        except Exception as e:
            logger.critical(f"Error listing worksheets in spreadsheet. Please check permissions. Error: {e}")
            raise # Re-raise jika tidak bisa membaca daftar worksheet

        # Menggunakan nama worksheet "Users" (sesuai kesepakatan)
        worksheet = spreadsheet.worksheet("Users")
        all_data = worksheet.get_all_values()

        if not all_data or len(all_data) < 2: # Periksa jika sheet kosong atau hanya header
            logger.warning("Users sheet is empty or only contains headers.")
            admin_ids.clear()
            admin_ids.add(OWNER_ID) # Owner tetap admin meskipun sheet kosong
            logger.info(f"User roles loaded. Current Admins: {sorted(list(admin_ids))}")
            return

        admin_ids.clear()
        admin_ids.add(OWNER_ID) # Owner_ID selalu menjadi admin

        # Loop melalui baris data, mulai dari baris kedua (index 1) untuk melewati header
        for i, row in enumerate(all_data[1:]):
            row_num = i + 2 # Nomor baris di sheet Google (mulai dari 2)
            try:
                user_id_str = row[0] if len(row) > 0 else None
                if not user_id_str:
                    logger.warning(f"Skipping row {row_num} in 'Users' due to missing 'user_id' in column A.")
                    continue
                user_id = int(user_id_str.strip()) # Pastikan user_id bisa diubah ke integer

                role_str = row[1] if len(row) > 1 else None
                if not role_str:
                    logger.warning(f"Skipping row {row_num} in 'Users' due to missing 'role' in column B.")
                    continue
                role = str(role_str).strip().lower() # Normalisasi role

                if role == 'admin':
                    admin_ids.add(user_id)
            except (ValueError, TypeError) as e:
                logger.warning(f"Skipping row {row_num} in 'Users' sheet due to invalid data in column A (user_id) or B (role). Data: {row}. Error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error processing row {row_num} in 'Users' sheet. Data: {row}. Error: {e}")

        logger.info(f"User roles loaded. Current Admins: {sorted(list(admin_ids))}")

    except Exception as e:
        logger.critical(f"Failed to load user roles from Google Sheet (Users). Please check Google Cloud Console API status, Service Account permissions, and sheet access. Error: {e}")
        raise # Re-raise for bot to crash if user roles cannot be loaded

# --- Decorator untuk Admin Command ---
def admin_only(func):
    """Decorator untuk membatasi akses perintah hanya untuk admin."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in admin_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk admin.")
            logger.warning(f"Unauthorized access attempt by {update.effective_user.id} ({update.effective_user.username}) to {func.__name__} (command: {update.message.text})")
    return wrapper

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani perintah /start."""
    await update.message.reply_text("Halo! Saya bot Sales Check-in Anda. Gunakan /help untuk melihat perintah.")
    logger.info(f"User {update.effective_user.id} ({update.effective_user.username}) started the bot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan daftar perintah yang tersedia."""
    help_text = (
        "Daftar perintah:\n"
        "/start - Memulai bot\n"
        "/help - Menampilkan pesan bantuan ini\n"
        "/checkin <produk> <harga> - Untuk mencatat penjualan (contoh: /checkin ProdukA 150000)\n"
    )
    if update.effective_user.id in admin_ids:
        help_text += "\n--- Admin Commands ---\n"
        help_text += "/reloadroles - Memuat ulang peran pengguna dari Google Sheet\n"
        help_text += "/showadmins - Menampilkan ID admin yang terdaftar\n"
    await update.message.reply_text(help_text)
    logger.info(f"User {update.effective_user.id} ({update.effective_user.username}) requested help.")

@admin_only
async def reload_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memuat ulang peran pengguna dari Google Sheet (Admin Only)."""
    try:
        load_user_roles()
        await update.message.reply_text("Peran pengguna berhasil dimuat ulang.")
        logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) reloaded user roles.")
    except Exception as e:
        await update.message.reply_text(f"Gagal memuat ulang peran: {e}")
        logger.error(f"Admin {update.effective_user.id} ({update.effective_user.username}) failed to reload roles: {e}")

@admin_only
async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan ID admin yang terdaftar (Admin Only)."""
    admin_list = "\n".join(map(str, sorted(list(admin_ids))))
    await update.message.reply_text(f"Daftar Admin ID:\n{admin_list}")
    logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) requested admin list.")

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mencatat data penjualan ke Google Sheet 'Sales Data'."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Format salah. Gunakan: `/checkin <produk> <harga>` (contoh: `/checkin ProdukA 150000`)")
        logger.warning(f"User {update.effective_user.id} ({update.effective_user.username}) used wrong format for checkin: {update.message.text}")
        return

    product_name = args[0]
    try:
        price = int(args[1])
    except ValueError:
        await update.message.reply_text("Harga harus berupa angka. Contoh: `/checkin ProdukA 150000`")
        logger.warning(f"User {update.effective_user.id} ({update.effective_user.username}) entered non-numeric price: {args[1]}")
        return

    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    timestamp = update.message.date.strftime("%Y-%m-%d %H:%M:%S")
    user_id = update.effective_user.id

    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)
        # Asumsikan data penjualan masuk ke sheet bernama "Sales Data"
        worksheet = spreadsheet.worksheet("Sales Data")

        # Menemukan baris terakhir yang berisi data untuk append ke baris berikutnya
        next_row = len(worksheet.get_all_values()) + 1

        # Menulis data ke baris baru.
        # SESUAIKAN URUTAN KOLOM DI SINI JIKA HEADER SHEET "Sales Data" BERBEDA
        # Contoh: timestamp, user_id, username, product_name, price
        worksheet.insert_row([timestamp, user_id, username, product_name, price], next_row)
        
        await update.message.reply_text(f"Check-in berhasil!\nProduk: {product_name}\nHarga: {price}\nDicatat oleh: {username}")
        logger.info(f"Check-in by {user_id} ({username}): Product={product_name}, Price={price}")

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan saat mencatat check-in: {e}. Mohon coba lagi nanti.")
        logger.error(f"Error during check-in for {user_id} ({username}): {e}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani perintah yang tidak dikenali."""
    await update.message.reply_text("Maaf, perintah tersebut tidak saya kenali. Gunakan /help untuk melihat daftar perintah.")
    logger.info(f"Unknown command received from {update.effective_user.id} ({update.effective_user.username}): {update.message.text}")

# --- Main Function ---
def main():
    logger.info("Starting bot initialization...")

    try:
        # Panggil fungsi init Google Sheets dan load roles di awal
        get_google_sheet_client()
        load_user_roles() # Ini akan memuat peran pengguna
    except Exception:
        # Error saat init/load roles sudah dicatat sebagai CRITICAL, jadi langsung keluar
        logger.critical("Bot initialization failed. Exiting.")
        exit(1)

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("checkin", checkin))
    application.add_handler(CommandHandler("reloadroles", reload_roles))
    application.add_handler(CommandHandler("showadmins", show_admins))

    # Message Handler untuk perintah yang tidak dikenali
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # --- Webhook setup for Render ---
    logger.info(f"Setting up webhook: https://{WEBHOOK_HOST}/{TELEGRAM_TOKEN} on port {PORT}")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"https://{WEBHOOK_HOST}/{TELEGRAM_TOKEN}"
    )
    logger.info("Bot is running via webhook.")

if __name__ == '__main__':
    main()
