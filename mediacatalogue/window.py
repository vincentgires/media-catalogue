import os
from functools import partial
from mediacatalogue.qt import QtCore, QtWidgets, QtGui
from mediacatalogue.categories import (
    get_categories_by_family, get_category_item,
    CollectionItem as CollectionItemData)
from mediacatalogue.thumbnails import ThumbnailsContainerWidget
from mediacatalogue.imageviewer import available_image_viewer_widgets

collections_view_minimum_width = 100


class CollectionItem():
    def __init__(self, data=None, parent=None):
        self.name = data.name or 'none'
        self.checkable = self.checkable = bool(data.files or data.files_loader)
        # Item is checkable if it has files or a loader function defined
        self.checked = QtCore.Qt.Unchecked
        self.children = []
        self.parent = parent
        self.expandable = data.collections_loader is not None  # Expose arrow
        # to expand tree even if no children set, for lazy loading. Only if
        # loader function is defined.
        self.data: CollectionItemData = data  # Keep reference to original data
        # item

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    def display_role(self):
        return self.name


class CollectionsModel(QtCore.QAbstractItemModel):
    item_checked = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []

    def columnCount(self, parent):
        return 1

    def rowCount(self, parent):
        if not parent.isValid():
            return len(self.items)
        item = parent.internalPointer()
        return len(item.children)

    def flags(self, index):
        item = index.internalPointer()
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if getattr(item, 'checkable', False):
            flags |= QtCore.Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role):
        item = index.internalPointer()
        match role:
            case QtCore.Qt.CheckStateRole:
                if getattr(item, 'checkable', False):
                    return item.checked
            case QtCore.Qt.DisplayRole:
                return item.display_role()

    def index(self, row, column, parent):
        if not parent.isValid():
            item = self.items[row]
        else:
            item = parent.internalPointer().children[row]
        return self.createIndex(row, column, item)

    def parent(self, index):
        if not index.isValid():
            return QtCore.QModelIndex()
        item = index.internalPointer()
        if item.parent is None:
            return QtCore.QModelIndex()
        parent_item = item.parent
        if parent_item.parent is None:
            row = self.items.index(parent_item)
        else:
            row = parent_item.parent.children.index(parent_item)
        return self.createIndex(row, 0, parent_item)

    def setData(self, index, value, role):
        if role == QtCore.Qt.CheckStateRole:
            item = index.internalPointer()
            item.checked = value
            self.dataChanged.emit(index, index, [QtCore.Qt.CheckStateRole])
            self.item_checked.emit(item)
            return True
        return False

    def hasChildren(self, parent):
        if not parent.isValid():
            return len(self.items) > 0
        item = parent.internalPointer()
        # Real children or unknown for lazy loading
        return bool(item.children) or item.expandable


class CollectionsView(QtWidgets.QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)  # Dislpay arrows for item with children

    def sizeHint(self):  # noqa N802
        return QtCore.QSize(collections_view_minimum_width, 0)

    def minimumSizeHint(self):  # noqa N802
        return QtCore.QSize(collections_view_minimum_width, 0)


class CollectionsWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = CollectionsView(self)
        self.model = CollectionsModel(self)
        self.view.setModel(self.model)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.addWidget(self.view)
        self.setLayout(self.main_layout)


def _fill_collection_from_files(
        thumbnails_container_widget: ThumbnailsContainerWidget,
        collection_data: CollectionItemData,
        collection_item: CollectionItem,
        expand_group: bool = False):
    files = collection_data.load_files(force=True)
    if files is None:
        return
    if not expand_group:
        tw = thumbnails_container_widget.current_thumbnails_widget()
        for file in files:
            tw.add_collection_item(
                path=file.path,
                tags=file.tags,
                collection_item=collection_item)
    else:
        for group, grouped_files in collection_data.files_by_group().items():
            tw = thumbnails_container_widget.add_thumbnails_widget(group)
            for file in grouped_files:
                tw.add_collection_item(
                    file.path,
                    tags=file.tags,
                    collection_item=collection_item)


