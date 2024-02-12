import os
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor
from mediacatalogue.qt import QtWidgets, QtCore, QtGui
from mediacatalogue.image import FileObject, ImageLoader
from mediacatalogue.imageviewer import ImageViewerWidget

default_item_spacing = 5
default_item_size = (285, 150)
_thread_pool_executor = ThreadPoolExecutor()


def _process_item(item):
    item.refresh()


class ThumbnailItem(QtGui.QStandardItem):
    def __init__(self, image_path):
        super().__init__()
        self.thumbnail_image = ImageLoader(image_path)
        self.thumbnail_image.image_loaded.connect(
            self.emitDataChanged, QtCore.Qt.QueuedConnection)
        item_background_brush = QtGui.QBrush(QtCore.Qt.Dense6Pattern)
        item_font = QtGui.QFont()
        self.setEditable(False)
        self.setBackground(item_background_brush)
        self.setFont(item_font)

    @property
    def file_path(self):
        return self.thumbnail_image.file_object.filePath()

    def refresh(self):
        self.thumbnail_image.run()
        self.emitDataChanged()

    def data(self, role):
        match role:
            case QtCore.Qt.DecorationRole:
                return self.thumbnail_image.image
            case QtCore.Qt.DisplayRole:
                return self.thumbnail_image.file_object.filePath()
        return QtGui.QStandardItem.data(self, role)

    def type(self):
        return QtGui.QStandardItem.UserType

    def setSizeHint(self, size):  # noqa N802
        self.thumbnail_image.set_scaled_size(size)
        return QtGui.QStandardItem.setSizeHint(self, size)


class ThumbnailItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.always_show_header_text = False
        self.view_edit_mode = False

    def paint(self, painter, option, index):
        option = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(option, index)

        item_background = index.data(QtCore.Qt.BackgroundRole)
        item_image = index.data(QtCore.Qt.DecorationRole)

        state = option.state
        rect = option.rect

        # Item background
        if index.data(QtCore.Qt.BackgroundRole):
            painter.save()
            painter.fillRect(rect, item_background)
            painter.restore()

        # Item image
        if index.data(QtCore.Qt.DecorationRole):
            painter.save()

            if self.view_edit_mode:
                painter.setOpacity(0.35)
                if state & QtWidgets.QStyle.State_Selected:
                    painter.setOpacity(1)

            image_rect = item_image.rect()
            image_size = QtCore.QSize(image_rect.size())
            image_size.scale(rect.size(), QtCore.Qt.KeepAspectRatio)
            image_rect.setSize(image_size)

            image_rect.moveCenter(option.rect.center())

            painter.drawImage(image_rect, item_image)
            painter.restore()

        if self.always_show_header_text or (
                state & QtWidgets.QStyle.State_MouseOver):
            self.paint_header_text(painter, option, index)

    def fit_value(self, rect, value):
        factor = rect.height() / float(value)
        return value * (factor / value)

    def paint_header_text(self, painter, option, index):
        item_text = index.data(QtCore.Qt.DisplayRole)
        item_font = index.data(QtCore.Qt.FontRole)
        header_rect = QtCore.QRect(option.rect)
        header_rect.setHeight(18)

        if index.data(QtCore.Qt.FontRole):
            painter.save()
            painter.setRenderHints(QtGui.QPainter.Antialiasing)
            painter.setOpacity(0.8)
            painter.setBrush(QtCore.Qt.black)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(header_rect, 4, 4)
            painter.restore()

            painter.save()
            painter.setFont(item_font)
            painter.setPen(QtCore.Qt.gray)
            painter.drawText(
                header_rect,
                (QtCore.Qt.AlignCenter | QtCore.Qt.AlignTop),
                os.path.basename(item_text))
            painter.restore()


