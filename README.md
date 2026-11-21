# Домашнее задание №3 по Docker
## Содержимое репозитория

- `app/` — исходный код приложения (`app.py`, `requirements.txt`, `README.md` — без изменений)
- `Dockerfile` — сборка образа приложения на базе `python:3.13-slim` от непривилегированного пользователя (`UID 1000`)
- `.dockerignore` — исключения контекста сборки
- `compose.yaml` — конфигурация Docker Compose (`app` + `redis`, named volume, `healthcheck`, ограничения процесса и ресурсов)
- `.env.example` — пример файла настроек окружения (порт, приветствие, имя проекта Compose)
- `scripts/check.sh` и `scripts/check.py` — автоматические сценарии проверки работы и восстановления из резервной копии

---

## 1. На 4 балла — один контейнер

### Команды сборки, запуска и проверки

```bash
docker build -t counter-app .
docker run -d --name counter-single -p 8080:8000 -e GREETING="Hello from Docker!" counter-app

curl -fsS http://127.0.0.1:8080/
curl -fsS -X POST http://127.0.0.1:8080/increment
curl -fsS -X POST http://127.0.0.1:8080/increment
curl -fsS http://127.0.0.1:8080/

docker logs counter-single
docker rm -f counter-single
```

### Результаты запросов

```text
{"greeting": "Hello from Docker!", "count": 0, "hostname": "74d29eb32722", "storage": "sqlite"}
{"greeting": "Hello from Docker!", "count": 1, "hostname": "74d29eb32722", "storage": "sqlite"}
{"greeting": "Hello from Docker!", "count": 2, "hostname": "74d29eb32722", "storage": "sqlite"}
{"greeting": "Hello from Docker!", "count": 2, "hostname": "74d29eb32722", "storage": "sqlite"}
```

### Логи контейнера (`docker logs counter-single`)

```text
2026-11-13 19:57:28,702 listening port=8000 storage=sqlite
2026-11-13 19:57:30,494 http 172.17.0.1 "GET / HTTP/1.1" 200 -
2026-11-13 19:57:30,540 http 172.17.0.1 "POST /increment HTTP/1.1" 200 -
2026-11-13 19:57:30,583 http 172.17.0.1 "POST /increment HTTP/1.1" 200 -
2026-11-13 19:57:30,603 http 172.17.0.1 "GET / HTTP/1.1" 200 -
```

---

## 2. На 6 баллов — Compose и сохранение данных

Настройки вынесены в переменные окружения. Перед ручным запуском создаётся `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Основные параметры в `.env.example`:
- `COMPOSE_PROJECT_NAME=hw3_counter` — имя проекта Compose по умолчанию (полезно, если папка названа не на латинице)
- `APP_PORT=8080` — внешний порт на хосте
- `PORT=8000` — внутренний порт приложения
- `GREETING=Hello, Docker!` — текст поля `greeting` в ответе
- `STORAGE=redis`, `REDIS_URL=redis://redis:6379/0` — подключение к хранилищу

Запуск и проверка сохранения счётчика после удаления и пересоздания контейнеров через `docker compose down` и `docker compose up -d` объединены в отчёте уровня 8 ниже.

---

## 3. На 8 баллов — отдельное хранилище Redis

В `compose.yaml` настроены два сервиса:
1. `app` — собирается из `Dockerfile`, использует `STORAGE=redis` и `REDIS_URL=redis://redis:6379/0`; наружу публикуется только порт `${APP_PORT:-8080}:${PORT:-8000}`.
2. `redis` — `redis:7.4-alpine` с включённым сохранением на диск (`redis-server --appendonly yes`) и именованным томом `redis_data:/data`.
3. Для обоих сервисов добавлены `healthcheck`, `app` ждёт готовности `redis` (`condition: service_healthy`).

### Отчёт о проверках

#### 1. Сохранение значения `N = 3` после `docker compose down` и `docker compose up -d`

Команды:
```bash
docker compose up -d --build
curl -fsS -X POST http://127.0.0.1:8080/increment
curl -fsS -X POST http://127.0.0.1:8080/increment
curl -fsS -X POST http://127.0.0.1:8080/increment

docker compose down
docker compose up -d
curl -fsS http://127.0.0.1:8080/
```

Результат:
```text
{"greeting": "Hello, Docker!", "count": 1, "hostname": "fb736dc0247a", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 2, "hostname": "fb736dc0247a", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 3, "hostname": "fb736dc0247a", "storage": "redis"}

# После docker compose down && docker compose up -d (новый контейнер d99dd51c58a1):
{"greeting": "Hello, Docker!", "count": 3, "hostname": "d99dd51c58a1", "storage": "redis"}
```

#### 2. Остановка Redis (`docker compose stop redis`)

Команды:
```bash
docker compose stop redis
curl -i -s http://127.0.0.1:8080/healthz
curl -i -s http://127.0.0.1:8080/readyz
curl -i -s -X POST http://127.0.0.1:8080/increment
```

Результат:
```text
-- /healthz --
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:37 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 19
Cache-Control: no-store

{"status": "alive"}

-- /readyz --
HTTP/1.0 503 Service Unavailable
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:41 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 32
Cache-Control: no-store

{"error": "storage_unavailable"}

-- POST /increment --
HTTP/1.0 503 Service Unavailable
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:45 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 32
Cache-Control: no-store

{"error": "storage_unavailable"}
```

#### 3. Повторный запуск Redis (`docker compose start redis`)

Команды:
```bash
docker compose start redis
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/
curl -fsS -X POST http://127.0.0.1:8080/increment
docker compose down -v
```

Результат (без перезапуска контейнера `app`, `hostname` остался `d99dd51c58a1`):
```text
{"status": "ready", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 3, "hostname": "d99dd51c58a1", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 4, "hostname": "d99dd51c58a1", "storage": "redis"}
```

