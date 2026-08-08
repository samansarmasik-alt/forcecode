#!/usr/bin/env python3
"""Deterministic guard: sessiz icra sozlesmesi — niyet aciklamasi yerine dogrudan arac."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).parents[1]
TARGET = ROOT / "forgecode.py"


def main() -> int:
    text = TARGET.read_text(encoding="utf-8", errors="replace")
    checks = []
    # 1. Sabit tanimli mi
    if "SILENT_EXECUTION_BANNED_PHRASES" not in text:
        print("FAIL: SILENT_EXECUTION_BANNED_PHRASES sabiti yok", file=sys.stderr)
        return 1
    checks.append("constant")
    # 2. Sessiz icra dokumani var mi (SILENT DIRECT EXECUTION)
    if "SILENT DIRECT EXECUTION" not in text:
        print("FAIL: SILENT DIRECT EXECUTION dokumani yok", file=sys.stderr)
        return 1
    checks.append("doc")
    # 3. Dusuncme/niyet strip mekanizmasi var mi
    if "_THINKING_MARKERS" not in text or "_THINKING_STRIP_RE" not in text:
        print("FAIL: thinking strip mekanizmasi eksik", file=sys.stderr)
        return 1
    checks.append("thinking")
    # 4. Guard kendisi bos degil
    self_text = pathlib.Path(__file__).read_text(encoding="utf-8")
    if len(self_text) < 200:
        print("FAIL: guard dosyasi bos", file=sys.stderr)
        return 1
    print(f"SILENT_EXECUTION OK: {','.join(checks)} — yasakli niyet ifadeleri icin dogrudan arac sozlesmesi aktif.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
