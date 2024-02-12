import sys
from mediacatalogue.qt import QtWidgets
from mediacatalogue import application_name
from mediacatalogue.window import MainWindow


def run() -> None:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(application_name)
    main_window = MainWindow(app.desktop())
    main_window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    run()