class ContextWidget(QtWidgets.QWidget):
    def __init__(self, context_name, parent=None):
        super().__init__(parent=parent)
        self.context_name = context_name
        self.collections_widget = CollectionsWidget(self)
        self.thumbnails_container_widget = ThumbnailsContainerWidget(self)

        # Set if container widget uses tabs
        category = get_category_item(context_name)
        self.thumbnails_container_widget.set_content(
            use_tabs=category.expand_group)

        # Layout
        main_layout = QtWidgets.QHBoxLayout()
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.collections_widget)
        splitter.addWidget(self.thumbnails_container_widget)
        main_layout.addWidget(splitter)
        splitter.setStretchFactor(1, 2)
        self.setLayout(main_layout)

        # Signals
        self.collections_widget.model.item_checked.connect(
            self.on_collection_checked, QtCore.Qt.QueuedConnection)
        self.thumbnails_container_widget.viewer_created.connect(
            self.on_viewer_created)
        self.collections_widget.view.expanded.connect(self.on_item_expanded)

    def on_item_expanded(self, index: QtCore.QModelIndex):
        item: CollectionItem = index.internalPointer()
        model = self.collections_widget.model

        if not item.expandable:
            return

        children_data = item.data.collections_loader(item.data) or []

        # Get existing on new item to manage
        existing_by_name = {c.name: c for c in item.children}
        new_by_name = {d.name: d for d in children_data}

        # Children to delete
        to_remove = [c for c in item.children if c.name not in new_by_name]
        if to_remove:
            for child in reversed(to_remove):
                row = item.children.index(child)
                model.beginRemoveRows(index, row, row)
                item.children.pop(row)
                model.endRemoveRows()

        # New children to add
        new_children = []
        for child_data in children_data:
            if child_data.name not in existing_by_name:
                new_children.append(
                    CollectionItem(data=child_data, parent=item))

        if new_children:
            start = len(item.children)
            end = start + len(new_children) - 1
            model.beginInsertRows(index, start, end)
            for c in new_children:
                item.add_child(c)
            model.endInsertRows()

    def on_collection_checked(self, item):
        if not item.checked:
            for tw in self.thumbnails_container_widget.thumbnails_widgets:
                tw.remove_collection_items(collection_item=item)
            return
        category = get_category_item(self.context_name)
        if category is None:
            return
        collection_data = item.data
        if collection_data is None:
            return
        _fill_collection_from_files(
            thumbnails_container_widget=self.thumbnails_container_widget,
            collection_data=collection_data,
            collection_item=item,
            expand_group=category.expand_group)

    def on_viewer_created(self, image_viewer_widget, thumbnail_item_model):
        image_viewer_widget.history_show.connect(self.on_history_show)
        image_viewer_widget.previous_image.connect(
            lambda x: self.show_next_item_from_view(
                backward=True,
                thumbnail_item_model=thumbnail_item_model,
                image_viewer_widget=x))
        image_viewer_widget.next_image.connect(
            lambda x: self.show_next_item_from_view(
                thumbnail_item_model=thumbnail_item_model,
                image_viewer_widget=x))
        image_viewer_widget.first_image.connect(
            lambda x: self.show_next_item_from_view(
                first=True,
                thumbnail_item_model=thumbnail_item_model,
                image_viewer_widget=x))
        image_viewer_widget.last_image.connect(
            lambda x: self.show_next_item_from_view(
                last=True,
                thumbnail_item_model=thumbnail_item_model,
                image_viewer_widget=x))

    def _fill_history(self, image_viewer_widget):
        category_item = get_category_item(self.context_name)
        if category_item is None:
            return
        if category_item.find_history is None:
            return
        history_widget = image_viewer_widget.history_widget
        history_files = category_item.find_history(
            history_widget.initial_filepath)
        history_widget.fill(history_files)
        if history_files:
            history_widget.history_listwidget.setCurrentRow(0)

    def on_history_show(self, image_viewer_widget):
        self._fill_history(image_viewer_widget)

    def show_next_item_from_view(
            self, backward=False, first=False, last=False,
            thumbnail_item_model=None,
            image_viewer_widget=None):

        if thumbnail_item_model is None:
            return

        file = image_viewer_widget.history_widget.initial_filepath
        cur_w = self.thumbnails_container_widget.current_thumbnails_widget()
        view_model = cur_w.view.model()

        view_indexes = []
        for proxy_row in range(view_model.rowCount()):
            match_index = view_model.mapToSource(
                view_model.index(proxy_row, 0))
            view_indexes.append(match_index)

        if not view_indexes:
            return

        current_item = thumbnail_item_model.findItems(
            file, QtCore.Qt.MatchExactly)[0]
        current_index = thumbnail_item_model.indexFromItem(current_item)
        iter_indexes = (
            iter(reversed(view_indexes)) if backward else iter(view_indexes))
        next_match = view_indexes[0] if backward else view_indexes[-1]

        if all(not x for x in (first, last)):
            next_index = (
                next(iter_indexes, next_match)
                if current_index in iter_indexes else view_indexes[0])
        if first:
            next_index = view_indexes[0]
        elif last:
            next_index = view_indexes[-1]

        if next_index == current_index:
            return

        if next_index is not None:
            filepath = next_index.data(QtCore.Qt.DisplayRole)
            image_viewer_widget.set_image_file_path(filepath)
            image_viewer_widget.load_image()

        if image_viewer_widget.is_history_mode:
            self._fill_history(image_viewer_widget)


