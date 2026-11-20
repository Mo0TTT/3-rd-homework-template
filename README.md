# Домашнее задание №3 по Docker

Упаковка учебного веб-приложения со счётчиком в Docker и настройка запуска через Docker Compose с отдельным хранилищем Redis, ограничениями безопасности и автоматическим сценарием проверки восстановления.

Исходный код приложения в каталоге `app/` не изменялся.

---

## Содержимое репозитория

| Файл / каталог | Назначение |
| --- | --- |
| `app/` | Исходный код сервиса (`app.py`, `requirements.txt`, `README.md` — без изменений) |
| `Dockerfile` | Сборка образа приложения на базе `python:3.13-slim` от непривилегированного пользователя (`UID 1000`) |
| `.dockerignore` | Исключение лишних файлов и артефактов из контекста сборки |
| `compose.yaml` | Конфигурация Docker Compose (`app` + `redis`, именованный том, `healthcheck`, лимиты ресурсов и `read_only`) |
| `.env.example` | Пример файла с настраиваемыми переменными окружения |
| `scripts/check.sh` | Автоматический Bash-сценарий проверки работы и восстановления из резервной копии |
| `scripts/check.py` | Автоматический Python-сценарий проверки работы и восстановления из резервной копии |

---

## Быстрый старт (Docker Compose)

```bash
cp .env.example .env
docker compose up -d --build
```

Проверка эндпоинтов после запуска:

```bash
curl -fsS http://127.0.0.1:8080/
curl -fsS -X POST http://127.0.0.1:8080/increment
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

Остановка проекта:

```bash
docker compose down
```

---

## 1. Уровень на 4 балла — один контейнер

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

```json
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

## 2. Уровень на 6 баллов — Compose и сохранение данных

Настройки вынесены в переменные окружения. Пример конфигурации находится в файле `.env.example`:

```dotenv
COMPOSE_PROJECT_NAME=hw3_counter
APP_PORT=8080
PORT=8000
GREETING=Hello, Docker!
STORAGE=redis
DATA_FILE=/data/counter.db
REDIS_URL=redis://redis:6379/0
```

- `APP_PORT` — порт приложения, публикуемый на хост-машине (`8080` по умолчанию).
- `PORT` — порт внутри контейнера (`8000` по умолчанию).
- `GREETING` — текст приветствия в JSON-ответе.
- Именованный том `redis_data` сохраняет состояние счётчика при удалении и повторном создании контейнеров (`docker compose down` и `docker compose up -d`).

---

## 3. Уровень на 8 баллов — отдельное хранилище Redis

В `compose.yaml` описаны два сервиса:

1. **`app`** — собирается из `Dockerfile`, работает с переменными `STORAGE=redis` и `REDIS_URL=redis://redis:6379/0` (подключение по имени сервиса `redis`). На хосте публикуется только порт приложения `${APP_PORT:-8080}:${PORT:-8000}`.
2. **`redis`** — образ `redis:7.4-alpine` с включённой записью данных на диск (`redis-server --appendonly yes`) и подключённым именованным томом `redis_data:/data`.
3. **Готовность** — для обоих сервисов настроены `healthcheck`; сервис `app` запускается после перехода `redis` в состояние `service_healthy`.

### Отчёт о проверках

#### Проверка 1. Сохранение значения `N = 3` после `docker compose down` и `up -d`

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

```json
{"greeting": "Hello, Docker!", "count": 1, "hostname": "fb736dc0247a", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 2, "hostname": "fb736dc0247a", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 3, "hostname": "fb736dc0247a", "storage": "redis"}
```

После `docker compose down` и повторного `docker compose up -d` (в новом контейнере `d99dd51c58a1`):

```json
{"greeting": "Hello, Docker!", "count": 3, "hostname": "d99dd51c58a1", "storage": "redis"}
```

#### Проверка 2. Остановка Redis (`docker compose stop redis`)

Команды:

```bash
docker compose stop redis
curl -i -s http://127.0.0.1:8080/healthz
curl -i -s http://127.0.0.1:8080/readyz
curl -i -s -X POST http://127.0.0.1:8080/increment
```

Результат (`GET /healthz` возвращает **200**, а `GET /readyz` и `POST /increment` — **503**):

