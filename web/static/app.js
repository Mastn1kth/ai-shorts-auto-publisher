const form = document.querySelector('#job-form');
const fileInput = document.querySelector('#video-input');
const dropZone = document.querySelector('#drop-zone');
const selectedFile = document.querySelector('#selected-file');
const sourceUrl = document.querySelector('#source-url');
const privacy = document.querySelector('#privacy');
const results = document.querySelector('#results');
const jobState = document.querySelector('#job-state');
const statusMessage = document.querySelector('#status-message');
const clips = document.querySelector('#clips');
const startButton = document.querySelector('#start-button');
const connectionsPanel = document.querySelector('#connections');
const videoMode = document.querySelector('#video-mode');
const sequenceOptions = document.querySelector('#sequence-options');
let lastState = '';
let lastClipsSignature = '';
function updateVideoMode() { sequenceOptions.hidden = videoMode.value !== 'sequence'; }
videoMode.addEventListener('change', updateVideoMode);
updateVideoMode();
connectionsPanel.addEventListener('toggle', () => {
  connectionsPanel.querySelector('.summary-action').textContent = connectionsPanel.open ? 'ЗАКРЫТЬ ↑' : 'ОТКРЫТЬ ↗';
});

function connectionFeedback(message, isError = false) {
  const target = document.querySelector('#connection-message');
  target.textContent = message;
  target.classList.toggle('error', isError);
}

async function connectionRequest(url, data) {
  const response = await fetch(url, { method: 'POST', body: data });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Не удалось сохранить настройки');
  return payload;
}

function updateConnections(status) {
  const savedAI = Object.entries(status.ai_saved || {}).filter(([, saved]) => saved).map(([name]) => name);
  document.querySelector('#ai-status').textContent = savedAI.length ? `Сохранено: ${savedAI.join(', ')}` : 'Добавь хотя бы один ключ';
  document.querySelector('#youtube-status').textContent = status.youtube_auth.status === 'connected'
    ? 'Вход Google подтверждён'
    : status.youtube_auth.status === 'pending' ? 'Ожидаем вход через Google…'
      : status.youtube_token_ready ? 'Токен есть · права не проверены' : status.youtube_client_ready ? 'OAuth JSON добавлен' : 'Не подключён';
  document.querySelector('#youtube-connect-button').textContent = status.youtube_token_ready ? 'ПРОВЕРИТЬ ВХОД ↗' : 'АВТОРИЗОВАТЬСЯ ↗';
  document.querySelector('#vk-status').textContent = status.vk_token_saved ? 'Токен сохранён · права не проверены' : 'Не подключён';
  document.querySelector('#vk-setup-button').textContent = status.vk_token_saved ? 'ИЗМЕНИТЬ НАСТРОЙКИ ↗' : 'ПОДКЛЮЧИТЬ VK ↗';
  document.querySelector('#telegram-status').textContent = status.telegram_token_saved && status.telegram_chat_id
    ? `Бот сохранён · ${status.telegram_chat_id}` : 'Не подключён';
  document.querySelector('#telegram-setup-button').textContent = status.telegram_token_saved && status.telegram_chat_id
    ? 'ИЗМЕНИТЬ НАСТРОЙКИ ↗' : 'ПОДКЛЮЧИТЬ TELEGRAM ↗';
  document.querySelector('#tiktok-status').textContent = status.tiktok_token_saved ? 'Токен сохранён' : 'Не подключён';
  document.querySelector('#tiktok-setup-button').textContent = status.tiktok_token_saved ? 'ИЗМЕНИТЬ НАСТРОЙКИ ↗' : 'ПОДКЛЮЧИТЬ TIKTOK ↗';
  if (status.youtube_auth.status === 'failed') connectionFeedback(status.youtube_auth.error || 'Ошибка входа Google', true);
}

async function refreshConnections() {
  try {
    const response = await fetch('/api/connections');
    if (!response.ok) throw new Error('Не удалось проверить подключения');
    const status = await response.json();
    updateConnections(status);
    if (status.youtube_auth.status === 'pending') setTimeout(refreshConnections, 2500);
  } catch (error) {
    connectionFeedback(error.message, true);
  }
}

