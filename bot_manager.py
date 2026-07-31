"""
پنل مدیریت ربات — یه اپ وب سبک که کنار فایل ربات (rps_bot.py) اجرا می‌شه.
باهاش می‌تونی از تو مرورگر (بدون نوشتن هیچ دستوری تو cmd):

  - بات رو روشن/خاموش/ری‌استارت کنی
  - لاگ زنده‌ی بات رو ببینی
  - وقتی نسخه‌ی جدیدی از فایل بات آماده شد، همینجا آپلودش کنی (خودش قبلیو
    بکاپ می‌گیره و اگه بات روشن بود، با نسخه‌ی جدید ری‌استارتش می‌کنه)
  - پیش‌نیازهای پایتونی بات (python-telegram-bot و ...) رو نصب کنی

راه‌اندازی اولیه (فقط همین یه بار):
  1) پکیج Flask رو نصب کن: pip install flask
     (فایل start_manager.bat کنارش هم هست و اگه Flask نصب نباشه خودش نصبش می‌کنه)
  2) روی start_manager.bat دوبار کلیک کن — یه پنجره‌ی کوچیک (مینیمایز‌شده تو
     تسک‌بار) باز می‌شه و مرورگر خودش می‌ره رو آدرس پنل.
  3) از این به بعد همیشه از همون صفحه‌ی مرورگر همه‌چی رو کنترل کن.

فایل rps_bot.py باید کنار همین فایل باشه.
"""

import atexit
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_FILENAME = "rps_bot.py"
BOT_PATH = os.path.join(BASE_DIR, BOT_FILENAME)
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

# ==== تنظیمات پنل ====
MANAGER_HOST = "127.0.0.1"   # فقط رو خود سیستم در دسترسه
MANAGER_PORT = 8099
MANAGER_USERNAME = "admin"
MANAGER_PASSWORD = "poya"   # قبل از استفاده‌ی واقعی حتماً عوضش کن
BOT_ACTIVITY_PANEL_URL = "http://127.0.0.1:8088"  # همون داشبورد داخلِ خودِ رات (اگه فعالش کرده باشی)

LOG_MAXLEN = 500
log_lines = deque(maxlen=LOG_MAXLEN)
log_lock = threading.Lock()
state_lock = threading.Lock()

bot_process = None  # subprocess.Popen | None
bot_started_at = None  # float | None
setup_running = False  # وقتی داره پیش‌نیازها رو نصب می‌کنه True می‌شه


def _log(line: str) -> None:
    with log_lock:
        log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")


def _reader_thread(proc: subprocess.Popen) -> None:
    try:
        for raw_line in iter(proc.stdout.readline, ""):
            if not raw_line:
                break
            with log_lock:
                log_lines.append(raw_line.rstrip("\n"))
    except Exception:
        pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


def is_running() -> bool:
    return bot_process is not None and bot_process.poll() is None


def start_bot():
    global bot_process, bot_started_at
    with state_lock:
        if is_running():
            return False, "بات از قبل روشنه."
        if not os.path.exists(BOT_PATH):
            return False, f"فایل {BOT_FILENAME} پیدا نشد کنار پنل مدیریت."

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        popen_kwargs = dict(
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        bot_process = subprocess.Popen([sys.executable, BOT_FILENAME], **popen_kwargs)
        bot_started_at = time.time()
        threading.Thread(target=_reader_thread, args=(bot_process,), daemon=True).start()
        _log(f"بات روشن شد (PID {bot_process.pid}).")
    return True, "بات روشن شد."


def stop_bot():
    global bot_process
    with state_lock:
        if not is_running():
            return False, "بات از قبل خاموشه."
        try:
            bot_process.terminate()
            bot_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            bot_process.kill()
            try:
                bot_process.wait(timeout=5)
            except Exception:
                pass
        _log("بات خاموش شد.")
    return True, "بات خاموش شد."


def restart_bot():
    was_running = is_running()
    if was_running:
        stop_bot()
        time.sleep(1)
    ok, msg = start_bot()
    return ok, "بات ری‌استارت شد." if ok else msg


@atexit.register
def _cleanup_on_exit():
    try:
        if is_running():
            bot_process.terminate()
    except Exception:
        pass


def uptime_display() -> str:
    if not bot_started_at:
        return "—"
    seconds = int(time.time() - bot_started_at)
    if seconds < 60:
        return f"{seconds} ثانیه"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقیقه"
    hours = minutes // 60
    return f"{hours} ساعت و {minutes % 60} دقیقه"


def install_requirements_async():
    global setup_running

    def _run():
        global setup_running
        setup_running = True
        _log("شروع نصب پیش‌نیازهای بات (ممکنه چند دقیقه طول بکشه)...")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "flask", "python-telegram-bot[job-queue]"],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for raw_line in iter(proc.stdout.readline, ""):
                if not raw_line:
                    break
                with log_lock:
                    log_lines.append("[setup] " + raw_line.rstrip("\n"))
            proc.wait()
            _log("نصب پیش‌نیازها تموم شد ✅" if proc.returncode == 0 else "نصب پیش‌نیازها با خطا مواجه شد ❌")
        except Exception as e:
            _log(f"خطا تو نصب پیش‌نیازها: {e}")
        finally:
            setup_running = False

    threading.Thread(target=_run, daemon=True).start()


