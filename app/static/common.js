/* 公共：侧边栏注入 + 主题切换 + 项目选择器（所有页面共用） */
(function () {
  const h = document.documentElement;
  if (localStorage.getItem("dm_theme") === "dark") h.classList.add("dark");

  const SUN = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>';
  const MOON = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>';
  const NAVS = [
    { file: "index.html", id: "search", label: "搜索", icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>' },
    { file: "volumes.html", id: "volumes", label: "册列表", icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>' },
    { file: "versions.html", id: "versions", label: "版本对比", icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg>' },
    { file: "inventory.html", id: "inventory", label: "图纸清册", icon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/></svg>' },
  ];

  window.dmBindSidebar = function () {
    if (document.getElementById("sidebar")) return;
    const page = location.pathname.split("/").pop() || "index.html";
    const aside = document.createElement("aside");
    aside.id = "sidebar";
    aside.innerHTML = `
      <div class="sb-logo" title="工程图纸文件管理">📐<span class="sb-label">图纸管理</span></div>
      <div class="sb-proj"><select id="projSel" class="projsel" title="切换项目"></select></div>
      <nav class="sb-nav">
        ${NAVS.map(n => `<a class="sb-link${page === n.file ? " active" : ""}" href="${n.file}" title="${n.label}">${n.icon}<span class="sb-label">${n.label}</span></a>`).join("")}
      </nav>
      <div class="sb-foot">
        <div class="themeseg" id="themeSeg" role="group" aria-label="切换日间/夜间主题">
          <span class="segthumb" aria-hidden="true"></span>
          <button type="button" class="segopt" data-mode="light" aria-pressed="true" title="浅色主题">${SUN}<span class="seglabel">浅色</span></button>
          <button type="button" class="segopt" data-mode="dark" aria-pressed="false" title="深色主题">${MOON}<span class="seglabel">深色</span></button>
        </div>
        <button type="button" id="sbToggle" class="sb-collapse" title="收起侧边栏">«<span class="sb-label"> 收起</span></button>
      </div>`;
    const content = document.createElement("div");
    content.className = "content";
    document.body.prepend(aside);
    document.body.appendChild(content);
    const header = document.querySelector("body > header");
    const main = document.querySelector("body > main");
    if (header) content.appendChild(header);
    if (main) content.appendChild(main);
    // 收起状态持久化
    const apply = (c) => {
      document.body.classList.toggle("sb-collapsed", c);
      aside.querySelector("#sbToggle").innerHTML =
        c ? '»' : '«<span class="sb-label"> 收起</span>';
      aside.querySelector("#sbToggle").title = c ? "展开侧边栏" : "收起侧边栏";
    };
    apply(localStorage.getItem("dm_sidebar") === "1");
    aside.querySelector("#sbToggle").onclick = () => {
      const c = document.body.classList.toggle("sb-collapsed");
      localStorage.setItem("dm_sidebar", c ? "1" : "0");
      apply(c);
    };
  };

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
      b.setAttribute("aria-pressed",
        String((b.dataset.mode === "dark") === h.classList.contains("dark")));
    });
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
