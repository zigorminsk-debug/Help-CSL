#!/usr/bin/env bash
# Сборка HelpCSL-Setup.msi (нужны пакеты: wixl / msitools).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HOME/HelpCSL-Setup.msi}"
EXE="${2:-$HOME/HelpCSL.exe}"
cd "$(dirname "$0")"
if [[ ! -f "$EXE" ]]; then
  echo "Нет $EXE — сначала соберите HelpCSL.exe" >&2
  exit 1
fi
cp -f "$EXE" HelpCSL.exe
cp -f "$ROOT/assets/icon.ico" icon.ico
cp -f license.rtf License.rtf
wixl --ext ui -a x64 -o "$OUT" HelpCSL.wxs
rm -f HelpCSL.exe
ls -lh "$OUT"
echo "Готово: $OUT"
