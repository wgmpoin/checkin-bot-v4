let shareButton = UIButton(type: .system)
shareButton.setTitle("📍 Share Location", for: .normal)  // Ubah teks tombol
shareButton.addTarget(self, action: #selector(requestLocation), for: .touchUpInside)

@objc func requestLocation() {
  locationManager.requestWhenInUseAuthorization()
  locationManager.startUpdatingLocation()
}
