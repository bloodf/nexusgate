# Networking

NexusGate balances by operation/flow, not by machine.

## Default policy

- WAN1 weight 50
- WAN2 weight 50
- WAN3/4G backup metric 3
- Sticky disabled for default traffic

This lets one PC use both links when it opens multiple connections.

## Sticky exceptions

Sticky enabled only for:

- Gaming UDP
- VoIP/SIP/RTP
- Video calls if needed
- Banking/login-sensitive domains if user adds rule

## Expected behavior

| Workload | Result |
|---|---|
| One TCP flow | one WAN max |
| Multi-stream speedtest | WAN1+WAN2 aggregate |
| Steam/browser/package downloads | often WAN1+WAN2 aggregate |
| Gaming/VoIP | one WAN sticky |
| WAN failure | active flows may reconnect; new flows use surviving WAN |
