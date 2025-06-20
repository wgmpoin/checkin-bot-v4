import os
import logging
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)

# --- Konfigurasi Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
try:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    OWNER_ID = int(os.getenv('OWNER_ID')) # Pastikan ini diubah jadi integer
    WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
    PORT = int(os.getenv('PORT', 8080)) # Default ke 8080 jika tidak ada
    SHEET_URL = os.getenv('SHEET_URL')
    GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')

    if not all([TELEGRAM_TOKEN, OWNER_ID, WEBHOOK_HOST, PORT, SHEET_URL, GOOGLE_CREDENTIALS_JSON]):
        raise ValueError("Missing one or more required environment variables.")

except ValueError as e:
    logger.critical(f"Bot crashed during initialization: {e}")
    exit(1) # Keluar dari aplikasi jika ada variabel yang hilang/salah

# --- Google Sheets Initialization ---
gsheet_client = None
admin_ids = set() # Set untuk menyimpan ID admin

def get_google_sheet_client():
    global gsheet_client
    if gsheet_client:
        return gsheet_client

    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gsheet_client = gspread.authorize(creds)
        logger.info("Google Sheet client initialized successfully.")
        return gsheet_client
    except json.JSONDecodeError as e:
        logger.critical(f"Google Sheets init failed: JSON credentials parse error: {e}. Pastikan GOOGLE_APPLICATION_CREDENTIALS_JSON adalah JSON yang valid.")
        raise
    except Exception as e:
        logger.critical(f"Google Sheets init failed: {e}. Pastikan SHEET_URL benar dan Service Account memiliki izin Editor.")
        raise

def load_user_roles():
    global admin_ids
    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)
        worksheet = spreadsheet.worksheet("USER ROLE") # Sesuaikan nama sheet jika berbeda
        
        records = worksheet.get_all_records()
        
        # Bersihkan admin_ids setiap kali dimuat ulang
        admin_ids.clear()
        
        # Tambahkan owner_id sebagai admin default
        admin_ids.add(OWNER_ID) 

        for row in records:
            try:
                user_id = int(row.get('user_id'))
                role = str(row.get('role')).strip().lower()
                if role == 'admin':
                    admin_ids.add(user_id)
            except (ValueError, TypeError):
                logger.warning(f"Skipping row with invalid user_id or role: {row}")

        logger.info(f"User roles loaded. Admins: {admin_ids}")

    except Exception as e:
        logger.critical(f"Failed to load user roles from Google Sheet: {e}. Please check Google Cloud Console API status and Service Account permissions.")
        raise

# --- Decorator untuk Admin Command ---
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in admin_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk admin.")
            logger.warning(f"Unauthorized access attempt by {update.effective_user.id} to {func.__name__}")
    return wrapper

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya bot Sales Check-in Anda. Gunakan /help untuk melihat perintah.")
    logger.info(f"User {update.effective_user.id} started the bot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Daftar perintah:\n"
        "/start - Memulai bot\n"
        "/help - Menampilkan pesan bantuan ini\n"
        "/checkin <produk> <harga> - Untuk mencatat penjualan (contoh: /checkin ProdukA 150000)\n"
    )
    if update.effective_user.id in admin_ids:
        help_text += "/reloadroles - Memuat ulang peran pengguna dari Google Sheet (Admin Only)\n"
        help_text += "/showadmins - Menampilkan ID admin (Admin Only)\n"
    await update.message.reply_text(help_text)
    logger.info(f"User {update.effective_user.id} requested help.")

@admin_only
async def reload_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        load_user_roles()
        await update.message.reply_text("Peran pengguna berhasil dimuat ulang.")
        logger.info(f"Admin {update.effective_user.id} reloaded user roles.")
    except Exception as e:
        await update.message.reply_text(f"Gagal memuat ulang peran: {e}")
        logger.error(f"Admin {update.effective_user.id} failed to reload roles: {e}")

@admin_only
async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_list = "\n".join(map(str, sorted(list(admin_ids))))
    await update.message.reply_text(f"Daftar Admin ID:\n{admin_list}")
    logger.info(f"Admin {update.effective_user.id} requested admin list.")

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Format salah. Gunakan: /checkin <produk> <harga> (contoh: /checkin ProdukA 150000)")
        logger.warning(f"User {update.effective_user.id} used wrong format for checkin.")
        return

    product_name = args[0]
    try:
        price = int(args[1])
    except ValueError:
        await update.message.reply_text("Harga harus berupa angka. Contoh: /checkin ProdukA 150000")
        logger.warning(f"User {update.effective_user.id} entered non-numeric price.")
        return

    username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    timestamp = update.message.date.strftime("%Y-%m-%d %H:%M:%S")
    user_id = update.effective_user.id

    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)
        # Asumsikan data penjualan masuk ke sheet bernama "Sales Data"
        worksheet = spreadsheet.worksheet("Sales Data") 

        # Menemukan baris terakhir yang berisi data
        # Jika sheet kosong, start_row akan menjadi 1 (header)
        # Jika ada data, kita akan append ke baris berikutnya
        next_row = len(worksheet.get_all_values()) + 1

        # Menulis data ke baris baru
        # Sesuaikan urutan kolom jika header sheet berbeda
        # Contoh: timestamp, user_id, username, product_name, price
        worksheet.insert_row([timestamp, user_id, username, product_name, price], next_row)
        
        await update.message.reply_text(f"Check-in berhasil!\nProduk: {product_name}\nHarga: {price}\nDicatat oleh: {username}")
        logger.info(f"Check-in by {user_id} ({username}): Product={product_name}, Price={price}")

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan saat mencatat check-in: {e}. Mohon coba lagi nanti.")
        logger.error(f"Error during check-in for {user_id}: {e}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Maaf, perintah tersebut tidak saya kenali. Gunakan /help untuk melihat daftar perintah.")
    logger.info(f"Unknown command received from {update.effective_user.id}: {update.message.text}")

# --- Main Function ---
def main():
    logger.info("Starting bot initialization...")

    try:
        # Panggil fungsi init Google Sheets dan load roles di awal
        get_google_sheet_client()
        load_user_roles()
    except Exception:
        # Error saat init/load roles sudah dicatat sebagai CRITICAL, jadi langsung keluar
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
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_TOKEN,
        webhook_url=f"https://{WEBHOOK_HOST}/{TELEGRAM_TOKEN}"
    )
    logger.info("Bot is running via webhook.")

if __name__ == '__main__':
    main()
