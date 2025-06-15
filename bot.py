import os
import logging
from datetime import datetime
import gspread
from telegram import Update
from telegram.ext import Updater, CommandHandler
from oauth2client.service_account import ServiceAccountCredentials

# ======================
# SETUP LOGGING
# ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======================
# CONFIGURATION
# ======================
def get_credentials():
    """Load and validate Google Sheets credentials"""
    try:
        private_key = os.getenv('GSHEET_PRIVATE_KEY', '').replace('\\n', '\n')
        
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            raise ValueError("Invalid private key format")

        return {
            "type": "service_account",
            "project_id": os.getenv('GSHEET_PROJECT_ID'),
            "private_key_id": os.getenv('GSHEET_PRIVATE_KEY_ID'),
            "private_key": private_key,
            "client_email": os.getenv('GSHEET_CLIENT_EMAIL'),
            "client_id": os.getenv('GSHEET_CLIENT_ID'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GSHEET_CLIENT_EMAIL', '').replace('@', '%40')}"
        }
    except Exception as e:
        logger.error(f"Credential setup failed: {str(e)}")
        raise

# ======================
# GOOGLE SHEETS SETUP
# ======================
def init_gsheet():
    """Initialize Google Sheets connection"""
    try:
        scope = ["https://spreadsheets.google.com/feeds"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(get_credentials(), scope)
        client = gspread.authorize(creds)
        sheet_url = os.getenv('SHEET_URL')
        if not sheet_url:
            raise ValueError("SHEET_URL environment variable not set")
        return client.open_by_url(sheet_url).sheet1
    except Exception as e:
        logger.error(f"Google Sheets init failed: {str(e)}")
        raise

# ======================
# TELEGRAM HANDLERS
# ======================
def start(update: Update, context):
    try:
        update.message.reply_text('✅ Bot Check-in Sales siap! Gunakan /checkin')
        logger.info(f"Start command from {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Start command failed: {str(e)}")

def checkin(update: Update, context):
    try:
        user = update.effective_user
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row = [
            str(user.id),
            user.first_name or '',
            user.username or '',
            timestamp
        ]
        
        sheet = init_gsheet()
        sheet.append_row(row)
        
        update.message.reply_text('✅ Data berhasil dicatat!')
        logger.info(f"Check-in recorded for {user.id} at {timestamp}")
    except Exception as e:
        logger.error(f"Check-in failed: {str(e)}")
        update.message.reply_text('❌ Gagal mencatat data. Coba lagi nanti.')

# ======================
# MAIN APPLICATION
# ======================
def main():
    try:
        logger.info("Starting bot initialization...")
        
        # Validate essential environment variables
        required_vars = [
            'TELEGRAM_TOKEN',
            'GSHEET_PRIVATE_KEY',
            'GSHEET_CLIENT_EMAIL',
            'SHEET_URL'
        ]
        
        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Missing required environment variable: {var}")
        
        # Initialize bot
        updater = Updater(os.getenv('TELEGRAM_TOKEN'))
        dp = updater.dispatcher
        
        # Add handlers
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(CommandHandler("checkin", checkin))
        
        # Start polling
        updater.start_polling()
        logger.info("Bot started and polling...")
        updater.idle()
        
    except Exception as e:
        logger.critical(f"Bot crashed: {str(e)}")
        raise

if __name__ == '__main__':
    main()
