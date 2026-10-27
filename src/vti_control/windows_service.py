"""Native Windows service host. Run the packaged EXE with install/start/stop/remove."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
import servicemanager
import win32event
import win32service
import win32serviceutil
import win32timezone
from .service import Service, read_config, DEFAULT_CONFIG

class VTIWindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'VTIControl'
    _svc_display_name_ = 'VTI Control acquisition service'
    _svc_description_ = 'Continuous local Oxford Teslatron logging and instrument communication broker.'
    if getattr(sys, 'frozen', False):
        _exe_name_ = sys.executable
    def __init__(self, args):
        super().__init__(args)
        self.stopped = threading.Event()
        self.backend = None
    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stopped.set()
        if self.backend:
            self.backend.stop.set()
    def SvcDoRun(self):
        config = read_config(DEFAULT_CONFIG)
        logs = Path(config['log_dir'])
        logs.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
            handlers=[RotatingFileHandler(logs/'service.log', maxBytes=2_000_000, backupCount=5)])
        self.backend = Service(config)
        self.backend.start()
        try:
            while not self.stopped.wait(2):
                if not all(w.is_alive() for w in self.backend.workers.values()) or not self.backend.archive.is_alive():
                    raise RuntimeError('A backend worker stopped')
        finally:
            self.backend.close()

def main():
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(VTIWindowsService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(VTIWindowsService)
