#!/bin/bash

#########################################################################
# wrowfusion will be installed in the following directory. This script
# will create the directory if it doesn't already exist. (Do not include
# a trailing slash / )
app_dir="/opt/wrowfusion"

# The application will be run on startup by the following system user.
# This script will create this system user.
app_user="wrowfusion"
#########################################################################

set -e  # Exit the script if any command fails

echo " "
echo " "
echo " "
echo " "
echo "  WRowFusion for Waterrower"
echo " "                                                             
echo " "
echo " This script will install all the needed packages and modules "
echo " to make the Waterrower Ant and BLE Raspbery Pi Module working"
echo " "

echo " "
echo "----------------------------------------------"
echo " Install required system software packages "
echo "----------------------------------------------"
echo " "

echo " - Refreshing list of available softare packages"
sudo apt-get update
echo " "

echo " - Installing softare packages"
sudo apt-get install -y \
    python3 \
    python3-gi \
    python3-gi-cairo \
    gir1.2-gtk-3.0 \
    python3-pip \
    libatlas-base-dev \
    libglib2.0-dev \
    libdbus-1-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7 \
    libtiff6

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Configure system user ${app_user}"
echo "----------------------------------------------"
echo " "

if ! id "$app_user" &>/dev/null; then
  if ! sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$app_user"; then
      echo "Failed to create user $app_user. Exiting."
      exit 1
  fi
fi

sudo usermod -aG bluetooth,dialout,gpio "$app_user"

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Check for any existing wrowfusion service."
echo "----------------------------------------------"
echo " "

if systemctl is-active --quiet "wrowfusion"; then
    echo " Stopping existing wrowfusion service..."
    sudo systemctl stop "wrowfusion"
else
    echo " wrowfusion is not running."
fi

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Install the application in the directory:"
echo " ${app_dir}"
echo "----------------------------------------------"
echo " "


echo " Cleaning any existing $app_dir..."
sudo rm -rf "$app_dir"/*

sudo mkdir -p "$app_dir"

# Untested code to delete everything within the app directory except the log directory and its contents
#echo " Cleaning any existing $app_dir while preserving logs..."
#shopt -s extglob
#cd "$app_dir" || exit 1
#sudo rm -rf !(logs)

echo " Done."

echo " Copying application files to $app_dir..."
script_dir=$(cd "$(dirname "$0")" && pwd)
sudo cp -r "$script_dir"/* "$app_dir/"
sudo chown -R "$app_user:$app_user" "$app_dir"

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Set up virtual environment        "
echo "----------------------------------------------"
echo " "

sudo -u "$app_user" python3 -m venv "$app_dir"/venv

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Install python modules needed by WRowFusion"
echo "----------------------------------------------"
echo " "

sudo -u "$app_user" "$app_dir"/venv/bin/python3 -m pip install --upgrade --no-cache-dir pip setuptools wheel
sudo -u "$app_user" "$app_dir"/venv/bin/python3 -m pip install --no-cache-dir -r "$app_dir"/requirements.txt

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Check for Ant+ dongle in order to set udev"
echo " rules. Load the Ant+ dongle with FTDI driver"
echo " and ensure that the user has access to it"
echo "----------------------------------------------"
echo " "

# https://unix.stackexchange.com/questions/67936/attaching-usb-serial-device-with-custom-pid-to-ttyusb0-on-embedded

IFS=$'\n'
arrayusb=($(lsusb | cut -d " " -f 6 | cut -d ":" -f 2))

for i in "${arrayusb[@]}"
do
  if [ $i == 1008 ]|| [ $i == 1009 ] || [ $i == 1004 ]; then
    echo "Ant dongle found"
    echo 'ACTION=="add", ATTRS{idVendor}=="0fcf", ATTRS{idProduct}=="'$i'", RUN+="/sbin/modprobe ftdi_sio" RUN+="/bin/sh -c '"'echo 0fcf 1008 > /sys/bus/usb-serial/drivers/ftdi_sio/new_id'\""'' > /etc/udev/rules.d/99-garmin.rules
    echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0fcf", ATTR{idProduct}=="'$i'", MODE="666"' >> /etc/udev/rules.d/99-garmin.rules
    echo "udev rule written to /etc/udev/rules.d/99-garmin.rules"
    break
  else
    echo "No Ant stick found !"
  fi

done
unset IFS

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Change the Pi's bluetooth name to WRowFusion"
echo "----------------------------------------------"
echo " "

echo "PRETTY_HOSTNAME=WRowFusion" | sudo tee -a /etc/machine-info > /dev/null

#echo " "
#echo "------------------------------------------------------------"
#echo " Update bluetooth settings according to Apple specifications"
#echo "------------------------------------------------------------"
#echo " "
# update bluetooth configuration and start supervisord from rc.local
#
#cp services/update-bt-cfg.service services/update-bt-cfg.service.tmp
#sed -i 's@#REPO_DIR#@'"$repo_dir"'@g' services/update-bt-cfg.service.tmp
#sudo mv services/update-bt-cfg.service.tmp /etc/systemd/system/update-bt-cfg.service
#sudo chown root:root /etc/systemd/system/update-bt-cfg.service
#sudo chmod 655 /etc/systemd/system/update-bt-cfg.service
#sudo systemctl enable update-bt-cfg

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Configure bluetooth settings in "
echo " /etc/bluetooth/main.conf"
echo "----------------------------------------------"
echo " "

# Set ControllerMode to le
if ! grep -q '^ControllerMode' /etc/bluetooth/main.conf; then
    echo "ControllerMode = le" | sudo tee -a /etc/bluetooth/main.conf > /dev/null
else
    sudo sed -i 's/^ControllerMode=.*/ControllerMode = le/' /etc/bluetooth/main.conf
