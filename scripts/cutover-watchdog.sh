#!/bin/sh
# NexusGate cutover watchdog -- DORMANT until launched.
# Guards the Vivo (eth1/pppoe-wan1) cutover. If the box goes FULLY dark
# (no egress on ANY path) it restores the Claro/eth2 default so SSH/Tailscale
# recover. Acts only on total blackout; never touches routes while anything works.
# Self-exits after WINDOW seconds. Launch:  setsid sh /root/cutover-watchdog.sh &
WINDOW=1800          # total guard window (30 min)
CHECK=15             # seconds between probes
DARK_MAX=4           # consecutive dark probes (=60s) before recovery acts
LOG=/tmp/cutover-watchdog.log
elapsed=0; dark=0
echo "$(date) watchdog armed window=${WINDOW}s" >> "$LOG"
while [ "$elapsed" -lt "$WINDOW" ]; do
    if ping -W2 -c1 1.1.1.1 >/dev/null 2>&1 || ping -W2 -c1 8.8.8.8 >/dev/null 2>&1; then
        dark=0
    else
        dark=$((dark+1))
        echo "$(date) dark probe $dark/$DARK_MAX" >> "$LOG"
        if [ "$dark" -ge "$DARK_MAX" ]; then
            CG=$(ip route show table 10 2>/dev/null | awk '/^default/{print $3;exit}')
            CD=$(ip route show table 10 2>/dev/null | awk '/^default/{print $5;exit}')
            if [ -n "$CG" ] && [ -n "$CD" ]; then
                echo "$(date) RECOVER -> default via $CG dev $CD" >> "$LOG"
                ip route replace default via "$CG" dev "$CD" 2>>"$LOG"
            fi
            /etc/init.d/omr-tracker restart >>"$LOG" 2>&1 || true
            dark=0
        fi
    fi
    sleep "$CHECK"; elapsed=$((elapsed+CHECK))
done
echo "$(date) watchdog window ended, exit" >> "$LOG"
