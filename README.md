# VTI Control

Public repository: https://github.com/barreralab/vti-control

Standalone Windows logger for the Oxford Teslatron VTI and Mercury iTC/IPS.
The desktop application observes the system. Acquisition continues when its window closes.
Existing measurement scripts can query and control instruments through local forwarding ports.

## User manual

See [USER_MANUAL.md](USER_MANUAL.md), or open [USER_MANUAL.html](USER_MANUAL.html).
The desktop **User manual** button opens the local HTML copy.

## Locations

- Source: this Git repository in the 2DLaB SharePoint folder.
- Runtime and executables: `D:\VTI-control\app`.
- Configuration: `D:\VTI-control\config\vti.json`.
- Monthly primary archives: `D:\VTI-control\data\YYYY\vti-YYYY-MM.sqlite` (UTC months).
- Daily refreshed SQLite backup: `D:\VTI-control\backups` (same disk, not disaster recovery).
- Rotating diagnostic logs: `D:\VTI-control\logs\service.log`.
- Independent driver clone: `D:\VTI-control\BarreraLabDrivers`, branch `vti/mercury-communications`.

The old OneDrive driver checkout and acquisition notebooks are not changed.
The two original Teslatron scaffold files are retained for reference; the application does not import them.

## Running

Open `D:\VTI-control\app\VTI-Control\VTI-Control.exe` or the local `Open VTI Control.cmd` launcher.
The Windows service is named `VTIControl`. Closing the GUI leaves it running.
Use Windows Services to stop/start acquisition. Stop this service before attempting direct instrument access.
For foreground diagnostics, stop the Windows service and run `app\VTI-Logger\VTI-Logger.exe`.
Do not run both backends: the API port enforces a single instance.

In the GUI, drag to pan and wheel to zoom. Manual navigation disables Follow latest.
Reset view restores automatic vertical scaling; Log temperature switches the temperature axis.
Check channels to control visibility without affecting logging. Hover over a plot or time axis
for linked dotted guides and nearest recorded values, including each sample timestamp.
The dark theme, 1.8-pixel data curves, and spaced logarithmic ticks improve readability.
The GUI restores up to 24 hours of saved context, then displays new one-second readings.
Saved context is interval data; it has lower time resolution than the live trace.

## Measurement scripts and QCoDeS

These controllers rejected second simultaneous physical TCP connections in repeated read-only tests.
While the service runs, configure measurement scripts to use:

```yaml
MercuryiTC:
  type: barreralabdrivers.drivers.MercuryiTC
  address: TCPIP::127.0.0.1::17020::SOCKET
  timeout: 5
MercuryiPS:
  type: barreralabdrivers.drivers.OxfordMercuryIPS.MercuryiPS
  address: TCPIP::127.0.0.1::17021::SOCKET
  timeout: 5
```

Use the improved driver branch in an isolated measurement environment before adopting it in active experiments.
The new backend does not require QCoDeS or PyVISA. It uses one socket per controller.
The broker binds only to localhost and forwards READ/SET/*IDN? requests, one transaction at a time.
A localhost client can send control commands; this is intended for existing measurement scripts.
Concurrent scripts are serialized at transaction level, not at whole experimental-sequence level.
Do not issue conflicting control sequences from multiple scripts.
A SET timeout is ambiguous: the command may have been applied. Do not blindly retry it.

The driver clone contains strict numeric parsing, response/acknowledgement checks, a transaction lock,
configurable timeouts, numeric pressure-setpoint/heater properties, and no automatic iTC writes on connection.
The previous initialization writes are available only through explicit `configure_manual_needle_valve()`.
After a transport timeout, recreate a driver instance to avoid consuming a delayed reply.
No driver update is installed into existing measurement environments automatically.

## Data and quality

`save_interval` defaults to 10 seconds; restart the backend after changing configuration.
Polling defaults to one second independently per instrument. All thermometers, pressures,
heater powers and associated loop enabled states, valve position, and configured magnet-group signals are discovered.
PT1_DB8/PT2_DB7 are likely pulse-tube stages 1/2; physical assignments remain to be confirmed.
Only GRPZ is configured as a relevant magnet group; the full hardware catalog is saved.
PID values and setpoints are not logged.

Each numeric interval records last valid, min, max, mean, valid count, and attempted count.
State changes, alarms, connectivity, startup, and external SET acknowledgements are events.
A missing/invalid/alarmed sensor is not silently replaced with zero or its previous reading.
Disconnected gaps have explicit events. Counts describe attempted readings, not guaranteed one-Hz coverage.
SQLite uses WAL, FULL synchronization, one writer, and monthly UTC archives.
Retries and queues are bounded; storage errors and discarded records are exposed in the GUI/API.
No automatic deletion of primary archives is performed. Monitor available disk capacity.

The field display distinguishes supply FLD, persistent PFLD, switch-heater status, and action.
The inferred operating mode is provisional until checked against actual driven/persistent transitions.
PFLD is a controller register, not an independent field measurement. Do not use this logger as a safety interlock.

## Mercury driver change report

See [MERCURY_DRIVER_REPORT.md](MERCURY_DRIVER_REPORT.md) for the exact driver changes,
branch ancestry, compatibility notes, validation, and remaining work.

## Development

Use a local Python environment; do not put environments or live databases in SharePoint.

```powershell
D:\VTI-control\venv\Scripts\python.exe -m pip install -e .
D:\VTI-control\venv\Scripts\python.exe -m pytest tests
D:\VTI-control\venv\Scripts\python.exe build_windows.py
```

`requirements-windows.lock.txt` records the versions used for this build.
GUI dependencies are optional; service operation uses Python's standard library.
Packaging the native Windows service also requires pywin32.
Tests simulate malformed/unit-mismatched responses, late replies, concurrent clients, reconnection,
SQLite failures/recovery, summaries and backups, and real QCoDeS instances through the broker.
The hardware was commissioned with read commands only. Control forwarding is tested against a simulator.
The project is published at https://github.com/barreralab/vti-control.
The Mercury driver changes are proposed in [BarreraLabDrivers draft PR #4](https://github.com/barreralab/BarreraLabDrivers/pull/4).

## Commissioning still required

- Multi-day soak under representative measurement load and controlled power/reboot testing.
- Verification of persistent/driven transition interpretation against the Mercury display.
- Confirmation of pulse-tube stage labels and resolution of the reported probe open-circuit alarm.
- Longer-run CPU/memory/disk-growth checks and an off-disk backup destination.
- Review and adoption of the driver branch in the group repository.
