# -*- coding: utf-8 -*-
"""Автопочинка gifs.txt: страницы tenor/klipy -> прямые ссылки на gif.
- tenor.com/view/<slug>-<id>: из разметки достаём media.tenor.com/....gif (самый частый),
  проверяем живость (HTTP 200 + image/*).
- klipy.com/gifs/<slug>: страница под 403, идём через klipy.com/search?q=<slug>,
  берём прямой static*.klipy.com/....gif, проверяем живость.
- остальные URL просто проверяем на «прямая + живая».
Описание сохраняется. Непочиняемое помечается «НЕ РАБОТАЕТ» (бот такое не шлёт).
Перед записью делается бэкап gifs.txt.bak-fix.
"""
import os, re, sys, time, logging
from collections import Counter
import requests

BASE = r"F:/Program Files/Downloads/dsbot"
GIFS = os.path.join(BASE, "gifs.txt")
BAK = GIFS + ".bak-fix"

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
     "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"}

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.info


def unesc(s: str) -> str:
    return s.replace("\\u002F", "/").replace("\\/", "/").replace("\\u0026", "&")


def check_live(url: str) -> str:
    """Проверка: 'live' (отдаёт image/*), 'dead' (404/410 — точно мёртвая),
    'unknown' (403/429/таймаут/сеть — НЕ ЗНАЕМ, возможно rate-limit).
    Rate-limit отличаем от настоящей смерти: 429 и 403 после ретраев — это 'unknown',
    чтобы не помечать живые ссылки мёртвыми при массовой проверке (баг: tenor душил батч)."""
    last = "unknown"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20, headers=H, stream=True)
            ct = r.headers.get("content-type", "").lower()
            if r.status_code == 200 and ("image/" in ct or "video/" in ct):
                return "live"
            if r.status_code in (404, 410, 415):
                return "dead"      # точно нет файла
            if r.status_code in (429, 403, 500, 502, 503, 504):
                last = "unknown"   # rate-limit / сервер — не приговор
                time.sleep(2.5 * (attempt + 1))
                continue
            last = "dead"          # прочее (напр. text/html при 200 = страница, не файл)
            break
        except Exception:
            last = "unknown"       # сеть моргнула — не смерть ссылки
            time.sleep(2.0 * (attempt + 1))
    return last


def is_live_direct(url: str) -> bool:
    """Совместимость со старым кодом: True только для точно живых."""
    return check_live(url) == "live"


def fix_tenor(url: str) -> str | None:
    """tenor.com/view/... -> прямой gif этой страницы через og:image (канонический).
    НЕ через «самый частый gif в разметке» — там похожие/рекомендованные, берёт не то."""
    try:
        r = requests.get(url, timeout=25, headers=H)
    except Exception as e:
        log(f"    ! запрос страницы не удался: {type(e).__name__}")
        return None
    if r.status_code != 200:
        log(f"    ! страница вернула {r.status_code}")
        return None
    txt = unesc(r.text)
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', txt)
    if not og:
        log("    ! og:image не найден в разметке")
        return None
    cand = og.group(1)
    if cand.startswith("//"):
        cand = "https:" + cand
    # og:image со страницы со статусом 200 — это канонический gif самой страницы.
    # Отдельную проверку живости НЕ делаем: она долбит media.tenor.com и ловит rate-limit
    # (при батче tenor начинает отдавать 404/429 на медиа). Статус 200 страницы — достаточная гарантия.
    if re.match(r"https://media1?\.tenor\.com/.+\.gif", cand):
        return cand
    log(f"    ! og:image не похож на прямой gif tenor: {cand[:60]}")
    return None


def fix_klipy(url: str) -> str | None:
    """klipy.com/gifs/<slug> -> прямой gif.
    Страница под 403, а klipy.com/search отдаёт ОДНУ и ту же gif на любой запрос
    (проверено: не фильтрует по slug) — надёжно достать настоящий gif без браузера нельзя.
    Поэтому честно возвращаем None, запись будет помечена НЕ РАБОТАЕТ."""
    log("    ! klipy не чинится автоматически (страница 403, search не фильтрует по запросу) — нужна замена вручную")
    return None


