"""Inventory and display state; retain source field registers separately."""
from dataclasses import dataclass, asdict
import re

@dataclass(frozen=True)
class Channel:
    key: str
    instrument: str
    uid: str
    name: str
    command: str
    unit: str | None
    category: str
    def as_dict(self):
        return asdict(self)

def inventory(instrument, catalog, names=None, magnet_groups=('GRPZ',)):
    names, channels = names or {}, []
    def add(uid, suffix, unit, category, label=None):
        kind, rest = suffix.split(':', 1)
        channels.append(Channel(f"{instrument}.{uid}.{rest.replace(':', '.')}", instrument, uid,
                        label or names.get(uid, uid), f'READ:DEV:{uid}:{suffix}', unit, category))
    devices = re.findall(r'DEV:([^:]+):(TEMP|HTR|PRES|AUX|PSU)(?=:|$)', catalog)
    for uid, kind in devices:
        if kind == 'TEMP':
            add(uid, 'TEMP:SIG:TEMP', 'K', 'temperature')
            add(uid, 'TEMP:LOOP:ENAB', None, 'heater_state', names.get(uid, uid) + ' loop')
        elif kind == 'HTR':
            add(uid, 'HTR:SIG:POWR', 'W', 'heater_power')
        elif kind == 'PRES':
            add(uid, 'PRES:SIG:PRES', 'mB', 'pressure')
        elif kind == 'AUX':
            add(uid, 'AUX:SIG:PERC', '%', 'valve')
    if instrument == 'ips':
        present = {uid for uid, kind in devices if kind == 'PSU'}
        for uid in magnet_groups:
            if uid not in present:
                continue
            for suffix, unit, category, label in [
                ('SIG:FLD', 'T', 'supply_field', 'Supply field'),
                ('SIG:PFLD', 'T', 'persistent_field', 'Persistent register'),
                ('SIG:CURR', 'A', 'supply_current', 'Supply current'),
                ('SIG:SWHT', None, 'switch_heater', 'Switch heater'),
                ('SIG:RFLD', 'T/m', 'field_rate', 'Field ramp rate'),
                ('ACTN', None, 'magnet_action', 'Magnet action'),
                ('STAT', None, 'magnet_status', 'Magnet status')]:
                add(uid, 'PSU:' + suffix, unit, category, uid + ' ' + label)
    channels.append(Channel(f'{instrument}.alarms', instrument, 'SYS', instrument + ' alarms',
                            'READ:SYS:ALRM', None, 'alarms'))
    return channels

def magnet_state(channels, samples, now, stale_after=4):
    result = {}
    for group in sorted({c['uid'] for c in channels.values() if c['category'] == 'supply_field'}):
        found = {}
        for key, ch in channels.items():
            if ch['uid'] == group and ch['instrument'] == 'ips':
                sample = samples.get(key, {})
                if sample.get('quality') == 'ok' and now - sample.get('time', 0) <= stale_after:
                    found[ch['category']] = sample.get('value')
        heater, action = found.get('switch_heater'), found.get('magnet_action')
        mode, value = 'unknown', None
        if heater == 'ON' and action is not None and 'supply_field' in found:
            mode, value = 'driven (verify on controller)', found['supply_field']
        elif heater == 'OFF' and action is not None and 'persistent_field' in found:
            mode, value = 'persistent register (verify on controller)', found['persistent_field']
        result[group] = {'mode': mode, 'field': value, 'supply_field': found.get('supply_field'),
                         'persistent_field': found.get('persistent_field'), 'action': action,
                         'switch_heater': heater}
    return result
