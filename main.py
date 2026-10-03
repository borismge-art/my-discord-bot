import os
import re
import io
import json
import hashlib
import difflib
import base64
import asyncio
import contextlib
import time
import random
import string
import logging
from logging.handlers import TimedRotatingFileHandler
from collections import defaultdict, deque

import discord
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")  # openai-совместимый base_url твоего шлюза
LLM_MODEL = os.getenv("LLM_MODEL", "sonnet-5")  # уточни точное имя модели у продавца ключа

HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "12"))       # сколько последних сообщений канала помнить
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "3"))  # анти-спам между ответами в одном канале
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "300"))
CREATOR_NAME = os.getenv("CREATOR_NAME", "borisbrat").lower()  # юзернейм создателя: только ему положен титул и защита
PRESENCES = os.getenv("PRESENCES", "1") == "1"                 # читать активности (игры/spotify) — нужен Presence Intent в панели Discord
# сколько участников с активностью показывать в промпте при вопросе «во что играет X»
ACTIVITY_MAX_MEMBERS = int(os.getenv("ACTIVITY_MAX_MEMBERS", "25"))
# как часто прочёсывать участников сервера (сек). Без Members Intent кэш участников пуст,
# и discord.py ОТБРАСЫВАЕТ presence-события незнакомых людей — поэтому чужие игры не видны.
# Прочёс через query_members по префиксам a-z/0-9/_/. заполняет кэш без privileged intent.
MEMBER_SWEEP_INTERVAL = int(os.getenv("MEMBER_SWEEP_INTERVAL", "900"))
# гифки от этих пользователей бот игнорирует полностью (через запятую, юзернеймы):
# спам гифками ради реакции не получает ни ответа, ни траты токенов
GIF_IGNORE_USERS = {u.strip().lower() for u in os.getenv("GIF_IGNORE_USERS", "").split(",") if u.strip()}

# --- проактивный режим (бот сам решает, когда влезть в разговор без тега) ---
AUTO_REPLY = os.getenv("AUTO_REPLY", "1") == "1"                # 0 = старое поведение "только по тегу"
AUTO_COOLDOWN = int(os.getenv("AUTO_COOLDOWN", "60"))           # пауза после реального автоответа, сек
SILENT_COOLDOWN = int(os.getenv("SILENT_COOLDOWN", "15"))       # пауза после того как бот промолчал, сек
IMAGES_PER_REQUEST = int(os.getenv("IMAGES_PER_REQUEST", "3"))  # сколько последних картинок уходит в один запрос
IMAGE_MAX_MB = int(os.getenv("IMAGE_MAX_MB", "8"))              # картинки тяжелее этого не скачиваем
IMAGE_MAX_PX = int(os.getenv("IMAGE_MAX_PX", "1024"))           # длинная сторона картинки после сжатия, px (анти-413)
IMAGE_JPEG_Q = int(os.getenv("IMAGE_JPEG_Q", "85"))             # качество JPEG при сжатии, 1-95
MIN_AUTO_LEN = int(os.getenv("MIN_AUTO_LEN", "3"))              # сообщения короче этого без тега игнорируем
DUP_THRESHOLD = float(os.getenv("DUP_THRESHOLD", "0.82"))       # похожесть ответа на свой предыдущий (0..1), выше = дубль
MEDIA_COMMENT_CHANCE = float(os.getenv("MEDIA_COMMENT_CHANCE", "0.25"))  # шанс прокомментировать чистую гифку/картинку (0 = никогда, 1 = всегда)
SILENT_TOKEN = "%%SILENT%%"                                     # маркер "молчу" от модели
AUTO_SUFFIX = (
    "\n\n[СЛУЖЕБНАЯ ИНСТРУКЦИЯ] Это сообщение из общего чата, к тебе напрямую НЕ обращались. "
    "Ответь, только если тебе действительно есть что сказать по теме — смешно, метко, в твоём стиле. "
    "Если вмешиваться неуместно или тема не твоя — ответь ровно одним маркером: %%SILENT%% (без кавычек, без точки)."
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONA_PATH = os.path.join(BASE_DIR, "persona.md")
GIFS_PATH = os.path.join(BASE_DIR, "gifs.txt")
ALIASES_PATH = os.path.join(BASE_DIR, "aliases.txt")   # словарь кличек: "кличка = username"
GIF_CACHE_DIR = os.path.join(BASE_DIR, "gif_cache")   # кэш скачанных гифок для отправки вложениями
GIF_MAX_UPLOAD_MB = int(os.getenv("GIF_MAX_UPLOAD_MB", "8"))  # тяжелее этого шлём ссылкой (лимит вложения без Nitro)
GIF_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}

