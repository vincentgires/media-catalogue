import os
import sys
import argparse
from typing import Literal
from concurrent.futures import ThreadPoolExecutor
from mediacatalogue.qt import QtWidgets, QtCore, QtGui, shiboken
from mediacatalogue.image import FileObject, ImageLoader
from mediacatalogue.imageviewer import (
    available_image_viewer_widgets, ImageViewerWidget)

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
        self.tags: dict[str, str] = {}

        item_background_brush = QtGui.QBrush(QtCore.Qt.Dense6Pattern)
        item_font = QtGui.QFont()
        self.setEditable(False)
        self.setBackground(item_background_brush)
        self.setFont(item_font)

        self.placeholder = QtGui.QPixmap(*default_item_size)
        self.placeholder.fill(QtGui.QColor('black'))
        self.thumbnail_image.image = self.placeholder
        self.emitDataChanged()

    @property
    def file_path(self):
        return self.thumbnail_image.file_object.filePath()

    def load(self):
        if not shiboken.isValid(self):
            return
        self.thumbnail_image.run()
        self.emitDataChanged()

    def refresh(self):
        self.load()

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

            if isinstance(item_image, QtGui.QPixmap):
                painter.drawPixmap(image_rect, item_image)
            else:
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
        self.active_filters: dict[str, list[str | bool]] = {}
        self.filter_mode: Literal['all', 'any'] = 'all'

    def filterAcceptsRow(self, source_row, source_parent):  # noqa N802
        if not self.active_filters:
            return True  # No active filter: show everything

        index = self.sourceModel().index(source_row, 0, source_parent)
        item = self.sourceModel().itemFromIndex(index)
        tags = item.tags or {}

        matches = []
        for key, filter_values in self.active_filters.items():
            if not isinstance(filter_values, (list, tuple, set)):
                filter_values = [filter_values]
            tag_values = tags.get(key, None)
            if not isinstance(tag_values, (list, tuple, set)):
                tag_values = [tag_values]
            if self.filter_mode == 'all':
                matches.append(all(x in tag_values for x in filter_values))
            else:
                matches.append(any(x in tag_values for x in filter_values))

        return all(matches) if self.filter_mode == 'all' else any(matches)


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


def _set_icon(
        widget: QtWidgets.QPushButton, icon_path: str, label: str | None):
    if os.path.exists(icon_path):
        icon = QtGui.QIcon(icon_path)
        widget.setIcon(icon)
    elif label is not None:
        widget.setText(label)


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
        self.spacing_slider.setMinimum(0)
        self.spacing_slider.setMaximum(100)
        self.spacing_slider.setValue(5)

        label_size = QtWidgets.QLabel('size')
        label_spacing = QtWidgets.QLabel('spacing')

        self.main_layout.addWidget(label_size)
        self.main_layout.addWidget(self.size_slider, 0)

        self.main_layout.addWidget(label_spacing)
        self.main_layout.addWidget(self.spacing_slider, 0)
        self.main_layout.addStretch(1)


class FilterTag(QtWidgets.QFrame):
    removed = QtCore.Signal(object)
    updated = QtCore.Signal()

    def __init__(self, name: str, value: str | bool, parent=None):
        super().__init__(parent)
        self.name = name
        self.value = value
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.filter_btn = QtWidgets.QPushButton()
        _set_icon(
            widget=self.filter_btn,
            icon_path=os.path.expandvars('$ICONS_PATH/edit.svg'),
            label=None)
        self.filter_btn.clicked.connect(self.edit_filter)
        layout.addWidget(self.filter_btn)

        self.remove_btn = QtWidgets.QPushButton()
        _set_icon(
            widget=self.remove_btn,
            icon_path=os.path.expandvars('$ICONS_PATH/multiply.svg'),
            label='x')
        self.remove_btn.clicked.connect(self.on_remove)
        layout.addWidget(self.remove_btn)
        self.setLayout(layout)

        self.set_label()

    def set_label(self):
        label = (
            f'{self.name}:{self.value}'
            if isinstance(self.value, str) else self.name)
        self.filter_btn.setText(label)

    def on_remove(self):
        self.removed.emit(self)

    def edit_filter(self):
        dlg = SetFilterDialog(self)
        dlg.name_edit.setText(self.name)
        dlg.value_edit.setText(
            self.value if isinstance(self.value, str) else '')
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            name, value = dlg.get_data()
            if name and value:
                self.name = name
                self.value = value
                self.set_label()
                self.updated.emit()


class SetFilterDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('add filter')
        self.name_edit = QtWidgets.QLineEdit()
        self.value_edit = QtWidgets.QLineEdit()
        self.ok_btn = QtWidgets.QPushButton('ok')
        self.cancel_btn = QtWidgets.QPushButton('cancel')

        layout = QtWidgets.QFormLayout(self)
        layout.addRow('name', self.name_edit)
        layout.addRow('value', self.value_edit)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addRow(btn_layout)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def get_data(self):
        name, value = self.name_edit.text(), self.value_edit.text()
        if value == '':  # When value is not defined, label only will be used
            value = True  # True is the label only flag
        return name, value


class FiltersBar(QtWidgets.QWidget):
    filters_changed = QtCore.Signal(dict, str)

    def __init__(self):
        super().__init__()
        self.tags = []

        all_radio = QtWidgets.QRadioButton('all')
        any_radio = QtWidgets.QRadioButton('any')
        all_radio.setChecked(True)
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.addButton(all_radio)
        self.mode_group.addButton(any_radio)

        self.add_btn = QtWidgets.QPushButton('filters')
        _set_icon(
            widget=self.add_btn,
            icon_path=os.path.expandvars('$ICONS_PATH/add.svg'),
            label='filters +')

        self.add_btn.clicked.connect(self.add_new_filter)
        self.mode_group.buttonClicked.connect(self.emit_filters)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(*(0,) * 4)
        layout.setSpacing(4)
        layout.addWidget(QtWidgets.QLabel('match mode'))
        layout.addWidget(all_radio)
        layout.addWidget(any_radio)
        layout.addWidget(self.add_btn)

    def add_filter(self, name: str, value: str | bool):
        tag = FilterTag(name, value)
        tag.removed.connect(self.remove_filter)
        tag.updated.connect(self.emit_filters)
        self.tags.append(tag)
        self.layout().insertWidget(self.layout().count() - 1, tag)
        self.emit_filters()

    def remove_filter(self, tag: FilterTag):
        self.tags.remove(tag)
        tag.setParent(None)
        tag.deleteLater()
        self.emit_filters()

    def add_new_filter(self):
        dlg = SetFilterDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            name, value = dlg.get_data()
            if name and value:
                self.add_filter(name, value)

    def emit_filters(self):
        filters: dict[str, list[str]] = {}
        for tag in self.tags:
            filters.setdefault(tag.name, []).append(tag.value)
        selected_button = self.mode_group.checkedButton()
        selected_mode = selected_button.text()
        self.filters_changed.emit(filters, selected_mode)


