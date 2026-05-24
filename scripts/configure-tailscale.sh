#!/bin/sh
# Install + enable Tailscale on the NexusGate router for remote admin only.
#
# Default mode: SSH/LuCI ingress to router via tailnet IP from anywhere.
# Tailscale does NOT participate in LAN routing, is NOT an exit node, does NOT
# expose LAN clients. Pure remote-admin path.
#
# Opt-in subnet routing (only if you actually need to reach LAN hosts from
# tailnet — increases blast radius and can confuse routing if misconfigured):
#   SUBNET=1 scripts/configure-tailscale.sh
#
# Usage:
#   TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
#   # or interactive (prints login URL once):
#   scripts/configure-tailscale.sh

set -eu

HOSTNAME=${HOSTNAME:-nexusgate}
SUBNET=${SUBNET:-0}

opkg update
opkg install tailscale

/etc/init.d/tailscale enable
/etc/init.d/tailscale start

UP_ARGS="--hostname=$HOSTNAME --accept-dns=false --ssh --reset"
if [ "$SUBNET" = "1" ]; then
	ROUTES=${ADVERTISE_ROUTES:-192.168.100.0/24}
	UP_ARGS="$UP_ARGS --advertise-routes=$ROUTES"
fi

if [ -n "${TS_AUTHKEY:-}" ]; then
	# shellcheck disable=SC2086
	tailscale up --authkey="$TS_AUTHKEY" $UP_ARGS
else
	echo "No TS_AUTHKEY set. Running interactive login — open the printed URL."
	# shellcheck disable=SC2086
	tailscale up $UP_ARGS
fi

echo
echo "== Tailscale state =="
tailscale status || true
echo
echo "Tailnet IP: $(tailscale ip -4 2>/dev/null || echo '(not yet assigned)')"
echo
if [ "$SUBNET" = "1" ]; then
	echo "Subnet routing requested. Approve route in admin console:"
	echo "  https://login.tailscale.com/admin/machines"
else
	echo "SSH-only mode. SSH/LuCI reachable on the tailnet IP from any approved peer."
	echo "No subnet routing, no exit node, no impact on LAN routing."
fi
