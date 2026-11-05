#!/usr/bin/env bash
# Build an x86-64 CPU-only portable directory on Linux (glibc >= 2.35).
set -euo pipefail
cd "$(dirname "$0")"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Build requires Linux x86-64.' >&2; exit 1; }
python=${BABYMIND_BUILD_PYTHON:-python3}
command -v "$python" >/dev/null || { echo "Python interpreter not found: $python" >&2; exit 1; }
command -v curl >/dev/null
command -v c++ >/dev/null
command -v cmake >/dev/null || { echo 'Install cmake to build the bundled llama.cpp runtime.' >&2; exit 1; }
"$python" -m venv .venv
.venv/bin/python -m pip install -e '.[build]'
.venv/bin/python - <<'PYTHON'
import pathlib, sys, sysconfig
libdir = pathlib.Path(sysconfig.get_config_var("LIBDIR") or "")
name = sysconfig.get_config_var("LDLIBRARY") or ""
if not name or not (libdir / name).is_file():
    sys.exit("Building requires the Python shared library (for Debian/Ubuntu install the matching libpython3.x package).")
PYTHON
mkdir -p build
archive=build/llama-b11960.tar.gz
if [[ ! -f $archive ]]; then
  curl --fail --location --retry 3 --output "$archive.part" https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/b11960
  mv "$archive.part" "$archive"
fi
echo '2b37ffa871595f90b94164f6c510ad9a34bd7f94da21557cc9878587e163af37  '"$archive" | sha256sum --check
# Discard only our generated build directories, so stale files cannot be mixed
# into the verified source archive or reused during compilation.
rm -rf -- build/llama-source build/llama-build
mkdir -p build/llama-source
tar -xzf "$archive" -C build/llama-source --strip-components=1
GIT_CEILING_DIRECTORIES="$PWD" cmake -S build/llama-source -B build/llama-build -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=OFF -DBUILD_SHARED_LIBS=OFF -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON -DLLAMA_CURL=OFF \
  -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_BUILD_UI=OFF -DLLAMA_BUILD_COMMIT=b11960
cmake --build build/llama-build --target llama-server --parallel "${BABYMIND_BUILD_JOBS:-2}"
.venv/bin/pyinstaller --noconfirm --clean --onedir --name BabyMind \
  --paths src --add-data 'src/babymind/web:babymind/web' run_desktop.py
mkdir -p dist/BabyMind/llama.cpp dist/BabyMind/licenses
cp build/llama-build/bin/llama-server dist/BabyMind/llama.cpp/
cp build/llama-source/LICENSE dist/BabyMind/licenses/llama.cpp-MIT.txt
cp LICENSE dist/BabyMind/LICENSE
cp NOTICE dist/BabyMind/NOTICE
cp docs/LINUX_PORTABLE.md dist/BabyMind/README.txt
.venv/bin/python scripts/build_packaged_dev.py "$PWD" "$PWD/dist/BabyMind"
printf 'Built dist/BabyMind; start with ./dist/BabyMind/BabyMind\n'
