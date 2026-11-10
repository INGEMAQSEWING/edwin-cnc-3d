# Marca EDWIN CNC 3D: genera los íconos del programa con el logo oficial de EDWIN CNC.
# Uso:  py -3.10 edwin/marca3d.py   (desde la raíz del repositorio)
# Reemplaza resources/icons/ingetrazo_*.png, ingetrazo_master.png e ingetrazo.ico
# (se conservan los nombres de archivo para no tocar el resto del programa).
import os
from PIL import Image, ImageDraw, ImageFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = Image.open(os.path.join(RAIZ, "edwin", "logo-edwin-cnc.png")).convert("RGBA")  # 2720x1000
ICONOS = os.path.join(RAIZ, "resources", "icons")
F = "C:/Windows/Fonts/"
AMARILLO = (255, 242, 0)
NEGRO = (18, 18, 18)


def font(n, s):
    return ImageFont.truetype(F + n, s)


# Brazo robot del logo (pictograma), recortado del PNG original.
BRAZO = LOGO.crop((round(1600 * 1.36), round(110 * 1.36), round(1870 * 1.36), round(410 * 1.36)))


def icono(S, texto="3D"):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = S // 6
    d.rounded_rectangle([0, 0, S - 1, S - 1], r, fill=NEGRO)
    m = max(2, S // 22)
    d.rounded_rectangle([m, m, S - 1 - m, S - 1 - m], r - m, fill=AMARILLO)
    m2 = m * 2
    d.rounded_rectangle([m2, m2, S - 1 - m2, S - 1 - m2], r - m2, outline=NEGRO, width=max(1, S // 40))
    bw = int(S * 0.5)
    bh = round(BRAZO.height * bw / BRAZO.width)
    b = BRAZO.resize((bw, bh), Image.LANCZOS)
    im.alpha_composite(b, ((S - bw) // 2 + S // 30, int(S * 0.12)))
    f = font("ariblk.ttf", int(S * 0.26))
    tw = d.textlength(texto, font=f)
    d.text(((S - tw) / 2, S * 0.60), texto, font=f, fill=NEGRO)
    return im


grande = icono(1024)
grande.save(os.path.join(ICONOS, "ingetrazo_master.png"))
for s in (16, 32, 48, 64, 128, 256, 512):
    img = icono(s) if s >= 48 else icono(256).resize((s, s), Image.LANCZOS)
    img.save(os.path.join(ICONOS, f"ingetrazo_{s}.png"))
tamanos = [16, 24, 32, 48, 64, 128, 256]
capas = [icono(s) if s >= 48 else icono(256).resize((s, s), Image.LANCZOS) for s in tamanos]
capas[-1].save(os.path.join(ICONOS, "ingetrazo.ico"), sizes=[(s, s) for s in tamanos], append_images=capas[:-1])
print("íconos EDWIN CNC 3D listos")
