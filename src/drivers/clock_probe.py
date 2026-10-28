"""AidLux: reply to clock pings after SSH setup, so setup latency is excluded."""
import sys,time
print('CLOCK_READY',flush=True)
for line in sys.stdin:
    if line.strip()=='now':print(time.time(),flush=True)
