/* 项目管理视图：项目列表（含图纸文件夹归属）+ 新建 + 删除 */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const box = () => document.getElementById("proj-results");

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }

  async function createProject(name) {
    await api("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify({ name }) });
    await load();
    if (window.dmFillProjects) await window.dmFillProjects();  // 侧边栏选择器同步
  }

  async function renameProject(id, oldName) {
    const name = prompt(`重命名项目「${oldName}」：`, oldName);
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed === oldName) return;
    try {
      await api("/api/projects/rename", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, name: trimmed }) });
    } catch (e) { alert(String(e.message)); return; }
    await load();
    if (window.dmFillProjects) await window.dmFillProjects();
  }

  async function deleteProject(id, name) {
    if (!confirm(`确定删除项目「${name}」？`)) return;
    try {
      await api("/api/projects/delete", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) });
    } catch (e) {
      alert(String(e.message));  // 项目下还有文件夹等保护提示
      return;
    }
    await load();
    if (window.dmFillProjects) await window.dmFillProjects();
  }

  function render(list) {
    const rows = list.map(p => {
      const isDefault = p.id === 1;
      const isCurrent = p.id === (window.dmCurrentProject ? window.dmCurrentProject() : 1);
      return `
      <div class="card">
        <h3>🗂 ${esc(p.name)}
          ${isDefault ? `<span class="badge">默认项目</span>` : ""}
          ${isCurrent ? `<span class="badge new">当前项目</span>` : ""}
        </h3>
        <div class="meta">${p.folders} 个图纸文件夹归属此项目</div>
        <div class="fileline">
          <button class="pj-ren" data-id="${p.id}" data-name="${esc(p.name)}">✏️ 重命名</button>
          ${!isDefault ? `<button class="pj-del" data-id="${p.id}" data-name="${esc(p.name)}">🗑 删除</button>` : ""}
        </div>
      </div>`;
    }).join("");
    box().innerHTML = `
      <div class="card">
        <h3>➕ 新建项目</h3>
        <div id="newprojrow" style="display:flex;gap:8px;margin-top:6px">
          <input id="newProjName" placeholder="项目名称，如：XX电厂项目" style="flex:1;padding:8px 10px;font-size:13px;border:1px solid var(--line);border-radius:6px;background:var(--soft);color:var(--ink)">
          <button id="newProjGo" class="primary">创建项目</button>
        </div>
        <div class="meta" style="margin-top:6px">新建后在「册列表」把图纸文件夹归入项目；扫描入库时也会自动归入当前选中的项目</div>
      </div>
      <div class="section-title">共 ${list.length} 个项目</div>` + rows;

    document.getElementById("newProjGo").onclick = async () => {
      const name = document.getElementById("newProjName").value.trim();
      if (!name) { alert("请输入项目名称"); return; }
      try { await createProject(name); }
      catch (e) { alert(String(e.message)); }
    };
    document.getElementById("newProjName").addEventListener("keydown",
      e => { if (e.key === "Enter") document.getElementById("newProjGo").click(); });
    box().querySelectorAll(".pj-del").forEach(b => {
      b.onclick = () => deleteProject(parseInt(b.dataset.id, 10), b.dataset.name);
    });
    box().querySelectorAll(".pj-ren").forEach(b => {
      b.onclick = () => renameProject(parseInt(b.dataset.id, 10), b.dataset.name);
    });
  }

  async function load() {
    try {
      const list = await api("/api/projects");
      render(list);
    } catch (e) {
      box().innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`;
    }
  }

  window.dmLoadProjects = load;
})();
