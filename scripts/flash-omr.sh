#!/bin/sh
set -eu
IMG_URL=${IMG_URL:-https://www.openmptcprouter.com/download/openmptcprouter-v0.63-x86_64-ext4-efi.img.gz}
IMG_SHA256=${IMG_SHA256:-}
TARGET=${1:-}
[ -n "$TARGET" ] || { echo "usage: $0 /dev/sdX"; exit 2; }
echo "DANGER: will flash $IMG_URL to $TARGET"
printf 'Type YES: '; read ans; [ "$ans" = YES ]
wget -O /tmp/omr.img.gz "$IMG_URL"

# Integrity verification - fail-closed; never flash an unverified image.
# NOTE on trust model: the same-origin ${IMG_URL}.sha256 auto-fetch below only
# guards against a corrupted/partial DOWNLOAD. It does NOT prove authenticity -
# an attacker controlling the origin or MITMing the transfer controls both the
# image and its .sha256, so the two will always agree. For authenticity, pin
# IMG_SHA256 from a TRUSTED out-of-band source.
actual=$(sha256sum /tmp/omr.img.gz | awk '{print $1}')
echo "sha256: $actual"

if [ -z "$IMG_SHA256" ]; then
  rm -f /tmp/omr.img.gz.sha256
  wget -qO /tmp/omr.img.gz.sha256 "${IMG_URL}.sha256" || true
  if [ -s /tmp/omr.img.gz.sha256 ]; then
    IMG_SHA256=$(grep -oE '[0-9a-fA-F]{64}' /tmp/omr.img.gz.sha256 | head -n1)
  fi
fi

if [ -z "$IMG_SHA256" ]; then
  echo "ERROR: no expected sha256 available (no sibling .sha256 file and IMG_SHA256 not set)."
  echo "Obtain the expected hash from a TRUSTED out-of-band source (the project's"
  echo "release page or signed manifest - NOT the computed value above, which only"
  echo "echoes whatever was downloaded), then re-run:"
  echo "  IMG_SHA256=<trusted-hash> $0 $TARGET"
  exit 1
fi

expected_lower=$(printf '%s' "$IMG_SHA256" | tr 'A-F' 'a-f')
actual_lower=$(printf '%s' "$actual" | tr 'A-F' 'a-f')
if [ "$actual_lower" != "$expected_lower" ]; then
  echo "ERROR: sha256 mismatch."
  echo "  expected: $expected_lower"
  echo "  actual:   $actual_lower"
  exit 1
fi
echo "sha256 OK"

gzip -dc /tmp/omr.img.gz | dd of="$TARGET" bs=4M status=progress conv=fsync
