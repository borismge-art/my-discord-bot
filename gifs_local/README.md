# gifs_local — локальные гифки бота

Здесь лежат гифки файлами, а не ссылками. Бот шлёт их вложением — анимация
встраивается в чат (в отличие от голой ссылки, которая разворачивается в embed-карточку).

## Что уже скачано (7 штук, все с klipy.com)

klipy отдаёт страницу только краулеру `Discordbot`, а бот ходит как Chrome и получает 403.
Файлы вытащены через `og:image` и сохранены здесь. Discord официально поддерживает
анимированный WebP как вложение, поэтому конвертировать в GIF не нужно.

| файл | размер | кадров | откуда |
|---|---|---|---|
| goro-majima-hustle.webp | 2455 KB | 230 | klipy.com/gifs/goro-majima-hustle |
| hmmmm-20.webp | 86 KB | 14 | klipy.com/gifs/hmmmm-20 |
| iaica-v-puke-pila.webp | 513 KB | 100 | klipy.com/gifs/iaica-v-puke-pila |
| majima-majima-goro-1.webp | 319 KB | 30 | klipy.com/gifs/majima-majima-goro-1 |
| nevieebenno-poxui-yakuza.webp | 1530 KB | 90 | klipy.com/gifs/nevieebenno-poxui-yakuza |
| obeziana-obeziana-mem.webp | 3494 KB | 197 | klipy.com/gifs/obeziana-obeziana-mem |
| yakuza-majima-7.webp | 1342 KB | 88 | klipy.com/gifs/yakuza-majima-7 |

Все влезли в лимит `GIF_MAX_UPLOAD_MB=8` (без Nitro Discord не принимает вложения тяжелее 8 MB).

## Как добавить свою гифку

1. Скопируй файл в эту папку. Подойдут: `.gif`, `.webp` (анимированный тоже), `.png`, `.jpg`.
2. Проверь, что вес меньше 8 MB — иначе бот не сможет послать её вложением.
3. Пропиши её в `../gifs.txt` строкой вида:

```
gifs_local/имяфайла.webp | описание, когда её уместно послать
```

   Описание важно: по нему модель выбирает, какую гифку послать. Чем конкретнее — тем лучше
   («маджима танцует», «кот орёт», «палец вниз»).

## Что осталось недоскачанным (надо руками)

Эти ссылки вели на вложения в каналах, куда бот не входит (`403`). Сами сообщения в Discord
живы — мертва только подпись в URL, она действует 24 часа. Найди сообщение в клиенте и
скачай файл сам:

- cdn.discordapp.com/attachments/629717481778315264/1546213289212776518/09073.gif
- media.discordapp.net/attachments/926847171301625876/1081640244228669521/gif.gif
- media.discordapp.net/attachments/1235677154084126865/1293982625974849576/image.gif
- cdn.discordapp.com/attachments/1386381286754746442/1502930636053417994/doc_2026-05-10_10-08-40.gif
- cdn.discordapp.com/attachments/1220568870784471090/1356608446559944704/hah.gif
- cdn.discordapp.com/attachments/1507278467505328168/1530684545458769920/HN2_0GIX0AAHkSr.gif
- cdn.discordapp.com/attachments/925769315238707220/1527306652167180518/image0.gif
- cdn.discordapp.com/attachments/1208058920367554632/1362363555340484608/animation.gif.gif
- cdn.discordapp.com/attachments/1282996028773240874/1290292694060372020/file_1.gif
- cdn.discordapp.com/attachments/1014621078812893357/1252872358134546442/image0.gif

Невосстановимы (файлы удалены на сервере навсегда):

- cdn.discordapp.com/attachments/1458814472738312253/1529177033068908564/lv_0_20250908140450.gif — сообщение удалено
- images-ext-1.discordapp.net/external/013bNS9oGzeRwD3.../static.klipy.com/ii/2711dd8a... — прокси, 401
- api-cdn.rule34.xxx/images/6951/9765ca2b05d0acc575c1673ce0aa4765.gif — 404
