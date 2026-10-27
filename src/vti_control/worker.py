"""One instrument worker owns its connection and serializes external requests."""
from concurrent.futures import Future
import json
import logging
import queue
import re
import threading
import time
from .protocol import Transport, ProtocolError, numeric
from .model import inventory

log = logging.getLogger(__name__)

class InstrumentWorker(threading.Thread):
    def __init__(self, name, config, state, archive, stop):
        super().__init__(name=name, daemon=True)
        self.config, self.state, self.archive, self.stop = config, state, archive, stop
        self.transport = Transport(config['host'], config.get('port', 7020), config.get('timeout', .7))
        self.requests = queue.Queue(maxsize=64)
        self.channels, self.failed_channels = [], {}
        self.retry_at, self.failures, self.connected = 0, 0, False
    def submit(self, command, wait=4):
        future = Future()
        self.requests.put_nowait((command, future, time.monotonic() + wait))
        try:
            return future.result(timeout=wait)
        except TimeoutError:
            future.cancel()
            raise TimeoutError('Request deadline exceeded; a SET may already have been applied')
    def initialize(self):
        identity = self.transport.query('*IDN?')
        catalog = self.transport.query('READ:SYS:CAT')
        names = {}
        for uid, kind in re.findall(r'DEV:([^:]+):(TEMP|HTR|PRES|AUX)(?=:|$)', catalog):
            try:
                names[uid] = self.transport.query(f'READ:DEV:{uid}:{kind}:NICK').rsplit(':', 1)[-1]
            except ProtocolError:
                names[uid] = uid
        self.channels = inventory(self.name, catalog, names, self.config.get('magnet_groups', ['GRPZ']))
        with self.state.lock:
            self.state.channels.update({c.key: c.as_dict() for c in self.channels})
            self.state.instruments[self.name] = {'connected': True, 'identity': identity, 'catalog': catalog, 'error': ''}
        self.connected, self.failures = True, 0
        self.archive.event('connected', json.dumps({'instrument': self.name, 'identity': identity, 'catalog': catalog}))
    def disconnected(self, exc):
        self.connected = False
        self.transport.close()
        self.failures += 1
        self.retry_at = time.monotonic() + min(30, 2 ** min(self.failures - 1, 5))
        with self.state.lock:
            self.state.instruments.setdefault(self.name, {}).update(connected=False, error=str(exc))
            for ch in self.channels:
                old = self.state.samples.get(ch.key, {})
                self.state.samples[ch.key] = dict(old, quality='disconnected', error=str(exc))
        self.archive.event('disconnected', f'{self.name}: {exc}')
        for ch in self.channels:
            self.archive.sample(ch.key, None, 'disconnected', time.time())
        log.warning('%s disconnected: %s', self.name, exc)
    def external(self):
        for _ in range(4):
            try:
                cmd, future, deadline = self.requests.get_nowait()
            except queue.Empty:
                return
            if time.monotonic() > deadline:
                if not future.done():
                    future.set_exception(TimeoutError('Request expired before transmission'))
                continue
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if not self.connected:
                    raise ConnectionError('Instrument reconnecting')
                reply = self.transport.query(cmd)
                if cmd.startswith('SET:'):
                    self.archive.event('external_set', json.dumps({'instrument': self.name, 'command': cmd, 'reply': reply}))
                future.set_result(reply)
            except Exception as exc:
                future.set_exception(exc)
                if self.connected and not isinstance(exc, ProtocolError):
                    self.disconnected(exc)
    def poll(self, ch):
        stamp = time.time()
        value, quality, error = None, 'ok', ''
        try:
            reply = self.transport.query(ch.command)
            stamp = time.time()
            value = numeric(reply, ch.unit) if ch.unit is not None else reply[len('STAT:' + ch.command[5:] + ':'):]
            if ch.category in ('heater_state', 'switch_heater') and value not in ('ON', 'OFF'):
                raise ProtocolError(f'Unexpected state {value!r}')
            if ch.category == 'magnet_action' and value not in ('HOLD', 'RTOS', 'RTOZ', 'CLMP'):
                raise ProtocolError(f'Unexpected action {value!r}')
            if ch.category == 'temperature':
                with self.state.lock:
                    alarm_sample = self.state.samples.get(f'{self.name}.alarms', {})
                    alarm = alarm_sample.get('value') or ''
                if alarm_sample.get('quality') != 'ok' or stamp - alarm_sample.get('time', 0) > 4:
                    quality = 'alarm_unknown'
                elif ch.uid in alarm:
                    quality = 'sensor_alarm'
        except ProtocolError as exc:
            value, quality, error = None, 'invalid', str(exc)
            self.failed_channels[ch.key] = time.monotonic() + 60
        except (OSError, ConnectionError) as exc:
            self.disconnected(exc)
            return
        with self.state.lock:
            self.state.samples[ch.key] = {'value': value, 'quality': quality, 'time': stamp, 'error': error}
        self.archive.sample(ch.key, value, quality, stamp)
    def run(self):
        next_poll = time.monotonic()
        try:
            while not self.stop.is_set():
                self.external()
                if not self.connected:
                    if time.monotonic() >= self.retry_at:
                        try:
                            self.initialize()
                        except Exception as exc:
                            self.disconnected(exc)
                    self.stop.wait(.05)
                    continue
                now = time.monotonic()
                if now < next_poll:
                    self.stop.wait(min(.05, next_poll - now))
                    continue
                started = time.monotonic()
                for ch in sorted(self.channels, key=lambda c: c.category != 'alarms'):
                    if self.stop.is_set() or not self.connected:
                        break
                    self.external()
                    if not self.connected:
                        break
                    if time.monotonic() >= self.failed_channels.get(ch.key, 0):
                        self.poll(ch)
                with self.state.lock:
                    self.state.instruments[self.name]['last_cycle_seconds'] = time.monotonic() - started
                next_poll += self.config.get('poll_interval', 1)
                if next_poll < time.monotonic():
                    next_poll = time.monotonic() + self.config.get('poll_interval', 1)
        except Exception:
            log.exception('Instrument worker failed')
            self.disconnected('Worker stopped unexpectedly; restart service')
        finally:
            self.transport.close()
