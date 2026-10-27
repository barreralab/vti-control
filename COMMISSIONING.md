# Commissioning record

2026-10-26: Mercury iTC firmware 2.6.04.000 and IPS 2.5.09.000.
Repeated independent-client tests rejected connection B while A remained healthy.
Read-only inventory found five thermometers, three heater outputs, one pressure, and a valve.
Probe DB8.T1 returned a numeric value while an Open Circuit alarm was present; logger flags it.
The logger does not change controller configuration. No physical SET command was used in development.

This is an initial working build, not a completed multi-day reliability qualification.
See README for outstanding commissioning checks.

Additional observation: later iTC *IDN? responses returned OFF in the serial-number field,
while the earlier response gave 233850309; firmware remained 2.6.04.000.
No SET commands were sent to the hardware. Identity responses are retained verbatim.
This firmware/identity anomaly has not been diagnosed.

The packaged GUI and native Windows service were launched successfully.
Four simultaneous live broker clients and actual QCoDeS reads succeeded.
Local archive integrity passed after switching backends.

Release verification: 26 automated tests passed; native service is delayed-auto start
with 5/15/60-second failure recovery. GUI executable remains running independently.
Exclusive Windows port ownership and archive integrity verified after installing final backend.
Control forwarding has only been exercised against simulated hardware.
