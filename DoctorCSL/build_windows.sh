#!/usr/bin/env bash
# Сборка HelpCSL.exe через Wine + официальный CPython для Windows.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-csl}"
export WINEARCH=win64
export WINEDEBUG=-all
export WINEDLLOVERRIDES="mscoree,mshtml="
PY_VER="3.12.10"
PY_EXE="$ROOT/build/python-${PY_VER}-amd64.exe"
PY_URL="https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-amd64.exe"
WIN_PY='C:\\Python312\\python.exe'

mkdir -p "$ROOT/build" "$ROOT/dist"

if ! command -v wine >/dev/null; then
  echo "Нужен wine" >&2
  exit 1
fi

if [[ ! -f "$PY_EXE" ]]; then
  echo "Скачиваю CPython ${PY_VER} для Windows…"
  curl -L --fail -o "$PY_EXE" "$PY_URL"
fi

echo "Инициализация Wine prefix…"
wineboot --init || true

if ! wine "$WIN_PY" -c "import tkinter,sys; print(sys.version)" >/tmp/winpy.out 2>/tmp/winpy.err; then
  echo "Тихая установка Python…"
  wine "$PY_EXE" /quiet InstallAllUsers=1 PrependPath=0 Include_launcher=0 \
    Include_test=0 Include_doc=0 Include_pip=1 Include_tcltk=1 \
    CompileAll=0 Shortcuts=0 AssociateFiles=0 \
    TargetDir=C:\\Python312 || true
  sleep 3
fi

echo "Проверка Windows Python…"
wine "$WIN_PY" -c "import tkinter,sys; print('PY', sys.version)"

echo "Зависимости…"
wine "$WIN_PY" -m pip install --upgrade pip
wine "$WIN_PY" -m pip install --upgrade pyinstaller requests pillow

echo "PyInstaller…"
cd "$ROOT"
rm -rf build/pyi dist/HelpCSL.exe dist/DoctorCSL.exe
wine "$WIN_PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyi DoctorCSL.spec
ls -lh dist/HelpCSL.exe
echo "Готово: $ROOT/dist/HelpCSL.exe"
