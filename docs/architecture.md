# Архитектура MusicBot

Документ описывает текущее внутреннее устройство MusicBot после добавления VK Музыки, платформенного live-audio capture и нативного macOS backend.

## 1. Общая схема

В проекте существуют два разных типа источников музыки:

```text
Hitmo
  ↓
direct stream URL
  ↓
FFmpegPCMAudio
  ↓
Discord

VK Музыка
  ↓
Playwright / Chrome
  ↓
обычное воспроизведение VK
  ↓
platform AudioCapture
  ↓
PCM AudioSource
  ↓
Discord
```

`MusicPlayer` управляет очередью и Discord Voice, но не должен знать детали Windows/macOS capture.

## 2. Точка входа

`bot.py` остаётся минимальным:

```python
from music_bot.app import run

run()
```

Вся инициализация находится в `music_bot/app.py`.

## 3. `MusicBot` и lifecycle

`music_bot/app.py` создаёт:

1. Discord intents;
2. `HitmoProvider`;
3. один `MusicPlayer`;
4. `MusicCog` и `DebugCog`;
5. slash-команды для `GUILD_ID`.

При shutdown важно соблюдать порядок:

```text
MusicBot.close()
      ↓
MusicPlayer.close()
      ↓
provider.close()
      ↓
super().close()
```

`MusicPlayer.close()` отвечает за:

- установку флага `_closing`;
- отмену idle-задач;
- отмену VK live-end таймеров;
- остановку активного Discord source;
- `voice_client.disconnect(force=True)`;
- закрытие `AudioCapture`;
- закрытие VK BrowserContext/Playwright;
- очистку очередей и текущих треков.

Это не позволяет `after_playback` запустить новый трек во время shutdown.

## 4. Конфигурация

`music_bot/config.py`:

```text
.env
 ↓
Settings.from_env()
 ↓
Settings
```

Основные параметры:

```text
DISCORD_TOKEN
GUILD_ID
IDLE_TIMEOUT_SECONDS
SEARCH_LIMIT
```

Платформенные audio backend сейчас выбираются автоматически и не требуют отдельной переменной в `.env`.

## 5. Модель источников

`music_bot/music/models.py` содержит `MusicSource`:

```python
class MusicSource(StrEnum):
    HITMO = "hitmo"
    VK = "vk"
```

Это заменяет строки вида `"vk"` / `"hitmo"` внутри бизнес-логики.

### `TrackCandidate`

Унифицированная модель найденного трека:

```text
title
artist
stream_url | None
track_id | None
duration | None
source: MusicSource
```

Смысл полей зависит от источника:

#### Hitmo

```text
stream_url = прямой аудиопоток
track_id   = ID Hitmo, если доступен
source     = HITMO
```

#### VK

```text
stream_url = None
track_id   = точный href вида /audio...
source     = VK
```

Точный VK `track_id` сохраняется сразу после выбора результата и проходит через очередь без повторного fuzzy matching.

### `QueueItem`

```text
track: TrackCandidate
channel_id: int
```

`channel_id` используется для сообщения `Now playing` при автоматическом переходе по очереди.

## 6. Discord command layer

`music_bot/commands/music.py` содержит `MusicCog`.

Задачи Cog:

- проверить voice context;
- принять slash-параметры;
- выбрать источник поиска;
- получить `TrackCandidate[]`;
- показать `TrackSelectView`;
- вызвать методы `MusicPlayer`;
- сформировать сообщения пользователю.

`/play` поддерживает два источника:

```text
Hitmo
VK Музыка
```

### Hitmo search

`HitmoProvider` синхронный, поэтому используется:

```python
await asyncio.to_thread(
    self.provider.search,
    query,
    search_limit,
)
```

### VK search

VK search асинхронный и выполняется через `MusicPlayer.search_vk()` / `VKPlayer.search()`.

## 7. UI выбора результата

`music_bot/ui/track_select.py` содержит:

- `TrackSelectView`;
- `TrackSelectButton`.

Flow:

```text
/search results
      ↓
Discord buttons
      ↓
TrackSelectButton.callback
      ↓
QueueItem
      ↓
await MusicPlayer.enqueue_or_play()
```

`enqueue_or_play()` асинхронный, потому что запуск VK требует Playwright и live capture.

## 8. HitmoProvider

`music_bot/providers/hitmo.py` отвечает только за Hitmo.

