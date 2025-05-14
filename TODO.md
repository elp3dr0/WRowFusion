# ✅ TODO List for WRowFusion

## 📌 Current Focus
- [ ] Debug bluetooth server
- [ ] 

## 🧱 Infrastructure
- [x] Build systemd service for auto-start
- [x] Create install script to handle venv setup
- [x] Setup logging config file with rotation
- [x] Add user to the GPIO group so that the program can be run without root

## New functionality
- [ ] Turn USB ports off after 10mins of no rowing. Add a button that turns the USB ports back on.
- [ ] Review FTM_SUPPORTED_FEATURES in ble_server, make the list reflect what we actually support (refer to BLE specs
      determine what each thing means). Add functionality to support other features. Check whether supporting other
      features means having to transmit the features in two packets.


## 🔄 Data Handling
- [ ] Replace deque with shared DataLogger instance
- [ ] Replace reset q with object
- [ ] Make DataLogger accessible across threads
- [ ] Evaluate thread safety of DataLogger callbacks
- [ ] Remove TXValues from s4.py if shared access to DataLogger is working
- [ ] Remove CueToBLEANT from s4.py if shared access to DataLogger is working
- [ ] I want my application to be responsive to the workout mode that someone has selected on the S4. What frequency should I poll those at? Should the polling 
        be another loop in s4if, or should it be application side? Store the modes when the flags are read.
- [ ] The workout flags are currently being converted to decimal on import, so adjust the decode_flags method to accept either int or hex string.
- [ ] Respond to the workout mode in application side logic. E.g. store the workout limit field as a duration limit or distance limit.
- [x] See what's in registers 144-147 and 1E4-1E7. Result - s4 returns an error response when a request to read those addresses is sent
- [ ] Decide whether to inc sec_dec. In anycase decide whether to round or not and adjust the code as necessary.
- [ ] Handle all the rest of the workout data
- [ ] Figure out how to indicate just row or workout, and how to determine just row conditions - is it flags =0 or flags <16?
- [ ] In s4if Make get on demand command stuff thread safe. Decide how destructive it will be for existing requests in the buffer, and how
        impolite it will be with hogging the serial while waiting for its response.

## 📡 Bluetooth & ANT+
- [ ] Add peripheral Privacy Flag in advertisement and configure Pi to be able to handle address randomisation (see note 1)
- [ ] Add support for ANT+ HR broadcast
- [ ] Change the logic for recording Heart Rate:
        * On scanning for Heart Rate Monitor, find the best signal amongst both Bluetooth and Ant
        * Once an HRM is selected, record only those values in the hr_monitor class.
- [ ] Explore need for pyusb (for ANT+ reciever) and gatt (smartrow?) in requirements.txt
- [ ] Address the ERROR DIFF TRANSACTION COLLISION seen in nRF debug logs during a succesful connection (see note 4)
- [ ] Revisit MITM Bluetooth connection requests from Android. If they continue to be a significant hurdle, then explore a static passkey (see note 5).
- [ ] Consider adding BLE Heart Rate Control Point functionality to ble_client.py to allow a reset of Expended Energy for devices that support it.
- [ ] Investigate error: "src.ble_client: HeartRateBLEScanner Monitor loop error: [org.bluez.Error.InProgress] Operation already in progress. Retrying in 60 seconds." Likely to do with existing discovery process? Encountered after installation over previous installation. Or possibly whenever the service is restarted without a reboot. Currently a reboot clears it.
- [ ] Add Body Sensor Location Characteristic to Heart Rate service in ble_standard_service and BLE Server (see Bluetooth HRP V10 pdf)
- [ ] Add Heart Rate Control Point Characteristic to Heart Rate Service in ble_standard_service and application logic to handle reset events and computation of total session kcals, broadcasting that value to Heart rate clients. (see Bluetooth HRP V10 pdf and HRS Spec V10 pdf)
- [ ] IIRC, the BLE server custom exceptions are defined in ble_if and are repeated in ble_server. Instead they should just be imported (can they be made subclasses of a parent class which is then imported in one class?)

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
- [ ] Make necessary adjustments to /etc/bluetooth/main.conf during install script (see ble_notes.md)
- [ ] Populate README and add references to PiRowFlo.

---

### ✅ Done
- [x] Fork project structure from PiRowFlo
- [x] Initial Bluetooth HRM scan integration
- [x] Implement reconnection logic for BLE HRM
