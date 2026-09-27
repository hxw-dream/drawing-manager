/* 公共：主题切换 + 项目选择器（所有页面共用） */
(function () {
  const h = document.documentElement;
  if (localStorage.getItem("dm_theme") === "dark") h.classList.add("dark");

  window.dmSetTheme = function (mode) {
    const dark = mode === "dark";
    h.classList.toggle("dark", dark);
    localStorage.setItem("dm_theme", dark ? "dark" : "light");
    const seg = document.getElementById("themeSeg");
    if (seg) seg.querySelectorAll(".segopt").forEach(b =>
      b.setAttribute("aria-pressed",
        String((b.dataset.mode === "dark") === dark)));
  };

  window.dmBindTheme = function () {
    const seg = document.getElementById("themeSeg");
    if (!seg) return;
    seg.querySelectorAll(".segopt").forEach(b => {
      b.onclick = () => window.dmSetTheme(b.dataset.mode);
    });
    // 初始 aria 状态与当前主题对齐
    seg.querySelectorAll(".segopt").forEach(b =>
      b.setAttribute("aria-pressed",
        String((b.dataset.mode === "dark") === h.classList.contains("dark"))));
  };

  window.dmCurrentProject = function () {
    return parseInt(localStorage.getItem("dm_project") || "1", 10) || 1;
  };

  window.dmFillProjects = async function () {
    const sel = document.getElementById("projSel");
    if (!sel) return;
    const list = await (await fetch("/api/projects")).json();
    sel.innerHTML = list.map(p =>
      `<option value="${p.id}">${p.name}（${p.folders} 文件夹）</option>`).join("");
    const saved = window.dmCurrentProject();
    sel.value = list.some(p => p.id === saved) ? saved : 1;
    if (String(sel.value) !== String(saved)) localStorage.setItem("dm_project", sel.value);
    sel.onchange = () => {
      localStorage.setItem("dm_project", sel.value);
      document.dispatchEvent(new Event("dmprojectchange"));
    };
  };
})();
