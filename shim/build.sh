#!/bin/bash
# Build the shim and wrap it in a boot.img v2 that mirrors the stock Pixel 4
# (flame) header: dtb/boot_unpacked comes from tools/unpack_bootv2.py.
set -euo pipefail
cd "$(dirname "$0")"
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"
mkdir -p out
for f in start.S shim.c console.c mmu.c fdt.c loader.c ufs.c mdp.c; do
	$CC $CFLAGS ${EXTRA_CFLAGS:-} -c $f -o out/${f%.*}.o
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$(aarch64-linux-gnu-readelf -r out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/ufs.o out/mdp.o | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N \
	out/start.o out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/ufs.o out/mdp.o -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print $1}' | xargs -I{} python3 -c 'print(int("{}", 16))')
truncate -s "$size" out/Image
# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
if [ -n "${1:-}" ]; then
	cp "$1" out/ramdisk.bin
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi
# Same OS version and patch level as the stock boot.img: Pixel ABL hands them
# to Keymaster, and a newer patch level there can lock stock Android out of
# its keys after going back.
hdr=../dtb/boot_unpacked/header.txt
osv=$(awk '/^os_version_str:/{print $2}' "$hdr")
ospl=$(awk '/^os_patch_level:/{print $2}' "$hdr")
[ -n "$osv" ] && [ -n "$ospl" ] || { echo "error: re-run tools/unpack_bootv2.py on the stock flame boot.img" >&2; exit 1; }
# Pixel ABL (flame, 2026-10-21): only an LZ4 *frame* kernel is accepted (raw
# or `lz4 -l` legacy -> "Unsupported"), and the Image header needs
# text_offset 0x80000 (0 -> "Invalid Parameter"). Same as the stock kernel.
lz4 -9 -f -q out/Image out/Image.lz4
mkbootimg --header_version 2 --kernel out/Image.lz4 --ramdisk out/ramdisk.bin \
	--dtb ../dtb/boot_unpacked/dtb --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \
	--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \
	--os_version "$osv" --os_patch_level "$ospl" \
	--cmdline "console=null" -o out/shim-boot.img
# Stock boot.img has an AVB hash footer in a 64 MiB partition image; keep that
# (no signature: algorithm NONE, like stock). tools/avbtool.py is AOSP's.
python3 -I ../tools/avbtool.py add_hash_footer --image out/shim-boot.img --partition_size 67108864 \
	--partition_name boot --algorithm NONE --prop com.android.build.boot.os_version:13 \
	--prop com.android.build.boot.security_patch:2022-10-05
# Host render of the console layout.
gcc -O1 -Wall -o out/host_test console.c host_test.c && ./out/host_test
ls -l out/Image out/shim-boot.img
