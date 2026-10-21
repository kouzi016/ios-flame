#!/bin/bash
# Pull everything the flame port needs from a Pixel 4 (flame) into dumps/.
# Run with the phone in a root adb shell: rooted Android (Magisk) or a
# temporarily booted recovery (`fastboot boot twrp-flame.img`).
# Read-only on the phone. dumps/ is in .gitignore: it holds serials and
# per-device calibration data.
set -euo pipefail
cd "$(dirname "$0")/.."
out=dumps/$(date +%Y%m%d-%H%M%S)
mkdir -p "$out/parts"

rsh() { adb shell "su -c '$1' 2>/dev/null || $1"; }

adb get-state >/dev/null
rsh 'getprop ro.product.device; getprop ro.boot.hardware.sku; getprop ro.build.fingerprint; getprop ro.boot.slot_suffix' > "$out/props.txt"
grep -q flame "$out/props.txt" || { echo "not a Pixel 4 (flame):"; cat "$out/props.txt"; exit 1; }

# Hardware map: the device tree ABL booted with and the physical memory map
adb exec-out "su -c 'cat /sys/firmware/fdt' 2>/dev/null || cat /sys/firmware/fdt" > "$out/live.dtb"
rsh 'cat /proc/iomem' > "$out/iomem.txt"
rsh 'cat /proc/cpuinfo' > "$out/cpuinfo.txt"
rsh 'cat /proc/interrupts' > "$out/interrupts.txt"
rsh 'ls -l /dev/block/by-name/' > "$out/by-name.txt"
rsh 'cat /sys/class/graphics/fb0/modes /sys/class/drm/*/modes' > "$out/display-modes.txt" || true
rsh 'getevent -lp' > "$out/getevent.txt" || true
rsh 'ls /sys/bus/spi/devices /sys/bus/i2c/devices' > "$out/buses.txt" || true

# Partitions with per-device data (cannot be re-downloaded) plus boot images
slot=$(sed -n 4p "$out/props.txt" | tr -d '\r')
for p in persist modemst1 modemst2 fsg fsc efs1 efs2 efsc devinfo \
         "boot$slot" "dtbo$slot" "vbmeta$slot"; do
	if rsh "test -e /dev/block/by-name/$p && echo y" | grep -q y; then
		echo "pull $p"
		adb exec-out "su -c 'cat /dev/block/by-name/$p' 2>/dev/null || cat /dev/block/by-name/$p" > "$out/parts/$p.img"
	fi
done

# Primary GPT of every UFS LUN (4K sectors: PMBR, header, 4 entry blocks).
# ios-topaz's UFS driver once wiped LUN0's GPT; with these it can be
# written back from recovery with dd instead of a full reflash.
for lun in a b c d e f; do
	if rsh "test -e /dev/block/sd$lun && echo y" | grep -q y; then
		echo "pull gpt sd$lun"
		adb exec-out "su -c 'dd if=/dev/block/sd$lun bs=4096 count=6 2>/dev/null' 2>/dev/null || dd if=/dev/block/sd$lun bs=4096 count=6 2>/dev/null" > "$out/parts/gpt-sd$lun.bin"
	fi
done

if command -v dtc >/dev/null; then
	dtc -q -I dtb -O dts -o "$out/live.dts" "$out/live.dtb"
	echo "live.dts: $(wc -l < "$out/live.dts") lines"
else
	echo "dtc not found (brew install dtc); live.dtb saved undecoded"
fi
( cd "$out" && shasum -a 256 live.dtb parts/* > SHA256SUMS )
echo "saved to $out"
