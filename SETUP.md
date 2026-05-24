# Setup

Run prompts in numeric order. Stop at each checkpoint. Never proceed if verification fails.

1. 00-04: base router, NICs, LAN bridge (eth0+eth3), WAN discovery. Fiber WAN PPPoE via `scripts/configure-wan-pppoe.sh` (Vivo Fibra creds `cliente@cliente`/`cliente`, GPON ONT bridge/router-mode detection).
2. 05: ECMP load balancing via `scripts/configure-load-balancing.sh`. mwan3 unsupported on OMR (nftables-only, missing `iptables-mod-conntrack-extra`). Kernel ECMP in table 991337 + post-tracking hook instead.
3. 06: OMR advanced multipath settings when required.
4. 07-08: SQM, policy routing.
5. 09: 4G failover out of scope v1.
6. 10-11: monitoring packages and LuCI web UI verification.
7. 12: AdGuard Home DNS filtering + filter list bootstrap via `scripts/configure-adguard-filters.sh`.
8. 12-hardening and 13: hardening/verification.

Default deployment does not require an external VPS.
