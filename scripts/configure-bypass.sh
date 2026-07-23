#!/bin/sh
set -eu
# Idempotent: delete any prior 'Gaming UDP' rule(s) before adding, so reruns
# don't stack duplicate omr-bypass rules.
while uci -q show omr-bypass | grep -q "name='Gaming UDP'"; do
	_sec=$(uci -q show omr-bypass | sed -n "s/^omr-bypass\.\(@rule\[[0-9]*\]\)\.name='Gaming UDP'$/\1/p" | head -n1)
	[ -n "$_sec" ] || break
	uci -q delete "omr-bypass.$_sec"
done
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
