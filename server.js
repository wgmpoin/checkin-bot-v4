import express from 'express';
import cors from 'cors';
import { log } from './logger.js';

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors({
  origin: ['https://your-app.koyeb.app', 'http://localhost:3000'],
  methods: ['POST', 'GET']
}));
app.use(express.json());

// Endpoint Penyimpanan
app.post('/api/locations', async (req, res) => {
  try {
    log('Received payload:', req.body);

    // Validasi
    if (!req.body?.location?.lat || !req.body?.location?.lng) {
      return res.status(400).json({
        error: 'Invalid payload',
        required_fields: ['location.lat', 'location.lng']
      });
    }

    // Simpan ke database (contoh MongoDB)
    const result = await db.collection('locations').insertOne({
      ...req.body,
      ip: req.ip,
      createdAt: new Date()
    });

    // Response sukses
    res.json({
      success: true,
      locationId: result.insertedId,
      timestamp: new Date()
    });

  } catch (err) {
    log('Server error:', err);
    res.status(500).json({
      error: 'Internal server error',
      details: process.env.NODE_ENV === 'development' ? err.message : null
    });
  }
});

// Health Check untuk Koyeb
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'OK',
    timestamp: new Date(),
    uptime: process.uptime()
  });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
