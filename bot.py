import logging
import os
import gspread
from datetime import datetime, timedelta
from telegram import Update, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext,
)
import json

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for check-in
LOCATION, AREA, CONFIRM, WAITING_LOCATION = range(4)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
GSHEET_SPREADSHEET_ID = os.getenv("GSHEET_SPREADSHEET_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") # For Render deployment

# Initialize Google Sheets
try:
    # Load credentials from the single GOOGLE_SERVICE_ACCOUNT_CREDENTIALS env var
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS environment variable is not set.")
    
    # Parse the JSON string into a Python dictionary
    creds_dict = json.loads(creds_json)
    
    gc = gspread.service_account_from_dict(creds_dict)
    # PERBAIKAN DI BARIS INI: Gunakan gc.open_by_key() bukan gc.open_by_id()
    spreadsheet = gc.open_by_key(GSHEET_SPREADSHEET_ID)
    checkin_sheet = spreadsheet.worksheet("Check-Ins")
    users_sheet = spreadsheet.worksheet("Users")
    logger.info("Successfully connected to Google Sheets.")
except Exception as e:
    logger.error(f"Error connecting to Google Sheets: {e}")
    raise

# User Roles Management (cached)
user_roles = {}

def load_user_roles():
    """Loads user roles from the 'Users' Google Sheet."""
    global user_roles
    try:
        records = users_sheet.get_all_records()
        user_roles = {str(record['user_id']): record for record in records if 'user_id' in record}
        logger.info(f"User roles loaded from Google Sheet. Loaded {len(user_roles)} entries.")
    except Exception as e:
        logger.error(f"Error loading user roles from Google Sheet: {e}")
        user_roles = {} # Clear roles on error to prevent using stale data

# Load roles on startup
load_user_roles()

# --- Command Handlers ---

def start(update: Update, context: CallbackContext) -> None:
    """Sends a welcome message and prompts for check-in."""
    msg = "👋 Halo! Saya Bot Check-in.\n"
    msg += "Gunakan perintah:\n"
    msg += "/checkin - Mulai proses check-in lokasi dan wilayah.\n"
    msg += "/menu - Tampilkan menu perintah."
    update.message.reply_text(msg)

def show_menu(update: Update, context: CallbackContext) -> None:
    """Displays the full menu for all users."""
    msg = "Berikut adalah perintah yang bisa Anda gunakan:\n\n"
    msg += "*/start* - Memulai bot dan sambutan\n"
    msg += "*/checkin* - Memulai proses check-in lokasi dan wilayah.\n"
    msg += "*/menu* - Menampilkan menu perintah ini.\n"
    msg += "*/myid* - Melihat ID Telegram Anda.\n"
    msg += "*/kontak* - Menampilkan informasi kontak penting.\n"
    msg += "*/help* - Bantuan dan informasi bot.\n\n"
    msg += "*Perintah Admin & Owner (Walaupun Terlihat, Hanya Bisa Dilakukan oleh yang Berhak):*\n"
    msg += "*/add_admin <user_id>* - Menambahkan user sebagai admin.\n"
    msg += "*/add_user <user_id>* - Menambahkan user biasa.\n"
    msg += "*/list_users* - Melihat daftar user terdaftar.\n"
    
    update.message.reply_text(msg, parse_mode='Markdown')

def my_id(update: Update, context: CallbackContext) -> None:
    """Sends the user's Telegram ID."""
    user_id = update.effective_user.id
    update.message.reply_text(f"ID Telegram Anda: `{user_id}`", parse_mode='Markdown')

def help_command(update: Update, context: CallbackContext) -> None:
    """Sends a help message."""
    update.message.reply_text(
        "Ini adalah bot check-in. "
        "Anda dapat menggunakan /checkin untuk memulai proses check-in lokasi Anda. "
        "Untuk melihat semua perintah yang tersedia, gunakan /menu."
    )

