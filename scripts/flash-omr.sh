#!/bin/sh
set -eu
IMG_URL=${IMG_URL:-https://www.openmptcprouter.com/download/openmptcprouter-v0.63-x86_64-ext4-efi.img.gz}
TARGET=${1:-}
[ -n "$TARGET" ] || { echo "usage: $0 /dev/sdX"; exit 2; }
echo "DANGER: will flash $IMG_URL to $TARGET"
printf 'Type YES: '; read ans; [ "$ans" = YES ]
wget -O /tmp/omr.img.gz "$IMG_URL"
gzip -dc /tmp/omr.img.gz | dd of="$TARGET" bs=4M status=progress conv=fsync
