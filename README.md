# AI Shorts Auto Publisher

Создаёт короткие вертикальные ролики из длинного YouTube-видео или локального MP4 и отправляет готовые клипы в YouTube Shorts, VK Видео и Instagram Reels.

Это CLI-проект для собственных аккаунтов. Он ищет фрагменты по транскрипту, нарезает видео и сохраняет результат публикации отдельно для каждой площадки. Публикация доступна только после настройки официальных API и разрешений соответствующих аккаунтов.

## Что уже есть

- Обработка YouTube-ссылки или локального файла.
- Два режима генерации: `api` через MuAPI и `local` через yt-dlp, faster-whisper, FFmpeg, OpenCV и OpenAI либо Gemini для выбора фрагментов.
- Выбор интересных моментов, удаление сильно пересекающихся фрагментов, обрезка до вертикального формата.
- Загрузка в YouTube через OAuth и YouTube Data API, в VK через `video.save` и upload URL, в Instagram через контейнер Reels и `media_publish`.
- Отдельный статус каждой загрузки в JSON и код выхода `2`, если хотя бы одна публикация завершилась ошибкой.

`local` не означает полностью автономную работу: для выбора фрагментов всё ещё нужен ключ OpenAI или Gemini. Проект пока не добавляет субтитры и не содержит веб-интерфейса или планировщика.

## Установка

Требуется Python 3.10+. В `local` режиме нужны FFmpeg в `PATH` и ресурсы для faster-whisper. Для YouTube-скачивания нужен yt-dlp.

```powershell
git clone https://github.com/Mastn1kth/ai-shorts-auto-publisher.git
cd ai-shorts-auto-publisher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-local.txt
pip install -r requirements-publish.txt
Copy-Item .env.example .env
```

На Linux/macOS активация окружения: `source .venv/bin/activate`, копирование настроек: `cp .env.example .env`.

Для одного `api` режима достаточно `pip install -r requirements.txt`. Для локальных MP4, отправляемых в Instagram, нужен `boto3` из `requirements-publish.txt`. Зависимости устанавливаются только для используемых режимов.

Заполните `.env` своими ключами. Не публикуйте `.env`, OAuth JSON и токены в Git.

## Генерация роликов

```powershell
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" --mode local --num-clips 3 --output-json result.json
```

Для локального файла:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --num-clips 3 --output-json result.json
```

Ролики в `local` режиме сохраняются в `LOCAL_OUTPUT_DIR` (по умолчанию `output`). `api` режим возвращает URL клипов от MuAPI.

## Публикация

Проверка сценария без обращения к API публикации:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk instagram --publish-dry-run --output-json dry-run.json
```

`--publish-dry-run` пропускает **только загрузку в соцсети**. Генерация роликов всё равно выполняется и может обращаться к MuAPI, OpenAI или Gemini. Эта проверка не подтверждает действительность токенов.

Приватная загрузка на YouTube и VK:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk --publish-privacy private --output-json result.json
```

Публичная загрузка на три площадки:

```powershell
python main.py "D:\Videos\interview.mp4" --mode local --publish youtube vk instagram --publish-privacy public --output-json result.json
```

`private` выбран по умолчанию. `unlisted` работает только для YouTube. Instagram Reels через этот API публикуются публично; для него нужно явно указать `--publish-privacy public`. Ошибочная комбинация отклоняется до обработки видео. Если одну площадку не удалось обработать, результат других остаётся в `result.json`.

### Повторный запуск после сбоя

После каждой успешной загрузки проект сохраняет результат в `PUBLISH_LEDGER_FILE` (по умолчанию `output/publishing-ledger.json`). При повторном запуске тот же клип не отправляется второй раз на площадку, принявшую его; остальные площадки пробуются снова. Для намеренной повторной загрузки добавьте `--force-republish`.

Смена `--publish-privacy` не изменяет видимость уже загруженного видео: журнал пропустит повторную отправку. Чтобы сделать приватный ролик публичным, измените его настройки на самой площадке; `--force-republish` создаст второй ролик.

Для локального MP4 совпадение определяется по содержимому готового клипа. Для клипа с удалённым URL используются исходная ссылка и временные границы фрагмента. Журнал ведётся для последовательных запусков на одном компьютере: не удаляйте его и не запускайте одновременно несколько копий публикации одного ролика. Изменение исходного ролика, границ клипа, аккаунта или пути к журналу может привести к новой загрузке. Если API принял файл, но журнал не удалось записать, команда показывает `tracking_error` и завершается с кодом `2`; перед повтором проверьте аккаунт площадки вручную.

Для YouTube ключ журнала по умолчанию привязан к пути `YOUTUBE_TOKEN_FILE`, чтобы он не менялся после первой авторизации. Если вы работаете с несколькими каналами или заменяете аккаунт в том же файле токена, задайте уникальный `YOUTUBE_ACCOUNT_ID` для каждого канала. При смене аккаунта проверьте журнал перед повторным запуском.

### YouTube Shorts

1. В Google Cloud включите YouTube Data API v3 и создайте OAuth-клиент типа Desktop.
2. Скачайте JSON и укажите его путь в `YOUTUBE_CLIENT_SECRET_FILE`.
3. При первой загрузке подтвердите доступ к своему YouTube-каналу в браузере. Токен сохраняется в `YOUTUBE_TOKEN_FILE`.

Не прошедшие аудит проекты YouTube API могут загружать видео только как приватные. Возвращённая ссылка не означает, что YouTube закончил обработку ролика. [Документация `videos.insert`](https://developers.google.com/youtube/v3/docs/videos/insert).

### VK Видео

Укажите `VK_ACCESS_TOKEN`. Для сообщества заполните `VK_GROUP_ID`; аккаунт и токен должны иметь право загружать видео в это сообщество. `VK_PUBLISH_TO_WALL=true` публикует видео на стене при публичном режиме. Код запрашивает `video.save`, затем отправляет MP4 на полученный upload URL. `unlisted` для VK не поддерживается.

### Instagram Reels

Нужен профессиональный аккаунт Instagram (Business или Creator), действующий токен с разрешением на публикацию и `INSTAGRAM_USER_ID`. Эта реализация использует вариант Instagram API с Facebook Login.

Instagram должен получить ролик по публичному HTTPS URL. Для клипа, созданного через MuAPI, используется его hosted URL. Для локального MP4 настройте S3-совместимое хранилище:

```dotenv
MEDIA_S3_BUCKET=my-bucket
MEDIA_S3_ENDPOINT=https://s3.example.com
MEDIA_PUBLIC_BASE_URL=https://cdn.example.com
```

Ключи хранилища `boto3` берёт из стандартной цепочки AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, профиль или роль). Сам бакет/CDN должен позволять Instagram читать загруженный объект по URL. Проект загружает MP4 в бакет, ждёт готовности контейнера Instagram и вызывает `media_publish`. Настроить права бакета и доступность CDN нужно в вашем хранилище.

## Как устроен результат

`--output-json` содержит транскрипт, список кандидатов и массив `shorts`. У каждого клипа появляется объект `publishing` со статусом для каждой площадки: `dry_run`, `uploaded`, `published`, `already_uploaded`, `already_published` или `failed`, а также ID/ссылка либо сообщение об ошибке. Статус `uploaded` у YouTube и VK означает, что API принял загрузку; окончательную обработку на площадке нужно проверить отдельно.

## Происхождение и лицензия

Проект создан на основе [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) Anil Chandra Naidu Matcha. Исходная MIT-лицензия и уведомление об авторских правах сохранены в [LICENSE](LICENSE). Этот репозиторий имеет самостоятельную историю Git и не зарегистрирован на GitHub как fork.