def contact(update: Update, context: CallbackContext) -> None:
    """Displays important contact information."""
    msg = "*Perintah:* /kontak\n\n"
    msg += "*Hotline Bebas Pulsa:* [08001119999](tel:+628001119999)\n"
    msg += "*Hotline:* [+6281231447777](tel:+6281231447777) (Kontak Telegram)\n" 
    msg += "*Email Support:* [support@mpoin.com](mailto:support@mpoin.com)\n\n"
    
    msg += "*PELAPORAN PELANGGARAN*\n"
    msg += "Laporkan kepada Internal Audit secara jelas & lengkap melalui:\n"
    msg += "[+62 812 3445 0505](tel:+6281234450505) | " 
    msg += "[+62 822 2909 3495](tel:+6282229093495) | "
    msg += "[+62 822 2930 9341](tel:+6282229309341)\n"
    msg += "*Email Pengaduan:* [pengaduanmpoin@gmail.com](mailto:pengaduanmpoin@gmail.com)\n\n"

    msg += "*HRD*\n"
    msg += "[+6281228328631](tel:+6281228328631)\n"
    msg += "*Email HRD:* [hrdepartment@mpoin.com](mailto:hrdepartment@mpoin.com)\n\n"

    msg += "*Sosial Media:*\n"
    msg += "Tiktok: @mpoin.id\n"
    msg += "IG: [@mpoinpipaku.id](https://www.instagram.com/mpoinpipaku.id)\n"
    msg += "FB: Mpoinpipakuid\n"
    msg += "Website: [www.mpoin.com](https://mpoin.com)"

    update.message.reply_text(msg, parse_mode='Markdown')


# --- Check-in Conversation Handlers ---

def checkin_start(update: Update, context: CallbackContext) -> int:
    """Starts the check-in conversation."""
    user_id = update.effective_user.id
    user_info = user_roles.get(str(user_id))
    
    context.user_data['user_id'] = user_id
    context.user_data['first_name'] = update.effective_user.first_name or "N/A"
    context.user_data['last_name'] = update.effective_user.last_name or ""
    context.user_data['username'] = update.effective_user.username or "N/A"
    context.user_data['full_name'] = update.effective_user.full_name

    msg = "🏷️ Baik, mari kita mulai check-in Anda!\n"
    msg += "Masukkan Nama Lokasi:"
    update.message.reply_text(msg)
    return LOCATION

def checkin_location(update: Update, context: CallbackContext) -> int:
    """Stores the location and asks for area."""
    context.user_data['lokasi'] = update.message.text
    update.message.reply_text("Masukkan Wilayah:")
    return AREA

def checkin_area(update: Update, context: CallbackContext) -> int:
    """Stores the area and asks for location via button."""
    context.user_data['wilayah'] = update.message.text

    lokasi = context.user_data['lokasi']
    wilayah = context.user_data['wilayah']

    msg = f"✅ Lokasi: {lokasi}\n"
    msg += f"🌍 Wilayah: {wilayah}\n\n"
    msg += "Terakhir, kirimkan lokasi Anda saat ini dengan menekan tombol lampiran (📎) lalu pilih *Lokasi* dan 'Kirim lokasi saya saat ini'."
    update.message.reply_text(msg, parse_mode='Markdown')
    return WAITING_LOCATION

