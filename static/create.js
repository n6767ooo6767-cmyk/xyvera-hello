const optionsBox = document.getElementById('options');
const mode = document.getElementById('mode');
const durationBox = document.getElementById('durationBox');
const form = document.getElementById('createForm');

function addOption(value = '') {
  const row = document.createElement('label');
  row.className = 'option-input';
  row.innerHTML = `<span>Вариант</span><input maxlength="100" required value="${value.replace(/"/g, '&quot;')}">`;
  optionsBox.appendChild(row);
}

addOption();
addOption();

mode.addEventListener('change', () => {
  durationBox.classList.toggle('hidden', mode.value !== 'timed');
});

const add = document.createElement('button');
add.type = 'button';
add.className = 'button';
add.textContent = '+ Добавить вариант';
add.onclick = () => {
  if (optionsBox.children.length < 10) addOption();
};
optionsBox.after(add);

form.addEventListener('submit', async event => {
  event.preventDefault();
  const error = document.getElementById('error');
  error.textContent = '';
  const options = [...optionsBox.querySelectorAll('input')].map(x => x.value.trim()).filter(Boolean);
  const body = {
    title: document.getElementById('title').value.trim(),
    mode: mode.value,
    duration: Number(document.getElementById('duration').value || 0),
    options
  };
  try {
    const response = await fetch('/api/polls', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось создать опрос');
    const result = document.getElementById('result');
    result.classList.remove('hidden');
    result.innerHTML = `<h2>Готово 🎉</h2><p>Ссылка зрителям: <a href="${data.url}">${location.origin}${data.url}</a></p><p>OBS: <a href="${data.overlay}">${location.origin}${data.overlay}</a></p><p>Управление: <a href="${data.control}">${location.origin}${data.control}</a></p>`;
    form.reset();
  } catch (e) {
    error.textContent = e.message;
  }
});
