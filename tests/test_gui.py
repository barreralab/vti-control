import math
import numpy as np
import pytest
from PySide6 import QtWidgets,QtCore
import pyqtgraph as pg
from vti_control.gui import Window
from vti_control.theme import apply_theme,COLORS
from vti_control.plotting import readable_log_ticks,nearest_sample

@pytest.fixture(scope='module')
def app():
    instance=pg.mkQApp('VTI GUI tests')
    apply_theme(instance)
    return instance

def snapshot(stamp=1700000010):
    channels={}
    samples={}
    history={}
    for key,uid,name,value in [('a','DB7.T1','PT2',3.),('b','DB8.T1','PT1',50.),('c','MB1.T1','Magnet',4.)]:
        channels[key]={'key':key,'instrument':'ips','uid':uid,'name':name,'unit':'K','category':'temperature'}
        samples[key]={'value':value,'quality':'ok','time':stamp}
        history[key]=[[stamp-10,value],[stamp-5,value*2]]
    channels['p']={'key':'p','instrument':'itc','uid':'DB5.P1','name':'Pressure','unit':'mB','category':'pressure'}
    samples['p']={'value':9.,'quality':'ok','time':stamp};history['p']=[[stamp-5,9.]]
    return {'time':stamp,'channels':channels,'samples':samples,'history':history,
            'instruments':{'itc':{'connected':True},'ips':{'connected':True}},
            'storage':{'ok':True},'magnet':{}}

@pytest.fixture
def window(app,tmp_path):
    w=Window('http://unused',start_fetcher=False,settings_path=tmp_path/'gui.ini')
    w.update_snapshot(snapshot());w.show();app.processEvents()
    yield w
    w.close();w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()

@pytest.mark.parametrize('low,high,pixels',[(.5,2.6,230),(math.log10(3.5),math.log10(4.3),200),(-3,4,130),(0,1,70),(.001,.002,300)])
def test_log_labels_are_separated(low,high,pixels):
    ticks=readable_log_ticks(low,high,pixels)
    assert ticks
    assert all(low-1e-9<=t<=high+1e-9 for t in ticks)
    assert all((b-a)*pixels/(high-low)>=34-1e-8 for a,b in zip(ticks,ticks[1:]))

def test_cursor_returns_real_samples_not_interpolated():
    data=np.array([[100.,2.],[105.,math.nan],[110.,4.]])
    assert nearest_sample(data,100)==(100.,2.)
    assert nearest_sample(data,105) is None
    assert nearest_sample(data,80) is None
    assert nearest_sample(data,120) is None

def test_visibility_is_display_only_and_persistent(window,app,tmp_path):
    assert window.curves['a'].opts['pen'].widthF()==pytest.approx(1.8)
    before=len(window.buffers['a'])
    window.channel_items['a'].setCheckState(0,QtCore.Qt.CheckState.Unchecked)
    assert not window.curves['a'].isVisible()
    window.update_snapshot(snapshot(1700000011))
    assert len(window.buffers['a'])==before+1
    window.inspect_at('temperature',1700000005)
    assert 'a' not in window.hover_values
    assert len(window.hover_values)==2
    window.close()
    reopened=Window('http://unused',start_fetcher=False,settings_path=tmp_path/'gui.ini')
    try:
        reopened.update_snapshot(snapshot())
        assert not reopened.curves['a'].isVisible()
        assert reopened.curves['b'].isVisible()
    finally:
        reopened.close();reopened.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)

def test_hover_is_linked_and_uses_kelvin_in_log_mode(window,app):
    assert window.log_t.isChecked()
    window.inspect_at('temperature',1700000005)
    assert window.hover_values['a']==(1700000005.,6.)
    assert '6 K' in window.cursor_values.text()
    assert len(window.hover_values)==3
    assert all(line.isVisible() and line.value()==1700000005 for line in window.lines.values())
    view=window.plots['temperature'].getViewBox()
    position=view.mapViewToScene(QtCore.QPointF(1700000005,math.log10(6.)))
    window.graphics.scene().sigMouseMoved.emit(position)
    assert window.hover_context[0]=='temperature'
    assert window.hover_context[1]==pytest.approx(1700000005)
    QtWidgets.QApplication.sendEvent(window.graphics.viewport(),QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert all(not line.isVisible() for line in window.lines.values())

def test_missing_sample_and_group_toggle(window):
    state=snapshot()
    state['samples']['a']['quality']='sensor_alarm'
    state['history']['a']=[[1700000005,None]]
    window.buffers['a'].clear()
    window.update_snapshot(state)
    window.inspect_at('temperature',1700000010)
    assert window.hover_values['a'] is None
    assert 'No valid reading' in window.cursor_values.text()
    window.groups['temperature'].setCheckState(0,QtCore.Qt.CheckState.Unchecked)
    assert all(not window.curves[key].isVisible() for key in ('a','b','c'))
    window.groups['temperature'].setCheckState(0,QtCore.Qt.CheckState.Checked)
    assert all(window.curves[key].isVisible() for key in ('a','b','c'))

def test_dark_palette_and_manual_pause(window,app):
    assert app.palette().window().color().name()==COLORS['background']
    window.manual_navigation()
    assert not window.follow
    window.reset()
    assert window.follow
