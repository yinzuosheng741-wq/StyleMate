"""出行衣橱助手 native desktop entry point; no HTTP server or browser runtime."""
import argparse
import importlib.util
import json
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="出行衣橱助手 原生桌面客户端")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-ui", action="store_true")
    parser.add_argument("--shutdown-after", type=float, default=0)
    args = parser.parse_args(argv)
    if args.shutdown_after < 0:
        parser.error("shutdown time must be nonnegative")
    native = importlib.util.find_spec("PySide6") is not None
    if args.check:
        print(json.dumps({"application": "出行衣橱助手", "interface": "native-qt", "native_window": native,
                          "http_server_required": False}))
        return 0 if native else 1
    if not native:
        print("请先安装桌面依赖：python -m pip install -r requirements-desktop.txt", file=sys.stderr)
        return 1
    try:
        from stylemate.desktop.application import run
        return run(shutdown_after=args.shutdown_after, no_ui=args.no_ui)
    except Exception as exc:
        import traceback
        from pathlib import Path
        root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        try:
            log = root / "data/desktop/startup-error.txt"
            log.parent.mkdir(parents=True, exist_ok=True)
            detail = str(exc) if isinstance(exc, ImportError) else type(exc).__name__
            log.write_text(detail + "\n" + "".join(traceback.format_list(traceback.extract_tb(exc.__traceback__))),
                           encoding="utf-8")
        except OSError:
            pass
        if sys.stdout is not None:
            print("客户端启动失败，请检查数据目录权限与运行依赖。", file=sys.stderr)
        if sys.platform == "win32" and not (args.no_ui or args.shutdown_after):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "客户端启动失败，请检查数据目录权限与运行依赖。", "出行衣橱助手", 16)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
