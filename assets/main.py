import sys
from multiprocessing import freeze_support

def main() -> int:
    from pathlib import Path
    from app.crashDiagnostics import enable_fault_log
    enable_fault_log(Path(__file__).resolve().parent / "user" / "debug")
    # Spawn workers import __main__; they must not import/create the GUI.
    from PySide6.QtWidgets import QApplication, QMessageBox
    from app.winUI import MainWindow
    app = QApplication(sys.argv)

    try:
        window = MainWindow()
    except (OSError, ValueError, TypeError, KeyError) as error:
        QMessageBox.critical(None, "앱 초기화 오류", f"프로젝트 설정을 확인하세요.\n{error}")
        return 1
    window.show()
    
    return app.exec()


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
