/* 公共：主题切换 + 项目选择器（所有页面共用） */
(function () {
  const h = document.documentElement;
  if (localStorage.getItem("dm_theme") === "dark") h.classList.add("dark");

  window.dmToggleTheme = function () {
    const dark = h.classList.toggle("dark");
    localStorage.setItem("dm_theme", dark ? "dark" : "light");
    const b = document.getElementById("themeBtn");
    if (b) b.textContent = dark ? "☀️" : "🌙";
  };

  window.dmBindTheme = function () {
    const b = document.getElementById("themeBtn");
    if (!b) return;
    b.textContent = h.classList.contains("dark") ? "☀️" : "🌙";
    b.onclick = window.dmToggleTheme;
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
