# Mercury driver improvements and validation report

Prepared 2026-10-27 for the BarreraLab VTI Control project.

## Publication status

- VTI Control: https://github.com/barreralab/vti-control (public).
- Driver repository: https://github.com/barreralab/BarreraLabDrivers (public).
- Driver commit: `780c64061f48e61a7c14003e4716dc5bacd8252b`.
- Driver branch: `vti/mercury-communications`, pushed to the organization repository.
- Draft pull request: https://github.com/barreralab/BarreraLabDrivers/pull/4, targeting `serial_comms`.
- The driver branch was rebased onto freshly fetched `origin/serial_comms` (`c7488cb`) before publication. Five focused driver/broker integration cases passed after that rebase.
- The driver pull request has not been merged. The original OneDrive checkout and existing measurement environments remain unchanged.

## Summary

The Mercury iTC and IPS QCoDeS drivers were changed to make ordinary parameter access predictable, avoid changing iTC configuration merely by connecting, and prevent several silent numeric-parsing errors. The existing parameter names and command mappings were preserved. The background VTI logger uses its own standard-library socket transport; these driver changes are for measurement scripts that use QCoDeS, including clients of the local VTI server.

These are communication and data-integrity improvements. They are not a redesign or qualification of the magnet control sequences.

## Repository and branch provenance

- Local checkout: `D:\VTI-control\BarreraLabDrivers`.
- Upstream remote: `https://github.com/barreralab/BarreraLabDrivers.git` (the former BarreraInstrumentDrivers URL redirects here).
- Working branch: `vti/mercury-communications`.
- Starting commit: `a65fa5890d9ab8d381fe4eeb3587e9f11065221b`.
- The checkout was cloned locally from the existing driver repository, whose checked-out branch was `serial_comms`. The new working branch therefore starts from that branch, not from `main`.
- No GitHub fork was created. The driver update was committed separately and pushed to its own organization-repository branch; it is not merged into a shared branch.
- The old OneDrive checkout and existing notebook environments were left unchanged.

The initial clone inherited a cached `origin/main` reference at `3dcb054`. Before publication, the organization repository was fetched and GitHub confirmed that its current default branch is `serial_comms`. The Mercury commit was rebased onto that branch at `c7488cb`; the two newer upstream commits changed unrelated files. The draft PR therefore contains only the six-file Mercury update against the current default branch, rather than proposing the entire serial_comms history against main.

## Files changed

| File | Purpose |
|---|---|
| `src/barreralabdrivers/drivers/OxfordMercuryITC.py` | Remove connection-time configuration writes; delegate communication/parsing to shared helpers; add explicit legacy configuration method; parse pressure setpoint numerically. |
| `src/barreralabdrivers/drivers/OxfordMercuryIPS.py` | Use shared communication/parsing; respect configured timeout; parse heater resistance and voltage limit numerically. |
| `src/barreralabdrivers/drivers/_mercury.py` (new) | Shared transaction lock, validated replies and acknowledgements, numeric parsing, and session-synchronization state. |
| `tests/test_mercury_communications.py` (new) | Standalone simulated TCP tests using actual QCoDeS driver instances. |
| `pyproject.toml` | Add optional `mercury` and `test` dependency groups. |
| `MERCURY_CHANGES.md` (new) | Concise change and adoption notes for driver reviewers. |

## 1. Connecting to the iTC no longer changes its configuration

Previously, creating a `MercuryiTC` instance immediately sent:

```text
SET:DEV:DB5.P1:PRES:LOOP:AUX:DB4.G1
SET:DEV:DB5.P1:PRES:LOOP:SWMD:OFF
SET:DEV:DB5.P1:PRES:LOOP:FAUT:OFF
```

A connection intended only for monitoring could therefore reassign the pressure loop's auxiliary device and change its operating configuration. Reconnecting repeated those writes.

The constructor no longer sends them. The previous sequence is available as the explicit method:

```python
itc.configure_manual_needle_valve()
```

That method deliberately changes hardware state and should be invoked only when the experiment requires the legacy configuration. It is not called by VTI Control. Identification queries still occur during connection.

