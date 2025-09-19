import os
import threading
from mediacatalogue.qt import QtCore, QtGui
import OpenImageIO as oiio


# QtMimeDatabase may fail identify some formats like .hdr, so there's a manual
# mapping when necessary.
ext_to_mime = {
    '.hdr': 'image/vnd.radiance',
    '.exr': 'image/x-exr'}


def get_mime_type_for_file(path: str) -> str:
    """Get the MIME type of a file based on its content or extension

    Some formats like .hdr are not correctly recognized by QtMimeDatabase (.hdr
    may be detected as text/x-mpsub). A manual mapping for these special cases,
    otherwise fall back to Qt's detection.
    """
    _, ext = os.path.splitext(path)
    return ext_to_mime.get(
        ext.lower(), QtCore.QMimeDatabase().mimeTypeForFile(path).name())


def get_supported_mimes():
    mime_db = QtCore.QMimeDatabase()
    mimes = set()
    for ext_bytes in QtGui.QImageReader.supportedImageFormats():
        ext = ext_bytes.data().decode()
        dummy_filename = f'file.{ext}'
        mimes.add(mime_db.mimeTypeForFile(dummy_filename).name())
    return mimes


supported_mimes = get_supported_mimes()
hdr_mimes = {  # These types will be handled by OpenImageIO
    'image/vnd.radiance',
    'image/x-exr'}


class FileObject(QtCore.QFileInfo):
    def __init__(self, file=None):
        super().__init__()
        if file is not None:
            self.setFile(file)

    @property
    def is_image(self):
        return self.file_mime in supported_mimes | hdr_mimes

    @property
    def file_mime(self):
        return get_mime_type_for_file(self.filePath())


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
        file_mime = self.file_object.file_mime
        self.load_regular_image(file_path)
        if file_mime in hdr_mimes:
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