def build_tree_items(
        collections: list[CollectionItemData]) -> list[CollectionItem]:
    """Convert categoriy data item into UI for the tree view"""

    items = []
    for data in collections:
        node = CollectionItem(data=data)

        # Recursively add sub-collections as children
        if data.collections:
            for sub in build_tree_items(data.collections):
                node.add_child(sub)

        items.append(node)
    return items


class ContextDockWidget(QtWidgets.QDockWidget):
    def __init__(self, name):
        super().__init__()
        self.context_name = name
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)

    def set_widget(self, widget):
        QtWidgets.QDockWidget.setWidget(self, widget)
        self.setWindowTitle(self.context_name)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
            self,
            parent=None,
            config_name: tuple[str, str] | None = None):
        super().__init__(parent=parent)
        self.resize(900, 600)
        self.setWindowTitle(QtWidgets.QApplication.applicationName())
        self.setWindowFlags(QtCore.Qt.Window)
        self.setDockOptions(
            QtWidgets.QMainWindow.AnimatedDocks
            | QtWidgets.QMainWindow.AllowNestedDocks
            | QtWidgets.QMainWindow.AllowTabbedDocks)
        self.setDockNestingEnabled(True)
        self.setTabPosition(
            QtCore.Qt.AllDockWidgetAreas,
            QtWidgets.QTabWidget.TabPosition.North)

        self.previous_tabbed_dock = None

        self.dummy_central = QtWidgets.QWidget()
        self.dummy_central.setVisible(False)
        self.setCentralWidget(self.dummy_central)

        # Menubar
        self.menu_bar = QtWidgets.QMenuBar()
        self.menu_bar.setVisible(False)
        self.menu_help = self.menu_bar.addMenu('help')
        self.show_shortcut_action = self.menu_help.addAction('show shortcuts')
        self.show_shortcut_action.triggered.connect(
            partial(_show_shortcuts, self))
        self.setMenuBar(self.menu_bar)

        # Toolbar
        self.context_toolbar = ContextToolbar()
        self.context_toolbar.add_action.triggered.connect(
            self.show_context_selection)
        self.context_toolbar.add_action.setShortcut('ctrl+n')
        self.context_toolbar.remove_action.triggered.connect(
            self.close_current_dockwidget)
        self.context_toolbar.remove_action.setShortcut('ctrl+w')
        self.context_toolbar.clear_action.triggered.connect(
            self.clear_dockwidgets)
        self.addToolBar(self.context_toolbar)

        # Settings
        if config_name is None:
            self._settings = None
        else:
            self._settings = QtCore.QSettings(*config_name)
            self.restore_settings()

    def closeEvent(self, event):  # noqa N802
        self.save_settings()
        available_image_viewer_widgets.clear()
        return QtWidgets.QMainWindow.closeEvent(self, event)

    def keyReleaseEvent(self, event):  # noqa N802
        if event.key() == QtCore.Qt.Key_Alt:
            self.menu_bar.setVisible(not self.menu_bar.isVisible())

    def show_context_selection(self):
        items = []
        for _, categories in get_categories_by_family().items():
            for category in categories:
                items.append(category.name)
        dialog = QtWidgets.QInputDialog(self, QtCore.Qt.WindowType.Popup)
        category, result = dialog.getItem(
            self, 'add context', 'category', items, editable=False)
        if result:
            return self.add_context_tab(category)

    def add_context_tab(self, context):
        category_item = get_category_item(context)
        if category_item is None:
            return

        context_widget = ContextWidget(context)

        # Build collections elements
        items = build_tree_items(category_item.collections)
        context_widget.collections_widget.model.items = items

        dock_contexttab = ContextDockWidget(context)
        dock_contexttab.set_widget(context_widget)

        self.addDockWidget(
            QtCore.Qt.RightDockWidgetArea,
            dock_contexttab, QtCore.Qt.Horizontal)

        if self.previous_tabbed_dock is not None:
            self.tabifyDockWidget(
                self.previous_tabbed_dock, dock_contexttab)
        self.previous_tabbed_dock = dock_contexttab

        dock_contexttab.show()
        dock_contexttab.raise_()
        return dock_contexttab

    def close_current_dockwidget(self):
        current_focus_widget = self.focusWidget()
        for dock in self.findChildren(ContextDockWidget):
            if current_focus_widget in dock.findChildren(QtWidgets.QWidget):
                self.removeDockWidget(dock)
                dock.deleteLater()
        QtWidgets.QApplication.processEvents()

        if not self.findChildren(ContextDockWidget):
            self.previous_tabbed_dock = None

    def clear_dockwidgets(self):
        for dock in self.findChildren(ContextDockWidget):
            dock.deleteLater()
        self.previous_tabbed_dock = None

    def save_settings(self):
        if self._settings is None:
            return
        open_categories = []
        for cw in self.findChildren(ContextWidget):
            cur_thumbs_w = (
                cw.thumbnails_container_widget.current_thumbnails_widget())
            size = cur_thumbs_w.view_controls.size_slider.value()
            spacing = cur_thumbs_w.view_controls.spacing_slider.value()
            tags = cur_thumbs_w.proxy_model.active_filters
            open_categories.append({
                'categorie': cw.context_name,
                'size': size,
                'spacing': spacing,
                'filters': tags})
        self._settings.beginGroup('windows')
        self._settings.setValue('categories', open_categories)
        self._settings.endGroup()

    def restore_settings(self):
        if self._settings is None:
            return
        self._settings.beginGroup('windows')
        if open_categories := self._settings.value('categories'):
            for data in open_categories:
                context_tab = self.add_context_tab(data['categorie'])
                cur_thumbs_w = (
                    context_tab.widget().thumbnails_container_widget
                    .current_thumbnails_widget())
                cur_thumbs_w.view_controls.size_slider.setValue(data['size'])
                cur_thumbs_w.view_controls.spacing_slider.setValue(
                    data['spacing'])
                for k, values in data['filters'].items():
                    for v in values:
                        cur_thumbs_w.search_controls.filters.add_filter(
                            key=k, value=v)
        self._settings.endGroup()