fi

# Set Experimental to false
if ! grep -q '^Experimental' /etc/bluetooth/main.conf; then
    echo "Experimental = false" | sudo tee -a /etc/bluetooth/main.conf > /dev/null
else
    sudo sed -i 's/^Experimental=.*/Experimental = false/' /etc/bluetooth/main.conf
fi

# Set JustWorksRepairing to always
if ! grep -q '^JustWorksRepairing' /etc/bluetooth/main.conf; then
    echo "JustWorksRepairing = always" | sudo tee -a /etc/bluetooth/main.conf > /dev/null
else
    sudo sed -i 's/^JustWorksRepairing=.*/JustWorksRepairing = always/' /etc/bluetooth/main.conf
fi

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Update bluart file as it prevents the start of"
echo " internal bluetooth if usb bluetooth dongle is "
echo " present                                       "
echo "----------------------------------------------"
echo " "

sudo sed -i 's/hci0/hci2/g' /usr/bin/btuart

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Configure logging for the local environment"
echo "----------------------------------------------"
echo " "

sudo -u "$app_user" cp "$app_dir"/config/logging.conf.orig "$app_dir"/config/logging.conf
sudo -u "$app_user" sed -i 's@#REPO_DIR#@'"$app_dir"'@g' "$app_dir"/config/logging.conf

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Initialising WRowFusion database..."
echo "----------------------------------------------"
echo " "

sudo -u "$app_user" "$app_dir"/venv/bin/python3 "$app_dir"/src/db/db_init.py

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Start WRowFusion when system boots"
echo "----------------------------------------------"
echo " "

sudo cp "$app_dir"/config/wrowfusion.service /etc/systemd/system/wrowfusion.service
sudo sed -i 's@#REPO_DIR#@'"$app_dir"'@g' /etc/systemd/system/wrowfusion.service
sudo sed -i 's@#APP_USER#@'"$app_user"'@g' /etc/systemd/system/wrowfusion.service
sudo chmod 644 /etc/systemd/system/wrowfusion.service
sudo systemctl daemon-reload
sudo systemctl enable wrowfusion

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Restart services and run wrowfusion service"
echo "----------------------------------------------"
echo " "

sudo systemctl restart bluetooth
sudo systemctl start wrowfusion

#echo " "
#echo "----------------------------------------------"
#echo " installation done ! rebooting in 3, 2, 1 "
#echo "----------------------------------------------"
#sleep 3
#sudo reboot

echo " Done."
echo " "
echo "----------------------------------------------"
echo " Installation complete!"
echo "----------------------------------------------"
echo " "

exit 0