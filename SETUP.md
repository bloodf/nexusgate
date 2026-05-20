# Setup

Run prompts in numeric order. Stop at each checkpoint. Never proceed if verification fails.

1. 00-04: base router and WAN discovery
2. 05: default SD-WAN load balancing via mwan3
3. 06: optional VPS bonding only if needed
4. 07-09: SQM, policy routing, 4G failover
5. 10-11: monitoring/dashboard
6. 12-13: hardening/verification

Default deployment does **not** require a VPS.
