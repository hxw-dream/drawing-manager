(function () {
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const baseName = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || p;

let vols = null;
let ignored = [];       // 已从索引移除的册
let folderNames = {};   // scan_root -> 自定义显示名
let projList = [];      // 全部项目
let selFolder = null;   // 当前选中的图纸库文件夹（scan_root），null = 文件夹列表视图

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function displayName(root) {
  return folderNames[root] || (root ? baseName(root) : "未分组");
}

async function loadAll() {
  const pid = dmCurrentProject();
  [vols, folderNames, projList, ignored] = await Promise.all([
    api("/api/volumes?project=" + pid), api("/api/folders"),
    api("/api/projects"), api("/api/volumes/ignored")]);
}

async function removeVolume(path, name) {
  if (!confirm(`确定把「${name}」从索引移除？
只移出索引，不删除磁盘文件；重扫不会自动恢复，可在此处恢复。`)) return;
  try {
    await api("/api/volumes/delete", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: path }) });
  } catch (e) { alert(String(e.message)); return; }
  await loadAll(); render();
}

async function removeFolder(root) {
  const name = displayName(root);
  if (!confirm(`确定把「${name}」下的全部册从索引移除？
只移出索引，不删除磁盘文件；重扫不会自动恢复，可在下方"已移除"区恢复。`)) return;
  try {
    const r = await api("/api/folders/delete", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root }) });
    await loadAll(); render();
  } catch (e) { alert(String(e.message)); }
}

async function restoreAll() {
  if (!confirm("恢复全部已移除的册？恢复后需重新扫描入库。")) return;
  for (const g of ignored) {
    await api("/api/volumes/restore", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: g.folder_path }) });
  }
  await loadAll(); render();
}

async function restoreVolume(path) {
  await api("/api/volumes/restore", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder_path: path }) });
  await loadAll(); render();
}

async function createProject() {
  const name = prompt("新项目名称：");
  if (!name || !name.trim()) return;
  await api("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ name: name.trim() }) });
  await dmFillProjects();
  await loadAll(); render();
}

async function assignFolder(root, projectId) {
  await api("/api/folders/assign", { method: "POST", headers: { "Content-Type": "application/json" },
                                     body: JSON.stringify({ root, project_id: projectId }) });
  if (projectId !== dmCurrentProject()) {  // 移走的文件夹从当前项目视图消失
    selFolder = null;
  }
  await Promise.all([dmFillProjects(), loadAll()]);
  render();
}

async function renameFolder(root) {
  const name = prompt("自定义该图纸库的显示名称（留空恢复默认文件夹名）：",
                      displayName(root));
  if (name === null) return;
  await api("/api/folders/rename", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ root, name })
  });
  await loadAll();
  render();
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
  const projOpts = projList.map(pr =>
    `<option value="${pr.id}" ${pr.id === dmCurrentProject() ? "selected" : ""}>${esc(pr.name)}</option>`).join("");
  const ignoredHtml = ignored.length ? `
    <div class="section-title">已从索引移除的册（${ignored.length}）
      <button id="restoreAllBtn" style="margin-left:10px">↩ 全部恢复</button></div>` +
    ignored.map(g => `
    <div class="card">
      <h3>🚫 ${esc(g.folder_name)}</h3>
      <div class="path">📁 ${esc(g.folder_path)}</div>
      <div class="fileline"><button class="vol-restore" data-path="${esc(g.folder_path)}">↩ 恢复</button></div>
    </div>`).join("") : "";
  return `<div class="section-title">共导入 ${folders.length} 个图纸库文件夹，点击进入查看该库的册</div>` +
    folders.map(f => `
    <div class="card volcard" data-key="${esc(f.root)}" style="cursor:pointer">
      <h3>🗂 ${esc(displayName(f.root))} <span class="badge">${f.list.length} 册</span></h3>
      <div class="meta">图纸条目 ${f.entries} 条 · 文件 ${f.files} 个</div>
      <div class="path">📁 ${esc(f.root || "（来源未记录的册，多为旧版索引遗留）")}</div>
      <div class="fileline">
        <span class="meta">点击查看该库的册 →</span>
        ${f.root ? `<span class="meta">归入项目:</span>
        <select class="assignSel" data-root="${esc(f.root)}">${projOpts}</select>
        <button class="renBtn" data-root="${esc(f.root)}">✏️ 重命名</button>
        <button class="fol-del" data-root="${esc(f.root)}" data-name="${esc(displayName(f.root))}">🗑 删除全部</button>` : ""}
      </div>
    </div>`).join("") + ignoredHtml;
}

