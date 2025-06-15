import os
import gspread
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime
from google.oauth2 import service_account

# ===== CONFIG =====
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_URL = os.getenv("SHEET_URL")
ADMIN_IDS = [123456789]  # Ganti dengan ID admin

# ===== GOOGLE AUTH =====
try:
    # Convert single-line key to proper format
    raw_key = os.getenv("GSHEET_PRIVATE_KEY")
    private_key = (
        raw_key
        .replace("-----BEGIN PRIVATE KEY-----", "")
        .replace("-----END PRIVATE KEY-----", "")
        .replace("\\n", "\n")
        .strip()
    )
    private_key = f"-----BEGIN PRIVATE KEY-----\n{private_key}\n-----END PRIVATE KEY-----"
    
    # Debug key (first 50 chars only)
    print("Private Key Format Check:", private_key[:50] + "...")
    
    # Service account config
    sa_info = {
        "type": "service_account",
        "project_id": os.getenv("GSHEET_PROJECT_ID"),
        "private_key": private_key,
        "client_email": os.getenv("GSHEET_CLIENT_EMAIL"),
        "token_uri": "https://oauth2.googleapis.com/token"
    }
    
    # Authenticate
    gc = gspread.service_account_from_dict(sa_info)
    sheet = gc.open_by_url(SHEET_URL).sheet1
except Exception as e:
    print("AUTH ERROR:", str(e))
    raise

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = "owner" if user_id in ADMIN_IDS else "user"
    await update.message.reply_text(
        f"Halo {update.effective_user.first_name}! Anda login sebagai {role}.\n"
        "Ketik /checkin untuk mulai."
    )

async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Masukkan nama toko dan wilayah (contoh: Toko Makmur, Jakarta Selatan):",
        reply_markup=ReplyKeyboardMarkup([["Batal"]], one_time_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Batal":
        await update.message.reply_text("Check-in dibatalkan.")
        return

    user = update.effective_user
    waktu = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    data = [user.first_name, text.split(",")[0].strip(), text.split(",")[1].strip(), waktu, "-"]
    sheet.append_row(data)
    await update.message.reply_text(
        f"✅ Data berhasil dicatat!\n"
        f"Toko: {data[1]}\nWilayah: {data[2]}\nWaktu: {waktu}"
    )

# ===== RUN BOT =====
if __name__ == "__main__":
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("checkin", checkin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()