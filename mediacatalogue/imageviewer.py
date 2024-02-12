import os
from mediacatalogue.qt import QtWidgets, QtCore, QtGui
from mediacatalogue.image import ImageLoader

default_image_viewer_size = (800, 500)


class ImageView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.fit_in_view = True
        self.background_brush = QtGui.QBrush(QtCore.Qt.BDiagPattern)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(self.background_brush)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.setCacheMode(QtWidgets.QGraphicsView.CacheNone)

        self.scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene)

    def wheelEvent(self, event):  # noqa N802
        self.fit_in_view = False
        scale_factor = 1.15
        if event.delta() > 0:
            self.scale(scale_factor, scale_factor)
        else:
            self.scale(1.0 / scale_factor, 1.0 / scale_factor)

    def resizeEvent(self, event):  # noqa N802
        if self.fit_in_view:
            self.fitInView(
                self.scene.itemsBoundingRect(), QtCore.Qt.KeepAspectRatio)
        QtWidgets.QGraphicsView.resizeEvent(self, event)

    def keyPressEvent(self, event):  # noqa N802
        ignore_keys = (
            QtCore.Qt.Key_Right,
            QtCore.Qt.Key_Left,
            QtCore.Qt.Key_Home,
            QtCore.Qt.Key_End,
            QtCore.Qt.Key_PageUp,
            QtCore.Qt.Key_PageDown,
            QtCore.Qt.Key_F,
            QtCore.Qt.Key_H,
            QtCore.Qt.Key_F10,
            QtCore.Qt.Key_F11)
        if event.key() in ignore_keys:
            event.ignore()


class HistoryWidget(QtWidgets.QWidget):
    file_data = QtCore.Qt.UserRole + 1
    file_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.initial_filepath = None

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        self.setFixedWidth(170)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)

        self.history_listwidget = QtWidgets.QListWidget(self)
        self.history_listwidget.currentItemChanged.connect(self.on_item_change)

        label = QtWidgets.QLabel('history')
        self.main_layout.addWidget(label)
        self.main_layout.addWidget(self.history_listwidget)

    def on_item_change(self, item):
        if item is None:
            return
        self.file_changed.emit(item.data(self.file_data))

    def fill(self, files=None):
        files = files or []
        self.history_listwidget.clear()

        for file in files:
            item = QtWidgets.QListWidgetItem(os.path.basename(file))
            item.setData(self.file_data, file)
            self.history_listwidget.addItem(item)

    def set_file_object(self, fileobject):
        self.initial_fileobject = fileobject
        self.initial_filepath = fileobject.filePath()

    def toggle_visibility(self):
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self.history_listwidget.setFocus()


class ImageViewerWidget(QtWidgets.QWidget):
    history_show = QtCore.Signal(object)
    next_image = QtCore.Signal(object)
    previous_image = QtCore.Signal(object)
    first_image = QtCore.Signal(object)
    last_image = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.image_loader = ImageLoader()
        self.image_loader.image_loaded.connect(self.set_pixmap)
        self.resize(QtCore.QSize(*default_image_viewer_size))
        self.setWindowFlags(QtCore.Qt.Window)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.image_pixmap = QtGui.QPixmap()
        self.image_view = ImageView(self)
        self.history_widget = HistoryWidget(self.image_view)
        self.history_widget.setVisible(False)
        self.history_widget.file_changed.connect(
            self.set_history_image_file_path)

        self.image_item = QtWidgets.QGraphicsPixmapItem()
        self.image_item.setPixmap(self.image_pixmap)
        self.image_item.setShapeMode(
            QtWidgets.QGraphicsPixmapItem.BoundingRectShape)
        self.image_item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        self.image_item.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.NoCache)

        self.image_view.scene.addItem(self.image_item)
        self.image_view.fileobject = self.image_loader.file_object

        self.file_entry = QtWidgets.QLineEdit()
        self.file_entry.returnPressed.connect(self.on_update_file_path)

        viewer_main_splitter = QtWidgets.QSplitter()
        viewer_main_splitter.addWidget(self.history_widget)
        viewer_main_splitter.addWidget(self.image_view)

        self.main_layout.addWidget(viewer_main_splitter)
        self.main_layout.addWidget(self.file_entry)
        self.setLayout(self.main_layout)

    @property
    def is_history_mode(self):
        return self.history_widget.isVisible()

    def keyPressEvent(self, event):  # noqa N802
        match event.key():

            # Zoom to 1:1
            case QtCore.Qt.Key_1:
                self.image_view.fit_in_view = False
                self.image_view.resetTransform()
                self.image_view.centerOn(self.image_item)

            # Zoom to Fit view
            case QtCore.Qt.Key_F:
                fit_in_view = self.image_view.fit_in_view
                self.image_view.fit_in_view = not fit_in_view
                if self.image_view.fit_in_view:
                    self.image_view.fitInView(
                        self.image_view.sceneRect(),
                        QtCore.Qt.KeepAspectRatio)

            case QtCore.Qt.Key_F11:
                if not self.isFullScreen():
                    self.showFullScreen()
                else:
                    self.showNormal()

            case QtCore.Qt.Key_Right:
                self.next_image.emit(self)

            case QtCore.Qt.Key_Left:
                self.previous_image.emit(self)

            case QtCore.Qt.Key_Home:
                self.first_image.emit(self)

            case QtCore.Qt.Key_End:
                self.last_image.emit(self)

            # History widget
            case QtCore.Qt.Key_H:
                self.history_widget.toggle_visibility()
                if self.history_widget.isVisible():
                    self.history_show.emit(self)
                if not self.history_widget.isVisible():
                    orig_file = self.history_widget.initial_filepath
                    self.set_image_file_path(orig_file)
                    self.set_image_widget()

            # Frameless
            case QtCore.Qt.Key_F10:
                self.toggle_frameless_mode()

    def closeEvent(self, event):  # noqa N802
        return QtWidgets.QWidget.closeEvent(self, event)

    def showEvent(self, event):  # noqa N802
        QtWidgets.QWidget.showEvent(self, event)
        self.load_image()

    def load_image(self):
        self.image_loader.set_scaled_size(QtCore.QSize())
        self.set_image_widget()

    def set_pixmap(self, image):
        self.image_pixmap = self.image_pixmap.fromImage(image)
        self.image_item.setPixmap(self.image_pixmap)

    def set_history_image_file_path(self, file_path):
        self.image_loader.file_object.setFile(file_path)
        self.set_image_widget()

    def set_image_file_path(self, filepath):
        self.image_loader.file_object.setFile(filepath)
        self.history_widget.set_file_object(self.image_loader.file_object)

    def on_update_file_path(self):
        self.set_image_file_path(self.file_entry.text())
        self.load_image()

    def set_image_widget(self):
        if not self.image_loader.file_object.exists():
            return
        self.setWindowTitle(
            f'ImageViewer - {self.image_loader.file_object.fileName()}')
        self.file_entry.setText(
            os.path.normpath(self.image_loader.file_object.filePath()))
        self.image_loader.run()

    def toggle_frameless_mode(self):
        flags = self.windowFlags()
        if flags & (
                QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.WindowStaysOnTopHint):
            self.file_entry.show()
            self.image_view.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarAsNeeded)
            self.image_view.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarAsNeeded)
        else:
            self.image_view.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarAlwaysOff)
            self.image_view.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarAlwaysOff)
            self.file_entry.hide()
        flags ^= (
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.show()


if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    viewer = ImageViewerWidget()
    viewer.set_image_file_path(os.path.expanduser('~/imagetest.png'))
    viewer.show()
    app.exec_()
