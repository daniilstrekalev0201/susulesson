"""Проверка: все символы исходников есть в Times New Roman (иначе в PDF будут квадратики)."""
import glob, os, sys
from fontTools.ttLib import TTFont

FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
# Times New Roman + запасной Segoe UI Symbol (его подставляет build.py для математических знаков).
cmap = set(TTFont(os.path.join(FONTS, "times.ttf")).getBestCmap()) | set(
    TTFont(os.path.join(FONTS, "seguisym.ttf")).getBestCmap())
bad = 0
for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "src", "**", "*.txt"), recursive=True)):
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        miss = {c for c in line if ord(c) > 127 and ord(c) not in cmap}
        if miss:
            bad += 1
            print(f"{os.path.relpath(path)}:{n}: {' '.join(sorted(miss))}")
sys.exit(1 if bad else 0)
