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
    CallbackQueryHandler,
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
    global admin_ids
    try:
        client = get_google_sheet_client()
        spreadsheet = client.open_by_url(SHEET_URL)

        try:
            worksheet_names = [ws.title for ws in spreadsheet.worksheets()]
            logger.info(f"Successfully connected to spreadsheet. Found worksheets: {worksheet_names}")
            if "Users" not in worksheet_names:
                logger.critical(f"Worksheet 'Users' NOT FOUND in spreadsheet. Available worksheets: {worksheet_names}")
                raise ValueError("Worksheet 'Users' not found.") # Raise an error to stop initialization
        except Exception as e:
            logger.critical(f"Error listing worksheets in spreadsheet. Please check permissions. Error: {e}")
            raise # Re-raise jika tidak bisa membaca daftar worksheet

        worksheet = spreadsheet.worksheet("Users") 
        all_data = worksheet.get_all_values()

        if not all_data:
            logger.warning("Users sheet is empty.")
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
                    logger.warning(f"Skipping row {row_num} in 'Users' due to missing 'user_id' in column A.")
                    continue
                user_id = int(user_id_str.strip()) # Pastikan user_id bisa diubah ke integer

                # role ada di kolom B (index 1)
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
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in admin_ids:
            return await func(update, context)
        else:
            await update.message.reply_text("Maaf, perintah ini hanya untuk admin.")
            logger.warning(f"Unauthorized access attempt by {update.effective_user.id} ({update.effective_user.username}) to {func.__name__} (command: {update.message.text})")
    return wrapper

# --- States for Conversation Handler ---
GET_LOCATION_NAME, GET_REGION, GET_LOCATION_PHOTO = range(3)

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Halo! Saya bot Sales Check-in Anda. Gunakan /help untuk melihat perintah.")
    logger.info(f"User {update.effective_user.id} ({update.effective_user.username}) started the bot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Daftar perintah:\n"
        "/start - Memulai bot\n"
        "/help - Menampilkan pesan bantuan ini\n"
        "/checkin - Untuk memulai proses check-in lokasi\n"
        "/cancel - Untuk membatalkan proses check-in yang sedang berjalan\n"
    )
    if update.effective_user.id in admin_ids:
        help_text += "\n--- Admin Commands ---\n"
        help_text += "/reloadroles - Memuat ulang peran pengguna dari Google Sheet\n"
        help_text += "/showadmins - Menampilkan ID admin yang terdaftar\n"
    await update.message.reply_text(help_text)
    logger.info(f"User {update.effective_user.id} ({update.effective_user.username}) requested help.")

@admin_only
async def reload_roles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        load_user_roles()
        await update.message.reply_text("Peran pengguna berhasil dimuat ulang.")
        logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) reloaded user roles.")
    except Exception as e:
        await update.message.reply_text(f"Gagal memuat ulang peran: {e}")
        logger.error(f"Admin {update.effective_user.id} ({update.effective_user.username}) failed to reload roles: {e}")

@admin_only
async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_list = "\n".join(map(str, sorted(list(admin_ids))))
    await update.message.reply_text(f"Daftar Admin ID:\n{admin_list}")
    logger.info(f"Admin {update.effective_user.id} ({update.effective_user.username}) requested admin list.")

async def checkin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the check-in conversation and asks for location name."""
    await update.message.reply_text("Baik, mari kita mulai proses check-in.\nMohon berikan **Nama tempat/lokasi** Anda:")
    context.user_data['checkin_data'] = {} # Initialize user_data for this check-in
    logger.info(f"User {update.effective_user.id} ({update.effective_user.username}) started checkin.")
    return GET_LOCATION_NAME

async def get_location_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives location name and asks for region."""
    location_name = update.message.text
    context.user_data['checkin_data']['nama_lokasi'] = location_name
    await update.message.reply_text(f"Baik, lokasi Anda: **{location_name}**.\nSekarang, mohon berikan **Wilayah** (misal: Jakarta Pusat, Surabaya, dll.):")
    logger.info(f"User {update.effective_user.id} provided location name: {location_name}")
    return GET_REGION

async def get_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives region and asks for location."""
    region = update.message.text
    context.user_data['checkin_data']['wilayah'] = region

    # Create a custom keyboard with a "Share Location" button
    keyboard = [[KeyboardButton("Bagikan Lokasi Saya", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        f"Terima kasih. Wilayah Anda: **{region}**.\n"
        "Terakhir, mohon **bagikan lokasi Google Maps Anda** melalui fitur lampiran di Telegram.\n"
        "Anda bisa menekan tombol di bawah atau ikon klip kertas (attachment) lalu pilih 'Location'.",
        reply_markup=reply_markup
    )
    logger.info(f"User {update.effective_user.id} provided region: {region}. Asking for location.")
    return GET_LOCATION_PHOTO

async def get_location_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives location data and saves to Google Sheet."""
    if update.message.location:
        location = update.message.location
        latitude = location.latitude
        longitude = location.longitude
        Maps_link = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"

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
            # Ensure the correct sheet name "Check-in Data"
            worksheet = spreadsheet.worksheet("Check-in Data") 

            # Data to be inserted, matching the sheet columns:
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
            
            worksheet.append_row(row_data) # Appends to the first empty row
            
            response_message = (
                "Check-in berhasil dicatat!\n\n"
                f"**Nama Tempat:** {nama_lokasi}\n"
                f"**Wilayah:** {wilayah}\n"
                f"**Link Google Maps:** {Maps_link}"
            )
            await update.message.reply_text(response_message)
            logger.info(f"Check-in by {user_id} ({username}): Location={nama_lokasi}, Region={wilayah}, Map={Maps_link}")

        except Exception as e:
            await update.message.reply_text(f"Terjadi kesalahan saat mencatat check-in ke Google Sheet: {e}. Mohon coba lagi nanti.")
            logger.error(f"Error during check-in for {user_id} ({username}): {e}")
        
        # Clear user_data and end the conversation
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Itu bukan lokasi yang valid. Mohon **bagikan lokasi Anda** dengan menekan ikon klip kertas (attachment) lalu pilih 'Location'."
        )
        logger.warning(f"User {update.effective_user.id} sent non-location message during location step.")
        return GET_LOCATION_PHOTO # Stay in the same state until location is received

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the conversation."""
    if 'checkin_data' in context.user_data:
        context.user_data.clear()
        await update.message.reply_text("Proses check-in dibatalkan.")
        logger.info(f"User {update.effective_user.id} cancelled check-in.")
    else:
        await update.message.reply_text("Tidak ada proses check-in yang sedang berjalan untuk dibatalkan.")
        logger.info(f"User {update.effective_user.id} tried to cancel, but no check-in was active.")
    return ConversationHandler.END

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Maaf, perintah tersebut tidak saya kenali. Gunakan /help untuk melihat daftar perintah.")
    logger.info(f"Unknown command received from {update.effective_user.id} ({update.effective_user.username}): {update.message.text}")

# --- Main Function ---
def main():
    logger.info("Starting bot initialization...")

    try:
        get_google_sheet_client()
        load_user_roles() # This will load user roles
    except Exception:
        logger.critical("Bot initialization failed. Exiting.")
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
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True # Allow users to start /checkin again if they get stuck
    )

    # Add conversation handler
    application.add_handler(checkin_conversation_handler)

    # Other Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reloadroles", reload_roles))
    application.add_handler(CommandHandler("showadmins", show_admins))
    
    # Message Handler for unknown commands (should be after specific command handlers)
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
