const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtSize = (n) => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
const fmtTime = (t) => new Date(t * 1000).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

let data = null;
let selected = null;   // 当前选中的册 folder_path，null = 图册列表视图

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

/* ---------- 视图一：含版本差异图纸的图册列表 ---------- */

function volumeList() {
  const byVol = {};
  for (const g of data.groups) {
    (byVol[g.folder_path] = byVol[g.folder_path] || {
      folder_name: g.folder_name, folder_path: g.folder_path, code: g.code,
      volume_title: g.volume_title, vol_date: g.vol_date, vol_rev: g.vol_rev,
      groups: []
    }).groups.push(g);
  }
  const vols = Object.values(byVol);
  return `<div class="section-title">${vols.length} 册存在多版本图纸，点击查看该册的版本差异</div>` +
    vols.map(v => {
      const nos = v.groups.map(g => g.drawing_no.split("-").pop()).join("、");
      const fileCount = v.groups.reduce((s, g) => s + g.versions.length, 0);
      return `
      <div class="card volcard" data-key="${esc(v.folder_path)}" style="cursor:pointer">
        <h3>${esc(v.volume_title || v.folder_name)} ${v.code ? `<span class="badge">${esc(v.code)}</span>` : ""}
          <span class="badge rev">${v.groups.length} 个图号多版本</span></h3>
        <div class="meta">${v.vol_date ? `📅 ${esc(v.vol_date)}` : ""}${v.vol_rev ? ` · 修订: ${esc(v.vol_rev)}` : ""}
          · 共 ${fileCount} 个版本文件</div>
        <div>涉及图号（末位）：${esc(nos)}</div>
        <div class="path">📁 ${esc(v.folder_path)}</div>
        <div class="fileline"><span class="meta">点击卡片展开版本差异 →</span>
          <span class="actions" data-path="${esc(v.folder_path)}" data-folder="1"></span></div>
      </div>`;
    }).join("");
}

/* ---------- 视图二：单册内的图号版本对比 ---------- */

function verLabel(v, i) {
  if (v.is_base) return "初版";
  return `第 ${i + 1} 版`;
}

function diffLine(v, prev) {
  const parts = [];
  if (v.note) parts.push(`修改内容：${v.note}`);
  if (v.ver_date) parts.push(`修改日期：${v.ver_date}`);
  if (prev) {
    const ds = v.size - prev.size;
    if (ds !== 0) parts.push(`文件大小${ds > 0 ? "增加" : "减少"} ${fmtSize(Math.abs(ds))}（${fmtSize(prev.size)} → ${fmtSize(v.size)}）`);
    else parts.push("文件大小未变");
  }
  return parts.join("　·　");
}

function detail() {
  const groups = data.groups.filter(g => g.folder_path === selected);
  const head = groups[0];
  return `
  <div class="section-title"><a href="#" id="backLink">← 返回图册列表</a></div>
  <div class="card">
    <h3>${esc(head.volume_title || head.folder_name)} ${head.code ? `<span class="badge">${esc(head.code)}</span>` : ""}</h3>
    <div class="meta">${head.vol_date ? `📅 ${esc(head.vol_date)}` : ""}${head.vol_rev ? ` · 修订: ${esc(head.vol_rev)}` : ""}</div>
    <div class="path">📁 ${esc(head.folder_path)}</div>
    <div class="fileline"><span class="actions" data-path="${esc(head.folder_path)}" data-folder="1"></span></div>
  </div>
  <div class="section-title">该册 ${groups.length} 个图号存在多版本</div>` +
  groups.map(g => {
    const vers = g.versions.map((v, i) => {
      const prev = i > 0 ? g.versions[i - 1] : null;
      const isNew = i === g.versions.length - 1;
      const badge = isNew ? `<span class="badge new">最新版</span>` : "";
      const note = (i === 0 && v.is_base) ? "" : `<div class="diff">${esc(diffLine(v, prev))}</div>`;
      return `
        <div class="ver">
          <div class="fileline">
            <span class="badge">${verLabel(v, i)}</span>${badge}
            <span class="fname">📄 ${esc(v.filename)}</span>
            <span class="actions" data-path="${esc(v.path)}"></span>
          </div>
          <div class="meta">文件时间 ${fmtTime(v.mtime)} · 大小 ${fmtSize(v.size)}</div>
          ${note}
        </div>`;
    }).join("");
    return `
    <div class="card">
      <h3>${esc(g.drawing_no)} <span class="badge rev">${g.versions.length} 个版本</span>
        ${g.rev ? `<span class="badge">目录 REV ${esc(g.rev)}</span>` : ""}</h3>
      <div>${esc(g.title || "")}</div>
      ${vers}
    </div>`;
  }).join("");
}

/* ---------- 渲染与事件 ---------- */

function render() {
  const box = document.getElementById("results");
  if (!data.groups.length) {
    box.innerHTML = `<div class="empty">暂无多版本图纸。<br><br>
      当同一图号的图纸在册文件夹里有多个文件时（如 xx-03.pdf 与 xx-03-2025.3.9修改说明.pdf），
      这里会按版本时间线展示每个版本的差异。</div>`;
    return;
  }
  box.innerHTML = selected ? detail() : volumeList();
  bindActions();
  document.querySelectorAll(".volcard").forEach(el => {
    el.onclick = () => { selected = el.dataset.key; render(); window.scrollTo(0, 0); };
  });
  const back = document.getElementById("backLink");
  if (back) back.onclick = (e) => { e.preventDefault(); selected = null; render(); };
}

api("/api/versions")
  .then(d => { data = d; render(); })
  .catch(e => { document.getElementById("results").innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`; });