class ThumbnailItemModel(QtGui.QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)

    def flags(self, index):
        flags = (
            QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsDragEnabled
            | QtCore.Qt.ItemIsDropEnabled)
        return flags

    def supportedDragActions(self):  # noqa N802
        return QtCore.Qt.CopyAction

    def supportedDropActions(self):  # noqa N802
        return QtCore.Qt.CopyAction

    def mimeTypes(self):  # noqa N802
        return ['text/plain', 'application/mediacatalogue', 'text/uri-list']


class ThumbnailItemFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)


class ThumbnailView(QtWidgets.QListView):
    item_clicked = QtCore.Signal(QtGui.QStandardItem)
    view_item = QtCore.Signal(QtGui.QStandardItem)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.set_view_layout('grid')

        self.setSpacing(default_item_spacing)
        self.setIconSize(QtCore.QSize(*default_item_size))
        self.setMouseTracking(True)

        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setItemDelegate(ThumbnailItemDelegate(self))
        self.setUniformItemSizes(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

        self.doubleClicked.connect(
            self.on_double_clicked, QtCore.Qt.AutoConnection)

        self.installEventFilter(self)
        self.viewport().installEventFilter(self)

        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)

    def _update_items_sizehint(self):
        model = self.model()
        if model is None:
            return
        source_model = model.sourceModel()
        for row in range(source_model.rowCount(QtCore.QModelIndex())):
            item = source_model.item(row)
            item.setSizeHint(self.iconSize())

    def _update_all_items(self):
        model = self.model()
        source_model = model.sourceModel()
        for row in range(source_model.rowCount(QtCore.QModelIndex())):
            item = source_model.item(row)
            _thread_pool_executor.submit(_process_item, item)
            QtWidgets.QApplication.processEvents()

    def mousePressEvent(self, event):  # noqa N802
        index = self.model().mapToSource(self.indexAt(event.pos()))
        item = self.model().sourceModel().item(index.row())

        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            if item:
                _thread_pool_executor.submit(_process_item, item)
        if item:
            self.item_clicked.emit(item)

        return QtWidgets.QListView.mousePressEvent(self, event)

    def on_double_clicked(self, index):
        model = self.model()
        index = model.mapToSource(index)
        source_model = model.sourceModel()
        item = source_model.item(index.row())
        self.view_item.emit(item)

    def mouseMoveEvent(self, event):  # noqa N802
        if event.type() != QtCore.QEvent.Type.MouseMove:
            return False
        return QtWidgets.QListView.mouseMoveEvent(self, event)

    def keyReleaseEvent(self, event):  # noqa N802
        if event.key() == QtCore.Qt.Key_O:
            show_header = self.itemDelegate().always_show_header_text
            self.itemDelegate().always_show_header_text = not show_header
            self.repaint()
        elif event.key() == QtCore.Qt.Key_F5:
            self._update_all_items()
        event.ignore()

    def setIconSize(self, size):  # noqa N802
        QtWidgets.QListView.setIconSize(self, size)
        self._update_items_sizehint()

    def on_size_change(self, value):
        self.setIconSize(QtCore.QSize(*default_item_size) * (value / 100))

    def set_view_layout(self, orientation):
        match orientation:
            case 'horizontal':
                self.setFlow(QtWidgets.QListView.TopToBottom)
            case 'grid':
                self.setFlow(QtWidgets.QListView.LeftToRight)
                self.setResizeMode(QtWidgets.QListView.Adjust)

    def set_proxy_filter(self, pattern):
        model = self.model()
        model.setFilterRegExp(pattern)


class ViewControlsWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout()
        self.setup()
        self.setLayout(self.main_layout)

    def setup(self):
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setValue(100)
        self.size_slider.setMinimum(1)
        self.size_slider.setMaximum(300)

        self.spacing_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.spacing_slider.setMinimum(1)
        self.spacing_slider.setMaximum(100)
        self.spacing_slider.setValue(5)

        label_size = QtWidgets.QLabel('size')
        label_spacing = QtWidgets.QLabel('spacing')

        self.main_layout.addWidget(label_size)
        self.main_layout.addWidget(self.size_slider, 0)

        self.main_layout.addWidget(label_spacing)
        self.main_layout.addWidget(self.spacing_slider, 0)
        self.main_layout.addStretch(1)


