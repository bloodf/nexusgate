# MPTCP Bonding

MPTCP kernel support is enabled on OMR but useless against non-MPTCP peers (i.e. virtually all public servers). It only helps when **both** endpoints speak MPTCP — typically via an OMR VPS aggregator.

For the common case (LAN clients hitting normal HTTPS/UDP services), kernel ECMP across wan1/wan2 (table 991337, L4 hash) handles fan-out. See `docs/NETWORKING.md`.

## Optional: VPS bonding

ShadowSocks handles TCP MPTCP subflows. Glorytun handles UDP/ICMP multipath. VPS aggregates egress to a single public IP.

Only deploy if single-flow throughput above one WAN is required (e.g. one massive single-connection download/upload).

## Verification

Run `prompts/13-verification.md` checklist after changes.
