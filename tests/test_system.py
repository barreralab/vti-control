import concurrent.futures
import json
import socket
import socketserver
import sqlite3
import threading
import time
from urllib.request import urlopen
import pytest
from vti_control.protocol import Transport, ProtocolError, numeric, validate
from vti_control.service import Service
from vti_control.model import inventory, magnet_state
from vti_control.storage import Archive

class Simulator(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    def __init__(self):
        self.commands = []
        self.bad_once, self.drop_once, self.delay_once = False, False, False
        super().__init__(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()
    def close(self):
        self.shutdown(); self.server_close(); self.thread.join()

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            cmd = line.decode().strip()
            self.server.commands.append(cmd)
            if self.server.drop_once:
                self.server.drop_once = False
                return
            if self.server.delay_once:
                self.server.delay_once = False
                time.sleep(.3)
            if cmd == '*IDN?':
                reply = 'IDN:OXFORD INSTRUMENTS:MERCURY ITC:SIM:1'
            elif cmd == 'READ:SYS:CAT':
                reply = 'STAT:SYS:CAT:DEV:DB8.T1:TEMP:DEV:DB3.H1:HTR:DEV:DB5.P1:PRES:DEV:GRPZ:PSU'
            elif cmd.startswith('SET:'):
                reply = 'STAT:' + cmd + ':VALID'
            else:
                value = ''
                if cmd.endswith(':NICK'): value = cmd.split(':')[2]
                elif cmd.endswith(':SIG:TEMP'): value = '-1.2E-3K'
                elif cmd.endswith(':SIG:POWR'): value = '2.5W'
                elif cmd.endswith(':SIG:PRES'): value = '9.0mB'
                elif cmd.endswith(':ENAB'): value = 'OFF'
                elif cmd.endswith(':SIG:SWHT'): value = 'OFF'
                elif cmd.endswith(':SIG:CURR'): value = '0.0A'
                elif cmd.endswith(':SIG:RFLD'): value = '0.0T/m'
                elif cmd.endswith(':SIG:FLD'): value = '0.0T'
                elif cmd.endswith(':SIG:PFLD'): value = '3.0T'
                elif cmd.endswith(':ACTN'): value = 'HOLD'
                elif cmd.endswith(':STAT'): value = '40000000'
                if self.server.bad_once:
                    self.server.bad_once = False
                    value = 'INVALID'
                reply = 'STAT:' + cmd[5:] + ':' + value
            try:
                self.wfile.write((reply+'\n').encode());self.wfile.flush()
            except OSError:
                return

@pytest.fixture
def simulator():
    sim = Simulator()
    yield sim
    sim.close()

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0));return sock.getsockname()[1]

def wait_until(fn, seconds=5):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if fn():return
        time.sleep(.02)
    raise AssertionError('Condition not reached')

@pytest.mark.parametrize('payload,value', [('1.2E-3K',.0012),('-1T',-1),('+3.0mB',3),('.5K',.5)])
def test_numeric(payload,value):
    assert numeric('STAT:DEV:DB5.P1:PRES:SIG:PRES:'+payload)==value

@pytest.mark.parametrize('payload',['INVALID','NaN','1.2.3K','','infK','1eK'])
def test_invalid_numeric(payload):
    with pytest.raises(ProtocolError):numeric('STAT:DEV:DB5.P1:PRES:SIG:PRES:'+payload)

def test_units_and_response_matching():
    with pytest.raises(ProtocolError):numeric('STAT:1.2V','K')
    with pytest.raises(ProtocolError):validate('READ:SYS:CAT','STAT:SYS:ALRM:')
    with pytest.raises(ProtocolError):validate('SET:X:1','STAT:X:1:INVALID')
    assert validate('SET:X:1','STAT:X:1:VALID')

def test_reconnect_does_not_consume_late_reply(simulator):
    t=Transport('127.0.0.1',simulator.server_address[1],.08)
    simulator.delay_once=True
    with pytest.raises(TimeoutError):t.query('*IDN?')
    assert t.sock is None
    assert t.query('READ:SYS:ALRM')=='STAT:SYS:ALRM:'
    t.close()

def test_discovery_and_persistent_state():
    catalog='STAT:SYS:CAT:DEV:DB7.T1:TEMP:DEV:DB8.T1:TEMP:DEV:MB1.T1:TEMP:DEV:GRPZ:PSU'
    channels={c.key:c.as_dict() for c in inventory('ips',catalog)}
    assert sum(c['category']=='temperature' for c in channels.values())==3
    samples={}
    for key,ch in channels.items():
        value={'switch_heater':'OFF','persistent_field':3,'supply_field':0,'magnet_action':'HOLD'}.get(ch['category'])
        samples[key]={'value':value,'quality':'ok','time':100}
    state=magnet_state(channels,samples,100)['GRPZ']
    assert state['field']==3 and state['supply_field']==0
    assert magnet_state(channels,samples,110)['GRPZ']['field'] is None

