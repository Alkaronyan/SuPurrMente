// Dashboard de SuPurrMente — gráficas de peso/visitas por gato + uso de la caja.
// Cargado como script clásico desde dashboard.html (al final del <body>), así que las
// funciones quedan globales y los onclick/onchange inline del HTML las encuentran.
// Los datos vienen de canned queries de Datasette (la instancia pública no permite SQL).

const COLORS = { pirata: '#e74c3c', robin: '#3498db' };
const charts = {};

// Active view: start/end are Date objects, or both null for "toda la historia".
const state = { mode: '90', start: null, end: null };

// ── Date helpers (local midnight, no timezone drift) ───────────────────────
function isoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function parseISO(s) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d);
}
function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}
function daysBetween(a, b) {
  return Math.round((b - a) / 86400000);
}

// ── Controls ───────────────────────────────────────────────────────────────
function onModeChange() {
  const v = document.getElementById('days').value;
  state.mode = v;
  const custom = document.getElementById('custom-fields');
  const arrows = document.getElementById('nav-arrows');

  if (v === 'all') {
    state.start = null;
    state.end = null;
    custom.hidden = true;
    arrows.hidden = true;          // no paging over "all history"
  } else if (v === 'custom') {
    custom.hidden = false;
    arrows.hidden = false;
    const si = document.getElementById('start-date');
    const ei = document.getElementById('end-date');
    if (!si.value || !ei.value) {  // seed sensible defaults on first switch
      const end = new Date();
      const start = addDays(end, -30);
      si.value = isoDate(start);
      ei.value = isoDate(end);
    }
    state.start = parseISO(si.value);
    state.end = parseISO(ei.value);
  } else {
    custom.hidden = true;
    arrows.hidden = false;
    const n = Number(v);
    const end = new Date();
    state.end = end;
    state.start = addDays(end, -n);
  }
  render();
}

function onCustomDateChange() {
  const si = document.getElementById('start-date').value;
  const ei = document.getElementById('end-date').value;
  if (!si || !ei) return;
  let s = parseISO(si);
  let e = parseISO(ei);
  if (s > e) [s, e] = [e, s];      // tolerate reversed input
  state.start = s;
  state.end = e;
  render();
}

// Move the window backward (-1) or forward (+1), keeping its width.
function shiftRange(dir) {
  if (!state.start || !state.end) return;
  const width = daysBetween(state.start, state.end) || 1;
  state.start = addDays(state.start, dir * width);
  state.end = addDays(state.end, dir * width);
  if (state.mode === 'custom') {
    document.getElementById('start-date').value = isoDate(state.start);
    document.getElementById('end-date').value = isoDate(state.end);
  }
  render();
}

function updateRangeLabel() {
  const el = document.getElementById('range-label');
  el.textContent = (!state.start || !state.end)
    ? 'Toda la historia'
    : `${isoDate(state.start)} → ${isoDate(state.end)}`;
}

// ── Gap detection ─────────────────────────────────────────────────────────
// Inserts a null sentinel in gaps >= gapDays so Chart.js breaks the line.
function insertGapNulls(data, gapDays = 4) {
  if (data.length < 2) return data;
  const result = [data[0]];
  for (let i = 1; i < data.length; i++) {
    const prev = parseISO(data[i - 1].dia);
    const curr = parseISO(data[i].dia);
    const gap = daysBetween(prev, curr);
    if (gap >= gapDays) {
      const mid = addDays(prev, Math.floor(gap / 2));
      result.push({ dia: isoDate(mid), peso: null, visitas: null });
    }
    result.push(data[i]);
  }
  return result;
}

