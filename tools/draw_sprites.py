"""Draw WidgetCity's original, reusable low-resolution PNG sprites (requires Pillow)."""

from pathlib import Path
from random import Random

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "widgetcity" / "sprites"
INK = "#171322"


def canvas(size):
    img = Image.new("RGBA", size)
    return img, ImageDraw.Draw(img)


def save(img, name):
    img.save(OUT / (name + ".png"), optimize=True)


def terrain():
    colors = {
        "grass": ("#302939", "#48384a", "#242233", "#393044", "#50394c"),
        "stone": ("#433440", "#574252", "#322938", "#4f3b4b", "#694b50"),
        "road": ("#59414a", "#6b4b52", "#3c303c", "#684b50", "#79545a"),
        "rail": ("#3c333e", "#534051", "#302a39", "#483847", "#5b4950"),
        "water": ("#112d3d", "#1a3c4b", "#132638", "#173848", "#215163"),
    }
    for kind, (base, edge, deep, high, warm) in colors.items():
        for variant in range(4):
            rng = Random(90 + variant)
            img, d = canvas((48, 36))
            if kind != "water":
                d.polygon([(0, 12), (24, 24), (47, 12), (47, 23), (24, 35), (0, 23)], fill=deep)
                d.polygon([(0, 13), (24, 25), (24, 34), (0, 22)], fill=edge)
                for nx in range(1, 47):
                    ny = 24 - abs(24 - nx) // 2
                    d.line((nx, ny + 3, nx, ny + 4), fill=base)
                    if nx % 8 == 1:
                        d.line((nx, ny + (1 if nx % 16 == 1 else 5), nx, ny + (3 if nx % 16 == 1 else 9)), fill=deep)
                d.line([(0, 22), (24, 34), (47, 23)], fill=INK)
            d.polygon([(0, 12), (24, 0), (47, 12), (24, 24)], fill=base)
            d.line([(0, 12), (24, 0), (47, 12)], fill=edge)
            d.line([(0, 12), (24, 24), (47, 12)], fill=high)
            for _ in range(90):
                x = rng.randrange(2, 46)
                radius = min(x, 48 - x) // 2
                if radius < 2:
                    continue
                y = 12 + rng.randrange(1 - radius, radius)
                color = rng.choice((base, high, deep, warm))
                d.line((x, y, min(x + rng.randrange(1, 4), 47 - 2 * abs(y - 12)), y), fill=color)
            if kind in ("road", "stone"):
                for offset in range(3, 24, 4):
                    d.line((24 - 2 * offset + max(0, offset - 12) * 4, offset,
                            24 + 2 * offset - max(0, offset - 12) * 4, offset), fill=deep)
                    for x in range(4 + (offset % 8) * 2, 45, 8):
                        if abs(x - 24) < 21 - 2 * abs(offset - 12):
                            d.point((x, offset - 1), fill=edge)
            if kind == "rail":
                for x in (15, 21, 27, 33):
                    y = x // 2
                    d.line((x - 5, y + 3, x + 5, y - 2), fill="#8e6557", width=2)
                for offset in (-3, 3):
                    d.line((12, 7 + offset, 35, 18 + offset), fill="#241f2b", width=2)
                    d.line((12, 6 + offset, 35, 17 + offset), fill="#bc8c72")
                d.line((10, 17, 24, 24, 37, 18), fill="#705568")
                if variant in (1, 3):
                    d.polygon([(9, 23), (11, 21), (15, 23), (17, 26), (17, 29), (9, 25)], fill="#201f30")
                    d.line((9, 22, 11, 20, 15, 22, 18, 26), fill="#634b5d")
            save(img, f"{kind}{variant}")