---

## 4. На 10 баллов — ограничения процесса и автоматическая проверка восстановления

### Ограничения сервиса `app`

- **Непривилегированный пользователь (`UID != 0`):** в `Dockerfile` создан пользователь с UID `1000` (`USER 1000:1000`), в `compose.yaml` задано `user: "1000:1000"`.
- **Корневая ФС только для чтения:** `read_only: true`.
- **Лимиты ресурсов:** память до `256 MiB` (`268435456` байт) и процессор до `1.0 CPU` (`1000000000` нано-CPU).

Проверка ограничений через `docker inspect`:
```text
$ docker inspect hw3_counter-app-1 --format "User={{.Config.User}} ReadOnly={{.HostConfig.ReadonlyRootfs}} Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}}"
User=1000:1000 ReadOnly=true Memory=268435456 NanoCpus=1000000000
```

### Автоматический сценарий проверки

Сценарий реализован в двух вариантах:
- `./scripts/check.sh` (Bash, требует только `docker`, `docker compose` и `curl`; упаковка резервной копии делается внутри временного контейнера `redis:7.4-alpine`)
- `python scripts/check.py` (Python 3)

Оба скрипта используют уникальное имя проекта Compose на базе PID процесса, не используют фиксированные `container_name` и общие volumes, задают тайм-ауты на ожидание и HTTP-запросы, сообщают этап при ошибке и удаляют свои тестовые ресурсы через `trap` / `finally`.

### Два успешных запуска подряд (`./scripts/check.sh`)

```text
=== CHECK.SH RUN 1 ===
==> 1. Создание тестового Compose-проекта и ожидание готовности
...
    Сервис готов (GET /readyz -> 200)
==> 2. Проверка начального счётчика (0) и выполнение 3 запросов POST /increment
    Начальное значение счётчика: 0
    POST /increment #1 -> count=1
    POST /increment #2 -> count=2
    POST /increment #3 -> count=3
    Текущее значение счётчика подтверждено: 3
==> 3. Пересоздание контейнера приложения и проверка сохранения счётчика
    После пересоздания app значение счётчика сохранилось: 3
==> 4. Проверка отключения и повторного запуска Redis
    При остановленном Redis: /healthz=200, /readyz=503, POST /increment=503
    После запуска Redis без перезапуска app: GET / -> 3, POST /increment -> 4
==> 5. Создание согласованной резервной копии данных Redis
    Резервная копия создана: backups/redis_backup_hw3_test_233.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_233 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_233_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_233, hw3_test_233_restore)...
RUN 1 EXIT: 0

=== CHECK.SH RUN 2 ===
==> 1. Создание тестового Compose-проекта и ожидание готовности
...
    Сервис готов (GET /readyz -> 200)
==> 2. Проверка начального счётчика (0) и выполнение 3 запросов POST /increment
    Начальное значение счётчика: 0
    POST /increment #1 -> count=1
    POST /increment #2 -> count=2
    POST /increment #3 -> count=3
    Текущее значение счётчика подтверждено: 3
==> 3. Пересоздание контейнера приложения и проверка сохранения счётчика
    После пересоздания app значение счётчика сохранилось: 3
==> 4. Проверка отключения и повторного запуска Redis
    При остановленном Redis: /healthz=200, /readyz=503, POST /increment=503
    После запуска Redis без перезапуска app: GET / -> 3, POST /increment -> 4
==> 5. Создание согласованной резервной копии данных Redis
    Резервная копия создана: backups/redis_backup_hw3_test_1378.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_1378 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_1378_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_1378, hw3_test_1378_restore)...
RUN 2 EXIT: 0
```

### Два успешных запуска подряд (`python scripts/check.py`)

```text
==> 1. Создание тестового Compose-проекта и ожидание готовности
    Сервис готов (GET /readyz -> 200)
==> 2. Проверка начального счётчика (0) и выполнение 3 запросов POST /increment
    Начальное значение счётчика: 0
    POST /increment #1 -> count=1
    POST /increment #2 -> count=2
    POST /increment #3 -> count=3
    Текущее значение счётчика подтверждено: 3
==> 3. Пересоздание контейнера приложения и проверка сохранения счётчика
    После пересоздания app значение счётчика сохранилось: 3
==> 4. Проверка отключения и повторного запуска Redis
    При остановленном Redis: /healthz=200, /readyz=503, POST /increment=503
    После запуска Redis без перезапуска app: GET / -> 3, POST /increment -> 4
==> 5. Создание согласованной резервной копии данных Redis
    Резервная копия создана: backups/redis_backup_hw3_test_16132.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_16132 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_16132_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_16132, hw3_test_16132_restore)...
==> 1. Создание тестового Compose-проекта и ожидание готовности
    Сервис готов (GET /readyz -> 200)
==> 2. Проверка начального счётчика (0) и выполнение 3 запросов POST /increment
    Начальное значение счётчика: 0
    POST /increment #1 -> count=1
    POST /increment #2 -> count=2
    POST /increment #3 -> count=3
    Текущее значение счётчика подтверждено: 3
==> 3. Пересоздание контейнера приложения и проверка сохранения счётчика
    После пересоздания app значение счётчика сохранилось: 3
==> 4. Проверка отключения и повторного запуска Redis
    При остановленном Redis: /healthz=200, /readyz=503, POST /increment=503
    После запуска Redis без перезапуска app: GET / -> 3, POST /increment -> 4
==> 5. Создание согласованной резервной копии данных Redis
    Резервная копия создана: backups/redis_backup_hw3_test_18172.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_18172 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_18172_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_18172, hw3_test_18172_restore)...
```
