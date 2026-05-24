#!/bin/sh
set -eu
uci -q batch <<'EOF'
add omr-bypass rule
set omr-bypass.@rule[-1].name='Gaming UDP'
set omr-bypass.@rule[-1].proto='udp'
set omr-bypass.@rule[-1].dest_port='3074 3478-3480 27015-27030'
set omr-bypass.@rule[-1].interface='wan1'
add omr-bypass rule
set omr-bypass.@rule[-1].name='Streaming domains'
set omr-bypass.@rule[-1].domains='netflix.com youtube.com googlevideo.com hulu.com disneyplus.com primevideo.com'
set omr-bypass.@rule[-1].interface='balanced'
commit omr-bypass
EOF
/etc/init.d/omr-bypass restart || true
