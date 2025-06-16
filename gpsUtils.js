// Fungsi deteksi GPS dengan timeout
function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Browser tidak mendukung GPS'));
      return;
    }

    const options = {
      enableHighAccuracy: true,
      timeout: 10000,  // 10 detik timeout
      maximumAge: 0
    };

    navigator.geolocation.getCurrentPosition(
      position => resolve({
        lat: position.coords.latitude,
        lng: position.coords.longitude
      }),
      error => {
        switch(error.code) {
          case 1: 
            reject(new Error('Aktifkan izin lokasi di browser'));
            break;
          case 2:
            reject(new Error('Lokasi tidak terdeteksi (pastikan GPS aktif)'));
            break;
          case 3:
            reject(new Error('Timeout: Cari lokasi lebih terbuka'));
            break;
          default:
            reject(new Error('Error tidak diketahui'));
        }
      },
      options
    );
  });
}
