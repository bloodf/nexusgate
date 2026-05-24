# Tailscale

Remote ingress to NexusGate from anywhere. Runs alongside ECMP load balancing without interference.

## Install + first login

```sh
ssh root@192.168.100.1
opkg update
opkg install tailscale
/etc/init.d/tailscale enable
/etc/init.d/tailscale start

tailscale up \
  --hostname=nexusgate \
  --advertise-routes=192.168.100.0/24 \
  --accept-dns=false \
  --ssh
```

Open printed `https://login.tailscale.com/a/...` URL, log in, approve node.

In admin console: Machines -> `nexusgate` -> Edit route settings -> approve `192.168.100.0/24`.

Non-interactive (preauth key from https://login.tailscale.com/admin/settings/keys):

```sh
tailscale up --authkey=tskey-auth-xxxx --hostname=nexusgate \
  --advertise-routes=192.168.100.0/24 --accept-dns=false --ssh
```

Or via repo installer:

```sh
TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
```

## How traffic flows now

### LAN ingress (admin from home Wi-Fi)

Home router AP/bridge mode -> client on `br-lan` (192.168.100.0/24) -> directly hits `192.168.100.1`. No Tailscale needed locally.

### WAN egress (browsing, downloads)

LAN client -> br-lan -> `ip rule iif br-lan lookup 991337` -> ECMP nexthop (L4 hash) -> pppoe-wan1 or eth2/wan2 -> Internet. Unchanged by Tailscale.

### Tailnet ingress (admin from anywhere)

Remote device on tailnet -> WireGuard UDP to nexusgate's tailnet IP (100.x.y.z) -> `tailscale0` -> local services (SSH/LuCI/AdGuard UI). Auth via tailnet identity (no SSH keys needed when `--ssh` enabled).

### Tailnet -> LAN clients

Remote device with `tailscale up --accept-routes` -> WireGuard to nexusgate -> nexusgate forwards into br-lan -> reaches `192.168.100.50` etc. as if on LAN.

### Tailnet egress (router as exit node — optional, not enabled by default)

Add `--advertise-exit-node` to make NexusGate an exit node. Peer enables `--exit-node=nexusgate` to route all its traffic via NexusGate's WANs (and ECMP).

## Port matrix after Tailscale

| Listener | Bind | Port | Reachable from |
|---|---|---:|---|
| LuCI HTTP | all | 80 | br-lan + tailnet |
| LuCI HTTPS | all | 443 | br-lan + tailnet |
| SSH (dropbear) | all | 22 | br-lan + tailnet |
| Tailscale SSH | tailscale0 | 22 | tailnet only (auth via identity) |
| AdGuard UI | all | 3000 | br-lan + tailnet |
| dnsmasq | LAN | 53 | br-lan only |
| AdGuard DNS backend | localhost | 5354 | router only |
| tailscaled | UDP 41641 | dynamic | Internet (peer discovery) |

## Routing tables involved

| Table | Owner | Purpose |
|---:|---|---|
| main | kernel | Default for router-originated traffic, tailnet egress |
| 6 | OMR | wan1 (pppoe-wan1) default |
| 10 | OMR | wan2 (eth2) default |
| 991337 | OMR + ECMP hook | Balanced multipath for `iif br-lan` |
| 52 | tailscaled | Tailscale subnet routes / exit node policy |

`tailscale0` and table 52 are isolated from ECMP — tailnet traffic does not get hashed across WANs (would break WireGuard session). Router uses main-table default for its own tailnet keepalives.

## Verification

```sh
# On router:
tailscale status
tailscale ip -4

# From remote tailnet device:
ssh root@<100.x.y.z>          # Tailscale SSH (identity auth)
curl http://<100.x.y.z>       # LuCI
ping 192.168.100.50           # LAN client via advertised subnet route
```

## Rollback

```sh
tailscale down
/etc/init.d/tailscale disable
opkg remove tailscale
```

## Notes

- UDP GRO warning on first `tailscale up` (`See https://tailscale.com/s/ethtool-config-udp-gro`) — cosmetic perf tuning, safe to ignore for v1.
- Tailscale subnet route conflicts with LAN: only one node should advertise `192.168.100.0/24`. Do not enable subnet routing on multiple gateways.
- Tailscale keys: rotate via admin console. Router stays online via `tailscaled` state under `/var/lib/tailscale/`.
