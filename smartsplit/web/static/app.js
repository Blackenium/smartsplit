"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// --------------------------------------------------------------------------- //
//  Tabs
// --------------------------------------------------------------------------- //
$$("#tabs button").forEach(btn => btn.addEventListener("click", () => {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b === btn));
  $$(".tab").forEach(t => t.hidden = t.id !== `tab-${btn.dataset.tab}`);
  if (btn.dataset.tab === "split") loadVideos();
  if (btn.dataset.tab === "clips") loadClips();
}));

// --------------------------------------------------------------------------- //
//  Editor options (shared by Split and Download --process)
// --------------------------------------------------------------------------- //
const SELECT = (field, opts) =>
  `<select data-field="${field}">${opts.map(o =>
    `<option value="${o[0]}">${o[1]}</option>`).join("")}</select>`;

function buildEditorOpts(fieldset) {
  fieldset.insertAdjacentHTML("beforeend", `
    <div class="row">
      <label>Plateforme ${SELECT("platform", [["both", "Les deux"], ["tiktok", "TikTok"], ["youtube", "YouTube"]])}</label>
      <label>Modèle ${SELECT("model", [["tiny", "tiny"], ["base", "base"], ["small", "small"], ["medium", "medium"], ["large-v3", "large-v3"]])}</label>
      <label>Recadrage ${SELECT("reframe", [["track", "track (visage)"], ["center", "center"], ["none", "aucun"]])}</label>
    </div>
    <div class="row">
      <label>Durée TikTok (s)<input data-field="tiktok_duration" type="number" min="1" placeholder="90"></label>
      <label>Durée YouTube (s)<input data-field="youtube_duration" type="number" min="1" placeholder="59"></label>
      <label>Langue<input data-field="language" value="fr"></label>
    </div>
    <div class="row">
      <label>Limite (test)<input data-field="limit" type="number" min="1" placeholder="—"></label>
      <label>Début (s)<input data-field="start" type="number" min="0" placeholder="0"></label>
      <label class="check" style="margin-top:22px"><input data-field="keep_clips" type="checkbox"> Garder les clips bruts</label>
    </div>`);
  // base/model default
  $('[data-field="model"]', fieldset).value = "base";
}

function readEditorOpts(fieldset) {
  const f = name => $(`[data-field="${name}"]`, fieldset);
  const num = el => el.value === "" ? null : Number(el.value);
  return {
    platform: f("platform").value,
    model: f("model").value,
    language: f("language").value || "fr",
    reframe: f("reframe").value,
    tiktok_duration: num(f("tiktok_duration")),
    youtube_duration: num(f("youtube_duration")),
    limit: num(f("limit")),
    start: num(f("start")) || 0,
    keep_clips: f("keep_clips").checked,
  };
}

buildEditorOpts($("#sp-opts"));
buildEditorOpts($("#dl-opts"));

// --------------------------------------------------------------------------- //
//  Download form
// --------------------------------------------------------------------------- //
function syncDownloadForm() {
  const yt = $("#dl-source").value === "youtube";
  $("#dl-match-wrap").hidden = !yt;
  $("#dl-kind-wrap").hidden = yt;
  $("#dl-opts").hidden = !$("#dl-process").checked;
}
$("#dl-source").addEventListener("change", syncDownloadForm);
$("#dl-process").addEventListener("change", syncDownloadForm);
syncDownloadForm();

$("#dl-go").addEventListener("click", async () => {
  const channel = $("#dl-channel").value.trim();
  if (!channel) return alert("Indique une chaîne, une URL ou un nom.");
  const body = {
    source: $("#dl-source").value,
    channel,
    latest: $("#dl-latest").value ? Number($("#dl-latest").value) : null,
    match: $("#dl-match").value.trim() || null,
    kind: $("#dl-kind").value,
    dest: $("#dl-dest").value.trim() || null,
    process: $("#dl-process").checked,
    ...readEditorOpts($("#dl-opts")),
  };
  await startJob("/api/download", body);
});

