// Fungsi utama penyimpanan lokasi
export const saveLocation = async (lat, lng) => {
  // 1. Siapkan payload standar
  const payload = {
    location: { lat, lng },
    metadata: {
      timestamp: new Date().toISOString(),
      device: navigator.platform,
      os: navigator.userAgent
    }
  };

  // 2. Coba simpan ke server
  try {
    const response = await fetch('https://your-app.koyeb.app/api/locations', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-App-Version': '1.0.0'
      },
      body: JSON.stringify(payload)
    });

    // 3. Handle response error
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Server rejected the request');
    }

    // 4. Hapus data offline jika ada
    await removeOfflineData(lat, lng);
    return await response.json();

  } catch (error) {
    // 5. Fallback ke offline storage
    await saveToIndexedDB(payload);
    throw new Error(`OFFLINE_MODE: ${error.message}`);
  }
};

// Helper: Simpan ke IndexedDB
const saveToIndexedDB = async (data) => {
  const db = await openDB('LocationCache', 1, {
    upgrade(db) {
      db.createObjectStore('unsaved', { keyPath: 'id', autoIncrement: true });
    }
  });
  await db.add('unsaved', data);
};
