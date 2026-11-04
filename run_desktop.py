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
    else:
        from babymind.desktop import main
        main()
