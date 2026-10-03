# AI Shorts Auto Publisher

> Из длинного видео — в готовые YouTube Shorts и VK Видео.

CLI-инструмент, который сам находит сильные фрагменты в видео, превращает их в вертикальные ролики и отправляет результат на нужные площадки.

Подходит для интервью, подкастов, лекций, стримов и любого контента, из которого хочется регулярно делать короткие видео без ручного просмотра многочасового исходника.

![Пример результата](assets/video-demo-thumb.png)

## Что умеет

- принимает ссылку на YouTube или локальный MP4;
- расшифровывает речь и ищет фрагменты, которые имеют смысл смотреть отдельно;
- убирает сильно пересекающиеся варианты;
- обрезает исходник под вертикальный формат;
- сохраняет клипы локально или получает их через MuAPI;
- публикует ролики в YouTube Shorts и VK Видео;
- ведёт журнал публикаций, чтобы не загружать один и тот же клип повторно после сбоя;
- возвращает подробный JSON-результат по каждому ролику и каждой площадке.

Сейчас проект работает из командной строки. Субтитры, веб-интерфейс и встроенный планировщик пока не входят в сценарий.

## Быстрый старт

Нужны Python 3.10+, FFmpeg и ключ OpenAI или Gemini для выбора фрагментов в локальном режиме.

```powershell
git clone https://github.com/Mastn1kth/ai-shorts-auto-publisher.git
cd ai-shorts-auto-publisher

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-local.txt
Copy-Item .env.example .env
```

Для Linux и macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env
```

Откройте `.env` и добавьте нужные ключи. Не коммитьте `.env`, OAuth-файлы и токены.

## Первый ролик

Из YouTube:

```powershell
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --num-clips 3 --output-json result.json
```

Из локального файла:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --num-clips 3 --output-json result.json
```

Готовые клипы появятся в `LOCAL_OUTPUT_DIR` — по умолчанию это папка `output`. JSON-файл содержит транскрипт, найденные кандидаты, созданные Shorts и статусы публикации.

## Публикация

Сначала удобно проверить весь сценарий в безопасном режиме:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk --publish-dry-run --output-json dry-run.json
```

Приватная загрузка на YouTube и VK:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk --publish-privacy private --output-json result.json
```

Публичная публикация на обеих площадках:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk --publish-privacy public --output-json result.json
```

По умолчанию используется `private`. Режим `unlisted` доступен только при публикации на YouTube.

## Подключение площадок

### YouTube Shorts

1. В Google Cloud включите YouTube Data API v3.
2. Создайте OAuth-клиент типа Desktop.
3. Укажите путь к JSON в `YOUTUBE_CLIENT_SECRET_FILE`.
4. При первой загрузке подтвердите доступ к каналу в браузере.

Токен сохраняется в `YOUTUBE_TOKEN_FILE`. Не прошедшие аудит проекты YouTube API могут загружать видео только как приватные.

### VK Видео

Укажите `VK_ACCESS_TOKEN`. Для публикации в сообщество добавьте `VK_GROUP_ID`; переменная `VK_PUBLISH_TO_WALL=true` также отправит публичное видео на стену сообщества.

## Два режима генерации

`local` скачивает или обрабатывает исходник на вашем компьютере. Для него нужны FFmpeg, `yt-dlp`, `faster-whisper` и ключ OpenAI или Gemini.

`api` использует MuAPI и подходит, если вы хотите вынести тяжёлую обработку за пределы локальной машины. В этом режиме достаточно зависимостей из `requirements.txt` и настроек MuAPI.

## Повторный запуск после сбоя

После каждой успешной загрузки результат записывается в `output/publishing-ledger.json`. При следующем запуске проект пропустит площадку, которая уже приняла этот клип, и попробует остальные.

Если нужно сознательно загрузить ролик заново, используйте:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube --force-republish
```

Если API принял файл, но журнал не успел сохраниться, команда покажет `tracking_error`. Перед повторной загрузкой в таком случае проверьте аккаунт вручную.

## Результат

В `result.json` у каждого клипа есть блок `publishing` со статусом по каждой площадке. Возможные статусы: `dry_run`, `uploaded`, `already_uploaded` и `failed`.

`uploaded` означает, что API принял файл. Финальную обработку и появление ролика в профиле площадки иногда нужно проверить отдельно.

## Полезные файлы

- `.env.example` — список настроек и ключей;
- `main.py` — CLI-точка входа;
- `shorts_generator/` — загрузка, транскрипция, поиск фрагментов и публикация;
- `tests/` — автоматические тесты издателей.

## Статус проекта

Проект развивается вокруг надёжного CLI-сценария: взять длинное видео, получить несколько осмысленных вертикальных фрагментов и безопасно отправить их на выбранные площадки. Если нашли проблему или есть идея по улучшению, создайте issue с примером команды, входным файлом/ссылкой и фрагментом JSON-результата.