class SearchInViewControls(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(SearchInViewControls, self).__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout()
        self.main_layout.setSizeConstraint(
            QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        label = QtWidgets.QLabel('filter')
        self.line_edit = QtWidgets.QLineEdit(self)
        self.line_edit.setFixedWidth(300)
        self.main_layout.addWidget(label)
        self.main_layout.addWidget(self.line_edit)
        self.setLayout(self.main_layout)


class ThumbnailsWidget(QtWidgets.QWidget):
    item_added = QtCore.Signal(QtGui.QStandardItem)
    viewer_created = QtCore.Signal(ImageViewerWidget, ThumbnailItemModel)

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.view = ThumbnailView(self)
        self.model = ThumbnailItemModel(self)
        self.proxy_model = ThumbnailItemFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.view.setModel(self.proxy_model)

        self.view_controls = ViewControlsWidget(self)
        self.search_controls = SearchInViewControls(self)

        self.view_controls.size_slider.valueChanged.connect(
            self.view.on_size_change, QtCore.Qt.QueuedConnection)
        self.view_controls.size_slider.sliderReleased.connect(
            self.view._update_all_items, QtCore.Qt.QueuedConnection)
        self.view_controls.spacing_slider.valueChanged.connect(
            self.view.setSpacing, QtCore.Qt.QueuedConnection)
        self.search_controls.line_edit.textChanged.connect(
            self.view.set_proxy_filter)

        self.view.view_item.connect(self.on_thumbnail_double_clicked)

        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.addWidget(self.view)
        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.addWidget(self.view_controls)
        controls_layout.addWidget(self.search_controls)
        self.main_layout.addLayout(controls_layout)

        self.setLayout(self.main_layout)

        self.setSizePolicy(
            QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Expanding)

        self.item_added.connect(
            self.send_item_to_thread_pool, QtCore.Qt.AutoConnection)

    def send_item_to_thread_pool(self, item):
        _thread_pool_executor.submit(_process_item, item)

    def add_collection_item(self, path, collection=None):
        item = ThumbnailItem(path)
        item.collection = collection  # Identifier to get from which
        # collection the item was added and be able to be deleted when
        # collection is unchecked
        item.setSizeHint(self.view.iconSize())
        self.model.appendRow(item)
        self.item_added.emit(item)

    def remove_collection_items(self, item_path=None, collection=None):
        items = _get_items_from_model(self.model)
        for item in items:
            if item.collection == collection:
                self.model.removeRow(item.row())

    def on_thumbnail_double_clicked(self, item):
        if item.thumbnail_image.file_object.is_image:
            viewer = ImageViewerWidget(self)
            viewer.set_image_file_path(
                item.thumbnail_image.file_object.filePath())
            viewer.show()
            self.viewer_created.emit(viewer, self.model)


def _get_items_from_model(model):
    items = []
    for x in range(model.rowCount()):
        for y in range(model.columnCount()):
            index = model.index(x, y)
            items.append(model.item(index.row()))
    return items


def run_standalone(files=None):
    def expand_path(path):
        return os.path.expandvars(os.path.expanduser(path))

    if files is None:
        parser = argparse.ArgumentParser()
        parser.add_argument('files', nargs='+')
        args, _ = parser.parse_known_args()
        files = args.files

    if len(files) == 1 and os.path.isdir(files[0]):
        files_ = [FileObject(os.path.join(files[0], p))
                  for p in os.listdir(expand_path(files[0]))]
    else:
        files_ = [FileObject(expand_path(p)) for p in files]
    images = [f for f in files_ if f.is_image]

    app = QtWidgets.QApplication(sys.argv)
    widget = ThumbnailsWidget()
    for image in images:
        widget.add_collection_item(image)
    widget.show()
    app.exec_()


if __name__ == '__main__':
    run_standalone()
