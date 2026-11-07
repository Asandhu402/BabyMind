"""Linux desktop launcher with a loopback-only local server."""
from __future__ import annotations

import os
import queue
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from .first_run import (
    MODEL_SIZE_LABEL, _data_home, _download_model, _sha256, prepare_local_engine,
)


def _run_with_progress(app, title, work, *, cancellable=False):
    """Run blocking startup work off the GUI thread and show honest progress."""
    from PySide6.QtWidgets import QProgressDialog

    updates = queue.Queue()
    cancelled = threading.Event()
    result = {}
    dialog = QProgressDialog(title, "Cancel" if cancellable else "", 0, 0)
    if not cancellable:
        dialog.setCancelButton(None)
    dialog.setWindowTitle("BabyMind")
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.show()

    def run():
        try:
            result["value"] = work(lambda done, total: updates.put((done, total)), cancelled)
        except Exception as error:
            result["error"] = error

    worker = threading.Thread(target=run, daemon=True, name="BabyMindStartup")
    worker.start()
    while worker.is_alive():
        app.processEvents()
        if cancellable and dialog.wasCanceled():
            cancelled.set()
        try:
            while True:
                done, total = updates.get_nowait()
                if total:
                    dialog.setRange(0, 1000)
                    dialog.setValue(min(1000, done * 1000 // total))
                    dialog.setLabelText(f"Downloading model: {done / 1e9:.2f} / {total / 1e9:.2f} GB")
                else:
                    dialog.setLabelText(f"Downloaded {done / 1e9:.2f} GB")
        except queue.Empty:
            pass
        time.sleep(0.05)
    worker.join()
    dialog.close()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _create_window(port: int):
    """Create the real Qt web view and restrict navigation to the app server."""
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class LocalPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            return url.scheme() == "http" and url.host() == "127.0.0.1" and url.port() == port

    view = QWebEngineView()
    view.setPage(LocalPage(view))
    view.setWindowTitle("BabyMind")
    view.resize(1280, 820)
    view.setMinimumSize(900, 620)
    view.load(QUrl(f"http://127.0.0.1:{port}/"))
    return view


def main() -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("BabyMind desktop supports Linux only.")
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # Check desktop system libraries early.
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as error:
        raise SystemExit(f"BabyMind requires Linux Qt WebEngine libraries: {error}. See README.txt.") from error

    os.environ.setdefault("BABYMIND_SANDBOX", "require")
    # Avoid a fixed-port collision with another model or BabyMind instance.
    if not os.environ.get("BABYMIND_LLAMA_PORT"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            os.environ["BABYMIND_LLAMA_PORT"] = str(probe.getsockname()[1])
    app = QApplication.instance() or QApplication(sys.argv)

    def download(model_path: Path) -> None:
        answer = QMessageBox.question(
            None, "Set up BabyMind's local AI",
            f"Download the local model ({MODEL_SIZE_LABEL})? It is verified and stored on this computer. "
            "The first download needs internet access and at least 4.5 GB of free space.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            raise RuntimeError("Model download cancelled. Reopen BabyMind to try again.")
        _run_with_progress(app, "Connecting to the model host…",
                           lambda progress, cancel: _download_model(model_path, progress, cancel),
                           cancellable=True)

    server = None
    session_lock = None
    learning_supervisor = None
    try:
        def verify(path: Path) -> str:
            return _run_with_progress(app, "Verifying the local model…",
                                      lambda _progress, _cancel: _sha256(path))

        prepare_local_engine(download, verify)
        # A shared lock tells the standalone learning service that this desktop
        # process owns the in-app supervisor and the local model right now.
        from .learning_service import hold_desktop_session
        session_lock = hold_desktop_session(_data_home())

        def start_server(_progress, _cancel):
            # Import after engine setup; the module constructs the coordinator.
            nonlocal learning_supervisor
            from .server import (
                DATA_HOME, Handler, ensure_autonomous_learning,
                init_db, learning_service, recover_development_reviews,
            )
            init_db()
            recover_development_reviews()
            learning_supervisor = learning_service()
            ensure_autonomous_learning()  # default-on permanent supervisor
            local_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=local_server.serve_forever, daemon=True,
                             name="BabyMindLocalServer").start()
            print(f"BabyMind data: {DATA_HOME}", flush=True)
            return local_server

        server = _run_with_progress(app, "Starting the local AI model; this can take several minutes…", start_server)
        port = server.server_address[1]

        view = _create_window(port)
        view.show()
        app.exec()
    except Exception as error:
        # The dialog is useful on a desktop; stderr also makes failures
        # diagnosable when the application was started from a terminal.
        print(f"BabyMind could not start: {error}", file=sys.stderr, flush=True)
        QMessageBox.critical(None, "BabyMind could not start", str(error))
        raise SystemExit(1) from error
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if learning_supervisor is not None:
            learning_supervisor.request_stop()
        if session_lock is not None:
            session_lock.close()


if __name__ == "__main__":
    main()
