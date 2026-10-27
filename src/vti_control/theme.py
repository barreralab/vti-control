"""Consistent dark desktop palette with no GPU rendering requirement."""
from PySide6 import QtGui
import pyqtgraph as pg
COLORS = {'background':'#0c1220', 'surface':'#131e30', 'raised':'#1a2940',
          'plot':'#101a2a', 'text':'#e4ecf7', 'muted':'#95a8c2',
          'border':'#293b54', 'accent':'#62c7f7', 'good':'#70d9b0', 'warning':'#ffc47a'}
CURVE_COLORS = ['#70d9b0','#ffc47a','#77b9ff','#e99ac8','#ae9bff','#61d8e0','#f59380','#c0d47e']
def apply_theme(app):
    app.setStyle('Fusion')
    app.setFont(QtGui.QFont('Segoe UI', 10))
    palette = QtGui.QPalette()
    for role, color in [(QtGui.QPalette.Window,COLORS['background']),
                        (QtGui.QPalette.WindowText,COLORS['text']),
                        (QtGui.QPalette.Base,COLORS['surface']),
                        (QtGui.QPalette.AlternateBase,COLORS['raised']),
                        (QtGui.QPalette.Text,COLORS['text']),
                        (QtGui.QPalette.Button,COLORS['raised']),
                        (QtGui.QPalette.ButtonText,COLORS['text']),
                        (QtGui.QPalette.Highlight,'#254f70'),
                        (QtGui.QPalette.HighlightedText,'#ffffff'),
                        (QtGui.QPalette.ToolTipBase,COLORS['raised']),
                        (QtGui.QPalette.ToolTipText,COLORS['text'])]:
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    app.setStyleSheet("""
        QMainWindow, QWidget#root { background: #0c1220; color: #e4ecf7; }
        QFrame#card { background: #131e30; border: 1px solid #293b54; border-radius: 10px; }
        QLabel { background: transparent; border: none; }
        QLabel#title { font-size: 23px; font-weight: 600; color: #eff6ff; }
        QLabel#subtitle { color: #95a8c2; font-size: 11px; }
        QLabel#section { color: #95a8c2; font-size: 10px; font-weight: 600; }
        QPushButton { border: 1px solid #344b68; border-radius: 6px; background: #1a2940;
                      padding: 7px 12px; color: #e4ecf7; }
        QPushButton:hover { border-color: #62c7f7; background: #223850; }
        QPushButton:checked { background: #23577b; border-color: #62c7f7; }
        QComboBox { background: #1a2940; border: 1px solid #344b68; border-radius: 6px;
                    padding: 6px 10px; min-width: 83px; }
        QComboBox QAbstractItemView { background: #1a2940; color: #e4ecf7; selection-background-color: #254f70; }
        QCheckBox { spacing: 7px; padding: 4px; }
        QTreeView, QTableView { background: #131e30; border: none; outline: 0; color: #e4ecf7;
                              alternate-background-color: #162337; selection-background-color: #254f70; }
        QTreeView::item { padding-top: 6px; padding-bottom: 6px; }
        QHeaderView::section { background: #19273b; color: #95a8c2; border: none;
                               border-bottom: 1px solid #293b54; padding: 7px 5px; }
        QTabWidget::pane { border: none; }
        QTabBar::tab { padding: 9px 12px; color: #95a8c2; background: #131e30; border-bottom: 2px solid transparent; }
        QTabBar::tab:selected { color: #e4ecf7; border-bottom: 2px solid #62c7f7; }
        QScrollBar:vertical { background: #131e30; width: 9px; margin: 0; }
        QScrollBar::handle:vertical { background: #3b506a; border-radius: 4px; min-height: 24px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { height: 9px; background: #131e30; }
        QScrollBar::handle:horizontal { background: #3b506a; min-width: 24px; }
        QSplitter::handle { background: #0c1220; width: 8px; }
        QToolTip { color: #e4ecf7; background: #1a2940; border: 1px solid #526982; padding: 6px; }
    """)
    pg.setConfigOptions(antialias=False, background=COLORS['plot'], foreground=COLORS['muted'])