```text
GET /search?q=<query>
      ↓
BeautifulSoup
      ↓
li.tracks__item.track[data-musmeta]
      ↓
JSON data-musmeta
      ↓
TrackCandidate(source=HITMO)
```

Из результата извлекаются:

- artist;
- title;
- duration;
- stream URL;
- ID, если доступен.

`MusicPlayer` не занимается HTML-разбором Hitmo.

## 9. VKPlayer

`music_bot/providers/vk/player.py` управляет persistent Google Chrome через Playwright.

VK browser profile:

```text
music_bot/providers/vk/browser_profile/
```

Он хранит cookies/session и не должен попадать в Git.

### 9.1 Lifecycle

`VKPlayer.start()`:

1. запускает Playwright;
2. запускает persistent Chrome context;
3. создаёт/восстанавливает две страницы;
4. открывает VK Audio.

`VKPlayer.stop()`:

1. ставит активный VK playback на паузу;
2. закрывает BrowserContext;
3. останавливает Playwright;
4. очищает page/current-track state.

### 9.2 Две вкладки

Используются две независимые страницы:

```text
BrowserContext
│
├── search_page
│      └── поиск новых треков
│
└── playback_page
       └── текущий VK playback
```

Это нужно, чтобы `/play` нового VK-трека не делал `goto()` на странице, где играет текущий трек.

### 9.3 VK search

Поиск выполняется через URL:

```text
https://vk.ru/audio?q=<encoded query>
```

Основные DOM selectors:

```text
[data-testid="MusicTrackRow"]
[data-testid="MusicTrackRow_Title"]
[data-testid="MusicTrackRow_Authors"]
[data-testid="MusicTrackRow_Duration"]
```

Для каждого результата сохраняется:

```text
track_id = href title element
```

Поэтому выбранный результат можно воспроизвести точно, а не искать наиболее похожий artist/title/duration второй раз.

### 9.4 Prepare / Play

Для live capture запуск VK разделён логически на подготовку и фактическое воспроизведение:

```text
prepare(track)
      ↓
playback_page открывает нужный поиск
      ↓
точный track_id найден
      ↓
кнопка готова
      ↓
AudioCapture создаёт source
      ↓
play(track)
      ↓
Enter по кнопке Play
```

Так live audio backend не приходится держать открытым во время долгой навигации страницы.

### 9.5 Pause active

VK способен автоматически включить следующий трек после окончания текущего.

Поэтому по завершении рассчитанной длительности `MusicPlayer` вызывает `VKPlayer.pause_active()`, затем останавливает Discord source.

## 10. MusicPlayer

`music_bot/music/player.py` — orchestration layer.

Основное состояние по guild:

```text
queues[guild_id]          -> deque[QueueItem]
current_tracks[guild_id]  -> QueueItem
idle_tasks[guild_id]      -> asyncio.Task
live_end_tasks[guild_id]  -> asyncio.Task
```

Дополнительно глобально существуют:

```text
VKPlayer
AudioCapture
```

### 10.1 enqueue_or_play

```text
enqueue_or_play()
      │
      ├─ VoiceClient playing/paused
      │       ↓
      │    queue.append(item)
      │
      └─ свободен
              ↓
         await start_track()
```

### 10.2 start_track

`start_track()`:

1. отменяет idle timer;
2. сохраняет `current_tracks[guild_id]`;
3. выбирает ветку по `MusicSource`.

```text
MusicSource.HITMO
      ↓
_start_hitmo_track()

MusicSource.VK
      ↓
_start_vk_track()
```

## 11. Hitmo playback

Для Hitmo используется прямой поток:

```text
TrackCandidate.stream_url
       ↓
discord.FFmpegPCMAudio
       ↓
VoiceClient.play()
```

FFmpeg получает HTTP reconnect options и User-Agent.

Hitmo playback не использует платформенный `AudioCapture`.

## 12. VK playback

VK не имеет `stream_url` в модели.

Flow:

```text
QueueItem
   ↓
VKTrack(track_id, artist, title, duration)
   ↓
VKPlayer.prepare()
   ↓
AudioCapture.create_source()
   ↓
VoiceClient.play(source)
   ↓
VKPlayer.play()
   ↓
Chrome начинает воспроизведение
   ↓
platform capture получает PCM
   ↓
Discord
```

После старта создаётся `live_end_task` на основе длительности трека.

## 13. Общий callback Discord playback

Все Discord source запускаются через `_play_source()`:

```python
voice_client.play(
    source,
    after=after_playback,
)
```

`after_playback` работает не в обычном asyncio flow, поэтому используется:

```python
asyncio.run_coroutine_threadsafe(
    self.play_next(guild_id),
    loop,
)
```

При `_closing == True` callback ничего нового не запускает.

## 14. Автоматический следующий трек

`play_next()`:

```text
cancel live-end timer
      ↓
clear current
      ↓
queue ?
 ├─ yes → popleft() → await start_track()
 └─ no  → start idle timer
```

### `/skip`

```text
не очищать queue
      ↓
stop current source
      ↓
after_playback
      ↓
play_next
```

### `/stop`

```text
clear queue/current
      ↓
stop current source
      ↓
after callback видит пустую очередь
```

Для VK перед stop/skip активный Chrome playback также ставится на паузу.

## 15. Idle disconnect

Если voice connection существует, но:

```text
current track == None
queue empty
```

создаётся idle task.

Через `IDLE_TIMEOUT_SECONDS` состояние проверяется повторно. Если bot всё ещё idle:

```python
await voice_client.disconnect()
```

Новый playback отменяет idle task.

## 16. AudioCapture abstraction

Ключевое архитектурное изменение — `MusicPlayer` не импортирует Windows/macOS backend напрямую.

```text
MusicPlayer
    ↓
AudioCapture Protocol
    ↓
create_audio_capture()
    ↓
platform.system()
    │
    ├─ Windows → WindowsAudioCapture
    └─ Darwin  → MacOSAudioCapture
```

Файлы:

```text
music_bot/audio/base.py
music_bot/audio/factory.py
music_bot/audio/windows.py
music_bot/audio/macos.py
```

Контракт минимален:

```text
create_source() -> discord.AudioSource
close()         -> async cleanup
```

## 17. Windows audio backend

Windows использует VB-CABLE.

Пользователь вручную направляет output Chrome в:

```text
CABLE Input (VB-Audio Virtual Cable)
```

Бот захватывает:

```text
CABLE Output (VB-Audio Virtual Cable)
```

`WindowsAudioCapture` создаёт `LiveFFmpegSource` с DirectShow input:

```text
-f dshow
-i audio=CABLE Output (...)
```

### `LiveFFmpegSource`

`music_bot/audio/live_ffmpeg.py` предназначен именно для live input.

Он запускает FFmpeg с output:

```text
s16le
48000 Hz
2 channels
stdout
```

`discord.AudioSource.read()` должен отдавать 20 ms PCM frame:

```text
3840 bytes
```

Поэтому `LiveFFmpegSource.read()` собирает данные до полного кадра, вместо того чтобы считать короткий pipe-read концом потока.

## 18. macOS audio backend

Текущая macOS-реализация **не использует BlackHole**.

Используется нативный Swift helper:

```text
native/macos/ChromeAudioTap.swift
native/macos/Info.plist
native/macos/bin/chrome_audio_tap
```

### 18.1 Назначение helper

Helper:

1. находит процессы Google Chrome;
2. переводит PID в Core Audio process `AudioObjectID`;
3. создаёт `CATapDescription` только для Chrome processes;
4. создаёт Core Audio Process Tap;
5. создаёт private aggregate device для tap;
6. получает Float32 PCM;
7. переводит его в stereo Int16 48 kHz;
8. пишет raw PCM в `stdout`.

Другие приложения в этот tap не входят.

Схема:

```text
Chrome
  ↓
Core Audio Process Tap
  ↓
Swift helper
  ↓
stdout: s16le / 48 kHz / stereo
  ↓
ProcessPCMSource
  ↓
Discord
```

### 18.2 ProcessPCMSource

`music_bot/audio/process_pcm.py`:

- запускает `chrome_audio_tap` subprocess;
- читает diagnostic stderr до сообщения `READY`;
- читает raw PCM из stdout;
- собирает ровно 3840-byte Discord frames;
- завершает helper в `cleanup()`.

### 18.3 MacOSAudioCapture

`music_bot/audio/macos.py` определяет путь до:

```text
native/macos/bin/chrome_audio_tap
```

и возвращает `ProcessPCMSource`.

Python-код не компилирует Swift автоматически. Helper должен быть собран на целевой машине заранее.

## 19. Сборка macOS helper

Из корня проекта:

