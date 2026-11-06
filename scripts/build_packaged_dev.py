#!/usr/bin/env python3
"""Build the isolated Python helper and source seed for the Linux package.

This creates a staging workspace for source edits. It does not rebuild or
activate the running PyInstaller executable.

The seed is a complete source copy: the packaged self-development check runs the
project's own test suite against it, so every top-level file the suite reads
(installer scripts, LICENSE/NOTICE, SECURITY.md, .gitmodules) has to be there.
"""
from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

SEED_DIRECTORIES = ("src", "tests", "scripts", "docs", "quality", ".github")
SECRET_FILENAMES = {".env"}
# Build products that may sit next to the checkout when this script runs.
GENERATED_SUFFIXES = (".spec",)


def seed_root_files(repo: Path) -> list[Path]:
    """Return the repository's top-level files to copy into the source seed.

    Every regular file at the repository root is copied so the seeded copy can
    run the project's own suite; only local secrets are skipped. Directories,
    symlinks and generated data are handled by the caller.
    """
    files: list[Path] = []
    for path in sorted(repo.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in SECRET_FILENAMES or path.name.startswith(".env."):
            continue
        if path.name.endswith(GENERATED_SUFFIXES):
            continue
        files.append(path)
    return files


def build(repo: Path, package: Path) -> None:
    import _cffi_backend
    import cffi
    import cryptography
    import pycparser

    repo = repo.resolve()
    package = package.resolve()
    runtime = package / "dev-python"
    seed = package / "dev-source-seed"
    if runtime.exists() or seed.exists():
        raise RuntimeError("Refusing to overwrite an existing packaged development runtime or seed.")
    lib = runtime / "lib"
    bin_dir = runtime / "bin"
    bin_dir.mkdir(parents=True)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(stdlib, lib / version, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "site-packages", "dist-packages", "test", "tests", "idlelib", "tkinter", "turtledemo"))
    shutil.copy2(Path(sys.executable).resolve(), bin_dir / "python3")
    ld_name = sysconfig.get_config_var("LDLIBRARY")
    ld_dir = sysconfig.get_config_var("LIBDIR")
    if ld_name and ld_dir and (Path(ld_dir) / ld_name).is_file():
        shutil.copy2((Path(ld_dir) / ld_name).resolve(), lib / ld_name)
        # The ELF SONAME may differ from LDLIBRARY (e.g. libpython3.11.so.1.0).
        source_lib = (Path(ld_dir) / ld_name).resolve()
        if source_lib.name != ld_name:
            shutil.copy2(source_lib, lib / source_lib.name)
    # Some distributions link the interpreter statically; the smoke check below
    # fails if a required shared library is absent.
    site = lib / version / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for module, name in ((cryptography, "cryptography"), (cffi, "cffi"), (pycparser, "pycparser")):
        shutil.copytree(Path(module.__file__).resolve().parent, site / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        metadata = Path(importlib.metadata.distribution(name)._path)
        if metadata.is_dir():
            shutil.copytree(metadata, site / metadata.name)
    shutil.copy2(Path(_cffi_backend.__file__).resolve(), site / Path(_cffi_backend.__file__).name)
    seed.mkdir()
    for name in SEED_DIRECTORIES:
        source = repo / name
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, seed / name, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for source in seed_root_files(repo):
        shutil.copy2(source, seed / source.name)
    license_dir = package / "licenses"
    license_dir.mkdir(exist_ok=True)
    for candidate in (Path(f"/usr/share/doc/python{sys.version_info.major}.{sys.version_info.minor}/copyright"),
                      Path("/usr/share/doc/python3/copyright")):
        if candidate.is_file():
            shutil.copy2(candidate, license_dir / "python-copyright.txt")
            break
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONHOME": str(runtime),
           "PYTHONNOUSERSITE": "1", "LD_LIBRARY_PATH": str(lib), "PYTHONPATH": str(site)}
    subprocess.run([str(bin_dir / "python3"), "-c", "import unittest, compileall; from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('Python helper and cryptography ready')"],
                   env=env, check=True, timeout=30)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_packaged_dev.py REPOSITORY PACKAGE_DIRECTORY")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
