#!/bin/sh
# Install + enable Tailscale on the NexusGate router for remote admin.
#
# Usage:
#   TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
#   # or, interactive (prints login URL once):
#   scripts/configure-tailscale.sh
#
# Effect:
#   - Router joins tailnet as "nexusgate".
#   - Advertises 192.168.100.0/24 so any tailnet device can reach LAN clients.
#   - SSH (port 22) and LuCI (80/443) reachable via the tailnet IP from anywhere.
#   - Survives reboot (init script enabled).

set -eu

HOSTNAME=${HOSTNAME:-nexusgate}
ADVERTISE_ROUTES=${ADVERTISE_ROUTES:-192.168.100.0/24}

opkg update
opkg install tailscale

/etc/init.d/tailscale enable
/etc/init.d/tailscale start

# Allow IPv4 forwarding + masquerade between tailnet and LAN. fw4 (nftables)
# default-accepts tailscale0 in the forward chain when interface is unmanaged,
# but explicitly adding it to the LAN zone keeps LuCI happy.
if ! uci -q get firewall.@zone[0].network | grep -q tailscale; then
	uci -q add_list firewall.@zone[0].network='tailscale'
fi
uci -q set network.tailscale=interface
uci -q set network.tailscale.proto='none'
uci -q set network.tailscale.device='tailscale0'
uci commit network
uci commit firewall
/etc/init.d/network reload
/etc/init.d/firewall reload

# Bring node up. Idempotent — re-running with same authkey is a no-op.
if [ -n "${TS_AUTHKEY:-}" ]; then
	tailscale up \
		--authkey="$TS_AUTHKEY" \
		--hostname="$HOSTNAME" \
		--advertise-routes="$ADVERTISE_ROUTES" \
		--accept-dns=false \
		--ssh
else
	echo "No TS_AUTHKEY set. Running interactive login — open the printed URL."
	tailscale up \
		--hostname="$HOSTNAME" \
		--advertise-routes="$ADVERTISE_ROUTES" \
		--accept-dns=false \
		--ssh
fi

echo
echo "== Tailscale state =="
tailscale status || true
echo
echo "Tailnet IP: $(tailscale ip -4 2>/dev/null || echo '(not yet assigned)')"
echo
echo "Next: in the Tailscale admin console, approve the advertised subnet"
echo "route 192.168.100.0/24 so other tailnet devices can reach LAN clients."