def test_archive_summary_and_backup(tmp_path):
    archive=Archive(tmp_path/'data',{},1,tmp_path/'backup')
    stamp=time.time()-3
    stamp=int(stamp)+.1
    archive.sample('temp',1.,'ok',stamp)
    archive.sample('temp',3.,'ok',stamp+.1)
    archive.sample('temp',100.,'sensor_alarm',stamp+.2)
    archive.start()
    wait_until(lambda: archive.health['last_commit'])
    archive.stop_event.set();archive.join(3)
    path=next((tmp_path/'data').rglob('*.sqlite'))
    with sqlite3.connect(path) as db:
        row=db.execute('SELECT last,min,max,mean,valid,total FROM summaries').fetchone()
        assert row==(3.,1.,3.,2.,2,3)
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert list((tmp_path/'backup').glob('*.sqlite'))

def test_service_multiple_clients_and_recovery(simulator,tmp_path):
    api,proxy=free_port(),free_port()
    config={'data_dir':str(tmp_path/'data'),'save_interval':1,'api_port':api,
            'instruments':{'itc':{'host':'127.0.0.1','port':simulator.server_address[1],
                                  'proxy_port':proxy,'poll_interval':.15,'timeout':.1}}}
    service=Service(config)
    service.start()
    try:
        wait_until(lambda:bool(service.state.samples))
        def client(index):
            t=Transport('127.0.0.1',proxy,3)
            try:
                for _ in range(5):
                    assert t.query('READ:SYS:ALRM')=='STAT:SYS:ALRM:'
                return True
            finally:t.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            assert all(pool.map(client,range(4)))
        assert not any(cmd.startswith('SET:') for cmd in simulator.commands)
        t=Transport('127.0.0.1',proxy,3)
        assert t.query('SET:DEV:DB8.T1:TEMP:LOOP:TSET:4').endswith(':VALID')
        t.close()
        simulator.drop_once=True
        wait_until(lambda:not service.workers['itc'].connected)
        wait_until(lambda:service.workers['itc'].connected)
        with urlopen(f'http://127.0.0.1:{api}/state') as response:
            state=json.load(response)
        assert state['instruments']['itc']['connected']
        assert state['samples']
    finally:service.close()
    assert not service.workers['itc'].is_alive()
    assert not service.archive.is_alive()

def test_storage_failure_is_reported_and_recovers(tmp_path):
    blocker=tmp_path/'blocked'
    blocker.write_text('not a directory')
    archive=Archive(blocker,{},1)
    archive.start()
    try:
        archive.event('test','event survives recovery')
        wait_until(lambda:not archive.health['ok'])
        archive.directory=tmp_path/'recovered'
        wait_until(lambda:archive.health['ok'])
    finally:
        archive.stop_event.set();archive.join(3)
    with sqlite3.connect(next((tmp_path/'recovered').rglob('*.sqlite'))) as db:
        assert db.execute("SELECT count(*) FROM events WHERE kind='test'").fetchone()[0]==1


def test_documented_set_acknowledgements():
    command='SET:DEV:DB8.T1:TEMP:LOOP:TSET:4'
    assert validate(command,'STAT:'+command+':VALID')
    assert validate(command,'STAT:'+command)
    with pytest.raises(ProtocolError):validate(command,'STAT:'+command+':INVALID')


def test_month_rotation_and_recent_context(tmp_path):
    from datetime import datetime, timezone
    from vti_control.history import recent
    a=Archive(tmp_path,{})
    october=datetime(2026,10,31,23,59,50,tzinfo=timezone.utc).timestamp()
    november=datetime(2026,11,1,0,0,0,tzinfo=timezone.utc).timestamp()
    try:
        a.persist([],[(october,october+9,'t',1,1,1,1,10,10),
                      (november,november+9,'t',2,2,2,2,10,10)])
    finally:
        if a.db:a.db.close()
    assert len(list(tmp_path.rglob('*.sqlite')))==2
    for p in tmp_path.rglob('*.sqlite'):
        with sqlite3.connect(p) as db:assert db.execute('SELECT count(*) FROM summaries').fetchone()[0]==1

def test_bounded_archive_queue_reports_drops(tmp_path):
    archive=Archive(tmp_path,{})
    for index in range(12005):archive.sample('t',float(index),'ok',time.time())
    assert len(archive.pending)==12000
    assert archive.health['dropped_records']==5


def test_duplicate_service_is_rejected(tmp_path):
    config={'data_dir':str(tmp_path),'api_port':free_port(),'instruments':{}}
    service=Service(config)
    try:
        with pytest.raises(OSError):Service(config)
    finally:
        for server in service.servers:server.server_close()

def test_sensor_not_trusted_without_alarm_channel(simulator,tmp_path):
    from vti_control.worker import InstrumentWorker
    from vti_control.service import State
    from vti_control.model import Channel
    state=State();archive=Archive(tmp_path,{})
    worker=InstrumentWorker('itc',{'host':'127.0.0.1','port':simulator.server_address[1]},state,archive,threading.Event())
    ch=Channel('t','itc','DB8.T1','Probe','READ:DEV:DB8.T1:TEMP:SIG:TEMP','K','temperature')
    try:
        worker.poll(ch)
        assert state.samples['t']['quality']=='alarm_unknown'
    finally:worker.transport.close()