Compatibility implication: a script that relied on those implicit initialization writes must now request that configuration explicitly, after checking that it is appropriate. Silent preservation of that behavior would defeat read-only connection semantics.

## 2. Replace buffer flushing with one command / one reply

Previously, every getter attempted an unsolicited `visa_handle.read()` before sending its query. With an empty response buffer, that read could wait for the 400 ms timeout. A normal multi-channel acquisition could spend seconds waiting for expected empty-buffer timeouts.

Setters sent `write()` followed by a read whose result was discarded, and suppressed read exceptions. A rejected SET or missing acknowledgement could therefore appear successful.

Both instrument roots now use a shared `MercuryCommunication` mixin. Parameter getters call `_mercury_query()` and setters call `_mercury_set()`. Those methods send and receive using `visa_handle.query()`. There is no preliminary read and no blanket suppression of transaction failures.

The old private helper names `_flush_then_get` and `_set_with_flush` remain to minimize changes to parameter declarations, but they now delegate to the transaction helpers; their historical names do not describe their new behavior.

## 3. Validate read replies and setter acknowledgements

For a READ command, the helper verifies the corresponding `STAT:` device/signal prefix. Identity replies must have an `IDN:` prefix. Terminal `INVALID`, `N/A`, `NAN`, and `ERROR` payloads raise errors instead of being parsed as measurements.

SET replies are checked against explicit successful echo forms, including Oxford's `STAT:SET:...` echo with or without `:VALID`, and the supported `STAT:...:VALID` form. An unexpected or negative acknowledgement raises `ValueError`. Commands are not automatically retried.

This makes failures visible to a measurement script. A SET timeout remains ambiguous: the hardware may have applied the command before communication failed. Callers must not blindly replay such operations. The supported echo forms have been exercised with simulated instruments; real hardware SET operations were not used during commissioning.

## 4. Correct numeric parsing

The old implementation searched the whole reply for numeric substrings and selected the last one. This could turn an invalid response into a believable number taken from the device identifier.

The shared `response_float()` now validates only the final colon-delimited payload, supports signed integers, decimal numbers and scientific notation, checks a defined unit-suffix whitelist, and rejects non-finite results.

Examples confirmed during the original review:

| Payload or response | Old result | New behavior |
|---|---:|---|
| `...:PRES:1.2E-3mB` | `3.0` | `0.0012` |
| `...:PFLD:-1T` | `1.0` | `-1.0` |
| `STAT:DEV:DB5.P1:PRES:SIG:PRES:INVALID` | `1.0`, from `DB5.P1` | Error |
| Malformed or non-finite numeric payload | Could parse a fragment | Error |

The driver helper validates recognized unit suffixes, not the physical dimension expected by every individual parameter. The separate logger transport performs its own per-channel expected-unit check. Those two levels of validation should not be confused.

## 5. Serialize in-process parameter transactions

The shared mixin creates one reentrant lock on the root instrument. Both root and submodule parameter helpers use that lock around a complete query or setter transaction. Concurrent threads using supported parameters on the same instrument instance therefore cannot interleave the write and read halves of an exchange.

This is not an inter-process lock and does not make multiple physical Mercury sockets reliable. Separate driver instances and scripts need the local VTI server for cross-client coordination. Direct low-level `write()`, `ask()`, or `visa_handle` use bypasses these parameter helpers and should not be mixed concurrently with them.

## 6. Respect configurable timeouts and fail explicitly after lost synchronization

The old drivers overwrote the VISA timeout with 400 ms. The new mixin supplies a default QCoDeS timeout of 2 seconds and preserves an explicit caller value. For example, `timeout=0.3` results in a 300 ms VISA timeout; that conversion is tested. QCoDeS timeout arguments are seconds, while direct PyVISA timeout arguments are milliseconds.

If a transport exception or mismatched read reply occurs, the driver marks the session as desynchronized and rejects subsequent helper transactions. The caller must close and recreate the driver instance. It does not keep reading through an uncertain stream and risk accepting a delayed reply as the next measurement.

