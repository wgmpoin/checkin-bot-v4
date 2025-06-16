import os
import logging
from datetime import datetime
import gspread
from telegram import Update
from telegram.ext import Updater, CommandHandler, Dispatcher
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# ======================
# FLASK & WEBHOOK SETUP
# ======================
app = Flask(__name__)

# ======================
# LOGGING CONFIG
# ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======================
# GOOGLE SHEETS CONFIG
# ======================
def init_gsheet():
    scope = ["https://spreadsheets.google.com/feeds"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        {
            "type": "service_account",
            "project_id": os.getenv('GSHEET_PROJECT_ID'),
            "private_key_id": os.getenv('GSHEET_PRIVATE_KEY_ID'),
            "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
            "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),
            "client_id": os.getenv('GSHEET_CLIENT_ID'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GSHEET_CLIENT_EMAIL', '').replace('@', '%40')}"
        },
        scope
    )
    client = gspread.authorize(creds)
    return client.open_by_url(os.getenv('SHEET_URL')).sheet1

# ======================
# TELEGRAM HANDLERS
# ======================
def start(update: Update, context):
    update.message.reply_text('✅ Bot Check-in siap! Gunakan /checkin')

def checkin(update: Update, context):
    user = update.effective_user
    sheet = init_gsheet()
    sheet.append_row([
        str(user.id),
        user.first_name or '',
        user.username or '',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ])
    update.message.reply_text('✅ Data tercatat!')

# ======================
# WEBHOOK ENDPOINT
# ======================
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), bot)
    dispatcher.process_update(update)
    return 'OK', 200

@app.route('/health')
def health():
    return 'OK', 200

# ======================
# INITIALIZATION
# ======================
bot = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True).bot
dispatcher = Dispatcher(bot, None, workers=0)
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("checkin", checkin))

# ======================
# MAIN (for local testing)
# ======================
if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
