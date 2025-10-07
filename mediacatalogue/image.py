import os
from concurrent.futures import ThreadPoolExecutor
from mediacatalogue.qt import QtCore, QtGui, shiboken
try:
    import OpenImageIO as oiio
    _oiio_available = True
except ImportError:
    _oiio_available = False

# QtMimeDatabase may fail identify some formats like .hdr, so there's a manual
# mapping when necessary.
ext_to_mime = {
    '.hdr': 'image/vnd.radiance',
    '.exr': 'image/x-exr'}

executor = ThreadPoolExecutor(max_workers=4)


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
    _hdr_ready = QtCore.Signal(object)
    _regular_ready = QtCore.Signal(object)

    def __init__(self, file=None):
        super().__init__()
        self.file_object = (
            file if isinstance(file, FileObject) else FileObject(file))
        self.image = QtGui.QImage()
        self.target_size = QtCore.QSize(0, 0)

        self._hdr_ready.connect(self._on_hdr_ready)
        self._regular_ready.connect(self._on_regular_ready)

    def set_scaled_size(self, size):
        self.target_size = size

    def run(self):
        if not self.file_object.is_image:
            return
        file_path = self.file_object.filePath()
        file_mime = self.file_object.file_mime
        if file_mime in hdr_mimes:
            if _oiio_available:
                self.load_hdr_image(file_path)
            else:
                print('OpenImageIO is not installed. Cannot load HDR images.')
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

    def load_async(self, executor):
        if not self.file_object.is_image:
            return

        file_path = self.file_object.filePath()
        file_mime = self.file_object.file_mime

        def task():
            if file_mime in hdr_mimes and _oiio_available:
                image = oiio.ImageInput.open(file_path)
                spec = image.spec()
                width, height = spec.width, spec.height
                channels = spec.nchannels
                pixels = image.read_image()
                image.close()
                return ('hdr', (pixels, width, height, channels))
            else:
                image_reader = QtGui.QImageReader(file_path)
                if not self.target_size.isNull():
                    image_size = image_reader.size()
                    image_size.scale(
                        self.target_size, QtCore.Qt.KeepAspectRatio)
                    image_reader.setScaledSize(image_size)
                return ('regular', image_reader.read())

        future = executor.submit(task)

        def when_done(future_):
            kind, data = future_.result()
            match kind:
                case 'hdr':
                    self._hdr_ready.emit(data)
                case 'regular':
                    self._regular_ready.emit(data)

        future.add_done_callback(when_done)

    def _on_regular_ready(self, data):
        qimage = data
        if not self.target_size.isNull() and not qimage.isNull():
            qimage = qimage.scaled(
                self.target_size,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation)
        self.image = qimage
        self.image_loaded.emit(qimage)

    def _on_hdr_ready(self, data):
        pixels, width, height, channels = data
        qimage = self.hdr_to_qimage(pixels, width, height, channels)
        self.image = qimage
        self.image_loaded.emit(qimage)
