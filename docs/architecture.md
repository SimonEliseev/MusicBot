# Архитектура MusicBot

Этот файл кратко описывает внутреннее устройство проекта и предназначен в первую очередь для дальнейшей модификации кода.

## 1. Точка входа

`bot.py` ничего не знает о поиске музыки, Discord-командах или очереди. Он только вызывает:

```python
from music_bot.app import run

run()
```

Это позволяет держать запуск отдельно от бизнес-логики.

## 2. Создание приложения

`music_bot/app.py` содержит класс `MusicBot`.

При создании приложения:

1. включаются стандартные Discord intents;
2. явно включается `voice_states`;
3. создаётся `HitmoProvider`;
4. создаётся один `MusicPlayer`;
5. подключаются `MusicCog` и `DebugCog`;
6. slash-команды синхронизируются для `GUILD_ID`.

На данный момент команды синхронизируются только с сервером, указанным в `.env`. Это удобно во время разработки, потому что изменения команд появляются почти сразу.

## 3. Конфигурация

`music_bot/config.py` превращает значения из `.env` в объект `Settings`:

```text
.env
 ↓
Settings.from_env()
 ↓
Settings
```

Обязательные поля валидируются при запуске. Если токен или ID сервера отсутствует, приложение завершается с понятной ошибкой.

## 4. Discord-команды

`music_bot/commands/music.py` содержит `MusicCog`.

Cog отвечает только за взаимодействие с пользователем:

- проверить контекст команды;
- получить параметры;
- вызвать провайдер или плеер;
- сформировать Discord-сообщение.

Поиск выполняется через:

```python
await asyncio.to_thread(self.provider.search, ...)
```

Это важно, потому что текущий `httpx.Client` в `HitmoProvider` синхронный. HTTP-запрос переносится в отдельный поток и не блокирует event loop Discord-бота.

## 5. Провайдер музыки

`music_bot/providers/hitmo.py` изолирует работу с конкретным источником.

Текущий алгоритм:

```text
GET https://ru.hitmoz.org/search?q=<query>
                ↓
        BeautifulSoup
                ↓
li.tracks__item.track[data-musmeta]
                ↓
        JSON data-musmeta
                ↓
        TrackCandidate
```

Из карточки извлекаются:

- `artist`;
- `title`;
- `stream_url`;
- `track_id`;
- `duration`.

Так как источник изолирован, в будущем можно добавить другой провайдер, не переписывая `MusicPlayer`.

## 6. Модели данных

`music_bot/music/models.py` содержит две простые dataclass-модели.

### `TrackCandidate`

Представляет найденный трек:

```text
artist
title
stream_url
track_id
duration
```

`display_name` возвращает строку:

```text
Исполнитель — Название
```

### `QueueItem`

Оборачивает трек и хранит `channel_id` текстового канала, куда нужно отправить уведомление, когда этот элемент очереди начнёт играть.

## 7. UI выбора трека

`music_bot/ui/track_select.py` содержит:

- `TrackSelectView`;
- `TrackSelectButton`.

После `/play` пользователь получает до `SEARCH_LIMIT` результатов и кнопки с номерами.

`interaction_check()` разрешает нажать кнопку только пользователю, который инициировал поиск.

После выбора:

1. определяется voice-канал пользователя;
2. бот подключается или перемещается туда;
3. создаётся `QueueItem`;
4. элемент передаётся в `MusicPlayer.enqueue_or_play()`.

Если ничего не играет, трек запускается сразу. Иначе метод возвращает позицию в очереди.

## 8. MusicPlayer

`music_bot/music/player.py` — центральная логика воспроизведения.

Для каждого `guild_id` хранятся:

```text
queues[guild_id]         -> deque[QueueItem]
current_tracks[guild_id] -> текущий QueueItem
idle_tasks[guild_id]     -> asyncio.Task
```

### Добавление трека

```text
enqueue_or_play()
      │
      ├─ уже играет → queue.append()
      │
      └─ свободен   → start_track()
```

### Запуск трека

`start_track()`:

1. отменяет idle-таймер;
2. запоминает текущий трек;
3. создаёт `discord.FFmpegPCMAudio`;
4. передаёт `stream_url` FFmpeg;
5. запускает `VoiceClient.play()`.

Для FFmpeg задаются параметры повторного подключения к HTTP-потоку:

```text
-reconnect 1
-reconnect_streamed 1
-reconnect_delay_max 5
```

и User-Agent, совместимый с запросами провайдера.

## 9. Автоматический следующий трек

`discord.VoiceClient.play()` получает callback `after_playback`.

Он вызывается после естественного окончания трека и после `voice_client.stop()`.

Так как callback вызывается не как обычная async-корутина, переход обратно в event loop выполняется через:

```python
asyncio.run_coroutine_threadsafe(
    self.play_next(guild_id),
    loop,
)
```

`play_next()`:

```text
очередь не пуста
    ↓
popleft()
    ↓
start_track()

очередь пуста
    ↓
очистить current_track
    ↓
запустить idle-таймер
```

Именно поэтому `/skip` достаточно вызвать `voice_client.stop()` — callback автоматически запускает следующий трек.

## 10. Разница между skip и stop

### `/skip`

Не очищает очередь:

```text
stop current audio
      ↓
after_playback
      ↓
play_next
```

### `/stop`

Сначала очищает очередь и текущий трек, затем останавливает аудио. Callback срабатывает, но очередь уже пустая, поэтому новое воспроизведение не начинается.

## 11. Idle-disconnect

Когда бот подключён к voice, но ничего не играет и очередь пуста, создаётся `asyncio.Task`.

Через `IDLE_TIMEOUT_SECONDS` состояние проверяется ещё раз. Если бот всё ещё бездействует, вызывается:

```python
await voice_client.disconnect()
```

При запуске нового трека idle-задача отменяется.

Важно: это отключает только voice-соединение. Сам Discord-бот и Python-процесс продолжают работать.

## 12. Жизненный цикл `/play`

Полный сценарий:

```text
/play "Linkin Park Numb"
        │
        ▼
MusicCog.play
        │
        ▼
HitmoProvider.search
        │
        ▼
TrackCandidate[0..N]
        │
        ▼
Discord Embed + TrackSelectView
        │
        ▼
пользователь нажал кнопку
        │
        ▼
TrackSelectButton.callback
        │
        ▼
QueueItem
        │
        ▼
MusicPlayer.enqueue_or_play
        │
        ├── очередь
        │
        └── start_track
                │
                ▼
              FFmpeg
                │
                ▼
          Discord Voice
```

## 13. Где что изменять

Если нужно изменить поиск или HTML-разбор источника:

```text
music_bot/providers/hitmo.py
```

Если нужно изменить очередь, idle timeout или воспроизведение:

```text
music_bot/music/player.py
```

Если нужно добавить slash-команду:

```text
music_bot/commands/music.py
```

Если нужно изменить отображение вариантов поиска и кнопки:

```text
music_bot/ui/track_select.py
```

Если нужно добавить настройку из `.env`:

```text
music_bot/config.py
```

## 14. Возможные следующие улучшения

Архитектура уже позволяет относительно просто добавить:

- `/pause` и `/resume`;
- удаление конкретного элемента очереди;
- очистку очереди без остановки текущего трека;
- кнопки управления плеером;
- постоянное хранение очереди в БД/Redis;
- несколько музыкальных провайдеров;
- поиск песни по фрагменту текста;
- обновление временного `stream_url` непосредственно перед началом воспроизведения;
- логирование вместо `print()`;
- тесты для парсера Hitmo и логики очереди.
