const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const baseName = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || p;

let vols = null;
let selFolder = null;   // 当前选中的图纸库文件夹（scan_root），null = 文件夹列表视图

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

function openBtn(path, label, select) {
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = (ev) => { ev.stopPropagation(); fetch("/api/open", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, select: !!select })
  }); };
  return b;
}

function bindActions() {
  document.querySelectorAll(".actions").forEach(el => {
    const p = el.dataset.path;
    if (el.dataset.folder) el.append(openBtn(p, "打开文件夹", false));
    else {
      el.append(openBtn(p, "打开所在文件夹", true));
      el.append(openBtn(p, "打开文件", false));
    }
  });
}

function verMeta(v, extra = []) {
  const parts = [];
  if (v.date_tag) parts.push(`📅 ${esc(v.date_tag)}`);
  if (v.rev_tag) parts.push(`<span class="badge rev">修订: ${esc(v.rev_tag)}</span>`);
  if (v.code) parts.push(`<span class="badge">${esc(v.code)}</span>`);
  extra.forEach(e => parts.push(e));
  return parts.join(" ");
}

/* ---------- 视图一：导入的图纸库文件夹 ---------- */

function folderList() {
  const byRoot = {};
  for (const v of vols) {
    const key = v.scan_root || "";
    (byRoot[key] = byRoot[key] || []).push(v);
  }
  const folders = Object.entries(byRoot).map(([root, list]) => ({
    root, name: root ? baseName(root) : "未分组",
    entries: list.reduce((s, v) => s + v.entry_count, 0),
    files: list.reduce((s, v) => s + v.file_count, 0),
    list,
  })).sort((a, b) => (a.root > b.root ? 1 : -1));
  return `<div class="section-title">共导入 ${folders.length} 个图纸库文件夹，点击进入查看该库的册</div>` +
    folders.map(f => `
    <div class="card volcard" data-key="${esc(f.root)}" style="cursor:pointer">
      <h3>🗂 ${esc(f.name)} <span class="badge">${f.list.length} 册</span></h3>
      <div class="meta">图纸条目 ${f.entries} 条 · 文件 ${f.files} 个</div>
      <div class="path">📁 ${esc(f.root || "（来源未记录的册，多为旧版索引遗留）")}</div>
      <div class="meta">点击查看该库的册 →</div>
    </div>`).join("");
}

/* ---------- 视图二：该文件夹下的册 ---------- */

function volumeList() {
  const list = vols.filter(v => (v.scan_root || "") === selFolder);
  return `
  <div class="section-title"><a href="#" id="backLink">← 返回文件夹列表</a></div>
  <div class="card">
    <h3>🗂 ${esc(baseName(selFolder) || "未分组")}</h3>
    <div class="meta">${list.length} 册 · 图纸条目 ${list.reduce((s, v) => s + v.entry_count, 0)} 条</div>
    <div class="path">📁 ${esc(selFolder || "")}</div>
    <div class="fileline"><span class="actions" data-path="${esc(selFolder)}" data-folder="1"></span></div>
  </div>
  <div class="section-title">该库已入库的册</div>` +
  list.map(v => `
    <div class="card">
      <h3>${esc(v.title || v.folder_name)} ${v.code ? `<span class="badge">${esc(v.code)}</span>` : ""}</h3>
      <div>${verMeta(v, [`${v.entry_count} 条目录 / ${v.file_count} 个文件`,
        v.parse_status !== "ok" ? `<span class="badge rev">${esc(v.parse_status)}</span>` : ""])}</div>
      <div class="path">📁 ${esc(v.folder_path)}</div>
      ${v.ml_file ? `<div class="fileline"><span class="fname">📑 目录文件: ${esc(v.ml_file)}</span><span class="actions" data-path="${esc(v.ml_path || (v.folder_path + "\\" + v.ml_file))}"></span></div>` : ""}
      <div class="fileline"><span class="actions" data-path="${esc(v.folder_path)}" data-folder="1"></span></div>
    </div>`).join("");
}

/* ---------- 渲染与事件 ---------- */

function render() {
  const box = document.getElementById("results");
  if (!vols.length) {
    box.innerHTML = `<div class="empty">索引为空，请先在主页扫描入库。</div>`;
    return;
  }
  box.innerHTML = selFolder ? volumeList() : folderList();
  bindActions();
  document.querySelectorAll(".volcard").forEach(el => {
    el.onclick = () => { selFolder = el.dataset.key; render(); window.scrollTo(0, 0); };
  });
  const back = document.getElementById("backLink");
  if (back) back.onclick = (e) => { e.preventDefault(); selFolder = null; render(); };
}

api("/api/volumes")
  .then(d => { vols = d; render(); })
  .catch(e => { document.getElementById("results").innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`; });