// ── Data + charts ────────────────────────────────────────────────────────
// Los datos vienen de canned queries de Datasette, NO de SQL arbitrario: la
// instancia pública tiene el SQL libre desactivado. start/end van vacíos para
// "toda la historia" (la query los trata como sin filtro).
async function cannedQuery(name, params = {}) {
  const qs = new URLSearchParams({ ...params, _shape: 'array' });
  const resp = await fetch(`/weights/${name}.json?${qs}`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function fetchData(cat, start, end) {
  return cannedQuery('cat_daily', {
    cat,
    start: start ? isoDate(start) : '',
    end: end ? isoDate(end) : '',
  });
}

function formatStats(data) {
  if (!data.length) return 'Sin datos';
  const weights = data.map(r => r.peso);
  const last = weights[weights.length - 1];
  const min = Math.min(...weights).toFixed(2);
  const max = Math.max(...weights).toFixed(2);
  const avg = (weights.reduce((a, b) => a + b, 0) / weights.length).toFixed(2);
  const totalVisits = data.reduce((a, r) => a + r.visitas, 0);
  const avgVisits = (totalVisits / data.length).toFixed(1);
  return `Último: ${last} kg &nbsp;|&nbsp; Min: ${min} &nbsp;|&nbsp; Máx: ${max} `
       + `&nbsp;|&nbsp; Media: ${avg} kg &nbsp;|&nbsp; Visitas: ${totalVisits} `
       + `(${avgVisits}/día)`;
}

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

async function buildChart(cat, start, end) {
  const card = document.getElementById(`card-${cat}`);
  const weightCanvas = document.getElementById(`chart-${cat}`);
  const freqCanvas = document.getElementById(`freq-${cat}`);
  const color = COLORS[cat];

  destroyChart(`${cat}-weight`);
  destroyChart(`${cat}-freq`);
  // Reset any previous empty-state and collapse state so reloads recover cleanly.
  card.querySelectorAll('.empty').forEach(e => e.remove());
  card.querySelectorAll('.chart-sub').forEach(h => h.classList.remove('collapsed'));
  weightCanvas.style.display = '';
  freqCanvas.style.display = '';

  let data;
  try {
    data = await fetchData(cat, start, end);
  } catch (e) {
    document.getElementById(`stats-${cat}`).innerHTML = 'Error al cargar datos';
    return;
  }

  document.getElementById(`stats-${cat}`).innerHTML = formatStats(data);

  if (!data.length) {
    weightCanvas.style.display = 'none';
    freqCanvas.style.display = 'none';
    card.insertAdjacentHTML('beforeend', '<p class="empty">Sin datos para este periodo</p>');
    return;
  }

  const expanded = insertGapNulls(data, 4);

  const timeScaleX = {
    type: 'time',
    time: { unit: 'day', displayFormats: { day: 'dd MMM', month: 'MMM yyyy' }, tooltipFormat: 'dd/MM/yyyy' },
    ticks: { maxTicksLimit: 8, font: { size: 11 } },
    ...(start && { min: isoDate(start) }),
    ...(end   && { max: isoDate(end)   }),
  };

  charts[`${cat}-weight`] = new Chart(weightCanvas, {
    type: 'line',
    data: {
      datasets: [{
        label: 'kg',
        data: expanded.map(r => ({ x: r.dia, y: r.peso })),
        borderColor: color,
        backgroundColor: color + '18',
        fill: true,
        tension: 0.35,
        spanGaps: false,
        pointRadius: data.length > 60 ? 0 : 3,
        pointHoverRadius: 5,
      }]
    },
    options: {
      responsive: true,
      aspectRatio: 3,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ctx.parsed.y === null ? 'Sin datos' : `${ctx.parsed.y} kg`
          }
        }
      },
      scales: {
        x: timeScaleX,
        y: {
          title: { display: true, text: 'kg', font: { size: 11 } },
          ticks: { font: { size: 11 } }
        }
      }
    }
  });

  charts[`${cat}-freq`] = new Chart(freqCanvas, {
    type: 'bar',
    data: {
      datasets: [{
        label: 'visitas',
        data: expanded.map(r => ({ x: r.dia, y: r.visitas })),
        backgroundColor: color + '99',
        borderColor: color,
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true,
      aspectRatio: 4,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.parsed.y} visita(s)` } }
      },
      scales: {
        x: { ...timeScaleX, offset: true },
        y: {
          beginAtZero: true,
          title: { display: true, text: 'visitas/día', font: { size: 11 } },
          ticks: { precision: 0, font: { size: 11 } }
        }
      }
    }
  });
}

function toggleChart(id, header) {
  const canvas = document.getElementById(id);
  const collapsed = canvas.style.display === 'none';
  canvas.style.display = collapsed ? '' : 'none';
  header.classList.toggle('collapsed', !collapsed);
}

// ── Box: total clean-cycle usage per day + current robot state ────────────
async function fetchBoxUsage(start, end) {
  return cannedQuery('box_daily', {
    start: start ? isoDate(start) : '',
    end: end ? isoDate(end) : '',
  });
}

function formatBoxStatus(rows, status) {
  const parts = [];
  if (rows.length) {
    const total = rows.reduce((a, r) => a + r.cycles, 0);
    const avg = (total / rows.length).toFixed(1);
    parts.push(`Ciclos: ${total} (${avg}/día)`);
  }
  if (status) {
    if (status.litter_level != null) parts.push(`Arena: ${Math.round(status.litter_level)}%`);
    if (status.waste_drawer_level != null) parts.push(`Cajón: ${Math.round(status.waste_drawer_level)}%`);
    if (status.is_online != null) parts.push(status.is_online ? 'En línea' : '⚠ Desconectado');
  }
  return parts.length ? parts.join(' &nbsp;|&nbsp; ') : 'Sin datos';
}

async function buildBoxChart(start, end) {
  const card = document.getElementById('card-caja');
  const canvas = document.getElementById('chart-caja');
  destroyChart('caja');
  card.querySelectorAll('.empty').forEach(e => e.remove());
  card.querySelectorAll('.chart-sub').forEach(h => h.classList.remove('collapsed'));
  canvas.style.display = '';

  let rows, status = null;
  try {
    rows = await fetchBoxUsage(start, end);
    const s = await cannedQuery('robot_status');
    status = s[0] || null;
  } catch (e) {
    document.getElementById('stats-caja').innerHTML = 'Error al cargar datos';
    return;
  }

  document.getElementById('stats-caja').innerHTML = formatBoxStatus(rows, status);

  if (!rows.length) {
    canvas.style.display = 'none';
    card.insertAdjacentHTML('beforeend', '<p class="empty">Sin datos de uso para este periodo</p>');
    return;
  }

  charts['caja'] = new Chart(canvas, {
    type: 'bar',
    data: {
      datasets: [{
        label: 'ciclos',
        data: rows.map(r => ({ x: r.day, y: r.cycles })),
        backgroundColor: '#7f8c8d99',
        borderColor: '#7f8c8d',
        borderWidth: 1,
      }]
    },
    options: {
      responsive: true,
      aspectRatio: 4,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.parsed.y} ciclo(s)` } }
      },
      scales: {
        x: {
          type: 'time',
          offset: true,
          time: { unit: 'day', displayFormats: { day: 'dd MMM', month: 'MMM yyyy' }, tooltipFormat: 'dd/MM/yyyy' },
          ticks: { maxTicksLimit: 8, font: { size: 11 } },
          ...(start && { min: isoDate(start) }),
          ...(end   && { max: isoDate(end)   }),
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: 'ciclos/día', font: { size: 11 } },
          ticks: { precision: 0, font: { size: 11 } }
        }
      }
    }
  });
}

async function render() {
  updateRangeLabel();
  await Promise.all([
    buildChart('pirata', state.start, state.end),
    buildChart('robin', state.start, state.end),
    buildBoxChart(state.start, state.end),
  ]);

  // En "toda la historia" no hay min/max explícito: cada chart auto-escala
  // a sus propios datos. Sincronizamos aquí leyendo el rango real de cada
  // eje ya renderizado y forzando el span global en todos.
  if (!state.start && !state.end) {
    const scales = ['pirata-weight', 'robin-weight', 'caja']
      .map(k => charts[k]?.scales?.x)
      .filter(Boolean);
    if (scales.length > 1) {
      const globalMin = Math.min(...scales.map(s => s.min));
      const globalMax = Math.max(...scales.map(s => s.max));
      Object.values(charts).forEach(c => {
        c.options.scales.x.min = globalMin;
        c.options.scales.x.max = globalMax;
        c.update('none');
      });
    }
  }
}

onModeChange();  // initialise from the default-selected option
