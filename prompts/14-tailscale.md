# 14 Tailscale

## Goal

Remote admin to NexusGate from anywhere via tailnet. Also reach LAN clients (192.168.100.0/24) over Tailscale subnet routing.

## Inputs

- Router IP: `192.168.100.1`
- Tailscale account + auth key (preauth, reusable, tagged `tag:router`)
- LAN CIDR to advertise: `192.168.100.0/24`

## Actions

1. Get an auth key: https://login.tailscale.com/admin/settings/keys (reusable, ephemeral=off, preauth=on).
2. Run installer:

   ```sh
   TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
   ```

   Or interactive:

   ```sh
   scripts/configure-tailscale.sh
   # open the printed login URL once
   ```
3. In Tailscale admin console -> Machines -> nexusgate -> Edit route settings -> approve `192.168.100.0/24`.
4. On remote device: enable "Use Tailscale subnets" (CLI: `tailscale up --accept-routes`).

## Verification

- `tailscale status` on router shows node online.
- `tailscale ip -4` returns a 100.x address.
- From remote tailnet device:
  - `ssh root@<tailnet-ip>` works.
  - `curl http://<tailnet-ip>` returns LuCI.
  - `ping 192.168.100.50` (or any LAN client IP) works after subnet route approved.

## Rollback

```sh
tailscale down
/etc/init.d/tailscale disable
opkg remove tailscale
```

## Notes

- `--accept-dns=false`: keep AdGuard as LAN DNS. Tailscale MagicDNS off.
- `--ssh`: enables Tailscale SSH (auth via tailnet identity, no key mgmt).
- Tailscale runs alongside ECMP load balancing — egress from router uses normal default route, no interference with table 991337.
