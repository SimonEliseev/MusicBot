# MusicBot

MusicBot — музыкальный Discord-бот на Python с двумя источниками музыки:

- **Hitmo** — поиск треков по HTML-разметке сайта и воспроизведение прямого аудиопотока через FFmpeg;
- **VK Музыка** — управление VK через Playwright/Google Chrome и передача уже воспроизводимого аудио в Discord через платформенный live-capture backend.

Бот показывает несколько результатов поиска, позволяет выбрать нужный трек кнопкой, поддерживает очередь, автоматически запускает следующий трек и отключается от voice-канала после периода бездействия.

> Hitmo использует HTML-разметку сайта, а не официальный API. Если структура страницы изменится, `music_bot/providers/hitmo.py` может потребовать обновления.
>
> VK-провайдер управляет обычным воспроизведением в Chrome. Он не извлекает ключи DRM и не получает прямой защищённый аудиопоток VK.

## Возможности

- `/play <query>` — поиск трека с выбором источника `Hitmo` или `VK Музыка`;
- несколько результатов поиска с Discord-кнопками;
- `/queue` — текущий трек и очередь;
- `/skip` — пропустить текущий трек;
- `/stop` — остановить воспроизведение и очистить очередь;
- `/join` — подключить бота к voice-каналу;
- `/leave` — отключить бота от voice-канала;
- `/ping` — проверка доступности бота;
- `/playtest` — локальный тест Discord Voice через `test.mp3`;
- автоматический переход к следующему треку;
- автоматический idle-disconnect;
- отдельная очередь для каждого Discord-сервера;
- точное сохранение выбранного VK `track_id`;
- отдельные вкладки Chrome для поиска и воспроизведения VK;
- платформенно-независимый слой `AudioCapture`;
- Windows: захват Chrome через VB-CABLE + FFmpeg/DirectShow;
- macOS: захват **только Chrome** через Core Audio Process Tap и нативный Swift helper;
- корректный lifecycle: остановка таймеров, аудио, Chrome/Playwright и voice-соединений при shutdown.

## Требования

Общие:

- Python 3.12 рекомендуется для текущей сборки;
- Google Chrome — для VK-провайдера;
- Discord-приложение с ботом, установленным на сервер через **Guild Install**;
- доступ к Discord API/Gateway, Hitmo и VK;
- Python-зависимости из `requirements.txt`.

FFmpeg всё ещё нужен для Hitmo и диагностического `/playtest`. На Windows он также используется для live-capture через VB-CABLE.

## Установка Python-зависимостей

Создай виртуальное окружение и установи зависимости:

### Windows

```powershell
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### macOS

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Для обновления полного списка Python-зависимостей из активного `venv`:

```bash
python -m pip freeze > requirements.txt
```

## Системные зависимости

### Windows 10/11

Нужны:

1. Google Chrome;
2. FFmpeg в `PATH`;
3. VB-CABLE;
4. вывод **Google Chrome** в Windows Volume Mixer должен быть направлен в:

```text
CABLE Input (VB-Audio Virtual Cable)
```

Бот читает устройство:

```text
CABLE Output (VB-Audio Virtual Cable)
```

Проверка FFmpeg:

```powershell
ffmpeg -version
```

Проверка DirectShow-устройств:

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

Схема VK на Windows:

```text
VK → Chrome
      ↓
CABLE Input
      ↓
CABLE Output
      ↓
FFmpeg / DirectShow
      ↓
LiveFFmpegSource
      ↓
Discord Voice
```

### macOS

Для текущего VK backend **BlackHole не нужен**.

Нужны:

- macOS 14.2+;
- Google Chrome;
- Xcode Command Line Tools / `xcrun swiftc`;
- Python 3.12;
- FFmpeg — для Hitmo и `/playtest`;
- Opus для Discord Voice.

Через Homebrew:

```bash
brew install python@3.12 ffmpeg opus
```

Проверь:

```bash
python3.12 --version
ffmpeg -version
xcrun swiftc --version
```

#### Сборка macOS Core Audio helper

Исходники helper находятся внутри проекта:

```text
native/macos/ChromeAudioTap.swift
native/macos/Info.plist
```

Создай каталог бинарника:

```bash
mkdir -p native/macos/bin
```

Собери helper из корня проекта:

```bash
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

