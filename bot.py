import os
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Updater, CommandHandler

# =============================================
# KONFIGURASI (SEMUA DIISI OTOMATIS DARI ENV VAR)
# =============================================
GSHEET_CREDENTIALS = {
    "type": "service_account",
    "project_id": os.getenv('GSHEET_PROJECT_ID'),               # Diisi otomatis
    "private_key_id": os.getenv('GSHEET_PRIVATE_KEY_ID'),       # Diisi otomatis
    "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),  # Diisi otomatis
    "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),           # Diisi otomatis
    "client_id": os.getenv('GSHEET_CLIENT_ID'),                # Diisi otomatis
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GSHEET_CLIENT_EMAIL').replace('@', '%40')}"  # Diisi otomatis
}

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')                   # Diisi otomatis
SHEET_URL = os.getenv('SHEET_URL')                             # Diisi otomatis

# =============================================
# FUNGSI BOT (TIDAK PERLU DIEDIT)
# =============================================
def init_gsheet():
    scope = ["https://spreadsheets.google.com/feeds"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GSHEET_CREDENTIALS, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(SHEET_URL).sheet1

sheet = init_gsheet()

def start(update: Update, context):
    update.message.reply_text('✅ Bot Check-in Sales siap! Gunakan /checkin')

def checkin(update: Update, context):
    user = update.effective_user
    row = [
        str(user.id),
        user.first_name or '',
        user.username or '',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]
    sheet.append_row(row)
    update.message.reply_text('✅ Data berhasil dicatat!')

def main():
    updater = Updater(TELEGRAM_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("checkin", checkin))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
