# EDWIN CNC 3D: usa EDWIN_VERSION (core/version.py) en Acerca de y en el aviso de actualización.
# Uso: py -3.10 edwin/aplicar_version.py (desde la raíz; una sola vez, falla si algo no calza)
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMBIOS = {
    "core/update_check.py": [
        ("from core.version import USER_AGENT, __version__",
         "from core.version import USER_AGENT, EDWIN_VERSION as __version__"),
    ],
    "views/about_dialog.py": [
        ('para("<b style=\'font-size:15px\'>EDWIN CNC 3D</b> "\n             f"{tr(\'Version\')} {version}{gl}<br>"',
         'from core.version import EDWIN_VERSION\n'
         '        para("<b style=\'font-size:15px\'>EDWIN CNC 3D</b> "\n'
         '             f"{tr(\'Version\')} {EDWIN_VERSION} (IngeTrazo {version}){gl}<br>"'),
    ],
}
mal = 0
for ruta, pares in CAMBIOS.items():
    p = os.path.join(RAIZ, ruta)
    with open(p, encoding="utf-8", newline="") as f:
        t = f.read()
    crlf = "\r\n" in t
    t = t.replace("\r\n", "\n")
    for a, b in pares:
        if t.count(a) != 1:
            print(f"NO CALZA ({t.count(a)}) en {ruta}: {a[:60]!r}")
            mal += 1
            continue
        t = t.replace(a, b)
    if crlf:
        t = t.replace("\n", "\r\n")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)
print("versión aplicada" if not mal else f"{mal} sin aplicar")
sys.exit(1 if mal else 0)