После сборки должен существовать файл:

```text
native/macos/bin/chrome_audio_tap
```

Запускать helper вручную вместе с ботом **не нужно**. `MacOSAudioCapture` запускает его автоматически, когда начинается VK-воспроизведение.

При первом использовании macOS может запросить разрешение на захват системного аудио. Разрешение должно быть выдано процессу, из которого запускается helper.

Схема VK на macOS:

```text
VK → Chrome
      ↓
Core Audio Process Tap
      ↓
chrome_audio_tap
      ↓
48 kHz stereo PCM
      ↓
ProcessPCMSource
      ↓
Discord Voice
```

Core Audio Tap настроен на процессы Chrome, поэтому звук других приложений в Discord не передаётся.

## Настройка `.env`

Скопируй пример:

```bash
cp .env.example .env
```

Минимальная конфигурация:

```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=123456789012345678
IDLE_TIMEOUT_SECONDS=600
SEARCH_LIMIT=5
```

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `DISCORD_TOKEN` | Токен Discord-бота | обязательна |
| `GUILD_ID` | Сервер для синхронизации slash-команд | обязательна |
| `IDLE_TIMEOUT_SECONDS` | Время до выхода из voice при простое | `600` |
| `SEARCH_LIMIT` | Число результатов поиска | `5` |

Не добавляй настоящий `.env` в Git.

## VK-сессия

VK использует persistent Chrome profile:

```text
music_bot/providers/vk/browser_profile/
```

При первом запуске VK-провайдера может потребоваться вручную войти в аккаунт в открывшемся Chrome. После этого cookies/session сохраняются в профиле.

Каталог содержит данные авторизации и должен быть исключён из Git:

```gitignore
music_bot/providers/vk/browser_profile/
```

## Запуск

После установки зависимостей и подготовки платформенного backend запуск одинаковый:

```bash
python bot.py
```

Swift helper на macOS и FFmpeg live-capture на Windows запускаются самим ботом по необходимости.

При успешном старте:

```text
Slash-команды зарегистрированы: ...
Бот запущен: MusicBox#....
```

## `/play` и выбор источника

`/play` поддерживает два источника:

```text
Hitmo
VK Музыка
```

Для Hitmo поиск выполняется синхронным `HitmoProvider` в отдельном worker thread.

Для VK:

1. при необходимости запускается persistent Chrome через Playwright;
2. `search_page` открывает страницу поиска VK;
3. результаты преобразуются в `TrackCandidate` с `MusicSource.VK`;
4. сохраняется точный `track_id` выбранной VK-записи;
5. при старте трека `playback_page` находит именно этот `track_id`;
6. платформенный `AudioCapture` начинает live-capture;
7. VK нажимает Play;
8. PCM отправляется в Discord.

Поиск следующего VK-трека выполняется в отдельной вкладке и не должен прерывать текущий playback.

## Очередь

Для каждого `guild_id` `MusicPlayer` хранит отдельную очередь.

Если ничего не играет:

```text
QueueItem → start_track()
```

Если текущий Discord source активен:

```text
QueueItem → deque
```

После завершения текущего source callback `VoiceClient.play(..., after=...)` возвращает управление в event loop и запускает `play_next()`.

Для VK дополнительно используется таймер длительности: по его завершении активный VK playback ставится на паузу, чтобы VK не начал автоматически следующий трек, затем останавливается Discord source и запускается следующий элемент очереди.

## Команды

### `/play <query>`

Ищет музыку в выбранном источнике и показывает варианты кнопками.

### `/queue`

Показывает текущий трек и очередь.

### `/skip`

Останавливает текущий source. Очередь не очищается, поэтому callback запускает следующий трек.

### `/stop`

Останавливает текущий трек и очищает очередь.

### `/join`

Подключает бота к voice-каналу пользователя.

### `/leave`

Очищает состояние текущего guild и отключает voice.

### `/ping`

Проверяет доступность бота.

### `/playtest`

Диагностический playback локального `test.mp3` без музыкальных провайдеров.

## Структура проекта

