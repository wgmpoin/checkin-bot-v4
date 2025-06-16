import os
import logging
from datetime import datetime
import gspread
from telegram import Update
from telegram.ext import Updater, CommandHandler, Dispatcher
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global variables for Telegram bot
bot = None
dispatcher = None

# Google Sheets setup
def init_gsheet():
    try:
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
    except Exception as e:
        logger.error(f"Google Sheets init failed: {str(e)}")
        raise

# Telegram command handlers
def start(update: Update, context):
    update.message.reply_text('✅ Bot Check-in Sales siap! Gunakan /checkin')

def checkin(update: Update, context):
    try:
        user = update.effective_user
        sheet = init_gsheet()
        sheet.append_row([
            str(user.id),
            user.first_name or '',
            user.username or '',
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ])
        update.message.reply_text('✅ Data berhasil dicatat!')
    except Exception as e:
        logger.error(f"Check-in failed: {str(e)}")
        update.message.reply_text('❌ Gagal mencatat data. Coba lagi nanti.')

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = Update.de_json(request.get_json(), bot)
        dispatcher.process_update(update)
        return 'OK', 200
    return 'Bad Request', 400

# Health check endpoint
@app.route('/health')
def health_check():
    return 'OK', 200

def setup_bot():
    global bot, dispatcher
    bot = Updater(token=os.getenv('TELEGRAM_TOKEN'), use_context=True).bot
    dispatcher = Dispatcher(bot, None, workers=0)
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("checkin", checkin))

# Initialize the bot
setup_bot()

if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
