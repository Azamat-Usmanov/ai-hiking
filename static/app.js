const form = document.querySelector('#planner-form');
const query = document.querySelector('#query');
const dateInput = document.querySelector('#trip-date');
const statusBox = document.querySelector('#status');
const results = document.querySelector('#results');
const submit = document.querySelector('#submit');

dateInput.value = new Date().toLocaleDateString('en-CA', {timeZone: 'Europe/Paris'});
dateInput.min = dateInput.value;

document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  query.value = button.dataset.query;
  query.focus();
}));

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function weatherText(w) {
  if (!w || w.status === 'outside_forecast') return 'Прогноз пока недоступен для этой даты';
  if (w.status !== 'ok') return 'Прогноз недоступен — проверьте погоду перед выходом';
  const parts = [`${Math.round(w.temperature_min_c)}…${Math.round(w.temperature_max_c)} °C`];
  if (w.precipitation_probability_percent !== null) parts.push(`осадки ${Math.round(w.precipitation_probability_percent)}%`);
  if (w.wind_max_kmh !== null) parts.push(`ветер до ${Math.round(w.wind_max_kmh)} км/ч`);
  return parts.join(' · ');
}

function makeCard(route) {
  const card = el('article', 'route-card');
  const visual = el('div', 'route-visual');
  visual.append(el('small', '', 'ИЛЛЮСТРАЦИЯ АЛЬП · НЕ ФОТО МАРШРУТА'));
  const content = el('div', 'route-content');
  content.append(el('h4', '', route.name));
  const meta = el('div', 'route-meta');
  [
    `${Math.floor(route.duration_minutes / 60)} ч ${String(route.duration_minutes % 60).padStart(2,'0')} мин`,
    `${route.distance_km} км`, `↑ ${route.ascent_m} м`,
    ({easy:'Легкий', moderate:'Умеренный', hard:'Сложный'})[route.difficulty]
  ].forEach(text => meta.append(el('span', '', text)));
  content.append(meta, el('p', '', route.reason));
  if (route.tradeoff || route.mismatches.length) content.append(el('p', 'tradeoff', route.tradeoff || `Отличие от запроса: ${route.mismatches.join(', ')}.`));
  content.append(el('div', 'weather', `Прогноз у старта: ${weatherText(route.weather)}`));
  const links = el('div', 'route-links');
  const source = el('a', '', 'Описание маршрута ↗');
  source.href = route.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
  const map = el('a', '', 'Точка старта ↗');
  map.href = `https://www.openstreetmap.org/?mlat=${route.lat}&mlon=${route.lon}#map=13/${route.lat}/${route.lon}`;
  map.target = '_blank'; map.rel = 'noopener noreferrer';
  links.append(source, map); content.append(links); card.append(visual, content);
  return card;
}

function render(data) {
  results.replaceChildren(); results.hidden = false;
  const head = el('div', 'results-head');
  const left = el('div');
  left.append(el('span', 'kicker', data.exact_match === false ? 'БЛИЖАЙШИЕ ВАРИАНТЫ' : 'ПОДОБРАННЫЕ МАРШРУТЫ'), el('h3', '', data.routes?.length ? 'Ваши варианты' : 'Пока нет маршрутов'));
  head.append(left, el('p', '', data.message)); results.append(head);
  if (data.routes?.length) {
    const grid = el('div', 'result-grid');
    data.routes.forEach(route => grid.append(makeCard(route)));
    results.append(grid);
  }
  if (data.trace?.length) {
    const details = el('details', 'trace');
    details.append(el('summary', '', 'Показать путь запроса: LLM → MCP → LLM'));
    details.append(el('pre', '', JSON.stringify(data.trace, null, 2)));
    results.append(details);
  }
  results.scrollIntoView({behavior:'smooth',block:'start'});
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  submit.disabled = true;
  statusBox.className = 'status loading';
  statusBox.textContent = 'Модель разбирает запрос, затем проверяет маршруты и погоду. На сервере без GPU это может занять до нескольких минут…';
  results.hidden = true;
  try {
    const response = await fetch('/api/plan', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:query.value,date:dateInput.value || null})});
    if (!response.ok) throw new Error('Сервис не смог завершить запрос. Попробуйте ещё раз.');
    render(await response.json());
    statusBox.textContent = '';
  } catch (error) {
    statusBox.textContent = error.message || 'Ошибка подключения к сервису.';
  } finally {
    submit.disabled = false;
    statusBox.className = 'status';
  }
});