Automatic reconnection and backoff are implemented in the separate VTI service, not in these QCoDeS drivers. A normal, correctly framed instrument rejection raises an error without unnecessarily poisoning the session.

## 7. Return numbers for additional numeric properties

The following getters now apply the numeric parser instead of returning raw protocol strings:

- `itc.vti.pset`.
- `ips.mag.htr_resistance`.
- `ips.mag.htr_vlim`.

Their parameter names remain unchanged. A caller that manipulated the old response strings must be updated to work with floats. State parameters retain their existing raw-response conventions to avoid changing the public interface broadly in this communication patch.

## 8. Optional dependencies

The driver package now offers:

- `mercury`: QCoDeS, NumPy, and the pure-Python PyVISA backend.
- `test`: pytest.

This keeps the base installation's existing lightweight dependency set while making the Mercury requirements explicit. The dependencies are not tightly version-pinned; the tested application environment is recorded separately in vti-control's `requirements-windows.lock.txt`.

## Validation and scope of evidence

### Driver-specific tests

`tests/test_mercury_communications.py` in the driver checkout has two parametrized test cases, one each for iTC and IPS. They use real QCoDeS objects connected to a simulated Oxford TCP server and verify:

- No SET commands are sent during construction.
- Explicit timeout values are respected.
- Scientific notation with a negative sign is parsed correctly.
- Concurrent parameter reads share transactions correctly.
- An invalid reply raises an error, and a subsequent valid query can succeed.
- The iTC's explicit configuration method sends its three commands, against the simulator only.
- Pressure-setpoint parsing returns a float.

Run them from the driver checkout with the appropriate extras installed:

```powershell
python -m pytest tests/test_mercury_communications.py
```

### VTI integration and regression tests

The latest combined suite passed **36 tests**, including those two standalone driver cases. Additional tests in vti-control cover actual QCoDeS clients through the simulated local broker, SET acknowledgement forms, late replies and reconnects, storage recovery, persistent-field register separation, GUI visibility/hover behavior, and logarithmic label spacing.

Not every failure case is exercised directly against the QCoDeS mixin. In particular, the broader socket transport timeout/reconnect tests validate the separate VTI transport and should not be presented as complete unit-test coverage of the mixin's desynchronized-session behavior.

### Read-only hardware commissioning

- Installed iTC firmware: `2.6.04.000`; IPS firmware: `2.5.09.000`.
- Repeated second-client tests rejected the second physical connection while the first remained healthy.
- Four simultaneous clients worked through the VTI broker.
- Actual QCoDeS reads through the broker returned temperature, pressure, and magnet-register data.
- No physical SET commands were sent as part of development and commissioning. Control forwarding was tested with simulated hardware.

The iTC also reported a probe open-circuit alarm despite returning a numeric temperature. That is handled by the logger's data-quality layer, not fixed in the driver. Later iTC identity replies returned `OFF` in the serial-number field; the original serial was `233850309`. This identity anomaly remains undiagnosed and is recorded in the commissioning notes.

## Remaining work before group adoption

1. Review draft PR #4 against `serial_comms`. The fresh fetch and rebase were completed before publication; the PR is intentionally not merged automatically.
2. Review successful/rejected SET response variants against the installed firmware before relying on new control workflows.
3. Add direct mixin tests for desynchronized-session handling and negative setter acknowledgements if stronger standalone driver coverage is needed.
4. Review the inherited magnet control sequences separately: field ramps can still block without an overall completion deadline, and switch-heater sequencing is not newly qualified by these changes.
5. Confirm compatibility with the group's measurement environments before updating them. The unchanged notebooks have not silently acquired the new drivers.
6. Conduct long-duration operation checks. The brief tests do not establish years of uninterrupted reliability or resolve physical sensor faults.

The VTI server's localhost addresses are iTC `127.0.0.1:17020` and IPS `127.0.0.1:17021`. Existing measurement scripts keep their QCoDeS parameter calls but must use those addresses while the service owns the physical connections. See `USER_MANUAL.md` for before/after examples and installation instructions.