# --- аватарка бота (Хоррор Масюня) ---
AVATAR_PATH = os.path.join(BASE_DIR, "avatar_cache.png")  # локальный кэш своей аватарки
AVATAR_PX = int(os.getenv("AVATAR_PX", "256"))            # размер скачиваемой аватарки (меньше = дешевле токены)
# вопросы о внешности/аватарке — только на них показываем модели картинку (экономия токенов)
AVATAR_ASK_RE = re.compile(
    r"аватар|аватарк|аву\b|авк|на аве|как ты выглядишь|внешность|внешн|масюн|твое лицо|твоё лицо|кто ты на фот|profile pic",
    re.IGNORECASE,
)

# вопросы про активность («во что играет Андрюха?», «что он слушает», «кто во что задротит») —
# на них показываем модели список активностей ВСЕГО сервера, а не только автора
ACTIVITY_ASK_RE = re.compile(
    r"во что (он|она|ты|они|кто|[а-яё]+)\s*(игра|задрот|рубит|катает|играет)|"
    r"что (он|она|ты|они)\s*(слуша|игра|стрим)|"
    r"какая (игра|активност)|чем (он|она|ты|они|народ|чат)\s*(занят|занимается)|"
    r"кто во что|во что игра|что игра|задротит во|играет сейчас|"
    r"активност|в доту играет|в кс играет|что за игра|какую игру|в какую игру|"
    r"посмотри во что|посмотри что играет|что слушает|что стримит|в каком статусе",
    re.IGNORECASE,
)

# --- память о людях (people.jsonl) ---
MEMORY_PATH = os.path.join(BASE_DIR, "people.jsonl")
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "1") == "1"
MEMORY_EXTRACT_INTERVAL = int(os.getenv("MEMORY_EXTRACT_INTERVAL", "120"))  # не чаще раза в N сек на канал (экономия токенов)
MEMORY_MAX_ENTRIES = int(os.getenv("MEMORY_MAX_ENTRIES", "500"))            # потолок файла, старое вытесняется
MEMORY_BLOCK_CHARS = int(os.getenv("MEMORY_BLOCK_CHARS", "2000"))           # сколько символов памяти подмешиваем в промпт
MEMORY_DUP_THRESHOLD = float(os.getenv("MEMORY_DUP_THRESHOLD", "0.79"))     # порог нечёткого дедупа фактов (внутри одного ника).
# 0.79 выбран по замерам: переформулировки одного факта дают 0.82-0.85,
# а похожие по шаблону, но РАЗНЫЕ факты («живёт в одной области с A» / «с B») — 0.75.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        # Ротация лога: новый файл каждые сутки в полночь, хранится 2 суток,
        # всё старее — удаляется автоматически (backupCount=2). bot.log всегда текущий.
        TimedRotatingFileHandler(
            os.path.join(BASE_DIR, "bot.log"),
            when="midnight",
            backupCount=2,
            encoding="utf-8",
        ),
        logging.StreamHandler(),  # чтобы ошибки было видно сразу в консоли, а не только в bot.log
    ],
)
_log_rotator = logging.getLogger().handlers[0]
_log_rotator.suffix = "%Y-%m-%d"


def _log_namer(default_name: str) -> str:
    """Архивы лога называем bot.2026-09-06.log вместо bot.log.2026-09-06. ОБЯЗАТЕЛЬНО: штатный getFilesToDelete ищет суффикс после префикса 'bot.' (баг bpo-44753 в Python: splitext отрезает '.log'), и имя 'log.2026-09-06' не проходит его регулярку — такие архивы НИКОГДА не удаляются. С именем 'bot.<дата>.log' суффикс '<дата>.log' регулярке соответствует, и файлы старше backupCount реально стираются."""
    d, rest = os.path.split(default_name)
    base, _, datepart = rest.partition(".log.")
    return os.path.join(d, f"{base}.{datepart}.log")


