// Deteksi dukungan & status GPS
export const checkGPS = async () => {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve({ supported: false });
      return;
    }

    // Cek permission status (hanya bekerja di beberapa browser)
    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'geolocation' })
        .then(permissionStatus => {
          resolve({
            supported: true,
            enabled: permissionStatus.state === 'granted',
            state: permissionStatus.state
          });
        });
    } else {
      // Fallback untuk browser lama
      navigator.geolocation.getCurrentPosition(
        () => resolve({ supported: true, enabled: true }),
        () => resolve({ supported: true, enabled: false }),
        { maximumAge: 0, timeout: 5000 }
      );
    }
  });
};

// Fungsi wrapper dengan timeout
export const getPositionWithTimeout = (options = {}) => {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('GPS_TIMEOUT')),
      options.timeout || 15000
    );

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timer);
        resolve(pos);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
      { 
        enableHighAccuracy: true,
        ...options 
      }
    );
  });
};