def measure_telegram_latency_async(samples: int = 5):
    import urllib.error

    def _run():
        _log(f"شروع تست سرعت اتصال به تلگرام ({samples} تلاش)...")
        times = []
        for i in range(samples):
            t0 = time.time()
            try:
                urllib.request.urlopen("https://api.telegram.org", timeout=6)
                ms = (time.time() - t0) * 1000
                times.append(ms)
                _log(f"[latency] تلاش {i + 1}: {ms:.0f} میلی‌ثانیه")
            except urllib.error.HTTPError:
                # جواب HTTP (حتی اگه خطا باشه، مثلاً 403) یعنی مسیر شبکه واقعاً وصل شده؛
                # فقط زمان رفت‌وبرگشت مهمه، نه کد وضعیتش
                ms = (time.time() - t0) * 1000
                times.append(ms)
                _log(f"[latency] تلاش {i + 1}: {ms:.0f} میلی‌ثانیه (وصل شد)")
            except Exception as e:
                _log(f"[latency] تلاش {i + 1}: ناموفق ({e})")
        if not times:
            _log("[latency] نتیجه: هیچ‌کدوم از تلاش‌ها موفق نشد — احتمالاً تلگرام از این شبکه فیلتر/مسدوده و بدون پروکسی/وی‌پی‌ان اصلاً بهش وصل نمی‌شی.")
        else:
            avg = sum(times) / len(times)
            if avg < 300:
                verdict = "خوبه، این اندازه تأخیر معمولاً باعث کندی محسوس نمی‌شه."
            elif avg < 800:
                verdict = "کمی بالاست؛ ممکنه گاهی کندی حس بشه."
            else:
                verdict = "بالاست — این می‌تونه دلیل اصلیِ دیر آپدیت شدن دکمه‌ها باشه. یه پروکسی/وی‌پی‌ان بهتر یا میزبانی رو یه VPS رو امتحان کن."
            _log(f"[latency] میانگین: {avg:.0f} میلی‌ثانیه روی {len(times)} تلاش موفق. {verdict}")

    threading.Thread(target=_run, daemon=True).start()


def create_app():
    from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

    app = Flask(__name__)
    app.secret_key = os.urandom(16)
    last_flash = {"msg": ""}

    @app.before_request
    def require_auth():
        auth = request.authorization
        if not auth or auth.username != MANAGER_USERNAME or auth.password != MANAGER_PASSWORD:
            return Response("لطفاً وارد شو", 401, {"WWW-Authenticate": 'Basic realm="bot manager"'})

    @app.route("/")
    def dashboard():
        msg = last_flash["msg"]
        last_flash["msg"] = ""
        return render_template("index.html", activity_url=BOT_ACTIVITY_PANEL_URL, flash_msg=msg)

    @app.route("/status.json")
    def status_json():
        with log_lock:
            log_copy = list(log_lines)
        return jsonify({
            "running": is_running(),
            "pid": bot_process.pid if is_running() else None,
            "uptime": uptime_display(),
            "setup_running": setup_running,
            "log": log_copy,
        })

    @app.route("/start", methods=["POST"])
    def route_start():
        ok, msg = start_bot()
        last_flash["msg"] = msg
        return redirect(url_for("dashboard"))

    @app.route("/stop", methods=["POST"])
    def route_stop():
        ok, msg = stop_bot()
        last_flash["msg"] = msg
        return redirect(url_for("dashboard"))

    @app.route("/restart", methods=["POST"])
    def route_restart():
        ok, msg = restart_bot()
        last_flash["msg"] = msg
        return redirect(url_for("dashboard"))

    @app.route("/install", methods=["POST"])
    def route_install():
        install_requirements_async()
        last_flash["msg"] = "نصب پیش‌نیازها تو پس‌زمینه شروع شد؛ تو لاگ پایین صفحه پیشرفتش رو ببین."
        return redirect(url_for("dashboard"))

    @app.route("/latency", methods=["POST"])
    def route_latency():
        measure_telegram_latency_async()
        last_flash["msg"] = "تست سرعت شروع شد؛ نتیجه تا چند ثانیه‌ی دیگه تو لاگ پایین صفحه میاد."
        return redirect(url_for("dashboard"))

    @app.route("/upload", methods=["POST"])
    def route_upload():
        f = request.files.get("file")
        if not f or not f.filename.endswith(".py"):
            last_flash["msg"] = "فقط فایل .py قابل قبوله."
            return redirect(url_for("dashboard"))

        os.makedirs(BACKUP_DIR, exist_ok=True)
        if os.path.exists(BOT_PATH):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(BOT_PATH, os.path.join(BACKUP_DIR, f"rps_bot_{stamp}.py"))

        f.save(BOT_PATH)
        _log(f"فایل بات با نسخه‌ی جدید ({f.filename}) جایگزین شد.")

        msg = "فایل جدید ذخیره شد (نسخه‌ی قبلی تو پوشه‌ی backups بکاپ گرفته شد)."
        if is_running():
            restart_bot()
            msg += " بات با نسخه‌ی جدید ری‌استارت شد."
        last_flash["msg"] = msg
        return redirect(url_for("dashboard"))

    return app


def main():
    try:
        app = create_app()
    except ImportError:
        print("پکیج flask نصب نیست. یه بار این رو بزن: pip install flask")
        sys.exit(1)

    print(f"پنل مدیریت روی http://{MANAGER_HOST}:{MANAGER_PORT} بالا اومد (یوزر/پس: {MANAGER_USERNAME})")
    app.run(host=MANAGER_HOST, port=MANAGER_PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
