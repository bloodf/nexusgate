# Traffic Classification

Goal: maximize aggregate throughput per operation while preserving real-time traffic stability.

## Non-sticky balanced

Default/general/download/streaming traffic uses `operation_balance` with `sticky=0`. A single device can open many flows and have them spread across WAN1/WAN2.

## Sticky low-latency

Gaming/VoIP uses sticky policy:

- UDP 3074
- UDP 3478-3480
- UDP 3659
- UDP 27000-27100
- SIP 5060-5061
- RTP 10000-20000

Reason: changing WAN/public IP mid-session causes packet loss, jitter, NAT breakage, or disconnects.

## Optional sticky domains

Add sticky rules for banking, SSO, payment, work VPN, video calls if session breaks.
