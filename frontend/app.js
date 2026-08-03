const form = document.getElementById("download-form");
const urlInput = document.getElementById("url-input");
const qualitySelect = document.getElementById("quality-select");
const formError = document.getElementById("form-error");
const jobsList = document.getElementById("jobs-list");
const settingsBtn = document.getElementById("settings-btn");

// When this frontend is deployed on its own (e.g. Vercel) it needs to know
// where the backend API lives. Empty string = same origin (default when the
// backend serves this frontend itself, as in local dev).
function getApiBase() {
  return localStorage.getItem("apiBase") || "";
}

function apiUrl(path) {
  return `${getApiBase()}${path}`;
}

settingsBtn.addEventListener("click", () => {
  const current = getApiBase();
  const next = window.prompt(
    "URL del backend (déjalo vacío si el frontend y el backend están en el mismo dominio):",
    current
  );
  if (next === null) return;
  localStorage.setItem("apiBase", next.trim().replace(/\/$/, ""));
});

const jobCards = new Map(); // job_id -> { el, timer }

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.classList.add("hidden");

  const url = urlInput.value.trim();
  const quality = qualitySelect.value;

  try {
    let res;
    try {
      res = await fetch(apiUrl("/api/jobs"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, quality }),
      });
    } catch {
      throw new Error(
        "No se pudo conectar con el backend. Revisa la URL configurada en ⚙️ Backend."
      );
    }
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(
        "El backend no respondió como se esperaba (¿URL correcta en ⚙️ Backend?)."
      );
    }
    if (!res.ok) {
      throw new Error(data.detail?.[0]?.msg || data.detail || "Error al crear la descarga");
    }
    urlInput.value = "";
    startTracking(data.job_id);
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove("hidden");
  }
});

function startTracking(jobId) {
  const card = createJobCard(jobId);
  jobsList.prepend(card.el);
  poll(jobId, card);
}

function createJobCard(jobId) {
  const el = document.createElement("div");
  el.className = "job-card";
  el.innerHTML = `
    <div class="job-header">
      <div class="job-title">Cargando…</div>
      <div class="job-status">extrayendo información…</div>
    </div>
    <div class="progress-bar"><div style="width:0%"></div></div>
    <div class="playlist-summary hidden">
      <span class="playlist-counts"></span>
      <button type="button" class="playlist-toggle">Ver pistas ▾</button>
    </div>
    <div class="items"></div>
  `;

  const card = {
    el,
    rows: new Map(),
    itemCount: 0,
    expanded: false,
    zipAutoTriggered: false,
  };

  const toggleBtn = el.querySelector(".playlist-toggle");
  const itemsEl = el.querySelector(".items");
  toggleBtn.addEventListener("click", () => {
    card.expanded = !card.expanded;
    itemsEl.classList.toggle("expanded", card.expanded);
    toggleBtn.textContent = card.expanded ? "Ocultar pistas ▴" : `Ver ${card.itemCount} pistas ▾`;
  });

  return card;
}

// Listas de cientos de canciones no deben machacar al navegador con
// sondeos constantes: cuanto más grande la lista, más se espacian.
function pollDelay(itemCount) {
  if (itemCount > 200) return 4000;
  if (itemCount > 50) return 2000;
  return 1200;
}

