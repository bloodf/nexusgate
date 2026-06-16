# Setup

Run prompts in numeric order. Stop at each checkpoint. Never proceed if verification fails.

1. **00-04**: base router, NICs, LAN bridge (eth0+eth3), WAN discovery. WAN1 PPPoE via
   `scripts/configure-wan-pppoe.sh` (set `<pppoe-username>`/`<pppoe-password>` for your ISP;
   see [Reference deployment in README](README.md#reference-deployment) for example values).
   GPON ONT bridge/router-mode auto-detection included.
2. **05 (wan-affinity)**: per-device WAN affinity via `scripts/configure-wan-affinity.sh`.
   Sets `CLARO_MACS` / `VIVO_MACS` lock lists, writes
   `/etc/nftables.d/20-wan-affinity.nft`, installs post-tracking hook `098-wan-affinity`,
   and adds ip rules (pri 40/41/45). mwan3 not installable on OMR (nftables-only, missing
   `iptables-mod-conntrack-extra`). No ECMP / external VPS required.
3. **06 (sqm-cake)**: SQM/CAKE shaping per WAN via `scripts/configure-sqm.sh`.
4. **07 (bypass-rules)**: gaming UDP bypass (WAN1 pin) via OMR bypass rules.
5. **08 (monitoring)**: monitoring packages (collectd, vnstat).
6. **09 (luci-web-ui)**: LuCI addons via `scripts/install-luci-addons.sh` + web UI
   verification.
7. **10 (adguard-home)**: AdGuard Home DNS filtering + filter list bootstrap via
   `scripts/configure-adguard-filters.sh`. ISP resolvers via
   `scripts/configure-isp-dns.sh`.
8. **11 (hardening)**: system hardening.
9. **12 (verification)**: full checklist - WAN health, affinity egress IPs, failover,
   DNS, SQM, AdGuard blocking.
10. **13 (tailscale)**: (optional) remote admin via `scripts/configure-tailscale.sh`.

Default deployment does not require an external VPS.
