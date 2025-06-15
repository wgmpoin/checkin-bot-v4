import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Updater, CommandHandler
from datetime import datetime

# Config
TOKEN = os.getenv('TELEGRAM_TOKEN')
GSHEET_CREDENTIALS = {
    "type": "service_account",
    "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),
    "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
    "token_uri": "https://oauth2.googleapis.com/token",
}
SHEET_URL = os.getenv('SHEET_URL')

# Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(GSHEET_CREDENTIALS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(SHEET_URL).sheet1

# Bot Commands
def start(update: Update, context):
    update.message.reply_text('✅ Bot Check-in Sales siap! Gunakan /checkin')

def checkin(update: Update, context):
    user = update.effective_user
    row = [
        str(user.id),
        user.first_name or "",
        user.username or "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]
    sheet.append_row(row)
    update.message.reply_text('✅ Data berhasil dicatat!')

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("checkin", checkin))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
