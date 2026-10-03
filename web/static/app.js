const form = document.querySelector('#job-form');
const fileInput = document.querySelector('#video-input');
const dropZone = document.querySelector('#drop-zone');
const selectedFile = document.querySelector('#selected-file');
const sourceUrl = document.querySelector('#source-url');
const provider = document.querySelector('#provider');
const model = document.querySelector('#model');
const baseUrlField = document.querySelector('#base-url-field');
const keyInput = document.querySelector('#api-key');
const privacy = document.querySelector('#privacy');
const results = document.querySelector('#results');
const jobState = document.querySelector('#job-state');
const statusMessage = document.querySelector('#status-message');
const clips = document.querySelector('#clips');
const startButton = document.querySelector('#start-button');
let lastState = '';
let lastClipsSignature = '';
const modelExamples = {
  openai: 'gpt-4o-mini',
  gemini: 'gemini-2.5-flash',
  openrouter: 'openai/gpt-4o-mini',
  groq: 'openai/gpt-oss-20b',
  custom: 'model-name'
};

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
    selectedFile.textContent = 'MP4 · до 4 ГБ · обрабатывается локально';
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

provider.addEventListener('change', () => {
  model.value = modelExamples[provider.value] || '';
  baseUrlField.classList.toggle('hidden', provider.value !== 'custom');
});
document.querySelector('#toggle-key').addEventListener('click', (event) => {
  const visible = keyInput.type === 'text';
  keyInput.type = visible ? 'password' : 'text';
  event.currentTarget.textContent = visible ? 'ПОКАЗАТЬ' : 'СКРЫТЬ';
  event.currentTarget.setAttribute('aria-label', visible ? 'Показать API-ключ' : 'Скрыть API-ключ');
});
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

async function pollJob(id) {
  try {
    const response = await fetch(`/api/jobs/${id}`);
    if (!response.ok) throw new Error('Задача не найдена. Возможно, сервер был перезапущен.');
    const job = await response.json();
    if (job.status === 'completed') {
      const pending = job.publish_state === 'pending';
      showStatus(pending ? 'ОЧЕРЕДЬ АКТИВНА' : 'ГОТОВО', pending
        ? `Создано клипов: ${job.shorts.length}. Публикация идёт по расписанию; держи программу запущенной.`
        : `Создано клипов: ${job.shorts.length}. Проверь результат на выбранных площадках.`);
      const signature = JSON.stringify(job.shorts);
      if (signature !== lastClipsSignature) {
        renderClips(job.shorts);
        lastClipsSignature = signature;
      }
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
    showStatus('В РАБОТЕ', 'Обрабатываем видео. Это может занять несколько минут — страницу можно оставить открытой.');
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

const existingJob = localStorage.getItem('shortform-active-job');
const lastJob = localStorage.getItem('shortform-last-job');
if (existingJob) startButton.disabled = true;
if (existingJob || lastJob) pollJob(existingJob || lastJob);
