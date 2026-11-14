# -*- coding: utf-8 -*-
"""生成 PWA 图标：深蓝底 + PE 走势折线 + 分位色带与指针 + PE 10Y 字样"""
from PIL import Image, ImageDraw, ImageFont
import os

NAVY = (18, 58, 107)
HILITE = (24, 74, 132)
BANDS = [(10, 160, 110), (92, 190, 90), (240, 200, 70), (240, 140, 50), (224, 56, 78)]


def band_color(t):
    seg = t * (len(BANDS) - 1)
    k = min(int(seg), len(BANDS) - 2)
    f = seg - k
    return tuple(int(BANDS[k][j] + (BANDS[k + 1][j] - BANDS[k][j]) * f) for j in range(3))


def make(size):
    im = Image.new("RGB", (size, size), NAVY)
    d = ImageDraw.Draw(im)
    # 右上斜向高光
    d.polygon([(int(.60 * size), 0), (size, 0), (size, int(.40 * size))], fill=HILITE)
    # 白色 PE 走势折线
    pts = [(.12, .43), (.24, .35), (.36, .40), (.48, .27), (.60, .32), (.72, .21), (.87, .26)]
    xy = [(int(x * size), int(y * size)) for x, y in pts]
    d.line(xy, fill=(255, 255, 255), width=max(3, int(.028 * size)), joint="curve")
    ex, ey = xy[-1]
    r = int(.030 * size)
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255))
    # 分位渐变色带
    x0, x1 = int(.12 * size), int(.88 * size)
    y0, y1 = int(.60 * size), int(.70 * size)
    n = 64
    for i in range(n):
        xa = x0 + (x1 - x0) * i / n
        xb = x0 + (x1 - x0) * (i + 1) / n + 1
        d.rectangle([int(xa), y0, int(xb), y1], fill=band_color(i / (n - 1)))
    # 白色指针
    px = x0 + int((x1 - x0) * 0.53)
    d.line([(px, int(.545 * size)), (px, int(.755 * size))],
           fill=(255, 255, 255), width=max(3, int(.020 * size)))
    d.polygon([(px - int(.038 * size), int(.545 * size)),
               (px + int(.038 * size), int(.545 * size)),
               (px, int(.605 * size))], fill=(255, 255, 255))
    # 底部文字
    fp = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font = ImageFont.truetype(fp, int(.115 * size))
    except Exception:
        font = ImageFont.load_default()
    d.text((size / 2, int(.845 * size)), "PE 10Y", font=font,
           fill=(255, 255, 255), anchor="mm")
    return im


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
    os.makedirs(out, exist_ok=True)
    for sz in (192, 512):
        make(sz).save(os.path.join(out, f"icon-{sz}.png"))
        print("icon", sz)
