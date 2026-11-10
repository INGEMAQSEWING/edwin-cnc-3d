# Aplica la marca EDWIN CNC 3D sobre el código de IngeTrazo (una sola vez; falla si algo no calza).
# Uso: py -3.10 edwin/aplicar_marca.py   (desde la raíz del repositorio)
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAMBIOS = {
    # ---- nombre del programa (y sus preferencias aparte de IngeTrazo)
    "main.py": [
        ('app.setApplicationName("IngeTrazo")\n    app.setOrganizationName("IngeTrazo")',
         'app.setApplicationName("EDWIN CNC 3D")\n    app.setOrganizationName("EDWIN CNC")'),
    ],
    "core/platform_choice.py": [
        ('QCoreApplication.setOrganizationName("IngeTrazo")', 'QCoreApplication.setOrganizationName("EDWIN CNC")'),
        ('QCoreApplication.setApplicationName("IngeTrazo")', 'QCoreApplication.setApplicationName("EDWIN CNC 3D")'),
    ],
    # ---- textos: "IngeTrazo" se muestra como "EDWIN CNC 3D"; idioma por defecto español
    "core/i18n.py": [
        ('    if choice and str(choice) != SYSTEM:\n        return str(choice)\n',
         '    if choice and str(choice) != SYSTEM:\n        return str(choice)\n'
         '    if not choice:\n        return "es"      # EDWIN CNC 3D: español por defecto\n'),
        ('def tr(text: str, /, **kwargs) -> str:',
         '#: EDWIN CNC 3D: nombre que se muestra en lugar de «IngeTrazo».\n'
         'NOMBRE_APP = "EDWIN CNC 3D"\n\n\n'
         'def tr_original(text: str, /, **kwargs) -> str:\n'
         '    """Como :func:`tr` pero sin cambiar el nombre (créditos de IngeTrazo)."""\n'
         '    out = _catalog.get(text, text)\n'
         '    if kwargs:\n'
         '        try:\n'
         '            out = out.format(**kwargs)\n'
         '        except (KeyError, IndexError, ValueError):\n'
         '            out = text.format(**kwargs)\n'
         '    return out\n\n\n'
         'def tr(text: str, /, **kwargs) -> str:'),
        ('            out = text.format(**kwargs)\n    return out\n',
         '            out = text.format(**kwargs)\n    return out.replace("IngeTrazo", NOMBRE_APP)\n'),
    ],
    # ---- milímetros por defecto
    "core/units.py": [
        ('DEFAULT_MODEL_UNITS = {"length": "m", "precision": 2}',
         'DEFAULT_MODEL_UNITS = {"length": "mm", "precision": 1}   # EDWIN CNC 3D: milímetros'),
    ],
    "core/scene.py": [
        ('units: dict = field(default_factory=lambda: {"length": "m", "precision": 2})',
         'units: dict = field(default_factory=lambda: {"length": "mm", "precision": 1})'),
        ('"decimals": 2, "units": "m", "font_size": 9,', '"decimals": 1, "units": "mm", "font_size": 9,'),
        ('self.units = {"length": "m", "precision": 2}', 'self.units = {"length": "mm", "precision": 1}'),
    ],
    # ---- actualizaciones: las de EDWIN CNC 3D, y apagado por defecto
    "core/update_check.py": [
        ('LATEST_API = "https://api.github.com/repos/ingelibre/ingetrazo/releases/latest"',
         'LATEST_API = "https://api.github.com/repos/INGEMAQSEWING/edwin-cnc-3d/releases/latest"'),
        ('RELEASES_PAGE = "https://github.com/ingelibre/ingetrazo/releases"',
         'RELEASES_PAGE = "https://github.com/INGEMAQSEWING/edwin-cnc-3d/releases"'),
        ('return str(settings.value(KEY_AUTO, "1")) != "0"', 'return str(settings.value(KEY_AUTO, "0")) != "0"'),
    ],
    # ---- título de la ventana
    "views/main_window.py": [
        ('            self.setWindowTitle("IngeTrazo")\n', '            self.setWindowTitle("EDWIN CNC 3D")\n'),
        ('self.setWindowTitle(f"IngeTrazo — {self._workspace.title()}{marker}")',
         'self.setWindowTitle(f"EDWIN CNC 3D — {self._workspace.title()}{marker}")'),
        ('self.setWindowTitle(f"IngeTrazo — {name}{marker}")', 'self.setWindowTitle(f"EDWIN CNC 3D — {name}{marker}")'),
    ],
    # ---- Acerca de: EDWIN CNC 3D arriba, créditos de IngeTrazo intactos
    "views/about_dialog.py": [
        ('para("<b style=\'font-size:15px\'>IngeTrazo</b> "\n'
         '             f"{tr(\'Version\')} {version}{gl}<br>"\n'
         '             f"{tr(\'Free 3D modeler for architecture, engineering and 3D design.\')}<br>"\n'
         '             f"{tr(\'Created by\')} <b>Marco Sumari Tellez</b> — "\n'
         '             f"{tr(\'Civil Engineer — Arequipa, Peru\')}")',
         'para("<b style=\'font-size:15px\'>EDWIN CNC 3D</b> "\n'
         '             f"{tr(\'Version\')} {version}{gl}<br>"\n'
         '             "Modelado 3D y desdoblado de láminas para corte CNC por plasma.<br>"\n'
         '             "Mejoras y marca: <b>EDWIN CNC</b> · "\n'
         '             "<a href=\'https://github.com/INGEMAQSEWING/edwin-cnc-3d\'>github.com/INGEMAQSEWING/edwin-cnc-3d</a>")\n'
         '        para("<b>Basado en IngeTrazo</b> "\n'
         '             f"— {tr(\'Free 3D modeler for architecture, engineering and 3D design.\')}<br>"\n'
         '             f"{tr(\'Created by\')} <b>Marco Sumari Tellez</b> — "\n'
         '             f"{tr(\'Civil Engineer — Arequipa, Peru\')}")'),
        ('self.setWindowTitle(tr("About IngeTrazo"))', 'self.setWindowTitle("Acerca de EDWIN CNC 3D")'),
    ],
    # ---- el cálculo del desdoblado va dentro del paquete
    "ingetrazo.spec": [
        ("    'core.textlabel',\n]", "    'core.textlabel',\n    'core.edwin_desdoblar',   # EDWIN CNC 3D: plugins/edwin_cnc.py\n]"),
    ],
}


