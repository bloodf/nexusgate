#!/bin/sh
set -eu
uci -q batch <<'EOF'
add omr-bypass rule
set omr-bypass.@rule[-1].name='Gaming UDP'
set omr-bypass.@rule[-1].proto='udp'
set omr-bypass.@rule[-1].dest_port='3074 3478-3480 27015-27030'
set omr-bypass.@rule[-1].interface='wan1'
commit omr-bypass
EOF
# Streaming intentionally NOT bypassed: it follows each device's WAN affinity (stable single WAN per device). The old 'balanced' bypass was ECMP residue.
/etc/init.d/omr-bypass restart || true
