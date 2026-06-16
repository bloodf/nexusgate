# 13 Tailscale

## Goal

Remote SSH/LuCI to NexusGate from anywhere via tailnet. Pure admin ingress. Does NOT participate in LAN routing.

## Inputs

- Router IP: `10.25.0.1`
- Tailscale account + auth key (preauth, reusable, tagged `tag:router`)

## Actions

1. Get auth key: https://login.tailscale.com/admin/settings/keys (reusable, ephemeral=off, preauth=on).
2. Run installer:

   ```sh
   TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
   ```

   Or interactive:

   ```sh
   scripts/configure-tailscale.sh
   # open printed login URL once
   ```

   Default is SSH-only — no subnet routing, no exit node.

## Verification

- `tailscale status` on router shows node online.
- `tailscale ip -4` returns 100.x address.
- From remote tailnet device:
  - `ssh root@<tailnet-ip>` works.
  - `curl http://<tailnet-ip>` returns LuCI.

## Rollback

```sh
tailscale down
/etc/init.d/tailscale disable
opkg remove tailscale
```

## Notes

- `--accept-dns=false`: keep AdGuard as LAN DNS. Tailscale MagicDNS off.
- `--ssh`: tailnet identity auth, no SSH key mgmt.
- No subnet route by default. Tailscale does NOT touch LAN routing tables, NOT an exit node, NOT advertising LAN.
- WAN affinity routing unaffected — egress from router uses main-table default, independent of tailscale0.

## Opt-in: subnet routing (only if you really need it)

Lets tailnet peers reach LAN clients (`10.25.x.y`) over the tunnel. Off by default because misconfiguration can confuse routing.

```sh
SUBNET=1 TS_AUTHKEY=tskey-auth-xxxx scripts/configure-tailscale.sh
```

Then in admin console: Machines -> `nexusgate` -> Edit route settings -> approve `10.25.0.0/16`. On remote device: `tailscale up --accept-routes`.

To revert SSH-only later:

```sh
tailscale up --hostname=nexusgate --accept-dns=false --ssh --reset
```

Also revoke the approved route in the admin console.