def checkin_receive_location(update: Update, context: CallbackContext) -> int:
    """Receives the geographic location and finalizes check-in."""
    if update.message.location:
        context.user_data['latitude'] = update.message.location.latitude
        context.user_data['longitude'] = update.message.location.longitude
        context.user_data['timestamp'] = datetime.now()

        # Save to Google Sheet
        try:
            checkin_sheet.append_row([
                str(context.user_data['user_id']),
                context.user_data['full_name'],
                context.user_data['username'],
                context.user_data['lokasi'],
                context.user_data['wilayah'],
                context.user_data['latitude'],
                context.user_data['longitude'],
                context.user_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            ])
            logger.info(f"Check-in recorded for {context.user_data['user_id']} at {context.user_data['timestamp']} - {context.user_data['lokasi']}, {context.user_data['wilayah']}")
            update.message.reply_text(
                "Terima kasih! Check-in Anda telah berhasil dicatat. "
                "Data Anda: \n"
                f"Lokasi: {context.user_data['lokasi']}\n"
                f"Wilayah: {context.user_data['wilayah']}\n"
                f"Koordinat: {context.user_data['latitude']}, {context.user_data['longitude']}\n"
                f"Waktu: {context.user_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            logger.error(f"Error recording check-in: {e}")
            update.message.reply_text("Terjadi kesalahan saat menyimpan data check-in Anda. Mohon coba lagi.")
        
        return ConversationHandler.END
    else:
        update.message.reply_text("Mohon kirimkan lokasi Anda menggunakan fitur 'Lokasi' di Telegram.")
        return WAITING_LOCATION

def checkin_cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the check-in conversation."""
    update.message.reply_text("Proses check-in dibatalkan.")
    return ConversationHandler.END

# --- User Management Handlers ---

def add_user_command(update: Update, context: CallbackContext) -> None:
    """Adds a new user to the Google Sheet with 'user' role."""
    user_id = str(update.effective_user.id)
    user_info = user_roles.get(user_id)
    user_role = user_info['role'] if user_info else None

    if user_role not in ['owner', 'admin']:
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk mengakses perintah ini.")
        return

    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("Penggunaan: /add_user <user_id>")
        return

    target_user_id = context.args[0]
    
    target_user_tg_info = None
    try:
        target_user_tg_info = context.bot.get_chat(target_user_id) 
    except Exception as e:
        logger.warning(f"Could not fetch info for user ID {target_user_id}: {e}")

    first_name = target_user_tg_info.first_name if target_user_tg_info else "N/A"
    username = target_user_tg_info.username if target_user_tg_info else "N/A"

    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        adder_id = update.effective_user.id
        adder_name = update.effective_user.full_name
        
        if target_user_id in user_roles:
            update.message.reply_text(f"User dengan ID {target_user_id} sudah terdaftar sebagai {user_roles[target_user_id]['role']}.")
            return

        users_sheet.append_row([
            target_user_id, 'user', first_name, username, str(adder_id), adder_name, current_time
        ])
        load_user_roles() # Reload cache
        update.message.reply_text(f"User {first_name} ({target_user_id}) berhasil ditambahkan sebagai *user*.", parse_mode='Markdown')
        logger.info(f"User {target_user_id} added by {adder_id}")
    except Exception as e:
        logger.error(f"Error managing user role: {target_user_id} - {e}")
        update.message.reply_text(f"Terjadi kesalahan saat mencoba menambahkan user. Mohon coba lagi. Detail: {e}")

def add_admin_command(update: Update, context: CallbackContext) -> None:
    """Adds a new user to the Google Sheet with 'admin' role."""
    user_id = str(update.effective_user.id)
    user_info = user_roles.get(user_id)
    user_role = user_info['role'] if user_info else None

    if user_role not in ['owner', 'admin']:
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk mengakses perintah ini.")
        return

    if not context.args or not context.args[0].isdigit():
        update.message.reply_text("Penggunaan: /add_admin <user_id>")
        return

    target_user_id = context.args[0]
    
    target_user_tg_info = None
    try:
        target_user_tg_info = context.bot.get_chat(target_user_id) 
    except Exception as e:
        logger.warning(f"Could not fetch info for user ID {target_user_id}: {e}")

    first_name = target_user_tg_info.first_name if target_user_tg_info else "N/A"
    username = target_user_tg_info.username if target_user_tg_info else "N/A"

    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        adder_id = update.effective_user.id
        adder_name = update.effective_user.full_name

        if target_user_id in user_roles:
            existing_role = user_roles[target_user_id]['role']
            if existing_role == 'owner' or existing_role == 'admin':
                update.message.reply_text(f"User {target_user_id} sudah terdaftar sebagai {existing_role}.")
                return
            else: # Update existing user to admin
                cell = users_sheet.find(target_user_id)
                if cell:
                    row_index = cell.row
                    users_sheet.update_cell(row_index, users_sheet.find('role').col, 'admin')
                    update.message.reply_text(f"Peran user {first_name} ({target_user_id}) berhasil diubah menjadi *admin*.", parse_mode='Markdown')
                else: 
                    users_sheet.append_row([
                        target_user_id, 'admin', first_name, username, str(adder_id), adder_name, current_time
                    ])
                    update.message.reply_text(f"User {first_name} ({target_user_id}) berhasil ditambahkan sebagai *admin*.", parse_mode='Markdown')
        else: # New user
            users_sheet.append_row([
                target_user_id, 'admin', first_name, username, str(adder_id), adder_name, current_time
            ])
            update.message.reply_text(f"User {first_name} ({target_user_id}) berhasil ditambahkan sebagai *admin*.", parse_mode='Markdown')

        load_user_roles() # Reload cache
        logger.info(f"Admin {target_user_id} added/updated by {adder_id}")

    except Exception as e:
        logger.error(f"Error managing user role: {target_user_id} - {e}")
        update.message.reply_text(f"Terjadi kesalahan saat mencoba menambahkan admin. Mohon coba lagi. Detail: {e}")

def list_users_command(update: Update, context: CallbackContext) -> None:
    """Lists all registered users and their roles."""
    user_id = str(update.effective_user.id)
    user_info = user_roles.get(user_id)
    user_role = user_info['role'] if user_info else None

    if user_role not in ['owner', 'admin']:
        update.message.reply_text("Maaf, Anda tidak memiliki izin untuk mengakses perintah ini.")
        return

    if not user_roles:
        update.message.reply_text("Belum ada user terdaftar.")
        return

    msg = "*Daftar Pengguna:*\n\n"
    for user_id, user_info in user_roles.items():
        role = user_info.get('role', 'N/A')
        full_name = user_info.get('first_name', 'N/A')
        username = user_info.get('username', 'N/A')
        
        msg += f"- *ID:* `{user_id}`\n"
        msg += f"  *Nama:* {full_name}\n"
        msg += f"  *Username:* @{username}\n"
        msg += f"  *Peran:* `{role}`\n\n"
    
    update.message.reply_text(msg, parse_mode='Markdown')


def error_handler(update: Update, context: CallbackContext) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if update.effective_message:
        update.effective_message.reply_text(
            "Terjadi kesalahan internal. Mohon laporkan ini kepada pengembang bot."
        )


def main() -> None:
    """Start the bot."""
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Add conversation handler for check-in
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("checkin", checkin_start)],
        states={
            LOCATION: [MessageHandler(Filters.text & ~Filters.command, checkin_location)],
            AREA: [MessageHandler(Filters.text & ~Filters.command, checkin_area)],
            WAITING_LOCATION: [MessageHandler(Filters.location, checkin_receive_location)],
        },
        fallbacks=[CommandHandler("cancel", checkin_cancel)],
    )

    dispatcher.add_handler(conv_handler)

    # Add other command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("menu", show_menu))
    dispatcher.add_handler(CommandHandler("myid", my_id))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("kontak", contact))
    dispatcher.add_handler(CommandHandler("add_user", add_user_command))
    dispatcher.add_handler(CommandHandler("add_admin", add_admin_command))
    dispatcher.add_handler(CommandHandler("list_users", list_users_command))

    # Log all errors
    dispatcher.add_error_handler(error_handler)

    # Start the Bot
    if WEBHOOK_HOST:
        PORT = int(os.environ.get('PORT', '10000')) # Render default port is 10000
        webhook_url = f"{WEBHOOK_HOST}/{TELEGRAM_BOT_TOKEN}"
        updater.start_webhook(listen="0.0.0.0",
                              port=PORT,
                              url_path=TELEGRAM_BOT_TOKEN,
                              webhook_url=webhook_url)
        logger.info(f"Bot configured for webhook. Listening on {webhook_url}")
    else:
        logger.info("Bot configured for polling.")
        updater.start_polling()

    updater.idle()

if __name__ == "__main__":
    main()
