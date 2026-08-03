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
    <div class="items"></div>
  `;
  return { el };
}

async function poll(jobId, card) {
  try {
    const res = await fetch(apiUrl(`/api/jobs/${jobId}`));
    if (!res.ok) return;
    const job = await res.json();
    render(card, job);

    if (job.status === "completed" || job.status === "completed_with_errors" || job.status === "error") {
      return;
    }
  } catch (err) {
    // network hiccup, keep polling
  }
  setTimeout(() => poll(jobId, card), 1200);
}

function render(card, job) {
  const title = card.el.querySelector(".job-title");
  const status = card.el.querySelector(".job-status");
  const bar = card.el.querySelector(".progress-bar > div");
  const itemsEl = card.el.querySelector(".items");

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

  itemsEl.innerHTML = "";
  for (const item of job.items) {
    const row = document.createElement("div");
    row.className = "item-row";

    const t = document.createElement("div");
    t.className = "item-title";
    t.textContent = item.title;
    if (item.bpm || item.camelot) {
      const meta = document.createElement("span");
      meta.className = "item-meta";
      const parts = [];
      if (item.bpm) parts.push(`${item.bpm} BPM`);
      if (item.camelot) parts.push(item.camelot);
      meta.textContent = parts.join(" · ");
      t.appendChild(document.createElement("br"));
      t.appendChild(meta);
    }
    row.appendChild(t);

    const p = document.createElement("div");
    p.className = "item-progress progress-bar";
    p.innerHTML = `<div style="width:${item.progress}%"></div>`;
    row.appendChild(p);

    if (item.status === "completed" && item.download_url) {
      const a = document.createElement("a");
      a.href = apiUrl(item.download_url);
      a.className = "item-link";
      a.textContent = "⬇ mp3";
      row.appendChild(a);
    } else if (item.status === "error") {
      const s = document.createElement("span");
      s.className = "item-link";
      s.style.color = "var(--error)";
      s.textContent = "error";
      row.appendChild(s);
    } else {
      const s = document.createElement("span");
      s.className = "item-link";
      s.textContent = item.status;
      row.appendChild(s);
    }

    itemsEl.appendChild(row);
  }

  const existingZip = card.el.querySelector(".zip-link");
  if (existingZip) existingZip.remove();
  if (job.is_playlist && (job.status === "completed" || job.status === "completed_with_errors")) {
    const zip = document.createElement("a");
    zip.className = "zip-link";
    zip.href = apiUrl(`/api/jobs/${job.id}/zip`);
    zip.textContent = "⬇ Descargar todo (ZIP)";
    card.el.appendChild(zip);
  }
}