```bash
mkdir -p native/macos/bin

xcrun swiftc -O \
  native/macos/ChromeAudioTap.swift \
  -o native/macos/bin/chrome_audio_tap \
  -framework CoreAudio \
  -framework Foundation \
  -Xlinker -sectcreate \
  -Xlinker __TEXT \
  -Xlinker __info_plist \
  -Xlinker native/macos/Info.plist
```

`Info.plist` содержит `NSAudioCaptureUsageDescription`, необходимый для системного разрешения audio capture.

## 20. Почему Windows и macOS backend разные

Оба backend реализуют один `AudioCapture`, но используют нативно подходящий механизм:

```text
Windows
Chrome → VB-CABLE → DirectShow → FFmpeg → PCM

macOS
Chrome → Core Audio Process Tap → Swift → PCM
```

`MusicPlayer` не меняется при переключении ОС.

## 21. Разделение Search и Playback VK

До рефакторинга одна страница Chrome использовалась для всего:

```text
play current track
+
goto(search URL)
```

Это могло нарушать playback.

Сейчас:

```text
search_page
   └── только навигация поиска

playback_page
   └── prepare/play/pause текущего трека
```

Это позволяет искать следующий VK-трек во время текущего playback.

## 22. Жизненный цикл `/play` для Hitmo

```text
/play query + Hitmo
      ↓
MusicCog
      ↓
HitmoProvider.search() в worker thread
      ↓
TrackCandidate[]
      ↓
TrackSelectView
      ↓
QueueItem
      ↓
MusicPlayer.enqueue_or_play()
      ↓
_start_hitmo_track()
      ↓
FFmpegPCMAudio
      ↓
Discord Voice
```

## 23. Жизненный цикл `/play` для VK

```text
/play query + VK
      ↓
MusicCog
      ↓
MusicPlayer.search_vk()
      ↓
VKPlayer.search(search_page)
      ↓
TrackCandidate(source=VK, exact track_id)
      ↓
TrackSelectView
      ↓
QueueItem
      ↓
MusicPlayer.enqueue_or_play()
      ↓
VKPlayer.prepare(playback_page)
      ↓
AudioCapture.create_source()
      ↓
VoiceClient.play(source)
      ↓
VKPlayer.play()
      ↓
Chrome audio
      ↓
WindowsAudioCapture / MacOSAudioCapture
      ↓
Discord Voice
```

## 24. Где что изменять

### Discord commands

```text
music_bot/commands/music.py
```

### Hitmo search/parser

```text
music_bot/providers/hitmo.py
```

### VK DOM/search/playback

```text
music_bot/providers/vk/player.py
```

### Queue / transitions / lifecycle

```text
music_bot/music/player.py
```

### Models and provider enum

```text
music_bot/music/models.py
```

### Windows capture

```text
music_bot/audio/windows.py
music_bot/audio/live_ffmpeg.py
```

### macOS capture Python side

```text
music_bot/audio/macos.py
music_bot/audio/process_pcm.py
```

### macOS Core Audio implementation

```text
native/macos/ChromeAudioTap.swift
native/macos/Info.plist
```

### Platform selection

```text
music_bot/audio/factory.py
```

### Track selection UI

```text
music_bot/ui/track_select.py
```

## 25. Текущие архитектурные ограничения

### Один VK playback pipeline

Есть один глобальный:

```text
VKPlayer
playback_page
AudioCapture
```

Поэтому одновременный независимый VK playback для нескольких guild не поддерживается, хотя сами queues разделены по `guild_id`.

### VK зависит от DOM

`data-testid` стабильнее CSS-классов, но изменение VK frontend всё равно может потребовать обновления selectors.

### VK end detection пока основан на duration

Завершение live VK source определяется таймером из длительности результата. Это рабочий, но не идеальный способ: сетевой buffering может внести небольшое расхождение.

Более надёжный будущий вариант — получать реальное playback state/currentTime непосредственно от VK player.

### Состояние не персистентно

Queues/current tracks живут только в памяти процесса.

## 26. Логичные следующие улучшения

- `Auto` source mode;
- `SearchResolver` перед конкретными providers;
- fuzzy/exact ranking результатов;
- поиск по фрагменту текста;
- AI semantic fallback только после обычного поиска;
- `/pause` и `/resume`;
- управление элементами очереди;
- real VK playback-end detection вместо duration timer;
- recovery/retry при зависшем VK playback или плохом соединении;
- logging вместо `print()`;
- unit/integration tests;
- optional multi-guild VK isolation с отдельными playback/capture pipelines.
