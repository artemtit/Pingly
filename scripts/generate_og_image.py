# -*- coding: utf-8 -*-
"""
Генерирует web/static/og-image.png (1200x630) — превью для Telegram/VK/соцсетей.
Композиция: слева заголовок лендинга, справа стилизованная карточка чата
с напоминанием и кнопками «Буду / Отменяю» (тот же mini-UI язык, что на сайте).

Запуск:  python scripts/generate_og_image.py
Зависимости: Pillow. Шрифты: Segoe UI (Windows), fallback — DejaVu.
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(__file__), "..", "web", "static", "og-image.png")

# Палитра — design-tokens.css
ORANGE_500 = (249, 115, 22)
ORANGE_700 = (194, 65, 12)
ORANGE_100 = (255, 237, 213)
ORANGE_50 = (255, 247, 237)
ORANGE_200 = (254, 215, 170)
FG1 = (17, 24, 39)
FG2 = (75, 85, 99)
FG3 = (107, 114, 128)
GRAY_100 = (243, 244, 246)
GRAY_200 = (229, 231, 235)
BUBBLE_BG = (248, 250, 252)
BUBBLE_BR = (226, 232, 240)
GREEN_BG = (220, 252, 231)
GREEN_TX = (21, 128, 61)
WHITE = (255, 255, 255)


def font(size: int, weight: str = "regular"):
    from PIL import ImageFont

    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = {
        "bold": [os.path.join(windir, "Fonts", "segoeuib.ttf"), "DejaVuSans-Bold.ttf"],
        "semibold": [os.path.join(windir, "Fonts", "seguisb.ttf"), "DejaVuSans-Bold.ttf"],
        "regular": [os.path.join(windir, "Fonts", "segoeui.ttf"), "DejaVuSans.ttf"],
    }[weight]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def check(draw: ImageDraw.ImageDraw, x, y, size, color, width=4):
    """Галочка линиями — глифа U+2713 нет в Segoe UI."""
    draw.line([(x, y + size * 0.55), (x + size * 0.38, y + size * 0.95)], fill=color, width=width)
    draw.line([(x + size * 0.38, y + size * 0.95), (x + size, y + size * 0.08)], fill=color, width=width)


def main() -> None:
    img = Image.new("RGB", (W, H), WHITE)

    # Фон: вертикальный тёплый градиент
    top, bottom = (255, 252, 248), (245, 245, 247)
    for y in range(H):
        t = y / H
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=c)

    # Оранжевое гало сверху (мягкое пятно, размытое)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([620, -260, 1380, 240], fill=ORANGE_100 + (170,))
    halo = halo.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), halo)
    draw = ImageDraw.Draw(img)

    # --- Левая колонка -----------------------------------------------------
    x = 72
    # Вордмарк: оранжевая точка-«пинг» + Pingly
    draw.ellipse([x, 78, x + 22, 100], fill=ORANGE_500)
    draw.text((x + 34, 66), "Pingly", font=font(40, "bold"), fill=FG1)

    # Заголовок (строки разбиты так, чтобы не заезжать под карточку справа)
    hl = font(54, "bold")
    draw.text((x, 178), "Ученики приходят.", font=hl, fill=FG1)
    draw.text((x, 244), "Ты не пишешь", font=hl, fill=FG1)
    draw.text((x, 310), "ни одного напоминания.", font=hl, fill=FG1)

    # Подзаголовок
    draw.text((x, 420), "Автонапоминания в Telegram", font=font(30, "regular"), fill=FG2)
    draw.text((x, 460), "для репетиторов", font=font(30, "regular"), fill=FG2)

    # Пилл внизу
    pill_f = font(24, "semibold")
    pill_t = "14 дней бесплатно · карта не нужна"
    tw = draw.textlength(pill_t, font=pill_f)
    rounded(draw, [x, 528, x + tw + 48, 528 + 52], 26, fill=ORANGE_100)
    draw.text((x + 24, 538), pill_t, font=pill_f, fill=ORANGE_700)

    # --- Правая колонка: карточка чата -------------------------------------
    cx, cy, cw, ch = 764, 96, 372, 438

    # Тень карточки
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [cx + 6, cy + 22, cx + cw + 6, cy + ch + 22], radius=32, fill=(15, 23, 42, 60)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    img = Image.alpha_composite(img, shadow)
    draw = ImageDraw.Draw(img)

    rounded(draw, [cx, cy, cx + cw, cy + ch], 32, fill=WHITE, outline=GRAY_200, width=1)

    # Шапка чата
    draw.ellipse([cx + 24, cy + 24, cx + 60, cy + 60], fill=ORANGE_500)
    draw.text((cx + 33, cy + 25), "P", font=font(26, "bold"), fill=WHITE)
    draw.text((cx + 72, cy + 22), "Pingly", font=font(22, "semibold"), fill=FG1)
    draw.ellipse([cx + 72, cy + 56, cx + 82, cy + 66], fill=(34, 197, 94))
    draw.text((cx + 90, cy + 50), "бот · онлайн", font=font(18, "regular"), fill=FG3)

    # Баббл бота
    bx, by, bw, bh = cx + 24, cy + 92, cw - 88, 116
    rounded(draw, [bx, by, bx + bw, by + bh], 18, fill=BUBBLE_BG, outline=BUBBLE_BR, width=1)
    bf = font(21, "regular")
    draw.text((bx + 18, by + 14), "Привет, Маша! Занятие", font=bf, fill=FG1)
    draw.text((bx + 18, by + 44), "сегодня в 15:00.", font=bf, fill=FG1)
    draw.text((bx + 18, by + 76), "Подтверди, пожалуйста:", font=bf, fill=FG3)

    # Кнопки «Буду / Отменяю»
    btn_f = font(22, "semibold")
    b1x, b1y, b1w, b1h = cx + 24, by + bh + 18, 156, 54
    rounded(draw, [b1x, b1y, b1x + b1w, b1y + b1h], 14, fill=GREEN_BG)
    check(draw, b1x + 32, b1y + 17, 18, GREEN_TX)
    draw.text((b1x + 62, b1y + 12), "Буду", font=btn_f, fill=GREEN_TX)
    b2x = b1x + b1w + 12
    rounded(draw, [b2x, b1y, b2x + b1w, b1y + b1h], 14, fill=GRAY_100)
    draw.text((b2x + 26, b1y + 12), "Отменяю", font=btn_f, fill=FG2)

    # Ответ ученика (справа)
    r_t = "Буду"
    r_f = font(21, "semibold")
    rw = draw.textlength(r_t, font=r_f) + 74
    rx1 = cx + cw - 24
    ry = b1y + b1h + 18
    rounded(draw, [rx1 - rw, ry, rx1, ry + 48], 16, fill=GREEN_BG)
    check(draw, rx1 - rw + 20, ry + 15, 16, GREEN_TX)
    draw.text((rx1 - rw + 46, ry + 9), r_t, font=r_f, fill=GREEN_TX)

    # Пуш репетитору
    nx, ny = cx + 24, ry + 48 + 18
    nw, nh = cw - 48, 62
    rounded(draw, [nx, ny, nx + nw, ny + nh], 14, fill=ORANGE_50, outline=ORANGE_200, width=1)
    draw.text((nx + 16, ny + 6), "Репетитору:", font=font(19, "semibold"), fill=FG1)
    draw.text((nx + 16, ny + 32), "Маша подтвердила занятие", font=font(19, "regular"), fill=FG2)

    out = os.path.abspath(OUT)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print("saved:", out, img.size)


if __name__ == "__main__":
    main()
