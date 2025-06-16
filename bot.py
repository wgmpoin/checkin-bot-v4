import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, ConversationHandler, Dispatcher
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request

app = Flask(__name__)

# ===== KONFIGURASI =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# State untuk ConversationHandler
LOCATION_NAME, AREA = range(2)

# ===== INISIALISASI BOT =====
def init_bot():
    updater = Updater(os.getenv('TELEGRAM_TOKEN'), use_context=True)
