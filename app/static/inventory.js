(function () {
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

function statCards(inv) {
  const totalFiles = inv.items.reduce((s, i) => s + i.file_count, 0);
  const cats = Object.keys(inv.categories).length;
  return `
  <div class="stat"><b>${inv.volumes.length}</b><span>图册（册）</span></div>
  <div class="stat"><b>${inv.items.length}</b><span>图纸条目（张）</span></div>
  <div class="stat"><b>${totalFiles}</b><span>版本文件（个）</span></div>
  <div class="stat"><b>${cats}</b><span>类别</span></div>`;
}

function catCards(inv) {
  const byCat = {};
  for (const i of inv.items) (byCat[i.category] = byCat[i.category] || []).push(i);
  return Object.entries(inv.categories).map(([cat, n]) => {
    const rows = byCat[cat].map(i => `
      <tr>
        <td class="no">${esc(i.drawing_no)}</td>
        <td>${esc(i.title || "—")}</td>
        <td>${esc(i.code || "")} ${esc(i.volume_title || "")}</td>
        <td style="text-align:center">${i.rev ?? ""}</td>
        <td style="text-align:center">${i.file_count || "—"}</td>
        <td class="no">${esc(i.latest_file || "—")}</td>
      </tr>`).join("");
    return `
    <div class="card catcard">
      <h3>${esc(cat)} <span class="badge rev">${n} 张</span></h3>
      <table>
        <tr><th>图号</th><th>图纸名称</th><th>所属册</th><th>REV</th><th>版本数</th><th>最新版文件</th></tr>
        ${rows}
      </table>
    </div>`;
  }).join("");
}

document.getElementById("exportBtn").onclick = () => {
  window.location.href = "/api/inventory/export?project=" + dmCurrentProject();
};

window.dmLoadInventory = function () {
  api("/api/inventory?project=" + dmCurrentProject())
    .then(inv => {
      if (!inv.items.length) {
        document.getElementById("inv-stats").style.display = "none";
        document.getElementById("inv-results").innerHTML = `<div class="empty">当前项目还没有图纸，请先在「搜索」页扫描入库。</div>`;
        return;
      }
      document.getElementById("inv-stats").style.display = "flex";
      document.getElementById("inv-stats").innerHTML = statCards(inv);
      document.getElementById("inv-results").innerHTML =
        `<div class="section-title">分类明细（生成于 ${esc(inv.generated_at.replace("T", " "))}）</div>` + catCards(inv);
    })
    .catch(e => { document.getElementById("inv-results").innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`; });
};
})();