function triggerDownload(url) {
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function poll(jobId, card) {
  try {
    const res = await fetch(apiUrl(`/api/jobs/${jobId}`));
    if (!res.ok) return;
    const job = await res.json();
    render(card, job);
    card.itemCount = job.items.length;

    const finished = job.status === "completed" || job.status === "completed_with_errors";
    if (finished && job.is_playlist && !card.zipAutoTriggered) {
      card.zipAutoTriggered = true;
      triggerDownload(apiUrl(`/api/jobs/${job.id}/zip`));
    }
    if (finished || job.status === "error") {
      return;
    }
  } catch (err) {
    // network hiccup, keep polling
  }
  setTimeout(() => poll(jobId, card), pollDelay(card.itemCount));
}

function buildItemRow() {
  const el = document.createElement("div");
  el.className = "item-row";

  const titleWrap = document.createElement("div");
  titleWrap.className = "item-title";
  const titleText = document.createElement("span");
  const br = document.createElement("br");
  br.style.display = "none";
  const meta = document.createElement("span");
  meta.className = "item-meta";
  meta.style.display = "none";
  titleWrap.append(titleText, br, meta);
  el.appendChild(titleWrap);

  const progressWrap = document.createElement("div");
  progressWrap.className = "item-progress progress-bar";
  const bar = document.createElement("div");
  progressWrap.appendChild(bar);
  el.appendChild(progressWrap);

  const action = document.createElement("a");
  action.className = "item-link";
  el.appendChild(action);

  return { el, titleText, br, meta, bar, action, sig: null };
}

function updateItemRow(row, item) {
  row.titleText.textContent = item.title;

  const parts = [];
  if (item.bpm) parts.push(`${item.bpm} BPM`);
  if (item.camelot) parts.push(item.camelot);
  if (parts.length) {
    row.meta.textContent = parts.join(" · ");
    row.meta.style.display = "";
    row.br.style.display = "";
  } else {
    row.meta.style.display = "none";
    row.br.style.display = "none";
  }

  row.bar.style.width = `${item.progress}%`;

  if (item.status === "completed" && item.download_url) {
    row.action.href = apiUrl(item.download_url);
    row.action.style.color = "";
    row.action.textContent = "⬇ mp3";
    row.action.removeAttribute("title");
  } else if (item.status === "error") {
    row.action.removeAttribute("href");
    row.action.style.color = "var(--error)";
    row.action.textContent = "error";
    row.action.title = item.error || "Error desconocido";
  } else {
    row.action.removeAttribute("href");
    row.action.style.color = "";
    row.action.textContent = item.status;
    row.action.removeAttribute("title");
  }
}

function render(card, job) {
  const title = card.el.querySelector(".job-title");
  const status = card.el.querySelector(".job-status");
  const bar = card.el.querySelector(".progress-bar > div");
  const itemsEl = card.el.querySelector(".items");
  const summary = card.el.querySelector(".playlist-summary");
  const counts = card.el.querySelector(".playlist-counts");
  const toggleBtn = card.el.querySelector(".playlist-toggle");

  title.textContent = job.title || job.url;
  bar.style.width = `${job.progress}%`;

  status.className = "job-status";
  const statusLabels = {
    pending: "en cola…",
    extracting: "leyendo enlace…",
    downloading: `descargando… ${job.progress}%`,
    completed: "completado ✅",
    completed_with_errors: "completado con errores ⚠️",
    error: `error: ${job.error || "desconocido"}`,
  };
  status.textContent = statusLabels[job.status] || job.status;
  if (job.status === "completed") status.classList.add("completed");
  if (job.status === "error") status.classList.add("error");

  // Solo se tocan las filas cuyo estado cambió desde el último sondeo, en
  // vez de tirar y reconstruir el DOM entero (crítico con listas de
  // cientos de pistas sondeadas cada pocos segundos).
  for (const item of job.items) {
    const sig = `${item.status}|${item.progress}|${item.bpm}|${item.camelot}|${item.download_url}`;
    let row = card.rows.get(item.id);
    if (!row) {
      row = buildItemRow();
      card.rows.set(item.id, row);
      itemsEl.appendChild(row.el);
    }
    if (row.sig === sig) continue;
    row.sig = sig;
    updateItemRow(row, item);
  }

  // Con una sola pista se ve todo directamente; con una playlist se
  // colapsa detrás de un resumen para no llenar la página de líneas.
  if (job.is_playlist) {
    summary.classList.remove("hidden");
    itemsEl.classList.add("collapsible");
    itemsEl.classList.toggle("expanded", card.expanded);
    toggleBtn.textContent = card.expanded ? "Ocultar pistas ▴" : `Ver ${job.items.length} pistas ▾`;

    const completedCount = job.items.filter((i) => i.status === "completed").length;
    const erroredCount = job.items.filter((i) => i.status === "error").length;
    counts.innerHTML = "";
    counts.append(`🎵 ${completedCount}/${job.items.length} completadas`);
    if (erroredCount) {
      const err = document.createElement("span");
      err.style.color = "var(--error)";
      err.textContent = ` · ${erroredCount} con error`;
      counts.appendChild(err);
    }
  } else {
    summary.classList.add("hidden");
    itemsEl.classList.remove("collapsible", "expanded");
  }

  const existingZip = card.el.querySelector(".zip-link");
  if (job.is_playlist && (job.status === "completed" || job.status === "completed_with_errors")) {
    if (!existingZip) {
      const zip = document.createElement("a");
      zip.className = "zip-link";
      zip.href = apiUrl(`/api/jobs/${job.id}/zip`);
      zip.textContent = "⬇ Descargar todo (ZIP)";
      card.el.appendChild(zip);
    }
  } else if (existingZip) {
    existingZip.remove();
  }
}