def window(d, x, y, width, height, slope, light=False):
    rise = int(width * slope / 2)
    d.polygon([(x, y), (x + width, y + rise), (x + width, y + rise + height), (x, y + height)],
              fill="#f2a652" if light else "#191624", outline="#ac6348" if light else "#6e4850")
    if light:
        d.line((x + 1, y + 1, x + 1, y + height - 1), fill="#ffcd76")
        d.line((x + width - 1, y + rise + 1, x + width - 1, y + rise + height - 1), fill="#ffd88d")
    mid = y + height // 2
    d.line((x, mid, x + width, mid + rise), fill="#9a533e" if light else "#453342")
    d.line((x + width // 2, y + rise // 2, x + width // 2, y + rise // 2 + height), fill="#8b5041" if light else "#423044")


def building(name, walls, roof, width, height, apex, number, editable=False):
    img, d = canvas((72, 80))
    lit, glow = canvas(img.size)
    left, right, trim = walls
    roof_a, roof_b, shingle = roof
    rng = Random(number)
    x, y = 36, 66
    sx, sy = width, width // 2
    w, s, e = (x - sx, y), (x, y + sy), (x + sx, y)
    wl, sl, el = [(a, b - height) for a, b in (w, s, e)]
    nl = (x, y - sy - height)
    d.polygon([w, wl, sl, s], fill=left, outline=INK)
    d.polygon([s, sl, el, e], fill=right, outline=INK)
    for polarity, start, color in ((1, wl, left), (-1, sl, right)):
        for iy in range(3, height, 4):
            ax, ay = start
            d.line((ax + 1, ay + iy, ax + sx - 1, ay + iy + polarity * sy), fill=trim)
            for step in range(3 + (iy % 8), sx - 1, 7):
                tx, ty = ax + step, ay + iy + step * polarity // 2
                d.line((tx, ty, tx, ty + 2), fill=color if rng.random() < .55 else "#4b353d")
    for edge_x, edge_y in (w, s, e):
        d.line((edge_x, edge_y - height + 1, edge_x, edge_y - 1), fill="#231d2a")
    windows = []
    for level in range(6, height - 5, 12):
        for ax, ay, slope in ((wl[0] + 3, wl[1] + level + 1, 1), (sl[0] + 4, sl[1] + level - 2, -1)):
            for dx in range(0, sx - 8, 8 if name != "station" else 7):
                windows.append((ax + dx, ay + dx * slope // 2, 5, 6, slope))
    for spec in windows:
        window(d, *spec)
        if name in ("cafe", "station", "warehouse") or rng.random() > .24:
            window(glow, *spec, light=True)
    if name in ("cafe", "station", "warehouse"):
        dw = 9 if name != "warehouse" else 12
        d.polygon([(x + 2, y + sy - 10), (x + 2 + dw, y + sy - 10 - dw // 2),
                   (x + 2 + dw, y + sy - dw // 2), (x + 2, y + sy)], fill="#231c28", outline="#ad7157")
        d.line((x + 3, y + sy - 2, x + 1 + dw, y + sy - dw // 2 - 1), fill="#db9a5d")
    wall_shapes = ([w, wl, sl, s], [s, sl, el, e])
    a = (x - sx // 2, y - height - sy // 2 - apex)
    b = (x + sx // 2, y - height + sy // 2 - apex)
    wl = (wl[0] - 2, wl[1] + 1)
    sl = (sl[0], sl[1] + 2)
    el = (el[0] + 2, el[1] + 1)
    nl = (nl[0], nl[1] - 1)
    d.polygon([sl, b, el], fill=trim, outline=INK)
    d.polygon([a, b, el, nl], fill=roof_b, outline=INK)
    d.polygon([wl, a, b, sl], fill=roof_a, outline=INK)
    for step in range(3, 25, 3):
        t = step / 25
        px, py = (round(a[0] + (wl[0] - a[0]) * t), round(a[1] + (wl[1] - a[1]) * t))
        qx, qy = (round(b[0] + (sl[0] - b[0]) * t), round(b[1] + (sl[1] - b[1]) * t))
        d.line((px, py, qx, qy), fill=shingle)
        for spot in range(3 + rng.randrange(4), qx - px - 1, 6):
            jy = py + round((qy - py) * spot / (qx - px))
            d.point((px + spot, jy - 1), fill=roof_b)
    d.line([wl, a, b, el], fill=shingle)
    d.line([wl, sl, b], fill="#242131")
    d.line([b, el], fill="#946257")
    if name == "phone":
        beacon, signal = canvas(img.size)
        bx, by = a[0] + 9, a[1] + 5
        d.line((bx, by, bx, by - 20), fill="#b08883", width=2)
        d.line([(bx - 4, by - 1), (bx, by - 17), (bx + 5, by + 2)], fill="#8e6a73")
        d.line((bx - 3, by - 11, bx + 5, by - 8), fill="#9b7175")
        d.rectangle((bx - 1, by - 22, bx + 1, by - 20), fill="#552833")
        signal.rectangle((bx - 4, by - 24, bx + 4, by - 18), fill=(255, 94, 75, 44))
        signal.rectangle((bx - 2, by - 23, bx + 2, by - 19), fill="#f7886a")
        signal.rectangle((bx - 1, by - 22, bx + 1, by - 20), fill="#ffd283")
        save(beacon, "phone_beacon")
    elif name not in ("station", "weather", "cyber"):
        bx, by = a[0] + 4, a[1] + 6
        chimney = 20 if name == "warehouse" else 11
        d.polygon([(bx - 3, by - chimney), (bx + 3, by - chimney - 1), (bx + 3, by), (bx, by + 2), (bx - 3, by)], fill="#5b3c45", outline=INK)
        for iy in range(by - chimney + 3, by, 4):
            d.line((bx - 2, iy, bx + 2, iy), fill="#9c5b54")
        d.line((bx - 3, by - chimney, bx + 3, by - chimney), fill="#bd705c")
    if name in ("cafe", "station"):
        sx1, sy1 = x + 2, y + sy - height + 6
        sx2 = x + width - 2
        points = [(sx1, sy1), (sx2, sy1 - (sx2 - sx1) // 2), (sx2, sy1 - (sx2 - sx1) // 2 + 7), (sx1, sy1 + 7)]
        d.polygon(points, fill="#2c2836", outline="#926050")
        glow.polygon(points, fill="#67364a", outline="#ffbc70")
        for i in range(3, sx2 - sx1 - 1, 3):
            d.line((sx1 + i, sy1 - i // 2 + 2, sx1 + i, sy1 - i // 2 + 4), fill="#c7947a")
            glow.line((sx1 + i, sy1 - i // 2 + 2, sx1 + i, sy1 - i // 2 + 4), fill="#ffe2a0")
        if name == "cafe":
            d.polygon([(17, 57), (29, 63), (28, 68), (13, 61)], fill="#5e354e", outline="#382138")
            for i in range(4):
                px, py = 15 + i*3, 60 + i*3//2
                d.line((px, py, px + 2, py - 4), fill="#ba656d")
            d.line((14, 62, 28, 69), fill="#db977a")
            d.rectangle((b[0] - 1, b[1] + 2, b[0] + 2, b[1] + 5), fill="#e59679")
            glow.rectangle((b[0], b[1] + 2, b[0] + 1, b[1] + 4), fill="#ffe3a3")
        else:
            edge = (x + width + 5, y + 7)
            d.line((x + 4, y + sy + 1, *edge), fill="#ac7762", width=2)
    if name == "cyber":
        cyber_roof_sign(d, a)
    elif name in ("mail", "weather", "shop", "books"):
        landmark_details(name, d, glow, width, height)
    if editable:
        for layer, shapes, colors in (
            ("walls", wall_shapes, (*walls, "#4b353d")),
            ("roof", ([a, b, el, nl], [wl, a, b, sl]), roof),
        ):
            mask, brush = canvas(img.size)
            for polygon in shapes:
                brush.polygon(polygon, fill="white")
            allowed = {Image.new("RGB", (1, 1), color).getpixel((0, 0)) for color in colors}
            art_pixels, mask_pixels = img.load(), mask.load()
            for py in range(img.height):
                for px in range(img.width):
                    if art_pixels[px, py][:3] not in allowed:
                        mask_pixels[px, py] = (0, 0, 0, 0)
            save(mask, f"{name}_{layer}")
    save(img, name)
    save(lit, name + "_lit")


def cyber_roof_sign(draw, ridge):
    neon, light = canvas((72, 80))

    def panel(x, y):
        return ridge[0] - 5 + x, ridge[1] - 20 + y + x // 2

    corners = [panel(0, 0), panel(31, 0), panel(31, 12), panel(0, 12)]
    for x in (7, 23):
        draw.line([panel(x, 10), panel(x, 19)], fill="#171624", width=3)
        draw.line([panel(x, 12), panel(x, 19)], fill="#6c5167")
    draw.polygon(corners, fill="#241b33", outline="#77516d")
    light.polygon([panel(-1, -1), panel(32, -1), panel(32, 13), panel(-1, 13)],
                  fill=(246, 109, 214, 72))
    light.polygon(corners, fill="#392245", outline="#f9a5df", width=2)
    controller = [panel(x, y) for x, y in ((8, 3), (22, 3), (25, 9), (21, 9), (18, 7),
                                         (13, 7), (10, 9), (6, 9), (8, 3))]
    draw.line(controller, fill="#594264")
    light.line(controller, fill="#86ecff", width=2)
    light.line([panel(10, 5), panel(14, 5)], fill="#e9f7ff", width=2)
    light.line([panel(12, 4), panel(12, 7)], fill="#e9f7ff", width=2)
    light.line([panel(19, 5), panel(21, 5)], fill="#ffe0f5", width=2)
    save(neon, "cyber_neon")


def landmark_details(name, d, glow, width, height):
    extra, layer = canvas((72, 80))
    y = 66 + width // 2 - height + 4
    end = 36 + width - 3
    sign = [(39, y), (end, y - (end - 39) // 2), (end, y + 6 - (end - 39) // 2), (39, y + 6)]
    palettes = {
        "mail": ("#592d40", "#dfa681", "#ffcf96"),
        "weather": ("#284754", "#6ca2ae", "#acd5cf"),
        "shop": ("#3c3e5c", "#a09ccd", "#d5cbff"),
        "books": ("#494751", "#b59467", "#f0bd7c"),
    }
    dark, border, highlight = palettes[name]
    d.polygon(sign, fill=dark, outline=border)
    glow.polygon(sign, fill=dark, outline=highlight)
    for x in range(42, end - 1, 3):
        glow.line((x, y + 2 - (x - 39) // 2, x, y + 4 - (x - 39) // 2), fill=highlight)
    if name == "mail":
        d.rectangle((18, 59, 24, 67), fill="#462935", outline=INK)
        d.line((19, 60, 23, 60), fill="#d69a81")
        d.line((20, 64, 23, 64), fill="#f2b0a1")
        layer.line((25, 63, 25, 53), fill="#d08275", width=2)
        layer.rectangle((25, 53, 30, 56), fill="#e46979", outline="#ffb594")
        save(extra, "mail_flag")
    elif name == "weather":
        d.line((37, 29, 37, 17), fill="#a79b9b")
        d.ellipse((31, 32, 44, 40), fill="#345368", outline="#819799")
        d.line((35, 34, 40, 32), fill="#a3cac2")
    elif name == "shop":
        d.polygon([(16, 57), (23, 60), (23, 67), (16, 64)], fill="#997455", outline=INK)
        d.line((19, 59, 19, 65), fill="#c19a6f")
    elif name == "books":
        for x in range(16, 27, 2):
            d.line((x, 57 + (x - 16) // 2, x, 62 + (x - 16) // 2), fill=palettes["books"][x % 3])
        layer.polygon([(22, 53), (27, 55), (27, 61), (22, 59)], fill="#ffe1a4")
        layer.line((23, 56, 26, 57), fill="#85654f")
        save(extra, "books_note")


def tree(index):
    img, d = canvas((72, 80))
    rng = Random(210 + index)
    d.ellipse((22, 63, 54, 74), fill=(12, 13, 26, 100))
    d.polygon([(31, 70), (35, 65), (33, 48), (30, 44), (35, 45), (38, 52),
               (44, 43), (45, 47), (40, 57), (40, 66), (46, 69), (38, 68)], fill="#503746", outline="#221c2d")
    d.line([(35, 65), (37, 57), (35, 50)], fill="#895359")
    palettes = (
        ("#21192d", "#3f2444", "#593055", "#74395e", "#904665", "#ae637c"),
        ("#182930", "#2a424b", "#3b555b", "#4b6767", "#64917c", "#92ab9c"),
        ("#322231", "#543237", "#6e423e", "#945849", "#b77550", "#c5875e"),
    )
    if index == 1:
        d.line([(35, 66), (37, 53), (34, 44)], fill="#b6a4a3", width=3)
        for py in (56, 60, 64):
            d.point((36, py), fill="#422e3a")
    if index >= 3:
        if index == 5:
            for branch in ([(36, 67), (36, 36), (31, 26)], [(36, 50), (46, 38), (47, 32)],
                           [(36, 54), (27, 45), (25, 36)], [(38, 47), (43, 29)]):
                d.line(branch, fill="#493340", width=3)
                d.line(branch, fill="#986655")
        else:
            profile = [(37, 24), (21, 56), (47, 59), (53, 54)] if index == 3 else [(36, 17), (20, 61), (48, 65), (52, 61)]
            d.polygon(profile, fill="#22434a" if index == 3 else "#283c4c", outline="#192a39")
            for yy in range(32, 60, 5):
                radius = (yy - 21) // 3
                d.line((36 - radius, yy, 35, yy + 4), fill="#3e6870")
                d.line((35, yy + 4, 33 + radius, yy + 2), fill="#305159")
            for _ in range(44):
                yy = rng.randrange(32, 60)
                d.point((rng.randrange(36 - (yy - 24) // 4, 37 + (yy - 24) // 4), yy), fill="#42656c")
        save(img, f"tree{index}")
        return
    colors = palettes[index]
    for cx, cy, r in ((26, 47, 12), (47, 46, 12), (35, 43, 17), (18, 40, 10), (50, 37, 12),
                       (31, 29, 12), (41, 30, 13), (32, 39, 13)):
        d.ellipse((cx - r, cy - r * 2 // 3, cx + r, cy + r * 2 // 3), fill=colors[1], outline=colors[0])
        for _ in range(r * 5):
            x, y = rng.randrange(-r, r), rng.randrange(-r // 2, r // 2)
            if x*x + 3*y*y < r*r:
                px, py = cx + x, cy + y
                shade = rng.randrange(1, 5) + (y < -3)
                d.line((px, py, px + rng.randrange(1, 4), py), fill=colors[shade], width=rng.choice((1, 2)))
    save(img, f"tree{index}")


def props():
    for name in ("lamp", "bench", "shrubs", "crate", "van", "worker", "worker_step", "cat", "cat_step", "train", "engine"):
        img, d = canvas((72, 80))
        if name == "lamp":
            for radius, alpha in ((15, 12), (12, 19), (9, 30), (6, 42)):
                d.ellipse((36 - radius, 67 - radius // 3, 36 + radius, 67 + radius // 3), fill=(251, 131, 58, alpha))
            d.line((36, 66, 36, 45), fill="#171624", width=3)
            d.line((37, 65, 37, 45), fill="#a16b5d")
            d.rectangle((34, 42, 38, 48), fill="#3d2731")
            d.rectangle((35, 42, 37, 47), fill="#ffb34f")
            d.line((36, 42, 36, 46), fill="#fff4ab")
            d.line((34, 41, 38, 41), fill="#d28756")
        elif name == "bench":
            d.line((27, 66, 42, 59), fill="#1b1724", width=3)
            d.line((28, 61, 42, 54), fill="#9e6864", width=2)
            d.line((28, 63, 42, 56), fill="#9e6864", width=2)
            d.line((28, 65, 42, 58), fill="#c18369", width=2)
        elif name == "shrubs":
            for x, y in ((30, 67), (37, 65), (42, 69), (34, 69), (38, 68)):
                d.rectangle((x - 4, y - 4, x + 3, y + 1), fill="#40213c")
                d.line((x - 2, y - 3, x + 2, y - 3), fill="#864766")
                d.point((x + 1, y - 4), fill="#b9667a")
        elif name == "crate":
            d.polygon([(32, 60), (36, 58), (40, 60), (40, 65), (36, 67), (32, 65)], fill="#ad714d", outline="#57383b")
            d.line([(32, 60), (36, 62), (40, 60)], fill="#f1b471")
            d.line((36, 62, 36, 66), fill="#6b473e")
        elif name.startswith("cat"):
            d.line([(31, 64), (28, 63), (26, 60)], fill="#ba8057")
            d.rectangle((31, 62, 37, 65), fill="#d89160")
            d.rectangle((37, 60, 40, 63), fill="#efaa6d")
            d.point((38, 59), fill="#efaa6d")
            d.point((40, 59), fill="#efaa6d")
            d.point((40, 61), fill="#ffe690")
            step = 2 if name == "cat_step" else 0
            d.line((32, 64, 31 + step, 67), fill="#b67458")
            d.line((37, 64, 38 - step, 67), fill="#eea875")
        elif name.startswith("worker"):
            step = 3 if name == "worker_step" else 0
            d.line((34, 61, 33 + step, 68), fill="#453757", width=2)
            d.line((37, 61, 38 - step, 67), fill="#45415a", width=2)
            d.rectangle((33, 57, 38, 62), fill="#5c6e83")
            d.rectangle((34, 54, 37, 57), fill="#df9a72")
            d.line((33, 53, 38, 53), fill="#f7ba70", width=2)
            d.line((37, 58, 41, 61), fill="#d99b71")
        elif name == "van":
            d.polygon([(22, 61), (22, 53), (31, 47), (48, 55), (51, 63), (41, 69)], fill="#a45f62", outline="#241e2c")
            d.polygon([(22, 53), (31, 47), (46, 54), (37, 60)], fill="#e49b80")
            d.polygon([(37, 60), (46, 54), (49, 58), (40, 63)], fill="#53747e")
            d.line((40, 66, 50, 61), fill="#d59b77")
            d.line((42, 65, 44, 64), fill="#ffdd98")
            d.line((48, 62, 50, 61), fill="#ffdd98")
            for x, y in ((27, 64), (37, 69)):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#1c1c2d", outline="#49363d")
        elif name == "train":
            d.polygon([(12, 48), (23, 43), (59, 61), (59, 68), (49, 74), (12, 55)], fill="#264a5d", outline="#181a28")
            d.polygon([(12, 48), (23, 43), (59, 61), (49, 66)], fill="#386476", outline="#233b50")
            d.line((14, 53, 49, 71), fill="#d6875b")
            for x in range(16, 49, 5):
                y = 49 + (x - 12) // 2
                d.line((x, y, x + 2, y + 1), fill="#ffc370", width=3)
                d.point((x, y + 1), fill="#fff1a7")
            for x, y in ((18, 58), (27, 62), (38, 68), (47, 72)):
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill="#151c29", outline="#625565")
            d.line((54, 67, 56, 66), fill="#ffbe64", width=2)
        else:
            d.polygon([(14, 52), (25, 46), (59, 63), (59, 67), (50, 73), (14, 55)],
                      fill="#243443", outline="#171b29")
            d.polygon([(15, 49), (15, 39), (24, 34), (37, 41), (37, 55), (27, 60)],
                      fill="#2f5362", outline="#191e2b")
            d.polygon([(14, 39), (23, 33), (38, 40), (28, 46)], fill="#4a6a78", outline="#232a3b")
            d.line((18, 44, 23, 46), fill="#f7b66b", width=3)
            d.polygon([(29, 51), (36, 45), (54, 53), (60, 58), (56, 65), (49, 66), (29, 57)],
                      fill="#33737a", outline="#203844")
            d.line((35, 47, 53, 55), fill="#58888d", width=2)
            d.polygon([(48, 50), (48, 43), (53, 42), (54, 44), (53, 53)],
                      fill="#374451", outline="#202837")
            d.line((49, 43, 53, 43), fill="#9a736b")
            d.ellipse((51, 55, 59, 64), fill="#284959", outline="#c48b6a")
            d.rectangle((55, 57, 57, 60), fill="#ffcf85")
            for x, y in ((21, 58), (30, 62), (39, 67), (47, 71)):
                d.ellipse((x - 3, y - 3, x + 3, y + 2), fill="#1a2331", outline="#686070")
            d.line((23, 58, 44, 69), fill="#ae7a69")
        save(img, name)


def umbrellas():
    for step, name in enumerate(("umbrella", "umbrella_step")):
        img, d = canvas((72, 80))
        d.line((35, 61, 33 + step * 4, 68), fill="#73566e")
        d.line((38, 61, 40 - step * 5, 67), fill="#514661")
        d.rectangle((34, 56, 39, 62), fill="#705467", outline=INK)
        d.line((38, 51, 38, 61), fill="#a27e79")
        d.polygon([(26, 53), (30, 48), (38, 45), (44, 48), (48, 53), (40, 54), (33, 53)], fill="#795274", outline=INK)
        d.line([(30, 51), (38, 46), (43, 50)], fill="#cc849b")
        d.point((38, 44), fill="#efd2b8")
        save(img, name)


def arrows():
    for suffix, points in (("down", ((1, 3), (4, 6), (7, 3))), ("up", ((1, 6), (4, 3), (7, 6)))):
        img, d = canvas((9, 9))
        d.line(points, fill="#dfb1ba")
        save(img, "arrow_" + suffix)


def shore_stones():
    for index in range(3):
        img, d = canvas((72, 80))
        rng = Random(719 + index)
        for x, y, size in ((31, 63, 6), (37, 64, 7), (42, 67, 5), (28, 67, 3), (36, 69, 4)):
            x += rng.randrange(-2, 3)
            y += rng.randrange(-2, 3)
            d.polygon([(x-size, y), (x-size+2, y-4), (x+1, y-6), (x+size, y-2),
                       (x+size-1, y+2), (x, y+4)], fill="#2e2a3d", outline="#1b2636")
            d.line((x-size+2, y-3, x+1, y-5, x+size-1, y-2), fill="#655062")
            d.line((x-size+2, y+2, x, y+4), fill="#3e5566")
            d.point((x, y), fill="#7b6268")
        if index == 1:
            for x, y in ((28, 61), (31, 59), (33, 62), (35, 63)):
                d.line((x, y+4, x-1, y), fill="#6c475e")
                d.point((x-1, y), fill="#976276")
        save(img, f"shoal{index}")


def icon():
    img, d = canvas((64, 64))
    d.rounded_rectangle((1, 1, 62, 62), radius=13, outline="#885b6d", fill="#312338")
    facade = Image.open(OUT / "cafe.png")
    facade.alpha_composite(Image.open(OUT / "cafe_lit.png"))
    img.alpha_composite(facade.crop((12, 17, 60, 78)), (8, 1))
    img.save(OUT / "widgetcity.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    terrain()
    for index in range(6):
        tree(index)
    building("house0", ("#5c404b", "#75505a", "#523c4b"), ("#38364f", "#51435c", "#63516a"), 18, 21, 10, 1)
    building("house1", ("#533e50", "#695261", "#4c384c"), ("#34384e", "#49435a", "#615369"), 17, 27, 12, 12)
    building("house2", ("#5d454d", "#80585a", "#583c49"), ("#3c3246", "#543c53", "#6d4b65"), 17, 17, 9, 41)
    building("cafe", ("#693f4b", "#935753", "#6b4351"), ("#493953", "#65475e", "#8a5b72"), 21, 23, 12, 9, True)
    for name, walls, roof, width, height, apex, seed in (
        ("mail", ("#6b4a53", "#87575c", "#593a48"), ("#492f48", "#654251", "#805569"), 17, 19, 10, 161),
        ("weather", ("#3e5661", "#516c74", "#354653"), ("#394861", "#4b6272", "#5e777f"), 16, 24, 8, 162),
        ("shop", ("#59536a", "#76607a", "#484054"), ("#3a3b56", "#545373", "#665d80"), 20, 23, 8, 163),
        ("books", ("#594a52", "#775c56", "#483b47"), ("#354951", "#526469", "#6f7775"), 18, 21, 13, 164),
        ("cyber", ("#4f4664", "#6c5374", "#3d324e"), ("#352e53", "#4c426f", "#635583"), 21, 24, 6, 165),
    ):
        building(name, walls, roof, width, height, apex, seed, True)
    building("phone", ("#504155", "#675260", "#4c3f51"), ("#30384d", "#464a65", "#595972"), 19, 26, 10, 4)
    building("warehouse", ("#68434a", "#865346", "#633c40"), ("#463145", "#664454", "#87565f"), 22, 23, 10, 7)
    building("station", ("#655054", "#83564e", "#6a4851"), ("#303f55", "#405268", "#5a6278"), 22, 22, 12, 8)
    props()
    umbrellas()
    arrows()
    shore_stones()
    icon()
