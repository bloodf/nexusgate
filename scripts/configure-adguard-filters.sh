#!/bin/sh
# Bootstrap AdGuard Home filter lists. OMR has no python3; YAML edit via awk.
# Idempotent: strips existing filters: block then appends fresh one.
set -eu

CFG=${CFG:-/etc/adguardhome.yaml}
[ -f "$CFG" ] || { echo "AdGuard config not found: $CFG"; exit 1; }

TMP=$(mktemp)
BAK="${CFG}.bak.$(date +%s)"
cp "$CFG" "$BAK"

# awk: drop existing filters: block (^filters: up to next top-level key starting at col 0 non-space, non-#).
awk '
  BEGIN { skip=0 }
  /^filters:/ { skip=1; next }
  skip==1 {
    if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*:/) { skip=0; print; next }
    next
  }
  { print }
' "$CFG" > "$TMP"

cat >> "$TMP" <<'EOF'
filters:
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt
    name: AdGuard DNS filter
    id: 1
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_2.txt
    name: AdAway Default Blocklist
    id: 2
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_11.txt
    name: AdGuard Tracking Protection filter
    id: 11
  - enabled: true
    url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_15.txt
    name: AdGuard DNS Popup Hosts filter
    id: 15
EOF

mv "$TMP" "$CFG"
echo "Backup: $BAK"

/etc/init.d/adguardhome restart
sleep 3

echo "Verify blocking:"
dig @192.168.100.1 doubleclick.net +short || true
echo "Verify resolution:"
dig @192.168.100.1 example.com +short || true
