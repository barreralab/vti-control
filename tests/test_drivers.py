"""Exercise the separate driver checkout against simulated TCP instruments."""
import importlib.util
from pathlib import Path
import sys
import types
import concurrent.futures
import pytest
import os
pytest.importorskip("qcodes")
from test_system import Simulator, free_port, wait_until
from vti_control.service import Service

DRIVERS = Path(r'D:\VTI-control\BarreraLabDrivers\src\barreralabdrivers\drivers')
package = types.ModuleType('mercury_test_drivers')
package.__path__ = [str(DRIVERS)]
sys.modules['mercury_test_drivers'] = package

def load(filename):
    name='mercury_test_drivers.'+filename
    spec=importlib.util.spec_from_file_location(name,DRIVERS/(filename+'.py'))
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

ITC=load('OxfordMercuryITC').MercuryiTC
IPS=load('OxfordMercuryIPS').MercuryiPS

@pytest.mark.parametrize('klass',[ITC,IPS])
def test_qcodes_connect_has_no_writes_and_validates_queries(klass):
    sim=Simulator()
    instrument=None
    try:
        instrument=klass('test_mercury',f'TCPIP::127.0.0.1::{sim.server_address[1]}::SOCKET',visalib='@py',timeout=.3)
        assert instrument.visa_handle.timeout==300
        assert not any(c.startswith('SET:') for c in sim.commands)
        param=instrument.probe.temp if klass is ITC else instrument.mag.temp
        assert param()==-.0012
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            assert all(v==-.0012 for v in pool.map(lambda _:param(),range(8)))
        sim.bad_once=True
        with pytest.raises(ValueError):param()
        assert param()==-.0012
        if klass is ITC:
            instrument.configure_manual_needle_valve()
            assert sum(c.startswith('SET:') for c in sim.commands)==3
            assert isinstance(instrument.vti.pset.get_parser('STAT:DEV:DB5.P1:PRES:LOOP:PSET:3mB'),float)
    finally:
        if instrument:instrument.close()
        sim.close()

def test_qcodes_through_local_service(tmp_path):
    sim=Simulator();port=free_port()
    service=Service({'data_dir':str(tmp_path),'api_port':free_port(),'save_interval':1,
                     'instruments':{'itc':{'host':'127.0.0.1','port':sim.server_address[1],
                                          'proxy_port':port,'poll_interval':.1}}})
    instrument=None
    service.start()
    try:
        wait_until(lambda:service.workers['itc'].connected)
        instrument=ITC('proxied_itc',f'TCPIP::127.0.0.1::{port}::SOCKET',visalib='@py')
        assert instrument.probe.temp()==-.0012
        instrument.probe.tset(4)
        assert any(c.endswith(':TSET:4') or c.endswith(':TSET:4.0') for c in sim.commands)
        assert service.workers['itc'].connected
    finally:
        if instrument:instrument.close()
        service.close();sim.close()
