"""Background logger and loopback-only Oxford forwarding endpoints."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
import json
import logging
import signal
import socket
import socketserver
import threading
import time
from . import __version__
from .protocol import ProtocolError
from .model import magnet_state
from .history import recent
from .storage import Archive
from .worker import InstrumentWorker

DEFAULT_CONFIG = r'D:\VTI-control\config\vti.json'
log = logging.getLogger(__name__)

class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.channels, self.samples, self.instruments = {}, {}, {}
        self.started, self.archive = time.time(), None
    def snapshot(self):
        now = time.time()
        with self.lock:
            samples = {k: dict(v) for k, v in self.samples.items()}
            for v in samples.values():
                if now - v.get('time', 0) > 4 and v.get('quality') == 'ok':
                    v['quality'] = 'stale'
            return {'version': __version__, 'time': now, 'started': self.started,
                    'channels': dict(self.channels), 'samples': samples,
                    'instruments': {k: dict(v) for k, v in self.instruments.items()},
                    'magnet': magnet_state(self.channels, samples, now),
                    'storage': dict(self.archive.health) if self.archive else {}}

class ExclusiveBind:
    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

class LocalHTTPServer(ExclusiveBind, ThreadingHTTPServer):
    allow_reuse_address = False

class LimitedServer(ExclusiveBind, socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close(); return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release(); raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

class Proxy(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(300)
        while True:
            try:
                line = self.rfile.readline(4098)
                if not line:
                    return
                if len(line) > 4096 or not line.endswith(b'\n'):
                    return
                cmd = line.decode('ascii').strip()
                if '\r' in cmd or not (cmd.startswith(('READ:', 'SET:')) or cmd == '*IDN?'):
                    raise ProtocolError('Unsupported command')
                reply = self.server.worker.submit(cmd)
            except (OSError, UnicodeError):
                return
            except Exception as exc:
                reply = 'ERROR:VTI:' + type(exc).__name__ + ':' + str(exc).replace('\n', ' ')
            try:
                self.wfile.write((reply + '\n').encode('ascii', errors='replace'))
                self.wfile.flush()
            except OSError:
                return

class API(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/state', '/health', '/recent'):
            self.send_error(404); return
        snapshot = self.server.state.snapshot()
        if self.path == '/recent':
            try:
                snapshot['history'] = recent(self.server.data_dir)
            except Exception as exc:
                snapshot['history_error'] = str(exc)
        body = json.dumps(snapshot, allow_nan=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass
    def log_message(self, *args):
        pass

class Service:
    def __init__(self, config):
        self.config, self.state, self.stop = config, State(), threading.Event()
        self.archive = Archive(config['data_dir'], self.state.channels, config.get('save_interval', 10), config.get('backup_dir'))
        self.state.archive = self.archive
        self.workers = {name: InstrumentWorker(name, settings, self.state, self.archive, self.stop)
                        for name, settings in config['instruments'].items()}
        self.servers = []
        self.http = LocalHTTPServer(('127.0.0.1', config.get('api_port', 17600)), API)
        self.http.daemon_threads = True
        self.http.state = self.state
        self.http.data_dir = config['data_dir']
        self.servers.append(self.http)
        try:
            for name, worker in self.workers.items():
                server = LimitedServer(('127.0.0.1', config['instruments'][name]['proxy_port']), Proxy)
                server.worker = worker
                self.servers.append(server)
        except Exception:
            for server in self.servers:
                server.server_close()
            raise
    def start(self):
        self.archive.start()
        self.archive.event('service_started', __version__)
        for server in self.servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        for worker in self.workers.values():
            worker.start()
        log.info('VTI service started')
    def close(self):
        self.stop.set()
        for server in self.servers:
            server.shutdown(); server.server_close()
        for worker in self.workers.values():
            worker.join(timeout=5)
        self.archive.event('service_stopped', 'Normal shutdown')
        self.archive.stop_event.set()
        self.archive.join(timeout=10)

def read_config(path):
    config = json.loads(Path(path).read_text())
    if not 1 <= config.get('save_interval', 10) <= 3600:
        raise ValueError('save_interval must be between 1 and 3600 seconds')
    for settings in config['instruments'].values():
        if not .1 <= settings.get('poll_interval', 1) <= 3600:
            raise ValueError('Invalid polling interval')
        if not .05 <= settings.get('timeout', .7) <= 30:
            raise ValueError('Invalid instrument timeout')
    return config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = read_config(args.config)
    log_dir = Path(config.get('log_dir', r'D:\VTI-control\logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'service.log', maxBytes=2_000_000, backupCount=5)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    service = Service(config)
    def stop(*_):
        service.stop.set()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    service.start()
    try:
        service.stop.wait()
    finally:
        service.close()

if __name__ == '__main__':
    main()
