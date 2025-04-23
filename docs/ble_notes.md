## Objectives

- Act as a client to recieve heart rate data from a heart rate monitor (HRM)
- Act as a server to send water rower data
- Act as a server to send heart rate data 

## Acting as a server

The project uses the Bluez Bluetooth Stack.
Bluez is a specific implementation of this Bluetooth stack designed for the Linux kernel. It's the software that provides the Bluetooth capabilities within the Linux operating system. It includes:
- **Core Components:** Bluez includes kernel modules (drivers) for interacting with Bluetooth hardware and a user-space daemon (bluetoothd) that manages higher-level Bluetooth functions through a D-Bus API.
- **Protocol Implementation:** Bluez implements the core Bluetooth protocols like HCI (Host Controller Interface), L2CAP (Logical Link Control and Adaptation Protocol), and others within the kernel.   
- **User Space Utilities:** It also provides command-line tools (like hcitool, hciconfig, bluetoothctl) and libraries (libbluetooth) that allow user-space applications to interact with the Bluetooth stack.
- **Profile Support:** Bluez enables the implementation of various Bluetooth profiles (like A2DP for audio, HSP for headsets, etc.), often integrating with other Linux subsystems like audio servers (e.g., PipeWire).   

Bluez uses D-Bus for its primary control and management interface. Think of D-Bus as the messenger and control panel for Bluez. Applications don't directly manipulate the Bluetooth hardware; instead, they send messages and commands to the Bluez daemon via D-Bus, and Bluez handles the interaction with the lower layers of the Bluetooth stack. So, while Bluez is the Bluetooth stack, D-Bus is the standard communication channel that applications use to interact with and control that stack.

The logic for the bluetooth server is handled by two modules:
- **bleif.py:** Generic BLE code for connecting and resolving services and interacting with BLE characteristics and descriptors.
- **ble_server.py:** Defines the task that manages the BLE server and configures the specific BLE services.

## Gotchas
**MITM services preventing connection**
The objective of the project is to behave as an appliance and the Raspberry Pi is not enivsaged to have any input device. Bluetooth pairing should therefore be automatic and not require the user to input a pairing code. Because we do not want the user to enter a code, the RaspberryPi's bluetooth server advertises itself with a capability of "NoInputNoOutput", which signifies that it cannot pass a connection code to a connecting device.

However, certain services require a code to be entered by the user to allow the two devices to connect. If the Raspberry Pi advertises one of these service that requires a code to allow pairing, then on connection, the connecting device will ask for the code, and the Raspberry Pi will respond that it is NoInputNoOutput, at which point the connection cannot continue because it is contingent on a code that cannot be entered and so the devices will disconnect. So even if the Raspberry Pi is advertising other services that do not require a code on connection, the existance of just one service that requires a connection can make it impossible to connect the Raspberry Pi to a bluetooth device.

It's important therefore to remove any services that might require a code on connection from the configuration of the Raspberry Pi server. To limit the possibilities of this problem, the Raspberry Pi's bluetooth configuration file should:
- be set to ble only (i.e. not traditional bluetooth): This will surpress a number of unrequired services that would be enabled by default (e.g. A/V Remote Control, Handsfree Audio Gateway, Audio Sink, Audio Source, etc).
- Disable D-Bus experimental interfaces: This will prevent the unwanted addition of the Volume Control service.

To achieve this, edit the bluetooth conf file (sudo nano /etc/bluetooth/main.conf) and in the General section, set:
- ControllerMode = le
- Experimental = false

**Bluez PnP Device Information prevents Coxswain from connecting**
Bluez versions greater than 5.50 introduced a PnP Device which is advertised by default by the Raspberry Pi. This is problematic because it will advertise a Device Information service (0x180A) that describes the Raspberry Pi as a PnP device. However, the Coxswain app interrogates the Device Information data to determine whether the device is a Rowing machine or not. Our project creates a Device Information service that presents the Raspberry Pi as if it were an S4 Waterrower. However, if on connection, Coxswain reads the PnP Device Information first, it will deduce that our Raspberry Pi is not a Waterrower. At the very least, it will prevent Coxswain from being able to issue a reset command to the S4 (according to the author of PiRowFlo), though it might also prevent Coxswain from connecting to the Raspberry Pi at all.

Check your Bluez version from the Raspberry Pi commandline:
bluetoothctl --version

If it is greater than 5.50, you likely need to remove the section of code from Bluez that creates the PnP device and then rebuild from source. To be clear, this involves modifying the source code of Bluez, not modifying the code of this project.

The problematic code was introduced with [this commit](https://git.kernel.org/pub/scm/bluetooth/bluez.git/commit/?id=d5e07945c4aa36a83addc3c269f55c720c28afdb)
The commit suggests that this behaviour can be controlled via the /etc/bluetooth/main.conf file. However as of April 2025 Bluez 5.66, it is not documented and is not clear how to prevent the addition of this PnP device by configuring main.conf. Consequently, in order to prevent the PnP device from creating a Device Information conflict, you will have to remove the problematic code from Bluez and rebuild.

Loosely, instructions are as follows:

✅ 1. Install Build Dependencies
Run these to get all the needed tools and libraries:
sudo apt update
sudo apt install -y libdbus-1-dev libudev-dev libical-dev libreadline-dev libglib2.0-dev libbluetooth-dev \
                    build-essential libtool autoconf automake pkg-config git

If your system uses libsystemd, you may also need:
sudo apt install -y libsystemd-dev

✅ 2. Download BlueZ 5.66 Source
cd ~
wget https://www.kernel.org/pub/linux/bluetooth/bluez-5.66.tar.xz
tar -xf bluez-5.66.tar.xz
cd bluez-5.66

✅ 3. Locate the Code that Adds the DIS (PnP) Service
The problematic code lives in:
src/gatt-database.c, specifically inside gatt_db_add_default_services().

Open the file in your preferred editor:
nano src/gatt-database.c

✅ 4. Comment Out the PnP code and just short-circuit the function:
static void populate_devinfo_service(struct btd_gatt_database *database)
{
    /*
    add the line above right at the start of the function code in order to start commenting it out

    and then add the line below at the end of the function code to turn all the existing code into a comment. And then add the return; statement so that the function won't produce an error if it's called, but it will do nothing.
    */

    return;
}

🏗️ Implementing your patch and restarting bluetooth
make clean
./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var
make -j$(nproc)
sudo make install
sudo systemctl restart bluetooth
