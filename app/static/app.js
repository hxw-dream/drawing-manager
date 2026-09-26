const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function openBtn(path, label, select) {
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = () => api("/api/open", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, select: !!select })
  });
  return b;
}

function verMeta(v, extra = []) {
  const parts = [];
  if (v.date_tag) parts.push(`📅 ${v.date_tag}`);
  if (v.rev_tag) parts.push(`<span class="badge rev">修订: ${esc(v.rev_tag)}</span>`);
  if (v.code) parts.push(`<span class="badge">${esc(v.code)}</span>`);
  extra.forEach(e => parts.push(e));
  return parts.join(" ");
}

function renderEntryGroups(groups) {
  if (!groups.length) return "";
  return `<div class="section-title">图纸条目（按图号分组，同图号多版本新在前）</div>` +
    groups.map(g => {
      const first = g.versions[0];
      const nVersions = g.versions.length > 1 ? `<span class="badge rev">${g.versions.length} 个版本</span>` : "";
      const vers = g.versions.map(v => {
        const files = v.files.map(f => `
          <div class="fileline">
            <span class="fname">📄 ${esc(f.filename)}</span>
            <span class="actions" data-path="${esc(f.path)}"></span>
          </div>`).join("") || `<div class="path">（该版本所在册内没有匹配到文件）</div>`;
        return `
        <div class="ver">
          <div>${verMeta(v, [esc(v.folder_name)])} ${v.rev ? `<span class="badge">REV ${esc(v.rev)}</span>` : ""}</div>
          <div class="path">📁 ${esc(v.folder_path)}</div>
          ${files}
        </div>`;
      }).join("");
      return `
      <div class="card">
        <h3>${esc(g.drawing_no)} ${nVersions}</h3>
        <div>${esc(first.title || "")}</div>
        ${vers}
      </div>`;
    }).join("");
}

function renderVolumes(vols) {
  if (!vols.length) return "";
  return `<div class="section-title">匹配的册</div>` + vols.map(v => `
    <div class="card">
      <h3>${esc(v.title || v.folder_name)} ${v.code ? `<span class="badge">${esc(v.code)}</span>` : ""}</h3>
      <div>${verMeta(v, [`${v.entry_count} 条目录`])}</div>
      <div class="path">📁 ${esc(v.folder_path)}</div>
      ${v.ml_file ? `<div class="fileline"><span class="fname">📑 目录文件: ${esc(v.ml_file)}</span><span class="actions" data-path="${esc(v.ml_path || (v.folder_path + '\\' + v.ml_file))}"></span></div>` : ""}
      <div class="fileline"><span class="actions" data-path="${esc(v.folder_path)}" data-openfolder="1"></span></div>
    </div>`).join("");
}

function renderLooseFiles(files) {
  if (!files.length) return "";
  return `<div class="section-title">未入目录的文件（按文件名命中）</div>` + files.map(f => `
    <div class="card">
      <h3>📄 ${esc(f.filename)}</h3>
      <div>${verMeta(f, [esc(f.folder_name)])}</div>
      <div class="path">📁 ${esc(f.path)}</div>
      <div class="fileline"><span class="actions" data-path="${esc(f.path)}"></span></div>
    </div>`).join("");
}

function bindActionButtons() {
  document.querySelectorAll(".actions").forEach(el => {
    const p = el.dataset.path;
    if (el.dataset.openfolder) el.append(openBtn(p, "打开文件夹", false));
    else {
      el.append(openBtn(p, "打开所在文件夹", true));
      el.append(openBtn(p, "打开文件", false));
    }
  });
}

async function doSearch() {
  const q = $("#q").value.trim();
  const box = $("#results");
  if (!q) { box.innerHTML = `<div class="empty">请输入关键字。</div>`; return; }
  box.innerHTML = `<div class="empty">搜索中…</div>`;
  try {
    const r = await api("/api/search?q=" + encodeURIComponent(q));
    const html = renderEntryGroups(r.entry_groups) + renderVolumes(r.volume_hits) + renderLooseFiles(r.loose_files);
    box.innerHTML = html || `<div class="empty">没有命中。试试别的关键字，或先扫描入库。</div>`;
    bindActionButtons();
  } catch (e) { box.innerHTML = `<div class="empty">搜索出错: ${esc(e.message)}</div>`; }
}

/* ---------- 扫描 ---------- */
let pollTimer = null;

const STATUS_LABEL = {
  empty: "目录未解析",
  failed: "解析失败",
  dwg_unsupported: "ML 非 PDF",
};

function renderScanIssues(report) {
  const box = $("#scanissues");
  const problems = (report?.volumes || [])
    .filter(v => v.status !== "ok")
    .map(v => ({
      name: (v.folder || "").split(/[\\/]/).pop(),
      tag: STATUS_LABEL[v.status] || v.status,
      reason: v.reason || "未记录原因",
    }));
  if (!problems.length) { box.style.display = "none"; box.innerHTML = ""; return; }
  box.style.display = "block";
  box.innerHTML = `<div class="card" style="border-color:#f59e0b">
    <h3>⚠ 扫描发现问题（${problems.length}）</h3>
    ${problems.map(p => `
      <div class="ver">
        <div><span class="badge rev">${esc(p.tag)}</span> <b>${esc(p.name)}</b></div>
        <div class="meta" style="margin-top:2px">原因：${esc(p.reason)}</div>
      </div>`).join("")}
  </div>`;
}

async function pollScan() {
  const st = await api("/api/scan/status");
  const el = $("#scanstatus");
  el.style.display = "block";
  el.textContent = st.log.join("\n") || (st.running ? "扫描启动中…" : "");
  el.scrollTop = el.scrollHeight;
  $("#scanBtn").disabled = st.running;
  if (!st.running) {
    clearInterval(pollTimer); pollTimer = null;
    if (st.error) el.textContent += `\n✗ ${st.error}`;
    else if (st.report) {
      const r = st.report;
      el.textContent += `\n✓ 完成：${r.ok} 册成功 / ${r.warn} 警告 / ${r.fail} 失败，${r.total_entries} 条目录条目` +
        (r.unmatched.length ? `\n⚠ 未匹配到目录条目的文件 ${r.unmatched.length} 个（仍可按文件名搜索）` : "");
      renderScanIssues(r);
    }
    return;
  }
  if (!pollTimer) pollTimer = setInterval(pollScan, 800);
}

async function startScan() {
  const root = $("#root").value.trim();
  if (!root) { alert("请填写图纸根目录路径"); return; }
  $("#scanissues").style.display = "none";
  try {
    await api("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" },
                             body: JSON.stringify({ root }) });
  } catch (e) {
    const msg = String(e.message || "");
    if (msg.includes("进行中")) {          // 已有扫描在跑：直接跟进进度，不算失败
      pollScan();
      pollTimer = setInterval(pollScan, 800);
      return;
    }
    if (/failed to fetch|networkerror|load failed/i.test(msg)) {
      alert("无法连接本地服务：请双击项目里的 run.bat 启动服务（保持窗口开着），再点扫描。");
      return;
    }
    alert("启动扫描失败: " + msg);
    return;
  }
  pollScan();
  pollTimer = setInterval(pollScan, 800);
}

$("#searchBtn").onclick = doSearch;
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
$("#scanBtn").onclick = startScan;

api("/api/scan/status").then(st => {
  if (st.last_root) { $("#root").value = st.last_root; $("#root").size = $("#root").value.length; }
  if (st.running || st.log.length) pollScan();
}).catch(() => {});
