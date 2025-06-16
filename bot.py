from telegram.ext import ConversationHandler

# Definisikan state
LOCATION_NAME, AREA = range(2)

def start_checkin(update: Update, context: CallbackContext):
    update.message.reply_text("🏷️ Masukkan NAMA LOKASI (contoh: TB Makmur Jaya, Kantor Pajak):")
    return LOCATION_NAME

def get_location_name(update: Update, context: CallbackContext):
    context.user_data['location_name'] = update.message.text
    update.message.reply_text("📍 Sekarang masukkan WILAYAH (contoh: Surabaya, Jl. Sudirman No. 5):")
    return AREA

def get_area_and_save(update: Update, context: CallbackContext):
    user = update.effective_user
    area = update.message.text
    
    sheet = init_gsheet().sheet1
    sheet.append_row([
        str(user.id),
        user.first_name or '',
        user.username or '',
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        context.user_data['location_name'],
        area,
        f"https://maps.google.com/?q={context.user_data.get('latitude', '')},{context.user_data.get('longitude', '')}"
    ])
    
    update.message.reply_text(f"""
✅ CHECK-IN BERHASIL
🏠 Lokasi: {context.user_data['location_name']}
📍 Wilayah: {area}
🕒 Waktu: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
""")
    
    # Reset data
    context.user_data.clear()
    return ConversationHandler.END

# Tambahkan handler baru
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('checkin', start_checkin)],
    states={
        LOCATION_NAME: [MessageHandler(Filters.text & ~Filters.command, get_location_name)],
        AREA: [MessageHandler(Filters.text & ~Filters.command, get_area_and_save)]
    },
    fallbacks=[]
)

dispatcher.add_handler(conv_handler)
