# VTI Control user manual

Continuous logging and live inspection of the Oxford Teslatron VTI.

## 1. What runs on this PC

VTI Control has two independent parts:

- **VTIControl Windows service:** maintains the two physical Mercury connections, polls the instruments, writes local archives, and serves measurement scripts. It runs in the background, including when the desktop GUI is closed or the user logs out.
- **VTI Control desktop GUI:** displays live and recent data. It connects only to the local service. Opening another display does not create another physical instrument connection.

The service starts automatically after Windows boots, using delayed automatic startup. Allow time for the service and instrument network to become available. Neither program needs VS Code, a notebook kernel, or a separately activated Python environment when using the packaged executables.

The GUI is a monitor. It has no cryostat control buttons. Existing measurement scripts can still send commands through the server.

## 2. Everyday startup

1. Ensure the PC and Mercury controllers are on and connected to the instrument network.
2. Open **Services** from the Windows Start menu. Find **VTI Control acquisition service**. Its status should be **Running**.
3. Double-click `D:\VTI-control\Open VTI Control.cmd`, or run `D:\VTI-control\app\VTI-Control\VTI-Control.exe`.
4. Check the connection strip at the top: both IPS and ITC should be connected, and Storage should be OK.
5. Check the Attention panel. An instrument connection can be healthy while a particular sensor has an alarm.

Closing the GUI leaves acquisition running. Reopen it at any time; it restores saved recent context and then adds live readings. Opening the GUI does not start a stopped service automatically.

### Starting or restarting the background service

Open **PowerShell as Administrator** for commands that change service state:

```powershell
Get-Service -Name VTIControl
Start-Service -Name VTIControl
Restart-Service -Name VTIControl
Stop-Service -Name VTIControl
```

Use only the command needed. Restarting briefly interrupts logging and script access. Do not restart during an active control sequence or measurement without coordinating with that experiment.

You can also use Start, Stop, and Restart in the Windows Services application. The installed service is configured to restart after failures, with delays of 5, 15, and 60 seconds.

### If the service is not installed

On this PC it is already installed. For a future reinstallation, use an Administrator PowerShell:

```powershell
& 'D:\VTI-control\app\VTI-Service\VTI-Service.exe' --startup auto install
sc.exe config VTIControl start= delayed-auto
sc.exe failure VTIControl reset= 86400 actions= restart/5000/restart/15000/restart/60000
sc.exe failureflag VTIControl 1
Start-Service -Name VTIControl
```

The packaged files must remain in their installed directories. The service configuration points to the EXE on D:. Moving the source repository does not move or reconfigure the installed service.

## 3. Reading the live display

The interface always uses a dark theme. Thermometers, pressure, and magnetic-field registers have separate plots with linked time axes. The data curves are slightly thicker for visibility, while grid lines and cursor guides remain subtle.

- **Plot channels tab:** check or uncheck a channel to show or hide its curve. Click a group checkbox to show or hide that entire plot group. The channel text and curve share a color. Selections are remembered between GUI launches.
- **System status tab:** see all acquired channels, including heater outputs, operating states, valve position, alarms, and data quality. Hiding a curve does not remove a channel from this tab.
- **Attention panel:** reports instrument alarms and acquisition/storage errors. Do not interpret a numeric value alone as proof that a sensor is healthy.
- **Magnet panel:** distinguishes the controller's persistent register from its power-supply field and reports the switch heater and current action.

**Visibility is display-only. All configured channels continue to be polled and logged.** No plot checkbox changes an instrument setting.

PT1 and PT2 are likely the pulse-tube first- and second-stage thermometers; their physical assignments still need confirmation. The probe currently has a reported open-circuit alarm. Its numeric reading is shown with a warning and excluded from valid plotted/summarized readings.

## 4. Zooming, panning, and scaling

- Drag within a plot to pan.
- Scroll the mouse wheel over a plot to zoom.
- Manual navigation pauses **Follow latest** so new points do not drag the view away from the region you are inspecting.
- Enable **Follow latest** to return to the moving live time window. Choose 5 minutes, 30 minutes, 2 hours, or 24 hours from the time selector.
- Use **Reset view** to restore vertical autoscaling and resume following the latest data.
- Toggle **Log temperature** to switch the thermometer vertical axis between linear and logarithmic scales. The tick labels show actual kelvin values and are spaced to avoid overlap. The channel list and cursor inspector always show kelvin, not logarithms.

