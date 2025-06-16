const { Telegraf } = require('telegraf');

const bot = new Telegraf(process.env.BOT_TOKEN);

// PERUBAHAN UTAMA DI SINI:
bot.command('start', (ctx) => {
  ctx.reply('Silakan share lokasi Anda:', {
    reply_markup: {
      keyboard: [
        [ 
          {
            text: "📍 Share Location",  // Teks tombol berubah
            request_location: true     // Tombol khusus minta lokasi
          }
        ]
      ],
      resize_keyboard: true,    // Tombol menyesuaikan ukuran
      one_time_keyboard: true    // Tombol hilang setelah diklik
    }
  });
});

// Handle lokasi yang dikirim user
bot.on('location', async (ctx) => {
  const { latitude, longitude } = ctx.message.location;
  await saveToDatabase(latitude, longitude);
  ctx.reply('Lokasi berhasil disimpan! 🗺️');
});

bot.launch();