class ContextToolbar(QtWidgets.QToolBar):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('context toolbar')
        self.add_action = QtGui.QAction(
            QtGui.QIcon(os.path.expandvars('$ICONS_PATH/add.svg')),
            'add', self)
        self.remove_action = QtGui.QAction(
            QtGui.QIcon(os.path.expandvars('$ICONS_PATH/remove.svg')),
            'remove', self)
        self.clear_action = QtGui.QAction(
            QtGui.QIcon(os.path.expandvars('$ICONS_PATH/clear.svg')),
            'clear', self)
        self.addAction(self.add_action)
        self.addAction(self.remove_action)
        self.addAction(self.clear_action)


class ShortcutsWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowStaysOnTopHint)
        self.set_layout()

    def keyPressEvent(self, event):  # noqa N802
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()

    def set_layout(self):
        shortcuts_groupbox = QtWidgets.QGroupBox('shortcuts')
        formlayout = QtWidgets.QFormLayout()
        formlayout.addRow('close me', QtWidgets.QLabel('[escape]'))
        shortcuts_groupbox.setLayout(formlayout)

        mainwindow_groupbox = QtWidgets.QGroupBox('global')
        formlayout = QtWidgets.QFormLayout()
        formlayout.addRow('toggle menubar', QtWidgets.QLabel('[released alt]'))
        formlayout.addRow('new context', QtWidgets.QLabel('[ctrl+n]'))
        formlayout.addRow(
            'close current context', QtWidgets.QLabel('[ctrl+w]'))
        mainwindow_groupbox.setLayout(formlayout)

        thumbnails_groupbox = QtWidgets.QGroupBox('thumbnails')
        formlayout = QtWidgets.QFormLayout()
        formlayout.addRow('view image', QtWidgets.QLabel('[double clic]'))
        formlayout.addRow('toggle show header', QtWidgets.QLabel('[o]'))
        formlayout.addRow('update all items', QtWidgets.QLabel('[f5]'))
        thumbnails_groupbox.setLayout(formlayout)

        imageviewer_groupbox = QtWidgets.QGroupBox('image viewer')
        formlayout = QtWidgets.QFormLayout()
        formlayout.addRow('zoom to 1:1', QtWidgets.QLabel('[1]'))
        formlayout.addRow('fit view', QtWidgets.QLabel('[f]'))
        formlayout.addRow('toggle fullscreen', QtWidgets.QLabel('[f11]'))
        formlayout.addRow('next image', QtWidgets.QLabel('[right]'))
        formlayout.addRow('previous image', QtWidgets.QLabel('[left]'))
        formlayout.addRow('first image', QtWidgets.QLabel('[home]'))
        formlayout.addRow('last image', QtWidgets.QLabel('[end]'))
        formlayout.addRow('toggle history', QtWidgets.QLabel('[h]'))
        formlayout.addRow('toggle frameless', QtWidgets.QLabel('[f10]'))
        imageviewer_groupbox.setLayout(formlayout)

        mainlayout = QtWidgets.QVBoxLayout()
        mainlayout.addWidget(shortcuts_groupbox)
        mainlayout.addWidget(mainwindow_groupbox)
        mainlayout.addWidget(thumbnails_groupbox)
        mainlayout.addWidget(imageviewer_groupbox)
        self.setLayout(mainlayout)


def _show_shortcuts(parent=None):
    widget = ShortcutsWidget(parent)
    widget.show()