Recent context on reopening uses saved interval data, so its resolution may be lower than the live trace. This is not yet a full historical-data comparison application.

## 5. Inspecting values with the mouse

Move the pointer across a plot or along its time axis:

1. A vertical dotted line appears at the time under the pointer. Matching guides appear on all three plots.
2. The **At cursor** panel names the active plot and displays the cursor time.
3. It lists the numeric value of each visible curve in that plot, with units.
4. Each row also shows the actual sample time and its offset from the cursor.

Readouts use the nearest recorded sample. They do not interpolate or invent an instantaneous measurement between samples. For example, an offset of `-3.0s` means that reading was acquired three seconds before the cursor time. Saved ten-second context can therefore have larger offsets than live one-second data.

A missing or invalid sample is shown as **No valid reading**. Hidden curves are omitted from the cursor list. Moving out of the plotting area clears the guide and returns the inspector to its idle state. Time labels use this PC's local clock/time zone.

## 6. How instrument access changed

### Before VTI Control

Each notebook or script opened its own physical Mercury socket. The addresses were:

- iTC: `TCPIP::192.168.73.30::7020::SOCKET`
- IPS: `TCPIP::192.168.73.31::7020::SOCKET`

Repeated tests of the installed firmware showed that a second simultaneous physical TCP client was rejected while the first continued working. A separate logger therefore could not simply open another independent connection reliably.

### With VTI Control

The service owns one physical connection to each controller. Scripts instead open local virtual endpoints:

- iTC: **`TCPIP::127.0.0.1::17020::SOCKET`**
- IPS: **`TCPIP::127.0.0.1::17021::SOCKET`**

`127.0.0.1` means this PC. The forwarding endpoints speak the Oxford text protocol and represent the real instruments; they are not independent simulated controllers. Several local clients can remain connected. The broker sends one instrument command at a time and returns each reply to its requesting client, interleaving logging queries between requests.

While the service runs, **do not connect measurement scripts directly to the physical addresses**. A script still using an old station YAML file may try to do that even if its notebook code is unchanged.

The server coordinates individual command/reply exchanges, not entire experiments. Two scripts issuing conflicting temperature or magnet commands can still conflict logically. Keep one owner of each control sequence.

## 7. Connecting with the laboratory QCoDeS drivers

Use the improved Mercury drivers in `D:\VTI-control\BarreraLabDrivers`, branch `vti/mercury-communications`. They preserve the familiar parameter names, remove automatic iTC configuration writes on connection, validate replies, and fix numeric parsing. The old notebook environments have not been changed automatically.

After reviewing/testing the driver branch, install it into the Python environment used by the measurement notebook, then restart that kernel. From that environment's terminal:

```powershell
python -m pip install -e 'D:\VTI-control\BarreraLabDrivers[mercury]'
```

To confirm which driver a notebook is importing:

```python
import inspect
from barreralabdrivers.drivers import MercuryiTC
print(inspect.getfile(MercuryiTC))
```

It should point into the intended D: checkout, rather than an old OneDrive checkout or an outdated installed copy.

### Direct construction: before and after

Previously, the iTC constructor used the physical address:

```python
# Previous connection, usable only when the service is stopped:
itc = MercuryiTC('itc', address='TCPIP::192.168.73.30::7020::SOCKET')
```

Now connect both instruments through the service:

```python
from barreralabdrivers.drivers import MercuryiTC, MercuryiPS

itc = MercuryiTC('itc', address='TCPIP::127.0.0.1::17020::SOCKET', timeout=5)
ips = MercuryiPS('ips', address='TCPIP::127.0.0.1::17021::SOCKET', timeout=5)

print(itc.vti.temp())
print(itc.vti.pressure())
print(ips.mag.field())          # The driver's PFLD/persistent-field register.
print(ips.mag.supply_field())   # Supply field; may differ in persistent mode.
```

The QCoDeS timeout above is in **seconds**. The usual parameter calls remain the same; the transport address changes. Close these client objects when finished. Closing a local client does not stop the service or its logging.

### QCoDeS station YAML

Keep the station's instrument names and class names, and replace the addresses:

```yaml
instruments:
  MercuryiTC:
    type: barreralabdrivers.drivers.MercuryiTC
    address: TCPIP::127.0.0.1::17020::SOCKET
    timeout: 5
  MercuryiPS:
    type: barreralabdrivers.drivers.OxfordMercuryIPS.MercuryiPS
    address: TCPIP::127.0.0.1::17021::SOCKET
    timeout: 5
```

