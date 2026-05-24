#!/bin/sh
# NexusGate per-connection load balancing installer (OMR-native, no mwan3).
#
# Background:
#   OpenMPTCProuter v0.63 ships nftables and refuses mwan3
#   (iptables-mod-conntrack-extra missing). We use kernel ECMP via OMR's
#   existing balanced routing table 991337 plus a post-tracking maintainer.
#
# Effect:
#   - Both WANs active simultaneously.
#   - Per-flow distribution: each new connection picks a WAN via L4 hash
#     (src IP, dst IP, src port, dst port, proto). One LAN client opening
#     many flows to one server spreads them across both WANs.
#   - Single TCP/UDP flow stays on one WAN (kernel invariant).
#   - Survives reboots and WAN flaps (omr-tracker re-runs the maintainer).

set -eu

SCRIPT_DIR=$(dirname "$0")

# 1. Make sure both WANs are tagged as multipath so OMR keeps their per-WAN
#    routing tables (6 = wan1, 10 = wan2) populated.
uci -q set network.wan1.multipath='on'
uci -q set network.wan2.multipath='on'
uci -q set network.wan1.defaultroute='0'
uci -q set network.wan2.defaultroute='0'
uci commit network

# 2. OMR balancing master switch.
uci -q set openmptcprouter.settings.master='balancing'
uci commit openmptcprouter

/etc/init.d/network reload

# 3. Install the ECMP maintainer into OMR's post-tracking hook directory.
install -m 0755 "$SCRIPT_DIR/ecmp-balance.sh" /usr/share/omr/post-tracking.d/099-ecmp-balance

# 4. Persist the L4 hash sysctl so balancing survives reboot even before the
#    first omr-tracker tick.
cat > /etc/sysctl.d/99-ecmp.conf <<'EOF'
net.ipv4.fib_multipath_hash_policy=1
net.ipv4.fib_multipath_use_neigh=1
EOF
sysctl -p /etc/sysctl.d/99-ecmp.conf

# 5. Boot-time guarantee: run the maintainer from rc.local in case
#    omr-tracker is slow to start.
if ! grep -q 099-ecmp-balance /etc/rc.local 2>/dev/null; then
	sed -i '/^exit 0/i /usr/share/omr/post-tracking.d/099-ecmp-balance >/dev/null 2>&1 || true' /etc/rc.local
fi

# 6. First-run trigger so user does not have to wait for the tracker tick.
/usr/share/omr/post-tracking.d/099-ecmp-balance

echo
echo "== ECMP state =="
ip route show table 991337
echo
echo "== Policy rules =="
ip rule show | head -20
echo
echo "== Hash policy =="
sysctl net.ipv4.fib_multipath_hash_policy
