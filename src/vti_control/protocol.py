"""Validated, single-owner Oxford TCP transport; no control commands on connect."""
import math
import re
import socket
import time

class ProtocolError(ValueError):
    pass

_NUMBER = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)([A-Za-z%/0-9]*)")

def numeric(reply, unit=None):
    match = _NUMBER.fullmatch(reply.rsplit(":", 1)[-1])
    if not match:
        raise ProtocolError(f"Not a numeric payload: {reply!r}")
    if match[2] not in {'', 'K', 'T', 'mB', 'mbar', 'mBar', 'A', 'W', 'V', '%', 'T/m', 'T/min', 'Ohm', 'ohm', 'Hz'}:
        raise ProtocolError(f'Unrecognized numeric unit: {match[2]!r}')
    value = float(match[1])
    if not math.isfinite(value):
        raise ProtocolError('Non-finite number')
    aliases = {'mbar': 'mB', 'mBar': 'mB', 'T/min': 'T/m'}
    if unit is not None and aliases.get(match[2], match[2]) != aliases.get(unit, unit):
        raise ProtocolError(f'Expected unit {unit!r}, got {match[2]!r}')
    return value

def validate(command, reply):
    if command == '*IDN?':
        if not reply.startswith('IDN:OXFORD INSTRUMENTS:MERCURY'):
            raise ProtocolError(f'Unexpected identity: {reply!r}')
    elif command.startswith('READ:'):
        prefix = 'STAT:' + command[5:] + ':'
        if not reply.startswith(prefix):
            raise ProtocolError(f'Response mismatch for {command!r}: {reply!r}')
        if reply[len(prefix):].strip().upper() in {'INVALID', 'N/A', 'NAN', 'ERROR'}:
            raise ProtocolError(f'Instrument rejected query: {reply!r}')
    elif command.startswith('SET:'):
        accepted = {'STAT:' + command + ':VALID', 'STAT:' + command, 'STAT:' + command[4:] + ':VALID'}
        if reply not in accepted:
            raise ProtocolError(f'Set not acknowledged: {reply!r}')
    else:
        raise ProtocolError('Only READ, SET and *IDN? are supported')
    return reply

class Transport:
    def __init__(self, host, port=7020, timeout=.7):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock, self.buffer = None, b''
    def close(self):
        if self.sock:
            self.sock.close()
        self.sock, self.buffer = None, b''
    def query(self, command):
        if '\n' in command or '\r' in command or len(command) > 4096:
            raise ProtocolError('Invalid command framing')
        try:
            deadline = time.monotonic() + self.timeout
            if self.sock is None:
                self.sock = socket.create_connection((self.host, self.port), self.timeout)
                self.sock.settimeout(self.timeout)
            self.sock.settimeout(max(.001, deadline - time.monotonic()))
            self.sock.sendall((command + '\n').encode('ascii'))
            while b'\n' not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Mercury transaction deadline exceeded')
                self.sock.settimeout(remaining)
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError('Controller closed connection')
                self.buffer += chunk
                if len(self.buffer) > 65536:
                    raise ProtocolError('Oversized reply')
            line, self.buffer = self.buffer.split(b'\n', 1)
            return validate(command, line.decode('ascii').rstrip('\r'))
        except Exception:
            self.close()
            raise
