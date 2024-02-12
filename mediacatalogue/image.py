import os
import threading
from mediacatalogue.qt import QtCore, QtGui


class FileObject(QtCore.QFileInfo):
    def __init__(self, file=None):
        super().__init__()
        if file is not None:
            self.setFile(file)

    @property
    def is_image(self):
        return (
            self.file_extension in QtGui.QImageReader.supportedImageFormats())

    @property
    def file_extension(self):
        return os.path.splitext(self.filePath().lower())[1][1:] or None


class ImageLoader(QtCore.QObject):
    image_loaded = QtCore.Signal(QtGui.QImage)

    def __init__(self, file=None):
        super().__init__()
        self.file_object = (
            file if isinstance(file, FileObject) else FileObject(file))
        self.image_reader = QtGui.QImageReader()
        self.image = QtGui.QImage()
        self.target_size = QtCore.QSize(0, 0)

    def set_scaled_size(self, size):
        self.target_size = size

    def run(self):
        self.image_reader.setFileName(self.file_object.filePath())
        if not self.target_size.isNull():
            image_size = self.image_reader.size()
            image_size.scale(self.target_size, QtCore.Qt.KeepAspectRatio)
            self.image_reader.setScaledSize(image_size)
        self.image = self.image_reader.read()
        self.image_loaded.emit(self.image)

    def load_image(self):
        thread = threading.Thread(target=self.run)
        thread.start()