_log_rotator.namer = _log_namer

if not DISCORD_TOKEN or not LLM_API_KEY or not LLM_BASE_URL:
    raise SystemExit(
        "Заполни .env (скопируй .env.example в .env и впиши свои значения) перед запуском."
    )


def load_persona() -> str:
    with open(PERSONA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_gifs() -> list[tuple[str, str]]:
    """gifs.txt -> [(url_или_локальный_путь, описание), ...]. Формат строки: 'URL | описание' или 'gifs_local/имя.webp | описание' (или без описания). Битые/помеченные строки (описание начинается с 'НЕ РАБОТАЕТ') отбрасываются. Локальные файлы принимаются тоже: они не зависят от чужих серверов и подписей Discord, которые истекают через 24 часа, поэтому надёжнее ссылок."""
    if not os.path.exists(GIFS_PATH):
        return []
    out = []
    with open(GIFS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "|" in s:
                url, _, desc = s.partition("|")
                url, desc = url.strip(), desc.strip()
            else:
                url, desc = s, ""
            if desc.upper().startswith("НЕ РАБОТАЕТ"):
                continue  # битые ссылки модели не показываем
            if url.startswith("http"):
                out.append((url, desc or "гифка без описания"))
                continue
            # локальный путь (gifs_local/имя.webp). Приводим к абсолютному и проверяем,
            # что файл на месте: несуществующий путь модели не показываем, иначе бот
            # пообещает гифку и не сможет её послать.
            local = url if os.path.isabs(url) else os.path.join(BASE_DIR, url.replace("/", os.sep))
            if os.path.exists(local) and os.path.getsize(local) > 0:
                out.append((local, desc or "гифка без описания"))
            elif url:
                logging.info("локальная гифка не найдена, пропускаю: %s", url)
    return out


def load_aliases() -> dict[str, str]:
    """aliases.txt -> {кличка(lower): username}. Формат строки: 'кличка = username'."""
    out: dict[str, str] = {}
    if not os.path.exists(ALIASES_PATH):
        return out
    try:
        with open(ALIASES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                alias, _, uname = s.partition("=")
                alias, uname = alias.strip().lower(), uname.strip()
                if alias and uname:
                    out[alias] = uname
    except Exception:
        logging.exception("Не удалось прочитать aliases.txt")
    return out


def gifs_prompt_block(gifs: list[tuple[str, str]]) -> str:
    """Кусок системного промпта: пронумерованный список гифок + инструкция, как их слать."""
    if not gifs:
        return ""
    lines = "\n".join(f"{i + 1}. {desc}" for i, (_, desc) in enumerate(gifs))
    return (
        "\n\n[ГИФКИ] У тебя есть запас гифок. Если какая-то из них подходит к ситуации — "
        "отправь её, вставив в свой ответ маркер %%GIF:номер%% (например %%GIF:2%%). "
        "Маркер можно поставить один, в любом месте ответа; текст до/после маркера будет отправлен как обычно, "
        "а можно отправить и один маркер без текста. Шли гифку только когда она реально в тему, не в каждый ответ.\n"
        f"Список гифок:\n{lines}"
    )


GIF_MARKER_RE = re.compile(r"%%GIF:(\d+)%%")

# ссылки на гифки в тексте сообщения (klipy/tenor/giphy/любой .gif) — их шлют вместо ответа
GIF_LINK_RE = re.compile(r"https?://\S*?(?:klipy\.com|tenor\.com|giphy\.com|\.(?:gif|mp4|webm))(?:\?\S*|/\S*|\S*)", re.IGNORECASE)


def is_gif_ignored(author_name: str, content: str, attachments=()) -> bool:
    """True, если это гифка от пользователя из GIF_IGNORE_USERS — такое сообщение игнорируем целиком. Игнорим только когда кроме гифок ничего осмысленного нет: если человек задал вопрос и приложил гифку — вопрос всё равно заслуживает ответа."""
    if not GIF_IGNORE_USERS:
        return False
    if (author_name or "").lower() not in GIF_IGNORE_USERS:
        return False
    # остался ли текст после вырезания гиф-ссылок?
    rest = GIF_LINK_RE.sub("", content or "").strip()
    # гифка/видео как вложение
    has_gif_att = False
    for a in attachments or ():
        ctype = (getattr(a, "content_type", None) or "").lower()
        fname = (getattr(a, "filename", None) or "").lower()
        if ctype.startswith("image/gif") or ctype.startswith("video/") or fname.endswith((".gif", ".mp4", ".webm")):
            has_gif_att = True
            break
    if rest:
        return False           # есть настоящий текст — отвечаем на него
    return bool(GIF_LINK_RE.search(content or "")) or has_gif_att


LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))  # сек на один запрос к шлюзу (дефолт openai = 600с: при зависании шлюза чат молчит минутами)
llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=LLM_TIMEOUT, max_retries=2)

