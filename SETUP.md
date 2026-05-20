# Setup

Run prompts in numeric order. Stop at each checkpoint. Never proceed if verification fails.

1. 00-04: base router, NICs, LAN/DHCP, WAN discovery
2. 05: operation-aware SD-WAN load balancing via mwan3
3. 06: OMR advanced multipath settings when required
4. 07-09: SQM, policy routing, 4G failover
5. 10-11: monitoring packages and LuCI web UI verification
6. 12-13: hardening/verification

Default deployment does not require an external VPS.
