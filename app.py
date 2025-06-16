from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# Endpoint penyimpanan lokasi
@app.route('/api/save-location', methods=['POST'])
def save_location():
    try:
        data = request.json
        lat = data.get('latitude')
        lng = data.get('longitude')
        
        if not lat or not lng:
            return jsonify({"error": "Latitude dan longitude diperlukan"}), 400
        
        # Contoh penyimpanan sederhana
        print(f"Menyimpan lokasi - Lat: {lat}, Lng: {lng}")
        
        return jsonify({
            "status": "success",
            "data": {"latitude": lat, "longitude": lng}
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check untuk Koyeb
@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