persona_cache = load_persona()
persona_cache_time = time.time()
gifs_cache = load_gifs()
gifs_cache_time = time.time()
aliases_cache = load_aliases()
aliases_cache_time = time.time()

intents = discord.Intents.default()
intents.message_content = True
if PRESENCES:
    intents.presences = True  # активности участников (игры/spotify/статусы); если intent не включён в панели — откат в main()
bot = discord.Client(intents=intents)

# история сообщений по каналам, чтобы бот помнил контекст диалога
# элемент = (имя автора, текст, is_self, список data-url картинок)
channel_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_LIMIT))
last_reply_time: dict[int, float] = defaultdict(float)
inflight_auto: set[int] = set()                         # каналы с уже идущим автозапросом (не плодить дубли)
auto_blocked_until: dict[int, float] = defaultdict(float)  # до этого времени автопроверки в канале не делаем
name_to_id: dict[str, int] = {}                         # ник (lowercase, любой вариант) -> discord user id, для рабочих тегов
uid_to_username: dict[int, str] = {}                    # user id -> уникальный юзернейм (его ищет query_members, его показываем модели)
uid_to_display: dict[int, str] = {}                     # user id -> отображаемое имя (для ростера: "username (Display)")
pending_tags: dict[int, discord.Message] = {}           # тег, проглоченный кулдауном — ответим сразу после
pending_tasks: dict[int, asyncio.Task] = {}             # фоновые задачи отложенных тег-ответов по каналам
msg_images: dict[int, list[str]] = {}                   # id сообщения -> скачанные картинки (для отложенных тегов)
MSG_IMAGES_MAX = 200                                    # потолок кэша, старое вытесняется


def remember_user(user_or_member):
    """Кладём все варианты имени пользователя в кэш ник->id + запоминаем его юзернейм."""
    uid = getattr(user_or_member, "id", None)
    if not uid:
        return
    uname = getattr(user_or_member, "name", None)
    if isinstance(uname, str) and uname:
        uid_to_username[uid] = uname  # username — стабильный и тег-резолвится по префиксу
    disp = getattr(user_or_member, "display_name", None) or getattr(user_or_member, "global_name", None)
    if isinstance(disp, str) and disp:
        uid_to_display[uid] = disp
    for attr in ("name", "global_name", "display_name"):
        val = getattr(user_or_member, attr, None)
        if isinstance(val, str) and val:
            name_to_id.setdefault(val.lower(), uid)


def roster_block() -> str:
    """Список юзернеймов в системный промпт — модель знает, кого можно тегать. Показываем именно username (не дисплей-имена), потому что его reliably резолвит query_members."""
    if not uid_to_username:
        return ""
    entries = []
    for uid in sorted(uid_to_username, key=lambda k: uid_to_username[k].lower())[:60]:
        uname = uid_to_username[uid]
        disp = uid_to_display.get(uid, "")
        entries.append(f"{uname} ({disp})" if disp and disp.lower() != uname.lower() else uname)
    # клички из aliases.txt — подсказка модели, ЧЕГО писать не надо
    alias_notes = ""
    if aliases_cache:
        by_user: dict[str, list[str]] = {}
        for a, u in aliases_cache.items():
            by_user.setdefault(u, []).append(a)
        notes = []
        for u, alist in sorted(by_user.items()):
            others = [a for a in alist if a != u]
            if others:
                notes.append(f"{u} (не пиши: {', '.join(others[:4])})")
        if notes:
            alias_notes = "\nЭти клички система поймёт, но лучше пиши юзернейм: " + "; ".join(notes[:25])
    return (
        "\n\n[ТЕГИ] Чтобы тегнуть человека, напиши в ответе @юзернейм — ТОЧНО как в списке ниже, "
        "латиницей, не переводи на русский и не искажай (не «@ксерон», а ровно @xeron6696). "
        "Система сама превратит его в рабочий дискорд-тег. В скобках — отображаемое имя, его писать не нужно. "
        "НИКОГДА не пиши <@...>, числовые id, @everyone и @here — это не работает. "
        "Когда перечисляешь/троллишь нескольких человек — тегни КАЖДОГО из них, о ком говоришь.\n"
        "Известные юзернеймы: " + ", ".join(entries) + alias_notes
    )


