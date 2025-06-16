val shareButton = findViewById<Button>(R.id.share_button)
shareButton.text = "📍 Share Location"  // Ubah teks tombol

shareButton.setOnClickListener {
  if (checkLocationPermission()) {
    requestLocationUpdates()
  } else {
    Toast.makeText(this, "Aktifkan GPS terlebih dahulu!", Toast.LENGTH_LONG).show()
  }
}
