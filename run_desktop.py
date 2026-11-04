"""PyInstaller entry point for the BabyMind Linux desktop app."""
import sys


def check_package() -> None:
    """Headless packaging check only; does not test the GUI or inference."""
    from pathlib import Path
    from babymind.first_run import _app_directory, _find_llama_server
    import cryptography
    import babymind

    app_dir = _app_directory()
    runtime = _find_llama_server(app_dir)
    web = Path(babymind.__file__).resolve().parent / "web" / "index.html"
    if runtime is None or not web.is_file():
        raise SystemExit("Package check failed: llama-server or web assets are missing.")
    print(f"Package files found: {runtime}; {web}; cryptography {cryptography.__version__}")
    print("This check does not test the GUI, model download, or inference.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-package"]:
        check_package()
    elif sys.argv[1:] == ["--check-desktop-deps"]:
        # Check that the bundled Qt WebEngine module and system libraries load.
        # This is not a window or model inference test.
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError as error:
            raise SystemExit(f"Desktop dependency check failed: {error}") from error
        print("Qt WebEngine libraries loaded; no window or model was tested.")
    else:
        from babymind.desktop import main
        main()
