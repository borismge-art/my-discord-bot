# -*- coding: utf-8 -*-
"""Генератор описаний гифок через зрение шлюза.
Читает gifs.txt, для каждой рабочей ссылки качает GIF, берёт несколько кадров,
просит модель описать 'какую ситуацию/эмоцию иллюстрирует' в <=8 слов.
Перезаписывает gifs.txt в формате 'URL | описание', битые помечает.
Ключ из .env, в вывод не попадает."""
import os, io, re, base64, struct, zlib, logging, requests, imageio.v3 as iio
logging.disable(logging.INFO)
from dotenv import load_dotenv
from openai import OpenAI

BASE = r"F:/Program Files/Downloads/dsbot"
load_dotenv(os.path.join(BASE, ".env"))
client = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=os.getenv("LLM_BASE_URL"))
model = os.getenv("LLM_MODEL", "claude-sonnet-5")

GIFS = os.path.join(BASE, "gifs.txt")
HDR = {"User-Agent": "Mozilla/5.0"}


def read_gif_lines(path):
    """-> (комментарии-шапка, [(url, существующее_описание или None), ...])"""
    header, items = [], []
    for line in open(path, encoding="utf-8"):
        raw = line.rstrip("\n")
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            header.append(raw)
            continue
        # формат 'URL | описание' или просто 'URL'
        if "|" in s:
            url, _, desc = s.partition("|")
            items.append((url.strip(), desc.strip() or None))
        else:
            items.append((s, None))
    return header, items


def frames_as_png_urls(data: bytes, n=3):
    """GIF bytes -> список data:image/png;base64 для n равномерно взятых кадров."""
    try:
        frames = iio.imread(io.BytesIO(data), plugin="pillow")  # (N,H,W,3or4)
    except Exception as e:
        return [], f"read fail: {type(e).__name__}: {e}"
    import numpy as np
    arr = np.asarray(frames)
    if arr.ndim == 3:          # одиночный кадр
        arr = arr[None, ...]
    total = arr.shape[0]
    idxs = sorted(set(int(round(i)) for i in np.linspace(0, total - 1, min(n, total))))

    def to_png(px):
        px = px[..., :3].astype("uint8")  # отбросить альфу
        h, w, _ = px.shape
        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
        raw = b"".join(b"\x00" + px[y].tobytes() for y in range(h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

    urls = ["data:image/png;base64," + base64.b64encode(to_png(arr[i])).decode() for i in idxs]
    return urls, f"{total} frames -> {len(urls)} shown"


def describe(urls):
    content = [{"type": "text", "text": (
        "Это несколько кадров одной анимированной GIF (по порядку). "
        "Опиши ОДНОЙ короткой фразой до 8 слов по-русски, КАКУЮ ситуацию или эмоцию она иллюстрирует — "
        "так, чтобы по описанию можно было понять, когда её уместно отправить в чат. "
        "Без вступлений, только сама фраза."
    )}]
    for u in urls:
        content.append({"type": "image_url", "image_url": {"url": u}})
    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}], max_tokens=40)
    return (r.choices[0].message.content or "").strip()


header, items = read_gif_lines(GIFS)
out_items = []
for url, existing in items:
    print("→", url[:70])
    try:
        r = requests.get(url, timeout=25, headers=HDR)
        ok = r.status_code == 200 and r.headers.get("content-type", "").lower().startswith("image/")
    except Exception as e:
        r, ok = None, False
        print("   сетевая ошибка:", type(e).__name__, str(e)[:80])
    if not ok:
        code = r.status_code if r is not None else "ERR"
        note = existing or "НЕ РАБОТАЕТ (проверь/замени ссылку)"
        out_items.append((url, note))
        print(f"   ✗ статус {code} — помечена как битая")
        continue
    urls, info = frames_as_png_urls(r.content)
    print(f"   {info}, {len(r.content)//1024} KB")
    if not urls:
        out_items.append((url, existing or "описание не удалось (не GIF?)"))
        print("   ✗ не удалось разобрать кадры")
        continue
    try:
        desc = describe(urls)
    except Exception as e:
        desc = existing or "описание не удалось"
        print("   ✗ ошибка описания:", type(e).__name__, str(e)[:80])
    desc = re.sub(r"\s+", " ", desc).strip(" .\"'`")
    out_items.append((url, desc or existing or "гифка"))
    print("   ✓ описание:", desc)

# перезапись gifs.txt
with open(GIFS, "w", encoding="utf-8") as f:
    if header:
        f.write("\n".join(header) + "\n")
    f.write("# Формат: URL | короткое описание (когда уместна). Описания сгенерированы через зрение модели.\n")
    f.write("# Битые ссылки помечены — замени их на рабочие прямые (https://.../file.gif).\n")
    for url, desc in out_items:
        f.write(f"{url} | {desc}\n")
print("\ngifs.txt перезаписан. Итог:")
for url, desc in out_items:
    print(f"  {desc}   <-   {url[:55]}")
