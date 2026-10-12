<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.svg?v=2">
    <img src="docs/banner-light.svg?v=2" alt="工程图纸文件管理系统 —— 本地图纸库：目录识别、秒级检索、版本对比、清册导出">
  </picture>
</p>
<p align="center">
  <a href="https://github.com/hxw-dream/drawing-manager/actions/workflows/ci.yml"><img src="https://github.com/hxw-dream/drawing-manager/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/hxw-dream/drawing-manager/releases"><img src="https://img.shields.io/github/v/release/hxw-dream/drawing-manager?include_prereleases&label=%E7%89%88%E6%9C%AC" alt="版本"></a>
  <img src="https://img.shields.io/badge/%E8%BF%90%E8%A1%8C%E6%96%B9%E5%BC%8F-%E5%AE%8C%E5%85%A8%E6%9C%AC%E5%9C%B0-blue" alt="完全本地">
</p>

# 工程图纸文件管理（drawing-manager）

本地网页应用：扫描本地图纸库，识别每册的 `-ML` 目录文件，建立可搜索索引，
定位文件所在文件夹，并按版本归类。**只读索引，绝不移动/修改图纸文件。**

## 约定

- 一册 = 一个文件夹，文件夹内有一个 `-ML` 后缀的目录文件（如 `F10001-D0401-ML.pdf`）
- 目录文件支持 PDF 与 DWG/DXF：
  - 带文字层的 PDF 直接提取；扫描件走本地 OCR（RapidOCR，离线，300 DPI）
  - DWG/DXF 调用 ODA File Converter 转 DXF 后提取矢量文字（无 OCR 误差），
    默认自动查找常见安装路径，也可用环境变量 `ODA_CONVERTER` 指定 exe
- 整册版本：同卷册号多文件夹（文件夹名含日期/修订标记，如 `…-2024.5.7-改明敷`）
- 单图版本：文件名 `图号-日期修改说明.pdf`，如 `…-03-2025.3.9桥架定位变化-模型.pdf`
- 图纸清册导出（Excel）：每册一行按图册号升序，类别合并块 + 逐张明细 + 分类统计

## 分发给别人用（绿色版打包）

双击 `build.bat`：自动用 PyInstaller 打成 onedir 文件夹并压缩为
`dist\drawing-manager-绿色版.zip`（约 120MB）。发给同事后：

1. 解压到任意位置（U 盘也行）
2. 双击 `DrawingManager.exe` —— 无窗口，自动在浏览器打开页面（`http://127.0.0.1:8000`）
3. 索引库建在 exe 旁的 `data\` 文件夹，整个文件夹可整体搬走
4. 停止服务：双击文件夹里的 `停止服务.bat`（或关机）

无需安装 Python 和任何依赖。DWG 目录识别需要对方另装
[ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)（免费），
没装不影响 PDF 目录功能。

## 开发模式启动

双击 `run.bat`（需先按 requirements.txt 建好 .venv），或：

```bash
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000 。仅监听本机。

## 使用

1. 顶部输入图纸根目录 → 「扫描入库」（可随时重扫，增量更新）
2. 搜索框输入关键字（图号 / 图名 / 册名 / 文件名 / 工程名，支持中英文）
3. 结果按图号分组、版本新在前；点「打开所在文件夹」在资源管理器中定位文件

图纸库暂时掉线或无权限时保留已有索引。仅在完整重扫一个可访问的根目录后，
清理该来源下确认已删除的子册；查看列表、搜索和清册不会自动删除索引。

## 数据位置

- 索引库：`data/index.db`（SQLite）
- 上次扫描根目录：`data/config.json`

## 开发检查

在虚拟环境中安装开发依赖和测试浏览器，再运行回归测试：

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium
python -m pytest tests -q
python -m ruff check app tests
```

浏览器测试覆盖恢复操作、项目切换及搜索请求乱序。已安装 Chromium 时，
也可用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指定浏览器路径。