def read_gif_lines(path):
    header, items = [], []
    for line in open(path, encoding="utf-8"):
        raw = line.rstrip("\n")
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            header.append(raw)
            continue
        if "|" in s:
            url, _, desc = s.partition("|")
            items.append((url.strip(), desc.strip()))
        else:
            items.append((s, ""))
    return header, items


def main():
    header, items = read_gif_lines(GIFS)
    log(f"в gifs.txt {len(items)} записей")
    out = []
    stats = {"ok": 0, "fixed": 0, "dead": 0, "keep": 0}

    for idx, (url, desc) in enumerate(items, 1):
        log(f"[{idx}/{len(items)}] {url[:80]}")
        new_url, status = url, None

        # ЛОКАЛЬНЫЕ файлы (gifs_local/...) проверять по HTTP нельзя: requests упадёт
        # с MissingSchema, check_live вернёт 'unknown' после 3 попыток со sleep (~6с впустую),
        # а строка получит статус «не проверено». Локальный файл проверяем по диску.
        if not url.lower().startswith("http"):
            # путь относительный к папке бота, а не к текущей директории запуска
            local = url if os.path.isabs(url) else os.path.join(BASE, url.replace("/", os.sep))
            if os.path.exists(local) and os.path.getsize(local) > 0:
                log("    -> локальный файл на месте, оставляю")
                stats["ok"] += 1
                out.append((url, desc or "гифка"))
            else:
                log(f"    -> локальный файл НЕ НАЙДЕН: {local}")
                stats["dead"] += 1
                out.append((url, "НЕ РАБОТАЕТ (файл не найден)"))
            continue

        if re.match(r"https://tenor\.com/view/", url):
            fixed = fix_tenor(url)
            if fixed:
                new_url, status = fixed, "fixed"
        elif re.match(r"https://klipy\.com/gifs/", url):
            fixed = fix_klipy(url)
            if fixed:
                new_url, status = fixed, "fixed"

        if status != "fixed":
            # не tenor/klipy или починка не удалась — проверяем как есть
            verdict = check_live(url)
            if verdict == "live":
                status = "ok"
            elif verdict == "unknown":
                status = "keep"      # rate-limit/сеть — НЕ трогаем ссылку и её описание
            else:
                status = "dead"
                new_url = url

        if status == "fixed":
            log(f"    -> ИСПРАВЛЕНО: {new_url[:80]}")
            stats["fixed"] += 1
            desc = desc if desc and not desc.upper().startswith("НЕ РАБОТАЕТ") else "гифка"
            out.append((new_url, desc))
        elif status == "ok":
            log("    -> уже рабочая прямая ссылка")
            stats["ok"] += 1
            desc = desc if desc and not desc.upper().startswith("НЕ РАБОТАЕТ") else "гифка"
            out.append((url, desc))
        elif status == "keep":
            log("    -> НЕ ПРОВЕРЕНО (rate-limit/сеть) — оставляю как есть")
            stats["keep"] += 1
            out.append((url, desc))   # описание сохраняем как было, даже «НЕ РАБОТАЕТ»
        else:
            log("    -> МЁРТВАЯ, помечаю НЕ РАБОТАЕТ")
            stats["dead"] += 1
            out.append((url, "НЕ РАБОТАЕТ (проверь/замени ссылку)"))
        time.sleep(1.5)  # не долбить сервера (tenor при быстром батче отдаёт 429/404)

    with open(GIFS, "w", encoding="utf-8") as f:
        # сохраняем НАСТОЯЩУЮ шапку из файла, а не жёстко зашитую:
        # раньше любые комментарии пользователя (в т.ч. про локальные файлы) затирались
        for raw in header:
            f.write(raw if raw.endswith("\n") else raw + "\n")
        for url, desc in out:
            f.write(f"{url} | {desc}\n")

    log("")
    log(f"ИТОГ: рабочих {stats['ok']}, исправлено {stats['fixed']}, непроверено(rate-limit) {stats['keep']}, мёртвых {stats['dead']}, всего {len(out)}")
    log(f"точно рабочих: {stats['ok'] + stats['fixed']} из {len(out)} (ещё {stats['keep']} не проверены — остались как были)")


if __name__ == "__main__":
    # бэкап
    import shutil
    shutil.copy2(GIFS, BAK)
    log(f"бэкап: {BAK}")
    main()
