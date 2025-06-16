import os
import logging
from datetime import datetime
import gspread
from telegram import Update
from telegram.ext import Updater, CommandHandler, Dispatcher
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

app = Flask(__name__)

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global bot variables
bot = None
dispatcher = None

def init_gsheet():
    """Initialize Google Sheets with error handling"""
    try:
        scope = ["https://spreadsheets.google.com/feeds"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            {
                "type": "service_account",
                "private_key": os.getenv('GSHEET_PRIVATE_KEY').replace('\\n', '\n'),
                "client_email": os.getenv('GSHEET_CLIENT_EMAIL')
            },
            scope
        )
        return gspread.authorize(creds).open_by_url(os.getenv('SHEET_URL')).sheet1
    except Exception as e:
        logger.error(f"Sheet error: {str(e)}")
        raise

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Telegram updates"""
    try:
        update = Update.de_json(request.get_json(), bot)
        dispatcher.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return 'Error', 500

@app.route('/health')
def health_check():
    """Koyeb health check"""
    return 'OK', 200

def setup_bot():
    """Initialize Telegram bot"""
    global bot, dispatcher
    bot = Updater(os.getenv('TELEGRAM_TOKEN'), use_context=True).bot
    dispatcher = Dispatcher(bot, None, workers=0)
    
    # Command handlers
    dispatcher.add_handler(CommandHandler("start", 
        lambda u,c: u.message.reply_text('✅ Bot aktif! /checkin')))
    dispatcher.add_handler(CommandHandler("checkin", 
        lambda u,c: (
            init_gsheet().append_row([
                str(u.effective_user.id),
                u.effective_user.first_name or '',
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]),
            u.message.reply_text('✅ Data tersimpan!')
        )))

# Initialize
setup_bot()

if __name__ == '__main__':
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000)
