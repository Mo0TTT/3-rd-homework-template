#!/usr/bin/env python3
"""Автоматический сценарий проверки восстановления (уровень на 10 баллов)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_NAME = f"hw3_test_{os.getpid()}"
RESTORE_PROJECT = f"{PROJECT_NAME}_restore"
APP_PORT = os.getenv("TEST_APP_PORT", "18080")
BASE_URL = f"http://127.0.0.1:{APP_PORT}"
N = 3
BACKUP_DIR = ROOT_DIR / "backups"
BACKUP_FILE = BACKUP_DIR / f"redis_backup_{PROJECT_NAME}.tar.gz"

ENV = os.environ.copy()
ENV.update(
    {
        "APP_PORT": APP_PORT,
        "PORT": "8000",
        "GREETING": "Test Greeting",
        "STORAGE": "redis",
        "REDIS_URL": "redis://redis:6379/0",
    }
)


def run_cmd(args, check=True):
    return subprocess.run(
        args,
        cwd=ROOT_DIR,
        env=ENV,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def request_http(method, path, timeout=5):
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}
        return exc.code, payload
    except Exception:
        return 0, {}


def wait_for_ready(timeout_sec=30):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        status, _ = request_http("GET", "/readyz", timeout=2)
        if status == 200:
            return
        time.sleep(1)
    raise RuntimeError(f"Тайм-аут ожидания готовности сервиса ({timeout_sec} сек)")


def cleanup():
    print(f"[cleanup] Очистка тестовых ресурсов ({PROJECT_NAME}, {RESTORE_PROJECT})...")
    for project in (PROJECT_NAME, RESTORE_PROJECT):
        run_cmd(
            ["docker", "compose", "-p", project, "down", "-v", "--remove-orphans"],
            check=False,
        )
    if BACKUP_FILE.exists():
        BACKUP_FILE.unlink()
    if BACKUP_DIR.exists() and not any(BACKUP_DIR.iterdir()):
        BACKUP_DIR.rmdir()


def main():
    stage = "Инициализация"
    try:
        stage = "1. Создание тестового Compose-проекта и ожидание готовности"
        print(f"==> {stage}")
        run_cmd(
            ["docker", "compose", "-p", PROJECT_NAME, "down", "-v", "--remove-orphans"],
            check=False,
        )
        run_cmd(["docker", "compose", "-p", PROJECT_NAME, "up", "-d", "--build"])
        wait_for_ready()
        print("    Сервис готов (GET /readyz -> 200)")

        stage = f"2. Проверка начального счётчика (0) и выполнение {N} запросов POST /increment"
        print(f"==> {stage}")
        status, data = request_http("GET", "/")
        if status != 200 or data.get("count") != 0:
            raise RuntimeError(f"Ожидался count=0, получено: status={status}, data={data}")
        print(f"    Начальное значение счётчика: {data['count']}")

        for i in range(1, N + 1):
            status, data = request_http("POST", "/increment")
            if status != 200 or data.get("count") != i:
                raise RuntimeError(f"Ошибка на шаге {i}: status={status}, data={data}")
            print(f"    POST /increment #{i} -> count={data['count']}")

        status, data = request_http("GET", "/")
        if status != 200 or data.get("count") != N:
            raise RuntimeError(f"Ожидался count={N}, получено: status={status}, data={data}")
        print(f"    Текущее значение счётчика подтверждено: {data['count']}")

        stage = "3. Пересоздание контейнера приложения и проверка сохранения счётчика"
        print(f"==> {stage}")
        run_cmd(
            [
                "docker",
                "compose",
                "-p",
                PROJECT_NAME,
                "up",
                "-d",
                "--force-recreate",
                "--no-deps",
                "app",
            ]
        )
        wait_for_ready()
        status, data = request_http("GET", "/")
        if status != 200 or data.get("count") != N:
            raise RuntimeError(f"Счётчик не сохранился: status={status}, data={data}")
        print(f"    После пересоздания app значение счётчика сохранилось: {data['count']}")

        stage = "4. Проверка отключения и повторного запуска Redis"
        print(f"==> {stage}")
        run_cmd(["docker", "compose", "-p", PROJECT_NAME, "stop", "redis"])
        code_health, _ = request_http("GET", "/healthz")
        code_ready, _ = request_http("GET", "/readyz")
        code_inc, _ = request_http("POST", "/increment")
        print(
            f"    При остановленном Redis: /healthz={code_health}, "
            f"/readyz={code_ready}, POST /increment={code_inc}"
        )
        if (code_health, code_ready, code_inc) != (200, 503, 503):
            raise RuntimeError("Неверные коды ответа при остановленном Redis")

        run_cmd(["docker", "compose", "-p", PROJECT_NAME, "start", "redis"])
        wait_for_ready()
        status, data = request_http("GET", "/")
        if status != 200 or data.get("count") != N:
            raise RuntimeError(f"Ожидался count={N} после старта Redis, получено {data}")
        expected_next = N + 1
        status, data = request_http("POST", "/increment")
        if status != 200 or data.get("count") != expected_next:
            raise RuntimeError(f"Ожидался count={expected_next}, получено {data}")
        print(
            f"    После запуска Redis без перезапуска app: "
            f"GET / -> {N}, POST /increment -> {data['count']}"
        )

        stage = "5. Создание согласованной резервной копии данных Redis"
        print(f"==> {stage}")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        run_cmd(["docker", "compose", "-p", PROJECT_NAME, "stop", "app", "redis"])
        with open(BACKUP_FILE, "wb") as f_out:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{PROJECT_NAME}_redis_data:/data:ro",
                    "redis:7.4-alpine",
                    "tar",
                    "-czpf",
                    "-",
                    "-C",
                    "/data",
                    ".",
                ],
                cwd=ROOT_DIR,
                env=ENV,
                check=True,
                stdout=f_out,
            )
        if not BACKUP_FILE.exists() or BACKUP_FILE.stat().st_size == 0:
            raise RuntimeError("Файл резервной копии не создан или пуст")
        print(f"    Резервная копия создана: backups/{BACKUP_FILE.name}")

        stage = "6. Удаление исходного тестового проекта вместе с volumes (down -v)"
        print(f"==> {stage}")
        run_cmd(["docker", "compose", "-p", PROJECT_NAME, "down", "-v"])
        print(f"    Проект {PROJECT_NAME} и его volumes удалены")

        stage = "7. Восстановление из резервной копии в новый проект и проверка счётчика"
        print(f"==> {stage}")
        run_cmd(["docker", "compose", "-p", RESTORE_PROJECT, "up", "--no-start"])
        with open(BACKUP_FILE, "rb") as f_in:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "-v",
                    f"{RESTORE_PROJECT}_redis_data:/data",
                    "redis:7.4-alpine",
                    "tar",
                    "-xzpf",
                    "-",
                    "-C",
                    "/data",
                ],
                cwd=ROOT_DIR,
                env=ENV,
                check=True,
                stdin=f_in,
            )
        run_cmd(["docker", "compose", "-p", RESTORE_PROJECT, "up", "-d"])
        wait_for_ready()
        status, data = request_http("GET", "/")
        if status != 200 or data.get("count") != expected_next:
            raise RuntimeError(
                f"Ожидался восстановленный count={expected_next}, получено: {data}"
            )
        print(f"    Данные успешно восстановлены в {RESTORE_PROJECT}: count={data['count']}")
        print("==> Все проверки успешно пройдены!")
    except Exception as exc:
        print(f"[ОШИБКА] Проверка прервана на этапе: {stage} ({exc})", file=sys.stderr)
        sys.exit(1)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
