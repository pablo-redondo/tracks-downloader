const form = document.getElementById("download-form");
const urlInput = document.getElementById("url-input");
const qualitySelect = document.getElementById("quality-select");
const formError = document.getElementById("form-error");
const jobsList = document.getElementById("jobs-list");

const jobCards = new Map(); // job_id -> { el, timer }

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.classList.add("hidden");

  const url = urlInput.value.trim();
  const quality = qualitySelect.value;

  try {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, quality }),
    });
    const data = await res.json();
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
    const res = await fetch(`/api/jobs/${jobId}`);
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
    row.appendChild(t);

    const p = document.createElement("div");
    p.className = "item-progress progress-bar";
    p.innerHTML = `<div style="width:${item.progress}%"></div>`;
    row.appendChild(p);

    if (item.status === "completed" && item.download_url) {
      const a = document.createElement("a");
      a.href = item.download_url;
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
    zip.href = `/api/jobs/${job.id}/zip`;
    zip.textContent = "⬇ Descargar todo (ZIP)";
    card.el.appendChild(zip);
  }
}
