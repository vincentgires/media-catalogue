import os
import threading
from mediacatalogue.qt import QtCore, QtGui
import OpenImageIO as oiio

hdr_extensions = ['.exr', '.hdr']


class FileObject(QtCore.QFileInfo):
    def __init__(self, file=None):
        super().__init__()
        if file is not None:
            self.setFile(file)

    @property
    def is_image(self):
        supported_formats = QtGui.QImageReader.supportedImageFormats()
        supported_extensions = [
            f'.{format.data().decode()}'
            for format in supported_formats] + hdr_extensions
        return self.file_extension in supported_extensions

    @property
    def file_extension(self):
        return os.path.splitext(self.filePath().lower())[1] or None


class ImageLoader(QtCore.QObject):
    image_loaded = QtCore.Signal(QtGui.QImage)

    def __init__(self, file=None):
        super().__init__()
        self.file_object = (
            file if isinstance(file, FileObject) else FileObject(file))
        self.image = QtGui.QImage()
        self.target_size = QtCore.QSize(0, 0)

    def set_scaled_size(self, size):
        self.target_size = size

    def run(self):
        file_path = self.file_object.filePath()
        if file_path.lower().endswith(tuple(hdr_extensions)):
            self.load_hdr_image(file_path)
        else:
            self.load_regular_image(file_path)

    def load_hdr_image(self, file_path):
        image = oiio.ImageInput.open(file_path)
        spec = image.spec()
        width, height = spec.width, spec.height
        channels = spec.nchannels
        pixels = image.read_image()
        image.close()
        # TODO: resize
        # if not self.target_size.isNull():
        #     ...
        self.image = self.hdr_to_qimage(pixels, width, height, channels)
        self.image_loaded.emit(self.image)

    def load_regular_image(self, file_path):
        image_reader = QtGui.QImageReader(file_path)
        if not self.target_size.isNull():
            image_size = image_reader.size()
            image_size.scale(self.target_size, QtCore.Qt.KeepAspectRatio)
            image_reader.setScaledSize(image_size)
        self.image = image_reader.read()
        self.image_loaded.emit(self.image)

    def hdr_to_qimage(self, hdr_image, width, height, channels):
        hdr_image = hdr_image.clip(0, 1)
        hdr_image = (hdr_image * 255).astype('uint8')
        if channels == 3:  # RGB
            image_format = QtGui.QImage.Format_RGB888
        elif channels == 4:  # RGBA
            image_format = QtGui.QImage.Format_RGBA8888
        else:
            raise ValueError('Unknown channels')
        data = hdr_image.tobytes()
        return QtGui.QImage(data, width, height, image_format)

    def load_image(self):
        thread = threading.Thread(target=self.run)
        thread.start()
