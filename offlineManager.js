// Sync otomatis saat online
window.addEventListener('online', async () => {
  const db = await openDB('LocationCache', 1);
  const tx = db.transaction('unsaved', 'readwrite');
  const store = tx.objectStore('unsaved');
  
  let cursor = await store.openCursor();
  while (cursor) {
    try {
      await fetch('https://your-app.koyeb.app/api/locations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cursor.value)
      });
      await cursor.delete();
    } catch (error) {
      console.error('Sync failed:', error);
    }
    cursor = await cursor.continue();
  }
});
