"""打包入口（PyInstaller）：无窗口启动本地服务并自动打开浏览器。

单实例：端口已被占用视为"已在运行"，只打开浏览器后退出。
崩溃时把原因写入 exe 旁的 crash.log 并弹窗提示。
"""
import socket
import sys
import threading
import webbrowser
from pathlib import Path

URL = "http://127.0.0.1:8000"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    if _port_in_use(8000):
        webbrowser.open(URL)  # 已有实例在跑：打开页面即退出
        return
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    import uvicorn
    from app.main import app as fastapi_app
    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
        (base / "crash.log").write_text(f"{type(ex).__name__}: {ex}\n", encoding="utf-8")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"启动失败: {ex}\n详情见 crash.log", "工程图纸文件管理", 0x10)
        except Exception:
            pass
        raise