```http
HTTP/1.0 200 OK
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:37 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 19
Cache-Control: no-store

{"status": "alive"}
```

```http
HTTP/1.0 503 Service Unavailable
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:41 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 32
Cache-Control: no-store

{"error": "storage_unavailable"}
```

```http
HTTP/1.0 503 Service Unavailable
Server: BaseHTTP/0.6 Python/3.13.18
Date: Fri, 13 Nov 2026 20:03:45 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 32
Cache-Control: no-store

{"error": "storage_unavailable"}
```

#### Проверка 3. Повторный запуск Redis (`docker compose start redis`)

Команды:

```bash
docker compose start redis
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/
curl -fsS -X POST http://127.0.0.1:8080/increment
docker compose down -v
```

Результат (без перезапуска `app` возвращается `N = 3`, следующий `POST /increment` возвращает `N + 1 = 4`):

```json
{"status": "ready", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 3, "hostname": "d99dd51c58a1", "storage": "redis"}
{"greeting": "Hello, Docker!", "count": 4, "hostname": "d99dd51c58a1", "storage": "redis"}
```

---

## 4. Уровень на 10 баллов — ограничения процесса и проверка восстановления

### Ограничения контейнера `app`

- **UID, отличный от 0:** пользователь `1000:1000` (`USER 1000:1000` в `Dockerfile` и `user: "1000:1000"` в `compose.yaml`).
- **Корневая файловая система только для чтения:** `read_only: true`.
- **Лимиты ресурсов:** не более **256 MiB RAM** (`mem_limit: 256m`) и **1 ядра CPU** (`cpus: 1.0`).

Проверка применённых ограничений через `docker inspect`:

```bash
docker inspect hw3_counter-app-1 --format "User={{.Config.User}} ReadOnly={{.HostConfig.ReadonlyRootfs}} Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}}"
```

```text
User=1000:1000 ReadOnly=true Memory=268435456 NanoCpus=1000000000
```

### Автоматический сценарий проверки

Сценарий доступен в двух вариантах:

```bash
./scripts/check.sh
# или
python scripts/check.py
```

Что делает скрипт без ручных действий:
1. Поднимает изолированный тестовый проект Compose с уникальным именем (`hw3_test_<PID>`) и пустым хранилищем, дожидается `GET /readyz -> 200` с тайм-аутом.
2. Проверяет начальное значение счётчика `0`, выполняет `N = 3` запросов `POST /increment` и проверяет результат `3`.
3. Пересоздаёт только контейнер `app` (`up -d --force-recreate --no-deps app`) и убеждается, что счётчик сохранился (`3`).
4. Останавливает `redis`, проверяет коды ответа (`/healthz -> 200`, `/readyz -> 503`, `POST /increment -> 503`), запускает `redis` обратно и проверяет, что без перезапуска `app` запрос `GET /` возвращает `3`, а `POST /increment` — `4`.
5. Штатно останавливает `app` и `redis`, создаёт согласованную резервную копию тома Redis с сохранением структуры и прав (`tar -czpf`) во внешний файл.
6. Удаляет исходный тестовый проект вместе с томами через `docker compose down -v`.
7. Восстанавливает данные из резервной копии в чистый том и проверяет, что приложение возвращает сохранённое значение счётчика (`4`), после чего через `trap` / `finally` очищает все тестовые ресурсы.

### Вывод двух успешных запусков подряд (`./scripts/check.sh`)

#### Запуск 1

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
    Резервная копия создана: backups/redis_backup_hw3_test_233.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_233 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_233_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_233, hw3_test_233_restore)...
```

#### Запуск 2

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
    Резервная копия создана: backups/redis_backup_hw3_test_1378.tar.gz
==> 6. Удаление исходного тестового проекта вместе с volumes (down -v)
    Проект hw3_test_1378 и его volumes удалены
==> 7. Восстановление из резервной копии в новый проект и проверка счётчика
    Данные успешно восстановлены в hw3_test_1378_restore: count=4
==> Все проверки успешно пройдены!
[cleanup] Очистка тестовых ресурсов (hw3_test_1378, hw3_test_1378_restore)...
```
