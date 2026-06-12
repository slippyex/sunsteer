# Disclaimer

**Sunsteer switches real heating equipment. Read this before you wire anything.**

## What SG-Ready switching means

Sunsteer drives a relay connected to your heat pump's **SG-Ready input**. What that
input does is defined by your **heat pump manufacturer**, not by Sunsteer: on most
units the contact Sunsteer uses is a *recommendation* to raise setpoints and consume
PV surplus, and the heat pump's own controller still protects the machine. Verify the
SG-Ready semantics of **your** model with its documentation or your installer before
connecting anything.

## Electrical work

The SG-Ready input expects a potential-free contact. Wiring a relay into a heat pump
is electrical work on a heating system — have it done (or at least checked) by a
**licensed electrician**. A miswired contact can damage the heat pump, the relay, or
worse.

## Built-in safety behaviour — and its limits

Sunsteer is designed to fail towards "heat pump runs normally, surplus mode off":

- Stale or missing meter data → the controller switches the relay **OFF** (it never
  acts blind).
- A dead controller → the relay's hardware **auto-off watchdog** switches OFF on its
  own (the controller must actively re-arm it every cycle).
- Minimum runtimes and off-times limit compressor cycling.
- The web UI requires authentication and serves nothing without it.

These layers reduce risk; they do not eliminate it. Network outages, misconfiguration,
hardware faults or bugs can still produce unwanted switching behaviour. **Monitor your
system, especially in the first weeks.**

## No warranty

Sunsteer is published under the [MIT license](LICENSE): the software is provided
**"as is", without warranty of any kind**. You run it at your own risk and you are
responsible for the safety and the consequences of its operation in your installation.

## Trademarks

SMA, Sunny Home Manager, Shelly, Viessmann, ViCare and related names are trademarks of
their respective owners. Sunsteer is a private open-source project and is **not
affiliated with, endorsed by, or supported by** any of these companies.