```text
MusicBot/
├── bot.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── docs/
│   └── architecture.md
│
├── native/
│   └── macos/
│       ├── ChromeAudioTap.swift
│       ├── Info.plist
│       └── bin/
│           └── chrome_audio_tap
│
└── music_bot/
    ├── app.py
    ├── config.py
    │
    ├── audio/
    │   ├── base.py
    │   ├── factory.py
    │   ├── live_ffmpeg.py
    │   ├── process_pcm.py
    │   ├── windows.py
    │   └── macos.py
    │
    ├── commands/
    │   ├── music.py
    │   └── debug.py
    │
    ├── music/
    │   ├── models.py
    │   └── player.py
    │
    ├── providers/
    │   ├── hitmo.py
    │   └── vk/
    │       ├── player.py
    │       └── browser_profile/
    │
    └── ui/
        └── track_select.py
```

## Роли основных модулей

- `bot.py` — минимальная точка входа;
- `music_bot/app.py` — создание Discord-приложения и lifecycle;
- `music_bot/config.py` — `.env` → `Settings`;
- `commands/music.py` — slash-команды;
- `providers/hitmo.py` — Hitmo search/parser;
- `providers/vk/player.py` — Playwright, persistent Chrome, VK search/playback;
- `music/models.py` — `MusicSource`, `TrackCandidate`, `QueueItem`;
- `music/player.py` — очередь и orchestration воспроизведения;
- `audio/base.py` — контракт платформенного live-capture;
- `audio/factory.py` — выбор Windows/macOS backend;
- `audio/windows.py` — VB-CABLE/DirectShow;
- `audio/live_ffmpeg.py` — live PCM reader поверх FFmpeg;
- `audio/macos.py` — запуск macOS Swift helper;
- `audio/process_pcm.py` — PCM из stdout нативного процесса;
- `native/macos/ChromeAudioTap.swift` — Core Audio Process Tap только для Chrome;
- `ui/track_select.py` — кнопки выбора результатов.

Подробнее внутренняя архитектура описана в `docs/architecture.md`.

## Важные особенности и ограничения

### VK зависит от DOM

Для поиска используются стабильные `data-testid`, а выбранный результат сохраняется по точному `track_id`. Тем не менее изменение VK DOM может потребовать обновления `music_bot/providers/vk/player.py`.

### Один глобальный VK playback pipeline

Текущая реализация использует один `VKPlayer`, один Chrome playback tab и один системный live-capture pipeline. Поэтому одновременно воспроизводить разные VK-треки на нескольких Discord-серверах нельзя. Очереди по guild разделены, но VK playback backend физически один.

### Hitmo и VK воспроизводятся по-разному

Hitmo:

```text
stream_url → FFmpegPCMAudio → Discord
```

VK:

```text
Chrome playback → platform AudioCapture → PCM AudioSource → Discord
```

### Очередь хранится в памяти

После рестарта процесса текущий трек и очередь теряются.

### macOS helper — build artifact

В Git рекомендуется хранить:

```text
native/macos/ChromeAudioTap.swift
native/macos/Info.plist
```

Бинарник `native/macos/bin/chrome_audio_tap` лучше собирать на целевой машине, особенно при переносе между Apple Silicon и Intel.

## Shutdown

При завершении приложения `MusicPlayer.close()` должен:

1. запретить запуск новых треков;
2. отменить idle/live-end задачи;
3. остановить активное аудио;
4. отключить voice clients;
5. закрыть платформенный audio backend;
6. закрыть VK BrowserContext/Playwright;
7. очистить очереди и текущее состояние.

`MusicBot.close()` затем вызывает `super().close()`, чтобы гарантированно закрыть Discord Gateway.

## Диагностика

### Windows: VK играет в Chrome, но в Discord тишина

Проверь маршрут Chrome:

```text
Chrome Output → CABLE Input
```

И наличие capture device:

```powershell
ffmpeg -list_devices true -f dshow -i dummy
```

### macOS: helper не найден

Собери его командой из раздела macOS и проверь:

```bash
ls -l native/macos/bin/chrome_audio_tap
```

### macOS: helper не получает аудио

Проверь разрешение System Audio Recording для терминала/процесса, из которого запускается бот.

### `OpusNotLoaded`

Проверь системный Opus:

```bash
brew list opus
```

### Поиск Hitmo перестал работать

Проверь актуальную HTML-разметку и `data-musmeta` в `music_bot/providers/hitmo.py`.