class SearchInViewControls(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(SearchInViewControls, self).__init__(parent)
        self.main_layout = QtWidgets.QHBoxLayout()
        self.main_layout.setSizeConstraint(
            QtWidgets.QLayout.SizeConstraint.SetFixedSize)
        self.filters = FiltersBar()
        self.main_layout.addWidget(self.filters)
        self.setLayout(self.main_layout)


class PropertyPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel('No selection')
        layout.addWidget(self.label)
        layout.addStretch()

    def set_item(self, item):
        def format_value(v):
            if isinstance(v, (list, tuple, set)):
                return ', '.join(map(str, v))
            return str(v)

        if item.tags is None:
            label = ''
        else:
            lines = [
                f'{k}: {format_value(v)}'
                for k, v in item.tags.items()]
            label = '<pre>' + '\n'.join(lines) + '</pre>'
        self.label.setText(label)


class ThumbnailsWidget(QtWidgets.QWidget):
    item_added = QtCore.Signal(QtGui.QStandardItem)
    viewer_created = QtCore.Signal(ImageViewerWidget, ThumbnailItemModel)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._pending_items = []
        self._is_loading = False

        self.view = ThumbnailView(self)
        self.model = ThumbnailItemModel(self)
        self.proxy_model = ThumbnailItemFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.view.setModel(self.proxy_model)

        self.view_controls = ViewControlsWidget(self)
        self.search_controls = SearchInViewControls(self)

        self.property_panel = PropertyPanel(self)

        self.view_controls.size_slider.valueChanged.connect(
            self.view.on_size_change, QtCore.Qt.QueuedConnection)
        self.view_controls.size_slider.sliderReleased.connect(
            self.view._update_all_items, QtCore.Qt.QueuedConnection)
        self.view_controls.spacing_slider.valueChanged.connect(
            self.view.setSpacing, QtCore.Qt.QueuedConnection)
        self.search_controls.filters.filters_changed.connect(
            self.on_filters_changed)

        self.view.view_item.connect(self.on_thumbnail_double_clicked)
        self.view.item_clicked.connect(self.on_thumbnail_clicked)

        self.set_layout()

    def set_layout(self):
        main_layout = QtWidgets.QVBoxLayout()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(self.property_panel)
        splitter.setSizes([1, 0])  # Hide self.property_panel by default
        main_layout.addWidget(splitter)
        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.addWidget(self.view_controls)
        controls_layout.addWidget(self.search_controls)
        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)

    def add_collection_item(self, path, tags=None, collection_item=None):
        item = ThumbnailItem(path)
        item.tags = tags
        item.collection_item = collection_item  # Identifier to get from which
        # collection the item was added and be able to be deleted when
        # collection is unchecked
        item.setSizeHint(self.view.iconSize())
        self.model.appendRow(item)
        self.item_added.emit(item)

        self._pending_items.append(item)
        if not self._is_loading:
            self._is_loading = True
            self._load_next_item()

    def _load_next_item(self):
        if not self._pending_items:
            self._is_loading = False
            return
        item = self._pending_items.pop(0)
        item.load()
        QtCore.QTimer.singleShot(0, self._load_next_item)

    def remove_collection_items(self, item_path=None, collection_item=None):
        items = _get_items_from_model(self.model)
        for item in items:
            if item.collection_item == collection_item:
                self.model.removeRow(item.row())

    def on_thumbnail_double_clicked(self, item):
        if item.thumbnail_image.file_object.is_image:
            viewer = ImageViewerWidget()
            viewer.set_image_file_path(
                item.thumbnail_image.file_object.filePath())
            viewer.set_tags(item.tags)
            viewer.show()
            available_image_viewer_widgets.append(viewer)
            self.viewer_created.emit(viewer, self.model)

    def on_thumbnail_clicked(self, item):
        self.property_panel.set_item(item)

    def on_filters_changed(
            self, filters: dict[str, list[str | bool]], mode: str):
        self.proxy_model.active_filters = filters
        self.proxy_model.filter_mode = mode
        self.proxy_model.invalidateFilter()


def _get_items_from_model(model):
    items = []
    for x in range(model.rowCount()):
        for y in range(model.columnCount()):
            index = model.index(x, y)
            items.append(model.item(index.row()))
    return items


class ThumbnailsContainerWidget(QtWidgets.QWidget):
    """A container for ThumbnailsWidget instances

    It can work in two modes:
      - single mode: just one ThumbnailsWidget
      - tabbed mode: multiple ThumbnailsWidget inside a QTabWidget
    """

    item_added = QtCore.Signal(QtGui.QStandardItem)
    viewer_created = QtCore.Signal(ImageViewerWidget, ThumbnailItemModel)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.thumbnails_widgets = []
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def set_content(self, use_tabs: bool = False):
        self.use_tabs = use_tabs

        if use_tabs:
            self._tabs = QtWidgets.QTabWidget(self)
            self.layout.addWidget(self._tabs)

        else:
            tw = ThumbnailsWidget(self)
            tw.item_added.connect(self.item_added)
            tw.viewer_created.connect(self.viewer_created)
            self.layout.addWidget(tw)
            self.thumbnails_widgets.append(tw)

    def add_thumbnails_widget(self, label: str = None):
        if label is not None:
            existing = self.get_thumbnails_widget(label)
            # Return existing widget if it has the same label
            if existing:
                return existing  # Don't recreate if label exists

        tw = ThumbnailsWidget(self)
        tw.item_added.connect(self.item_added)  # Relay signals
        tw.viewer_created.connect(self.viewer_created)
        self.thumbnails_widgets.append(tw)

        if self.use_tabs:
            if label is None:
                label = f'View {len(self.thumbnails_widgets)}'
            self._tabs.addTab(tw, label)
        return tw

    def current_thumbnails_widget(self):
        if self.use_tabs:
            return self._tabs.currentWidget()
        return self.thumbnails_widgets[0] if self.thumbnails_widgets else None

    def get_thumbnails_widget(self, label: str) -> ThumbnailsWidget | None:
        if not self.use_tabs:
            # In single mode, just return the first widget if it exists
            return (
                self.thumbnails_widgets[0]
                if self.thumbnails_widgets else None)
        for index in range(self._tabs.count()):
            if self._tabs.tabText(index) == label:
                return self._tabs.widget(index)


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
    app.exec()


if __name__ == '__main__':
    run_standalone()
