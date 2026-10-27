"""Dark, responsive live plots with channel controls and timestamped inspection."""
import argparse
from collections import deque
import html
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen
os.environ.setdefault('PYQTGRAPH_QT_LIB','PySide6')
from PySide6 import QtCore, QtWidgets, QtGui
import numpy as np
import pyqtgraph as pg
from .theme import COLORS, CURVE_COLORS, apply_theme
from .plotting import ReadableAxis, nearest_sample

PLOT_GROUPS = [('temperature','Thermometers','K'),('pressure','Pressure','mbar'),
               ('field','Magnetic field','T')]

def plot_group(channel):
    category=channel['category']
    return 'field' if category in ('supply_field','persistent_field') else category

def channel_name(ch):
    category=ch['category']
    if category=='temperature':
        return {('ips','DB7.T1'):'Pulse tube PT2',('ips','DB8.T1'):'Pulse tube PT1',
                ('ips','MB1.T1'):'Magnet',('itc','DB8.T1'):'Probe',('itc','MB1.T1'):'VTI'}.get((ch['instrument'],ch['uid']),ch['name'])
    return {'pressure':'VTI pressure','supply_field':'Supply field',
            'persistent_field':'Persistent register'}.get(category,ch['name'])

def format_value(value,unit=None):
    if value is None:
        return '--'
    if isinstance(value,(float,int)):
        return f'{value:.6g}' + (' '+('mbar' if unit=='mB' else unit) if unit else '')
    return str(value) if str(value) else 'None'

class Fetcher(QtCore.QThread):
    snapshot=QtCore.Signal(dict)
    failed=QtCore.Signal(str)
    def __init__(self,url):
        super().__init__()
        self.url=url
    def run(self):
        first=True
        while not self.isInterruptionRequested():
            try:
                target=self.url.rsplit('/',1)[0]+'/recent' if first else self.url
                with urlopen(target,timeout=2) as response:
                    self.snapshot.emit(json.load(response))
                first=False
            except Exception as exc:
                self.failed.emit(str(exc))
            for _ in range(10):
                if self.isInterruptionRequested():return
                self.msleep(100)

