# 12 AdGuard Home

## Goal
LAN-wide DNS filtering without breaking LuCI, SSH, OMR, DHCP, or DNS-based bypass logic.

## Port contract

| Service | Bind | Port | URL |
|---|---:|---:|---|
| LuCI HTTP | LAN/all | 80 | `http://192.168.100.1` |
| LuCI HTTPS | LAN/all | 443 | `https://192.168.100.1` |
| SSH | LAN | 22 | `ssh root@192.168.100.1` |
| AdGuard Home UI | LAN | 3000 | `http://192.168.100.1:3000` |
| Client DNS | LAN | 53 | `192.168.100.1` |
| AdGuard DNS backend | localhost | 5354 | `127.0.0.1#5354` |
| OMR admin API | internal/admin | 65500 | internal/admin only |

## Architecture

Keep `dnsmasq` as DHCP/client DNS frontend on LAN port 53. AdGuard Home DNS on localhost port 5354. `dnsmasq` upstream → `127.0.0.1#5354`.

```text
LAN clients -> dnsmasq :53 -> AdGuard Home 127.0.0.1:5354 -> upstream DNS
```

Preserves DHCP, local hostnames, OMR ipsets, OMR bypass behavior.

## Actions

1. Back up `/etc/config/dhcp`, `/etc/config/firewall`, `/etc/adguardhome.yaml` if present.
2. Install `adguardhome` (already present in OMR).
3. Configure AdGuard Home web UI on `0.0.0.0:3000` or LAN-only.
4. Configure AdGuard Home DNS on `127.0.0.1:5354`.
5. Configure `dnsmasq` to keep `:53` and forward upstream to `127.0.0.1#5354`.
6. **Bootstrap filter lists**: run `scripts/configure-adguard-filters.sh` to inject 4 filter URLs (AdGuard DNS filter id=1, AdAway id=2, Tracking Protection id=11, DNS Popup Hosts id=15). Without filters, AdGuard blocks nothing.
7. Restart AdGuard Home and dnsmasq.

## Verification

- LuCI still reachable at `http://192.168.100.1`.
- AdGuard Home reachable at `http://192.168.100.1:3000`.
- `dig @192.168.100.1 doubleclick.net +short` → `0.0.0.0` or NXDOMAIN (blocked).
- `dig @192.168.100.1 example.com +short` → real IP (resolves).
- Internet works from router and LAN clients.
- OMR services remain enabled.

## Rollback

Restore backups; revert dnsmasq upstream to previous resolver or `127.0.0.1#5353`.
