// server.js
app.post('/api/save', async (req, res) => {
  // Log semua request masuk
  console.log('Headers:', req.headers);
  console.log('Body:', req.body);

  // Validasi wajib
  if (!req.body.lat || !req.body.lng) {
    return res.status(400).json({ 
      error: "Koordinat tidak valid",
      contoh_format: { lat: -6.2, lng: 106.8 }
    });
  }

  // Simpan ke database
  try {
    const result = await db.collection('locations').insertOne({
      lat: parseFloat(req.body.lat),
      lng: parseFloat(req.body.lng),
      createdAt: new Date()
    });
    
    res.json({ success: true, id: result.insertedId });
  } catch (err) {
    console.error('DB Error:', err);
    res.status(500).json({ error: "Database error" });
  }
});