class Window(QtWidgets.QMainWindow):
    def __init__(self,url,start_fetcher=True,settings_path=None):
        super().__init__()
        self.setWindowTitle('VTI Control | Cryostat monitor')
        self.resize(1480,940)
        self.setMinimumSize(1050,720)
        settings_path=Path(settings_path or r'D:\VTI-control\config\gui.ini')
        settings_path.parent.mkdir(parents=True,exist_ok=True)
        self.settings=QtCore.QSettings(str(settings_path),QtCore.QSettings.Format.IniFormat)
        self.buffers,self.arrays,self.curves,self.plots,self.last={},{},{},{},{}
        self.channels,self.channel_items,self.channel_rows,self.colors={},{},{},{}
        self.lines,self.legends,self.groups={},{},{}
        self.follow=True
        self.closing=False
        self.fetcher=None
        self.hover_context=None
        self.hover_values={}
        self.last_scene_position=None
        root=QtWidgets.QWidget();root.setObjectName('root')
        self.setCentralWidget(root)
        layout=QtWidgets.QVBoxLayout(root);layout.setContentsMargins(20,16,20,12);layout.setSpacing(12)
        header=QtWidgets.QHBoxLayout()
        titles=QtWidgets.QVBoxLayout();titles.setSpacing(2)
        title=QtWidgets.QLabel('VTI Control');title.setObjectName('title');titles.addWidget(title)
        subtitle=QtWidgets.QLabel('LIVE CRYOSTAT MONITOR');subtitle.setObjectName('subtitle');titles.addWidget(subtitle)
        header.addLayout(titles);header.addStretch()
        self.health=QtWidgets.QLabel('CONNECTING TO LOCAL SERVICE');header.addWidget(self.health)
        manual=QtWidgets.QPushButton('User manual');manual.clicked.connect(self.open_manual);header.addWidget(manual)
        layout.addLayout(header)
        toolbar=QtWidgets.QHBoxLayout();toolbar.setSpacing(10)
        hint=QtWidgets.QLabel('Drag to pan  /  Scroll to zoom  /  Hover to inspect');hint.setObjectName('subtitle')
        toolbar.addWidget(hint,1)
        self.window_size=QtWidgets.QComboBox()
        for label,seconds in [('5 minutes',300),('30 minutes',1800),('2 hours',7200),('24 hours',86400)]:
            self.window_size.addItem(label,seconds)
        self.window_size.setCurrentIndex(int(self.settings.value('window_index',0)))
        self.window_size.setToolTip('Time window used when Follow latest is enabled')
        toolbar.addWidget(self.window_size)
        self.follow_button=QtWidgets.QPushButton('Follow latest');self.follow_button.setCheckable(True);self.follow_button.setChecked(True)
        self.follow_button.setToolTip('Keep the newest readings at the right edge; dragging pauses following')
        self.follow_button.toggled.connect(self.set_follow);toolbar.addWidget(self.follow_button)
        reset=QtWidgets.QPushButton('Reset view');reset.clicked.connect(self.reset);toolbar.addWidget(reset)
        self.log_t=QtWidgets.QCheckBox('Log temperature');self.log_t.setToolTip('Logarithmic temperature axis; hover values remain in kelvin')
        toolbar.addWidget(self.log_t)
        layout.addLayout(toolbar)
        self.split=QtWidgets.QSplitter();layout.addWidget(self.split,1)
        self.graphics=pg.GraphicsLayoutWidget();self.graphics.setBackground(COLORS['plot'])
        self.graphics.setMouseTracking(True);self.graphics.viewport().setMouseTracking(True)
        self.graphics.viewport().installEventFilter(self)
        self.split.addWidget(self.graphics)
        sidebar=QtWidgets.QWidget();sidebar.setMinimumWidth(360)
        side=QtWidgets.QVBoxLayout(sidebar);side.setContentsMargins(0,0,0,0);side.setSpacing(10)
        card,body=self.card('AT CURSOR')
        self.cursor_heading=QtWidgets.QLabel('Inspect a reading');self.cursor_heading.setStyleSheet('font-size: 14px; font-weight: 600;')
        body.addWidget(self.cursor_heading)
        self.cursor_time=QtWidgets.QLabel('Move over a plot or its time axis');self.cursor_time.setObjectName('subtitle');body.addWidget(self.cursor_time)
        self.cursor_values=QtWidgets.QLabel('A dotted guide marks the same time on all plots.');self.cursor_values.setWordWrap(True)
        self.cursor_values.setMinimumHeight(155);body.addWidget(self.cursor_values)
        side.addWidget(card)
        tabs=QtWidgets.QTabWidget();side.addWidget(tabs,1)
        self.tree=QtWidgets.QTreeWidget();self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(['Plot channels','Latest','Status'])
        self.tree.setRootIsDecorated(True);self.tree.setIndentation(14)
        self.tree.header().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1,100);self.tree.setColumnWidth(2,90)
        self.tree.setMinimumHeight(200)
        for category,label,_ in PLOT_GROUPS:
            group=QtWidgets.QTreeWidgetItem(self.tree,[label])
            group.setFlags(group.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsAutoTristate)
            group.setExpanded(True);self.groups[category]=group
        self.tree.itemChanged.connect(self.channel_changed)
        tabs.addTab(self.tree,'Plot channels')
        self.table=QtWidgets.QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['System channel','Current','Quality'])
        self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1,105);self.table.setColumnWidth(2,120);self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False);self.table.setAlternatingRowColors(True)
        tabs.addTab(self.table,'System status')
        card,body=self.card('MAGNET')
        self.magnet=QtWidgets.QLabel('Waiting for controller state');self.magnet.setWordWrap(True);body.addWidget(self.magnet)
        side.addWidget(card)
        self.alarm_card,body=self.card('ATTENTION')
        self.alarms=QtWidgets.QLabel('');self.alarms.setWordWrap(True);self.alarms.setStyleSheet('color: '+COLORS['warning'])
        body.addWidget(self.alarms);self.alarm_card.hide();side.addWidget(self.alarm_card)
        foot=QtWidgets.QLabel('Channel visibility affects plots only. Logging continues.');foot.setObjectName('subtitle');foot.setWordWrap(True);side.addWidget(foot)
        self.split.addWidget(sidebar);self.split.setSizes([970,430])
        previous=None
        for row,(category,title,unit) in enumerate(PLOT_GROUPS):
            left=ReadableAxis('left');left.setWidth(88);left.enableAutoSIPrefix(False)
            left.setStyle(tickFont=QtGui.QFont('Segoe UI',9),tickTextOffset=9,hideOverlappingLabels=True,autoExpandTextSpace=False)
            bottom=pg.DateAxisItem(orientation='bottom')
            bottom.setStyle(tickFont=QtGui.QFont('Segoe UI',9),tickTextOffset=8,hideOverlappingLabels=True,showValues=category=='field')
            plot=self.graphics.addPlot(row=row,col=0,axisItems={'left':left,'bottom':bottom})
            plot.setTitle(title,color=COLORS['text'],size='11pt')
            plot.setLabel('left',unit,color=COLORS['muted'])
            plot.showGrid(x=True,y=True,alpha=.12)
            plot.setClipToView(True)
            self.legends[category]=plot.addLegend(offset=(12,8),colCount=3,labelTextSize='9pt',labelTextColor=COLORS['text'],
                brush=pg.mkBrush(19,30,48,220),pen=pg.mkPen(COLORS['border']))
            plot.getViewBox().sigRangeChangedManually.connect(self.manual_navigation)
            if previous is not None:plot.setXLink(previous)
            previous=plot
            self.plots[category]=plot
            line=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen('#aec3dc',width=1,style=QtCore.Qt.PenStyle.DotLine))
            plot.addItem(line,ignoreBounds=True);line.setZValue(100);line.hide();self.lines[category]=line
        self.plots['field'].setLabel('bottom','Time (PC local)',color=COLORS['muted'])
        self.graphics.scene().sigMouseMoved.connect(self.mouse_moved)
        self.log_t.toggled.connect(lambda enabled:self.plots['temperature'].setLogMode(y=enabled))
        self.log_t.setChecked(self.settings.value('log_temperature',True,type=bool))
        if self.settings.contains('geometry'):self.restoreGeometry(self.settings.value('geometry'))
        if start_fetcher:
            self.fetcher=Fetcher(url);self.fetcher.snapshot.connect(self.update_snapshot)
            self.fetcher.failed.connect(self.connection_failed);self.fetcher.start()

    @staticmethod
    def card(title):
        frame=QtWidgets.QFrame();frame.setObjectName('card')
        body=QtWidgets.QVBoxLayout(frame);body.setContentsMargins(14,11,14,12);body.setSpacing(7)
        label=QtWidgets.QLabel(title);label.setObjectName('section');body.addWidget(label)
        return frame,body

    def open_manual(self):
        path=Path(r'D:\VTI-control\USER_MANUAL.html')
        if not path.exists():path=Path(__file__).resolve().parents[2]/'USER_MANUAL.html'
        if path.exists():QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        else:QtWidgets.QMessageBox.information(self,'User manual','See USER_MANUAL.md in the VTI-logging project.')

    def set_follow(self,enabled):self.follow=enabled
    def manual_navigation(self,*_):self.follow_button.setChecked(False)
    def reset(self):
        for plot in self.plots.values():plot.enableAutoRange(axis='y')
        self.follow_button.setChecked(True)

    def channel_changed(self,item,column):
        key=item.data(0,QtCore.Qt.ItemDataRole.UserRole)
        if column!=0 or key not in self.curves:return
        visible=item.checkState(0)==QtCore.Qt.CheckState.Checked
        self.curves[key].setVisible(visible)
        legend=self.legends[plot_group(self.channels[key])]
        legend.removeItem(self.curves[key])
        if visible:legend.addItem(self.curves[key],channel_name(self.channels[key]))
        self.settings.setValue('channels/'+key,visible)
        if self.hover_context:self.inspect_at(*self.hover_context)

    def eventFilter(self,watched,event):
        if watched is self.graphics.viewport() and event.type()==QtCore.QEvent.Type.Leave:
            self.clear_hover()
        return super().eventFilter(watched,event)

    def clear_hover(self):
        self.hover_context=None;self.hover_values={};self.last_scene_position=None
        for line in self.lines.values():line.hide()
        self.cursor_heading.setText('Inspect a reading')
        self.cursor_time.setText('Move over a plot or its time axis')
        self.cursor_values.setText('A dotted guide marks the same time on all plots.')

    def mouse_moved(self,position):
        for category,plot in self.plots.items():
            bounds=plot.getViewBox().sceneBoundingRect()
            if plot.sceneBoundingRect().contains(position) and bounds.left()<=position.x()<=bounds.right():
                self.last_scene_position=QtCore.QPointF(position)
                stamp=plot.getViewBox().mapSceneToView(position).x()
                self.inspect_at(category,stamp)
                return
        self.clear_hover()

    def inspect_at(self,category,stamp):
        self.hover_context=(category,stamp);self.hover_values={}
        for line in self.lines.values():line.setPos(stamp);line.show()
        self.cursor_heading.setText(dict((key,title) for key,title,_ in PLOT_GROUPS)[category])
        self.cursor_time.setText(time.strftime('%a %d %b  |  %H:%M:%S',time.localtime(stamp)))
        rows=[]
        for key,curve in self.curves.items():
            ch=self.channels[key]
            if plot_group(ch)!=category or not curve.isVisible():continue
            sample=nearest_sample(self.arrays.get(key),stamp)
            self.hover_values[key]=sample
            value='No valid reading' if sample is None else format_value(sample[1],ch['unit'])
            detail='' if sample is None else time.strftime('%H:%M:%S',time.localtime(sample[0]))+f' ({sample[0]-stamp:+.1f}s)'
            rows.append(f'<tr><td style="color:{self.colors[key]};padding:3px 8px 3px 0">{html.escape(channel_name(ch))}</td>'
                        f'<td align="right"><b>{html.escape(value)}</b><br><span style="color:{COLORS["muted"]};font-size:10px">{detail}</span></td></tr>')
        self.cursor_values.setText('<table width="100%">'+''.join(rows)+'</table>' if rows else 'No channels selected for this plot.')
        self.cursor_values.setToolTip('Nearest recorded sample, not interpolation. Each row shows its actual sample time and offset from the cursor.')

    def connection_failed(self,error):
        if self.closing:return
        self.health.setText('SERVICE OFFLINE | displayed values are stale')
        self.health.setStyleSheet('color: '+COLORS['warning'])
        self.alarms.setText(error);self.alarm_card.show()
        self.magnet.setText('UNKNOWN | acquisition service offline')
        for row in range(self.table.rowCount()):self.table.item(row,2).setText('STALE')
        for item in self.channel_items.values():item.setText(2,'STALE')

    def add_curve(self,key,ch,history):
        category=plot_group(ch)
        fixed={('ips','DB7.T1'):'#ffc47a',('ips','DB8.T1'):'#ae9bff',('ips','MB1.T1'):'#70d9b0',
               ('itc','DB8.T1'):'#e99ac8',('itc','MB1.T1'):'#77b9ff'}
        color=fixed.get((ch['instrument'],ch['uid']),CURVE_COLORS[len(self.curves)%len(CURVE_COLORS)])
        self.colors[key]=color
        curve=self.plots[category].plot(name=channel_name(ch),pen=pg.mkPen(color,width=1.8),connect='finite')
        curve.setDownsampling(auto=True,method='peak');curve.setClipToView(True)
        self.curves[key]=curve;self.buffers[key]=deque(maxlen=86400)
        self.buffers[key].extend((t,v if v is not None else math.nan) for t,v in history.get(key,[]))
        item=QtWidgets.QTreeWidgetItem([channel_name(ch),'--','Waiting'])
        item.setData(0,QtCore.Qt.ItemDataRole.UserRole,key)
        item.setToolTip(0,f"{ch['instrument'].upper()} | {ch['uid']} | {ch['name']}\n{key}")
        item.setForeground(0,QtGui.QBrush(QtGui.QColor(color)))
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        visible=self.settings.value('channels/'+key,True,type=bool)
        self.tree.blockSignals(True)
        self.groups[category].addChild(item)
        item.setCheckState(0,QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.channel_items[key]=item
        curve.setVisible(visible)
        if not visible:self.legends[category].removeItem(curve)

    def update_snapshot(self,state):
        if self.closing:return
        now,inst,storage=state['time'],state['instruments'],state['storage']
        healthy=bool(inst) and all(s.get('connected') for s in inst.values()) and storage.get('ok',False)
        self.health.setText(' | '.join(f"{name.upper()} {'connected' if s.get('connected') else 'OFFLINE'}" for name,s in sorted(inst.items()))+
                            f" | Storage {'OK' if storage.get('ok') else 'ERROR'}")
        self.health.setStyleSheet('color: '+(COLORS['good'] if healthy else COLORS['warning']))
        messages=[]
        if state.get('history_error'):messages.append('Recent context: '+state['history_error'])
        if storage.get('error'):messages.append('Storage: '+storage['error'])
        if storage.get('dropped_records'):messages.append(f"Dropped archive records: {storage['dropped_records']}")
        history=state.get('history',{})
        self.channels.update(state['channels'])
        for key,ch in state['channels'].items():
            sample=state['samples'].get(key)
            if not sample:continue
            value,quality=sample.get('value'),sample.get('quality')
            age=max(0,now-sample.get('time',now))
            quality_text=quality.replace('_',' ') if quality else 'unknown'
            quality_color=COLORS['muted'] if quality=='ok' else COLORS['warning']
            if key not in self.channel_rows:
                row=self.table.rowCount();self.table.insertRow(row);self.channel_rows[key]=row
                for col in range(3):self.table.setItem(row,col,QtWidgets.QTableWidgetItem())
                self.table.item(row,0).setText(ch['instrument'].upper()+' '+ch['name'])
                self.table.item(row,0).setToolTip(key)
            row=self.channel_rows[key]
            self.table.item(row,1).setText(format_value(value,ch['unit']))
            self.table.item(row,2).setText(f'{quality_text} | {age:.0f}s')
            self.table.item(row,2).setForeground(QtGui.QBrush(QtGui.QColor(quality_color)))
            self.table.item(row,2).setToolTip(sample.get('error',''))
            if ch['category']=='alarms' and value:messages.append(ch['instrument'].upper()+': '+str(value).replace('\t',' '))
            if plot_group(ch) not in self.plots:continue
            if key not in self.curves:self.add_curve(key,ch,history)
            item=self.channel_items[key]
            item.setText(1,format_value(value,ch['unit']))
            item.setText(2,'OK' if quality=='ok' else quality_text)
            item.setForeground(2,QtGui.QBrush(QtGui.QColor(quality_color)))
            item.setToolTip(2,f'{quality_text} | age {age:.1f}s\n'+sample.get('error',''))
            token=(sample.get('time'),quality)
            if token!=self.last.get(key):
                self.last[key]=token
                good=quality=='ok' and isinstance(value,(float,int))
                stamp=sample.get('time',now) if good else now
                if self.buffers[key] and stamp < self.buffers[key][-1][0]:self.buffers[key].clear()
                self.buffers[key].append((stamp,value if good else math.nan))
                self.arrays[key]=np.asarray(self.buffers[key])
                self.curves[key].setData(self.arrays[key][:,0],self.arrays[key][:,1])
        self.alarms.setText('\n'.join(messages));self.alarm_card.setVisible(bool(messages))
        text=[]
        for group,m in state.get('magnet',{}).items():
            text.append(f"{group} | {m['mode']}\nRegister: {format_value(m['field'],'T')}  /  Supply: {format_value(m['supply_field'],'T')}\nSwitch heater {m['switch_heater']}  |  {m['action']}")
        self.magnet.setText('\n'.join(text) or 'Waiting for controller state')
        if self.follow:self.plots['temperature'].setXRange(now-self.window_size.currentData(),now+1,padding=0)
        if self.last_scene_position is not None:self.mouse_moved(self.last_scene_position)
        elif self.hover_context:self.inspect_at(*self.hover_context)

    def closeEvent(self,event):
        if self.closing:
            event.accept();return
        self.closing=True
        self.graphics.viewport().removeEventFilter(self)
        self.graphics.scene().sigMouseMoved.disconnect(self.mouse_moved)
        self.settings.setValue('geometry',self.saveGeometry())
        self.settings.setValue('window_index',self.window_size.currentIndex())
        self.settings.setValue('log_temperature',self.log_t.isChecked())
        self.settings.sync()
        if self.fetcher:
            self.fetcher.requestInterruption();self.fetcher.wait(3000)
        event.accept()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:17600/state')
    parser.add_argument('--smoke-test',type=float)
    parser.add_argument('--screenshot')
    parser.add_argument('--inspect-plot',choices=['temperature','pressure','field'])
    args=parser.parse_args()
    app=pg.mkQApp('VTI Control');apply_theme(app)
    window=Window(args.url);window.show()
    if args.smoke_test:
        def finish():
            if args.inspect_plot and window.arrays:
                candidates=[data[-1,0] for key,data in window.arrays.items() if len(data) and plot_group(window.channels[key])==args.inspect_plot]
                if candidates:window.inspect_at(args.inspect_plot,min(candidates)-1)
            if args.screenshot:window.grab().save(args.screenshot)
            window.close()
        QtCore.QTimer.singleShot(int(args.smoke_test*1000),finish)
    result=app.exec()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)
    sys.exit(result)

if __name__=='__main__':main()