def main():
    errores = 0
    for ruta, pares in CAMBIOS.items():
        p = os.path.join(RAIZ, ruta)
        with open(p, encoding="utf-8", newline="") as f:
            txt = f.read()
        crlf = "\r\n" in txt
        if crlf:
            txt = txt.replace("\r\n", "\n")
        for viejo, nuevo in pares:
            n = txt.count(viejo)
            if n != 1:
                print(f"NO CALZA ({n}) en {ruta}: {viejo[:70]!r}")
                errores += 1
                continue
            txt = txt.replace(viejo, nuevo)
        if crlf:
            txt = txt.replace("\n", "\r\n")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(txt)
    # créditos del Acerca de sin renombrar
    p = os.path.join(RAIZ, "views", "about_dialog.py")
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    import re
    m = re.search(r"^from core\.i18n import (.*)$", txt, re.M)
    if m and "tr_original" not in m.group(0):
        nombres = [x.strip() for x in m.group(1).strip("()").split(",") if x.strip()]
        if "tr" in nombres:
            nombres.remove("tr")
            nuevo = "from core.i18n import " + ", ".join(nombres + ["tr_original as tr"])
            txt = txt.replace(m.group(0), nuevo, 1)
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt)
        else:
            print("about_dialog: no importa tr de core.i18n en una línea simple")
            errores += 1
    elif not m:
        print("about_dialog: no se encontró 'from core.i18n import'")
        errores += 1
    print("marca aplicada" if not errores else f"{errores} cambio(s) sin aplicar")
    sys.exit(1 if errores else 0)


main()
