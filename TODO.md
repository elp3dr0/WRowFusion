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

## 🖧 Comms with S4
- [ ] Consider handling situation when S4 gets disconnected from serial port. Currently
        the S4 Rower instance and the WRtoBLEANT DataLogger instance persist and the 
        main s4_data_task loop continues looping, trying to poll the data from the S4.
        That doesn't break anything, but it seems unnecesary when no s4 is connected.
        However, we'd only get into this situation if an S4 had already been detected,
        otherwise the code would loop in the S4.open method without ever entering the main
        data polling loop of s4_data_task. So if we're already in the main loop of 
        the s4_data_task, perhaps we don't want to kill the Datalogger and Rower instances
        even if the S4 gets disconnected because doing so could have unintended consequences
        on data flow (e.g. would it reset interval training?) And it's unknown how often
        disconnects might be detected - is it only when the plug is physically removed
        or does it happen momentarily from time to time? This might be a case of if it aint broke.  

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
