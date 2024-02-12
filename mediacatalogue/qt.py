import os
import importlib

qt_binding = os.environ.get('QT_BINDING', 'PySide6')


def import_module(name):
    return importlib.import_module(f'{qt_binding}.{name}')


QtWidgets = import_module('QtWidgets')
QtCore = import_module('QtCore')
QtGui = import_module('QtGui')

# Compatibility with older version
if qt_binding == 'PySide2':
    QtGui.QAction = QtWidgets.QAction
