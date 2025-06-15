import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Updater, CommandHandler
from datetime import datetime

# Config
TOKEN = os.getenv('7973184485:AAExm9nzRRyEMv6G3h0w3DQa8svxtrTlzsU')
GSHEET_CREDENTIALS = {
    "type": "service_account",
    "client_email": os.getenv('sales-bot@botsalestelegram.iam.gserviceaccount.com'),
    "private_key": os.getenv('-----BEGIN PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCnXYK9YlpUp5kxu7BLJA/yHv5P9U8uXSPJoBxO0xVja9NrdExD9FHfdjjIyn4n2Avqg8f+G/mnluMGodZ8sISFCIS0xIVtlkZmQd/M53xI8mk86TJMwtPXiGmL9Q02boqnps2vUq1whXj242MSQ0DTLuFt1xzysKDuA/Abps/SMo31uL6Y+NyVkkFdYd+hdXLrjCvAgYtXSAH+NSLim+CblMK8bwQn0A7y4brgilX+HLvpIYwusjO23JwAc56J9sbp9pXeNrRBHL5QwP7kD8v/p59Xtj6TZSS4VDqaqfyb7ypkIS4+cxup9wLEBqLc+vSGUkKtHoqA4MqEF+GJ0EW9AgMBAAECggEAFZ9kK7mQOA2rIhzAiwSutrZAXu4ve6r2266+2YQ16DFfECvnSoQ/K6KndXGL2PP1nifGZ9MPbxJ0ZD/2aQeZJ2LRWlVlc6INmFp8Yompqfb/l6n9IKOvINJz6GwRd+3SJhTL0BHbbIUh+qun+g0MS/xrjXhUOhqNwBJsK/ZiNSKy/K+20ytB2QMndu5/3z8sLQhqrk304W37SeR3emPdTcQVTPEPkhCuidlrJWevVJz+q2icm2IjenwLLvpSYy1eNb92sVM+sIA+mkmXUaGl0byUObrbQNHCrsmt8ugDGMG61ESia9TQUmYvorbNC1UmRnCx/MLAQZvjuFchvVrhgQKBgQDrb3ehraxxvBXlusqkmloHSCdpW3FrPebQ2fp9+d6ssF21C8CgSQC9peoN84u0Imt3fCKk67ZjhVDrZWNO8WYZpoJbc7MbzJOW4xvZ1ACd88MS1T7S+tXtBIrwMRFjxgL1bPePsJuLIDZB8AmwF5asdYNNV3yq3HQg87zo8k1i4QKBgQC1+/AoiG1u+81vEtrAV3hw3No7KXNSKBu4arbeY+f+oCj2Qdvg27Agg/dfj0Vro0OYpfrxLcvs1mbIbiZAIXoMnwu4/H2byevmA4tlfKJhbzPqvi2d+jAc/PluzDlTiz9V5Divj/OOv29cBwq2avuuHwzOaIHDc81YEtLw9TiaXQKBgFinQp8I7NRvBLfa3I+a56eyTdTocA734kBmtGJXgrf4OXEBGenBU5wWK8pRGRwdkeYOQmVjtOxIuS3KodiKIe4quw+Aw8MGB9Vbc5NUt17C+YPP9LYxafi0KzVC5M9zMo4EGDxtPkTnPkcaAivi1gPexDCNbw5PsRLvdQUqqGVBAoGAKaCSg8MJPTzN9h1a+mpHu5FZPfUyUtWn2ZxXbjFuLNlX5VSVRi8ab6WgHTS5jXCQEsfMygROxEMaybggecTulRqAZPUkilE666dd6H4E6sK0HnsYFi3XeZoIOGbwqgKNH0mQCeCktr9laqiVs7pvDZo+pKxVGm9Pxliv9bwyEWUCgYEA5ePySf0AgOIipQgIHORtIoYtGdzXX1jiR1jk43W9lnz8UK/22ykd56VzNph15hwMvI9ibFPCYTwTSjNy1hjw50VouORoTUXuk2jsz8LyTKncAevLE3Dhw5ayX2+RfAfelekSJgBQE8CAie2wvSPFc3B2B2E61UO9BtYLGi53hp0=-----END PRIVATE KEY-----').replace('\\n', '\n'),
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