document.querySelectorAll('.connection-token-form').forEach((settingsForm) => settingsForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const status = await connectionRequest('/api/connections/tokens', new FormData(settingsForm));
    settingsForm.querySelectorAll('input[type="password"]').forEach((input) => { input.value = ''; });
    const setup = settingsForm.closest('.connection-setup');
    if (setup) setup.open = false;
    updateConnections(status);
    connectionFeedback('Сохранено в хранилище Windows.');
  } catch (error) {
    connectionFeedback(error.message, true);
  }
}));
['vk', 'telegram', 'tiktok'].forEach((platform) => {
  document.querySelector(`#${platform}-setup-button`).addEventListener('click', () => {
    const setup = document.querySelector(`#${platform}-setup`);
    setup.open = true;
    setup.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setup.querySelector('input[type="password"]').focus();
  });
});

async function startYoutubeAuth() {
  await connectionRequest('/api/connections/youtube/authorize', new FormData(document.querySelector('#youtube-auth-form')));
  connectionFeedback('Откроется окно Google. Подтверди доступ к каналу.');
  refreshConnections();
}
document.querySelector('#youtube-client-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const status = await connectionRequest('/api/connections/youtube/client', new FormData(event.currentTarget));
    updateConnections(status);
    connectionFeedback('Файл добавлен. Открываем вход Google…');
    await startYoutubeAuth();
  } catch (error) {
    connectionFeedback(error.message, true);
  }
});
document.querySelector('#youtube-auth-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const status = await (await fetch('/api/connections')).json();
    if (!status.youtube_client_ready) {
      const setup = document.querySelector('#youtube-setup');
      setup.open = true;
      setup.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      connectionFeedback('Для первого входа добавь OAuth-файл. После этого откроется Google.');
      return;
    }
    await startYoutubeAuth();
  } catch (error) {
    connectionFeedback(error.message, true);
  }
});
refreshConnections();