# сырые дискорд-упоминания во ВХОДЯЩИХ сообщениях: <@id> / <@!id> (юзер), <#id> (канал), <@&id> (роль)
RAW_MENTION_RE = re.compile(r"<@!?(\d{15,25})>|<#(\d{15,25})>|<@&(\d{15,25})>")


async def humanize_mentions(text: str, guild=None) -> str:
    """Превращает сырые <@id>/<#id>/<@&id> в читаемые @юзернейм/#канал/@роль. Применяется к тексту ПЕРЕД записью в историю: модель никогда не должна видеть формат <@число>, иначе начинает его копировать и выдаёт (иногда выдуманные) id."""
    if "<" not in text:
        return text

    out = []
    pos = 0
    for m in RAW_MENTION_RE.finditer(text):
        out.append(text[pos:m.start()])
        out.append(await _humanize_one(m, guild))
        pos = m.end()
    if not out:
        return text
    out.append(text[pos:])
    return "".join(out)


async def _humanize_one(m: re.Match, guild) -> str:
    """Одно сырое упоминание -> читаемый текст."""
    if m.group(1):                                   # пользователь <@id> / <@!id>
        uid = int(m.group(1))
        uname = uid_to_username.get(uid)
        if not uname:
            try:
                remember_user(await bot.fetch_user(uid))  # REST, работает для любого id
                uname = uid_to_username.get(uid)
            except Exception:
                uname = None
        return f"@{uname}" if uname else "@кто-то"
    if m.group(2):                                   # канал <#id>
        if guild is not None:
            ch = guild.get_channel(int(m.group(2)))
            if ch:
                return f"#{ch.name}"
        return "#канал"
    uid = int(m.group(3))                            # роль <@&id>
    if guild is not None:
        role = guild.get_role(uid)
        if role:
            return f"@{role.name}"
    return "@роль"


async def _fetch_parent_message(message: discord.Message):
    """Родительское сообщение reply-цитаты: сначала ref.resolved (Discord прикладывает его сам), потом кэш, потом REST fetch_message — работает без privileged intents."""
    ref = getattr(message, "reference", None)
    if ref is None:
        return None
    resolved = getattr(ref, "resolved", None)
    if resolved is not None and not isinstance(resolved, discord.DeletedReferencedMessage):
        return resolved
    cached = getattr(ref, "cached_message", None)
    if cached is not None:
        return cached
    mid = getattr(ref, "message_id", None)
    ch = getattr(message, "channel", None)
    if mid is None or ch is None:
        return None
    try:
        return await ch.fetch_message(mid)
    except Exception:
        return None  # удалено / нет прав


async def reply_context_prefix(message: discord.Message) -> tuple[str, bool]:
    """Reply-цитата Discord -> (префикс для истории, is_reply_to_bot). Префикс вида «[в ответ @ник: «цитата»]» кладётся перед текстом сообщения в историю, чтобы модель видела, кому человек отвечает, а не голый текст. is_reply_to_bot=True, если человек ответил именно на сообщение бота (тогда это прямое обращение, даже без пинга)."""
    ref = getattr(message, "reference", None)
    if ref is None:
        return "", False
    # форварды (type=forward) — пересылка, не ответ; обрабатываем только обычные ответы
    rtype = getattr(ref, "type", discord.MessageReferenceType.default)
    if rtype != discord.MessageReferenceType.default:
        return "", False
    parent_id = getattr(ref, "message_id", None)
    parent