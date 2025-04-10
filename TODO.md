# ✅ TODO List for WRowFusion

- [ ] 

## 📌 Current Focus
- [ ] Bluetooth server
- [ ] 

## 🧱 Infrastructure
- [ ] Build systemd service for auto-start
- [ ] Create install script to handle venv setup
- [ ] Setup logging config file with rotation

## 🔄 Data Handling
- [ ] Replace deque with shared DataLogger instance
- [ ] Make DataLogger accessible across threads
- [ ] Evaluate thread safety of DataLogger callbacks

## 📡 Bluetooth & ANT+
- [ ] Add support for ANT+ HR broadcast
- [ ] Implement reconnection logic for BLE HRM
- [ ] Explore need for pyusb (for ANT+ reciever) and gatt (smartrow?) in requirements.txt

## 🧪 Testing & Debugging
- [ ] Add thread monitoring and auto-restart logic
- [ ] Write unit tests for `s4.py` module
- [ ] Create mock Rower class for test mode
- [ ] Split out dev & testing packages from requirements into requirements-dev.txt and handle accordingly in code

## 🗂️ Organisational
- [ ] Clean up unused imports across modules
- [ ] Refactor `wrowfusion.py` for clarity
- [ ] Add high-level project diagram

---

### ✅ Done
- [x] Fork project structure from PiRowFlo
- [x] Initial Bluetooth HRM scan integration