function setFile(file) {
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  selectedFile.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} МБ`;
  dropZone.classList.add('has-file');
  sourceUrl.value = '';
}

dropZone.addEventListener('click', (event) => {
  if (event.target !== fileInput) fileInput.click();
});
dropZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
sourceUrl.addEventListener('input', () => {
  if (sourceUrl.value.trim()) {
    fileInput.value = '';
    dropZone.classList.remove('has-file');
    selectedFile.textContent = 'MP4 · до 4 ГБ';
  }
});
['dragenter', 'dragover'].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.add('drag-over');
}));
['dragleave', 'drop'].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.remove('drag-over');
}));
dropZone.addEventListener('drop', (event) => setFile(event.dataTransfer.files[0]));

document.querySelectorAll('input[name="platforms"]').forEach((box) => box.addEventListener('change', () => {
  if (box.value === 'telegram' && box.checked) privacy.value = 'public';
}));

function showStatus(state, message) {
  results.hidden = false;
  jobState.textContent = state;
  statusMessage.textContent = message;
  if (state !== lastState) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
  lastState = state;
}

function renderClips(shorts) {
  clips.replaceChildren();
  shorts.forEach((item, index) => {
    const card = document.createElement('article');
    card.className = 'clip-card';
    const media = document.createElement('div');
    media.className = 'clip-media';
    if (item.video_url) {
      if (item.thumbnail_url) {
        const thumbnail = document.createElement('img');
        thumbnail.src = item.thumbnail_url;
        thumbnail.alt = `Превью: ${item.title || `клип ${index + 1}`}`;
        thumbnail.className = 'clip-thumbnail';
        media.append(thumbnail);
      }
      const video = document.createElement('video');
      video.controls = true;
      video.preload = 'metadata';
      video.src = item.video_url;
      if (item.thumbnail_url) video.poster = item.thumbnail_url;
      media.append(video);
    } else {
      media.classList.add('clip-error');
      media.textContent = 'Видео не создано';
    }
    const info = document.createElement('div');
    info.className = 'clip-info';
    const number = document.createElement('span');
    number.className = 'clip-number';
    number.textContent = `КЛИП ${String(index + 1).padStart(2, '0')}`;
    const title = document.createElement('h3');
    title.textContent = item.title || `Клип ${index + 1}`;
    const timing = document.createElement('p');
    timing.textContent = `${Number(item.start_time || 0).toFixed(1)}–${Number(item.end_time || 0).toFixed(1)} сек · оценка ${item.score ?? '—'}`;
    info.append(number, title, timing);
    if (item.description) {
      const description = document.createElement('p');
      description.className = 'clip-description';
      description.textContent = item.description;
      info.append(description);
    }
    if (item.scheduled_at) {
      const schedule = document.createElement('p');
      schedule.className = 'clip-schedule';
      schedule.textContent = `Публикация: ${new Date(item.scheduled_at).toLocaleString('ru-RU')}`;
      info.append(schedule);
    }
    if (item.error) {
      const error = document.createElement('p');
      error.className = 'clip-failure';
      error.textContent = item.error;
      info.append(error);
    }
    if (item.video_url) {
      const download = document.createElement('a');
      download.href = item.video_url;
      download.download = `short-${index + 1}.mp4`;
      download.textContent = 'СКАЧАТЬ MP4 ↗';
      download.className = 'download-link';
      info.append(download);
    }
    Object.entries(item.publishing || {}).forEach(([platform, status]) => {
      const line = document.createElement('p');
      line.className = 'publish-status';
      line.textContent = `${platform}: ${status.status}${status.error ? ` — ${status.error}` : ''}`;
      info.append(line);
    });
    card.append(media, info);
    clips.append(card);
  });
}

function renderApproval(job) {
  const existing = document.querySelector('#approve-publishing');
  if (existing) existing.remove();
  if (job.publish_state !== 'awaiting_approval') return;
  const button = document.createElement('button');
  button.id = 'approve-publishing';
  button.className = 'approve-button';
  button.textContent = 'РАЗРЕШИТЬ ПУБЛИКАЦИЮ ↗';
  button.addEventListener('click', async () => {
    button.disabled = true;
    const data = new FormData();
    data.append('csrf_token', form.querySelector('[name="csrf_token"]').value);
    const response = await fetch(`/api/jobs/${job.id}/approve`, { method: 'POST', body: data });
    const payload = await response.json();
    if (!response.ok) { button.disabled = false; return showStatus('ОШИБКА', payload.error || 'Не удалось начать публикацию'); }
    pollJob(job.id);
  });
  statusMessage.after(button);
}

async function pollJob(id) {
  try {
    const response = await fetch(`/api/jobs/${id}`);
    if (!response.ok) throw new Error('Задача не найдена. Возможно, сервер был перезапущен.');
    const job = await response.json();
    if (job.status === 'completed') {
      const pending = job.publish_state === 'pending';
      const approval = job.publish_state === 'awaiting_approval';
      showStatus(pending ? 'ОЧЕРЕДЬ АКТИВНА' : approval ? 'НУЖНО ПОДТВЕРЖДЕНИЕ' : 'ГОТОВО', pending
        ? `Создано клипов: ${job.shorts.length}. Публикация идёт по расписанию; держи программу запущенной.`
        : approval ? `Создано клипов: ${job.shorts.length}. Проверь ролики и нажми подтверждение, когда всё устроит.`
        : `Создано клипов: ${job.shorts.length}. Проверь результат на выбранных площадках.`);
      const signature = JSON.stringify(job.shorts);
      if (signature !== lastClipsSignature) {
        renderClips(job.shorts);
        lastClipsSignature = signature;
      }
      renderApproval(job);
      if (pending) setTimeout(() => pollJob(id), 15000);
      else localStorage.removeItem('shortform-active-job');
      localStorage.setItem('shortform-last-job', id);
      startButton.disabled = false;
      return;
    }
    if (job.status === 'failed') {
      localStorage.removeItem('shortform-active-job');
      localStorage.setItem('shortform-last-job', id);
      showStatus('ОШИБКА', job.error || 'Не удалось обработать видео');
      startButton.disabled = false;
      return;
    }
    showStatus('В РАБОТЕ', 'Обрабатываем видео. Это может занять несколько минут — окно программы можно оставить открытым.');
    setTimeout(() => pollJob(id), 2500);
  } catch (error) {
    localStorage.removeItem('shortform-active-job');
    showStatus('ОШИБКА', error.message);
    startButton.disabled = false;
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files[0] && !sourceUrl.value.trim()) return showStatus('НУЖЕН ИСТОЧНИК', 'Выбери MP4 или вставь ссылку YouTube.');
  startButton.disabled = true;
  clips.replaceChildren();
  showStatus('ЗАГРУЗКА', 'Сохраняем видео локально для обработки…');
  try {
    const response = await fetch('/api/jobs', { method: 'POST', body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || 'Не удалось запустить обработку');
    localStorage.setItem('shortform-active-job', payload.id);
    pollJob(payload.id);
  } catch (error) {
    showStatus('ОШИБКА', error.message);
    startButton.disabled = false;
  }
});

async function restoreLatestJob() {
  const existingJob = localStorage.getItem('shortform-active-job');
  const lastJob = localStorage.getItem('shortform-last-job');
  try {
    const response = await fetch('/api/jobs/latest');
    const latest = response.ok ? (await response.json()).id : null;
    const id = latest || existingJob || lastJob;
    if (id) pollJob(id);
  } catch (error) {
    if (existingJob || lastJob) pollJob(existingJob || lastJob);
  }
}
restoreLatestJob();
