# 05 WAN Affinity

## Goal
Pin each LAN device to a single WAN (stable per-device public IP) and enable automatic failover with shift-back when the failed WAN recovers.

Default devices egress via WAN1 (primary). Devices whose MAC is in the Claro lock list egress via WAN2 (secondary). Each device always has exactly one stable public IP - no alternation, no load-balancing.

## Inputs
- Router IP: `192.168.100.1`
- WAN roles: eth1=wan1 (primary), eth2=wan2 (secondary); eth0+eth3 bridged to br-lan
- Optional: `CLARO_MACS` and `VIVO_MACS` environment variables (space-separated MAC addresses) to pre-seed the lock lists on first install. If not set, defaults are used and the lock lists can be managed via the web UI after install.

## Actions

1. Back up `/etc/config/network`, `/etc/config/firewall`, and `/etc/nftables.d/` if present.
2. Set lock-list seed variables (optional):

   ```sh
   export CLARO_MACS="aa:bb:cc:dd:ee:ff 11:22:33:44:55:66"
   export VIVO_MACS=""
   ```

   Skip this step to accept the defaults. The lists become authoritative after first install; subsequent changes go through the web UI.

3. Run the affinity installer:

   ```sh
   sh scripts/configure-wan-affinity.sh
   ```

   The script:
   - Writes nft MAC-mark rules (marks matching Claro MACs for table 101, all others default to table 100).
   - Installs ip rules at pri-40 (fwmark -> table 100 / WAN1), pri-41 (fwmark -> table 101 / WAN2), pri-45 (iif br-lan -> table 100 default).
   - Installs `/usr/share/omr/post-tracking.d/098-wan-affinity` for failover and shift-back on each tracker tick (reads gateways from tables 6 and 10).
   - Sets `multipath=off` on both wan1 and wan2.
   - Ensures OMR master is not set to `balancing`.
   - Deploys the CGI web UI to `/www/cgi-bin/wan-affinity`.

4. Reload firewall and network:

   ```sh
   /etc/init.d/firewall restart
   /etc/init.d/network restart
   ```

5. Open the web UI to verify lock lists and current WAN assignments:
   `http://192.168.100.1/cgi-bin/wan-affinity`

## Checkpoint

- From a default LAN device: `curl -s https://api.ipify.org` repeated 5 times returns the SAME WAN1 public IP every time.
- From a Claro-locked device: repeated `curl -s https://api.ipify.org` returns the SAME WAN2 public IP every time.
- Unplug WAN1: default devices shift to WAN2 IP (one stable IP, not the same as before). Re-plug WAN1: after the next tracker tick, default devices shift back to the WAN1 IP.
- Web UI accessible at `http://192.168.100.1/cgi-bin/wan-affinity`.

## Rollback
Restore `/etc/config/*` backups and remove `/usr/share/omr/post-tracking.d/098-wan-affinity`; reboot.
