picotool reboot -uf; # reboot into BOOTSEL mode
sleep 5;
picotool load build/carrier_receiver_baseband.elf; # Load the elf file
picotool reboot;
sleep 2;
picocom -b 115200 /dev/ttyACM0; # Connect to see the output CTRL+A CTRL+X to exit picocom