/* ---------- 视图二：该文件夹下的册 ---------- */

function volumeList() {
  let list = vols.filter(v => (v.scan_root || "") === selFolder);
  if (!list.length && selFolder) {  // 所选文件夹不属于当前项目（切换项目后），回退到文件夹列表
    selFolder = null;
    return volumeList();
  }
  return `
  <div class="section-title"><a href="#" id="backLink">← 返回文件夹列表</a></div>
  <div class="card">
    <h3>🗂 ${esc(displayName(selFolder))}</h3>
    <div class="meta">${list.length} 册 · 图纸条目 ${list.reduce((s, v) => s + v.entry_count, 0)} 条</div>
    <div class="path">📁 ${esc(selFolder || "")}</div>
    <div class="fileline">
      <span class="actions" data-path="${esc(selFolder)}" data-folder="1"></span>
      ${selFolder ? `<button class="renBtn" data-root="${esc(selFolder)}">✏️ 重命名</button>` : ""}
    </div>
  </div>
  <div class="section-title">该库已入库的册</div>` +
  list.map(v => `
    <div class="card">
      <h3>${esc(v.title || v.folder_name)} ${v.code ? `<span class="badge">${esc(v.code)}</span>` : ""}</h3>
      <div>${verMeta(v, [`${v.entry_count} 条目录 / ${v.file_count} 个文件`,
        v.parse_status !== "ok" ? `<span class="badge rev">${esc(v.parse_status)}</span>` : ""])}</div>
      <div class="path">📁 ${esc(v.folder_path)}</div>
      ${v.ml_file ? `<div class="fileline"><span class="fname">📑 目录文件: ${esc(v.ml_file)}</span><span class="actions" data-path="${esc(v.ml_path || (v.folder_path + "\\" + v.ml_file))}"></span></div>` : ""}
      <div class="fileline">
        <span class="actions" data-path="${esc(v.folder_path)}" data-folder="1"></span>
        <button class="vol-del" data-path="${esc(v.folder_path)}" data-name="${esc(v.title || v.folder_name)}">🗑 从索引移除</button>
      </div>
    </div>`).join("");
}

/* ---------- 渲染与事件 ---------- */

function render() {
  const box = document.getElementById("vol-results");
  if (!vols.length) {
    box.innerHTML = `<div class="empty">索引为空，请先在主页扫描入库。</div>`;
    return;
  }
  box.innerHTML = selFolder ? volumeList() : folderList();
  bindActions();
  document.querySelectorAll(".volcard").forEach(el => {
    el.onclick = () => { selFolder = el.dataset.key; render(); window.scrollTo(0, 0); };
  });
  document.querySelectorAll(".renBtn").forEach(el => {
    el.onclick = (ev) => { ev.stopPropagation(); renameFolder(el.dataset.root); };
  });
  document.querySelectorAll(".vol-del").forEach(el => {
    el.onclick = () => removeVolume(el.dataset.path, el.dataset.name);
  });
  document.querySelectorAll(".vol-restore").forEach(el => {
    el.onclick = () => restoreVolume(el.dataset.path);
  });
  document.querySelectorAll(".fol-del").forEach(el => {
    el.onclick = (ev) => { ev.stopPropagation(); removeFolder(el.dataset.root); };
  });
  const rab = document.getElementById("restoreAllBtn");
  if (rab) rab.onclick = restoreAll;
  document.querySelectorAll(".assignSel").forEach(el => {
    el.value = String(dmCurrentProject());
    el.onclick = (ev) => ev.stopPropagation();
    el.onchange = () => assignFolder(el.dataset.root, parseInt(el.value, 10));
  });
  const back = document.getElementById("backLink");
  if (back) back.onclick = (e) => { e.preventDefault(); selFolder = null; render(); };
}

document.addEventListener("dmprojectchange", () => { selFolder = null; });

window.dmLoadVolumes = function () {
  loadAll()
    .then(render)
    .catch(e => { document.getElementById("vol-results").innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`; });
};
})();