Existing loading code still works:

```python
import qcodes as qc
station = qc.Station(config_file='your_updated_station.yml')
itc = station.load_instrument('MercuryiTC')
ips = station.load_instrument('MercuryiPS')
```

## 8. Connecting with PyVISA

QCoDeS is optional. A simple read-only client can use PyVISA:

```python
import pyvisa
rm = pyvisa.ResourceManager()
itc = rm.open_resource(
    'TCPIP::127.0.0.1::17020::SOCKET',
    read_termination='\n', write_termination='\n', timeout=5000,
)
try:
    print(itc.query('*IDN?'))
    print(itc.query('READ:DEV:MB1.T1:TEMP:SIG:TEMP'))
finally:
    itc.close()
    rm.close()
```

PyVISA's timeout here is in **milliseconds**. Consume one reply for every command, including SET acknowledgements. Do not flush an empty reply buffer before each query. The existing drivers handle the transactions for you.

The backend accepts READ, SET, and `*IDN?` requests from local clients. Logger polling itself uses only read queries. If a SET times out, the instrument may already have applied it; do not blindly resend it. After a transport timeout in an improved QCoDeS driver, close and recreate that client before continuing.

## 9. Data locations and cadence

- Primary data: `D:\VTI-control\data\YYYY\vti-YYYY-MM.sqlite`.
- Daily refreshed same-disk backup: `D:\VTI-control\backups`.
- Diagnostic log: `D:\VTI-control\logs\service.log`.
- Backend configuration: `D:\VTI-control\config\vti.json`.
- GUI preferences: `D:\VTI-control\config\gui.ini`.

Primary archives use UTC month boundaries. Displayed times use the PC local clock.

The default acquisition cadence is approximately one second per instrument. Numerical values are saved as ten-second summaries: last valid value, minimum, maximum, mean, and valid/attempted counts. State and alarm changes are recorded as events. The database keeps data-quality information; invalid values are not silently replaced with zero.

To save less frequently, change `save_interval` in the JSON configuration, for example to `60`, then restart the service. This changes saved summary resolution without changing the normal one-second polling target. Archive retention is not automatically pruned; monitor free disk capacity. The same-disk backup does not protect against failure of the D: drive.

## 10. Troubleshooting

### GUI says SERVICE OFFLINE

Check `Get-Service VTIControl`, start the service if necessary, and inspect `D:\VTI-control\logs\service.log`. The local health endpoint is `http://127.0.0.1:17600/health`. Reopening the GUI alone cannot fix a stopped backend.

### ITC or IPS is offline, but the service is running

Check controller power and networking. Close old direct instrument connections in notebooks or other applications. The service reconnects automatically with backoff. A healthy peer instrument can continue logging while the other is unavailable.

### A channel says sensor alarm, invalid, or stale

Inspect the Attention panel and System status tab. Sensor alarm means the instrument has reported a problem; invalid means a reply could not be accepted; stale means there has not been a recent valid update. Investigate the physical sensor/controller rather than treating the last numeric reading as current.

### Curves or time regions are missing

Check the channel checkboxes, press Reset view, and check data quality. The cursor may be outside the available recent buffer, or the sensor may have invalid readings. Hidden curves still log. More detailed historical comparison is a future feature.

### Storage error

Check free disk space and the service log. Storage failures are reported and retry buffers are bounded. Data may be lost during a prolonged storage failure; discarded records are reported. Do not move or delete the active SQLite database or its WAL files while the service is writing.

### Script cannot connect

Use the localhost endpoints, verify the service is running, and confirm the notebook is importing the intended driver checkout. Check the QCoDeS/PyVISA timeout units. An old physical address bypasses the broker and may be rejected.

### Foreground backend diagnostics

Stop the Windows service first, then run:

```powershell
& 'D:\VTI-control\app\VTI-Logger\VTI-Logger.exe'
```

Stop the foreground logger before starting the Windows service again. The server deliberately rejects duplicate backend instances.

## 11. Current limits

The GUI is not a safety interlock. Persistent/driven magnet interpretation still needs verification during real transitions, and PFLD is a controller register rather than an independent field measurement. Long-duration commissioning remains in progress. Control forwarding has been tested against simulated instruments; development hardware checks used read commands only. Source is published at https://github.com/barreralab/vti-control. The Mercury driver update is proposed in draft PR https://github.com/barreralab/BarreraLabDrivers/pull/4 and has not been merged.