// --------------------------------------------------------------------------- //
//  Split form
// --------------------------------------------------------------------------- //
async function loadVideos() {
  const sel = $("#sp-video");
  const vids = await (await fetch("/api/videos")).json();
  sel.innerHTML = vids.length
    ? vids.map(v => `<option value="${v.path}">${v.name}</option>`).join("")
    : `<option value="" disabled>aucune vidéo dans input_videos/</option>`;
}
$("#sp-refresh").addEventListener("click", loadVideos);

$("#sp-go").addEventListener("click", async () => {
  const video = $("#sp-video").value;
  if (!video) return alert("Aucune vidéo sélectionnée.");
  await startJob("/api/split", { video, ...readEditorOpts($("#sp-opts")) });
});

// --------------------------------------------------------------------------- //
//  Clips gallery
// --------------------------------------------------------------------------- //
async function loadClips() {
  const groups = await (await fetch("/api/clips")).json();
  const el = $("#clips");
  if (!groups.length) { el.innerHTML = `<p class="empty">Aucun clip pour le moment.</p>`; return; }
  el.innerHTML = groups.map(g => `
    <div class="clip-group">
      <h3>${g.name}</h3>
      <div class="clip-grid">${g.clips.map(c => `
        <div class="clip">
          <video controls preload="metadata" src="${c.url}"></video>
          <div class="cn"><span class="badge">${c.platform}</span> ${c.name}</div>
        </div>`).join("")}</div>
    </div>`).join("");
}
$("#cl-refresh").addEventListener("click", loadClips);

// --------------------------------------------------------------------------- //
//  Jobs + live log
// --------------------------------------------------------------------------- //
async function startJob(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { alert("Erreur: " + (await res.text())); return; }
  const { id } = await res.json();
  await refreshJobs();
  followJob(id);
}

const STATUS_TXT = { running: "en cours", succeeded: "terminé", failed: "échec", cancelled: "annulé" };

async function refreshJobs() {
  const jobs = await (await fetch("/api/jobs")).json();
  $("#jobs").innerHTML = jobs.length ? jobs.map(j => `
    <li data-id="${j.id}">
      <div class="jt">${j.title}</div>
      <div class="jm"><span class="dot ${j.status}"></span>
        <span class="status-txt">${STATUS_TXT[j.status] || j.status}</span></div>
    </li>`).join("") : `<p class="empty">Aucune tâche.</p>`;
  $$("#jobs li").forEach(li => li.addEventListener("click", () => followJob(li.dataset.id)));
}

let logSource = null;
let followedId = null;
let logState = { lines: [], transient: "" };

function renderLog() {
  const pre = $("#log");
  pre.textContent = logState.lines.join("\n") + (logState.transient ? "\n" + logState.transient : "");
  pre.scrollTop = pre.scrollHeight;
}

async function followJob(id) {
  if (logSource) logSource.close();
  followedId = id;
  logState = { lines: [], transient: "" };
  const job = await (await fetch(`/api/jobs/${id}`)).json();
  $("#log-title").textContent = job.title;
  $("#log-drawer").hidden = false;
  renderLog();

  logSource = new EventSource(`/api/jobs/${id}/events`);
  logSource.onmessage = e => {
    const ev = JSON.parse(e.data);
    if (ev.type === "log") {
      if (ev.transient) logState.transient = ev.text;
      else { logState.lines.push(ev.text); logState.transient = ""; }
      renderLog();
    } else if (ev.type === "status") {
      refreshJobs();
      if (["clips", "split"].includes(activeTab())) { loadClips(); loadVideos(); }
    } else if (ev.type === "end") {
      logSource.close();
    }
  };
  logSource.onerror = () => { if (logSource) logSource.close(); };
}

function activeTab() { return $("#tabs button.active").dataset.tab; }

$("#log-close").addEventListener("click", () => {
  if (logSource) logSource.close();
  $("#log-drawer").hidden = true;
});
$("#log-cancel").addEventListener("click", async () => {
  if (followedId) await fetch(`/api/jobs/${followedId}/cancel`, { method: "POST" });
});

// Initial load + periodic refresh
refreshJobs();
loadVideos();
setInterval(refreshJobs, 2500);
