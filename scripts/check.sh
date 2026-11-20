#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

PROJECT_NAME="hw3_test_$$"
RESTORE_PROJECT="${PROJECT_NAME}_restore"
export APP_PORT="${TEST_APP_PORT:-18080}"
export PORT="8000"
export GREETING="Test Greeting"
export STORAGE="redis"
export REDIS_URL="redis://redis:6379/0"

BASE_URL="http://127.0.0.1:${APP_PORT}"
N=3
BACKUP_DIR="$(pwd)/backups"
BACKUP_FILE="${BACKUP_DIR}/redis_backup_${PROJECT_NAME}.tar.gz"
STAGE="Инициализация"

cleanup() {
    echo "[cleanup] Очистка тестовых ресурсов (${PROJECT_NAME}, ${RESTORE_PROJECT})..."
    docker compose -p "$PROJECT_NAME" down -v --remove-orphans >/dev/null 2>&1 || true
    docker compose -p "$RESTORE_PROJECT" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "$BACKUP_FILE"
    rmdir "$BACKUP_DIR" >/dev/null 2>&1 || true
}

on_error() {
    local exit_code=$?
    echo "[ОШИБКА] Проверка прервана на этапе: ${STAGE} (код: ${exit_code})" >&2
    exit "$exit_code"
}

trap on_error ERR
trap cleanup EXIT

get_status() {
    local method="$1"
    local path="$2"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 5 -X "$method" "${BASE_URL}${path}") || code="000"
    echo "$code"
}

get_count() {
    local method="$1"
    local path="$2"
    local body
    body=$(curl -fsS --connect-timeout 2 --max-time 5 -X "$method" "${BASE_URL}${path}")
    echo "$body" | grep -o '"count": *[0-9]*' | grep -o '[0-9]*'
}

wait_for_ready() {
    local timeout_sec=30
    local elapsed=0
    while [ "$elapsed" -lt "$timeout_sec" ]; do
        local code
        code=$(get_status GET "/readyz")
        if [ "$code" = "200" ]; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    echo "Тайм-аут ожидания готовности сервиса (${timeout_sec} сек)" >&2
    return 1
}

STAGE="1. Создание тестового Compose-проекта и ожидание готовности"
echo "==> ${STAGE}"
docker compose -p "$PROJECT_NAME" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -p "$PROJECT_NAME" up -d --build
wait_for_ready
echo "    Сервис готов (GET /readyz -> 200)"

STAGE="2. Проверка начального счётчика (0) и выполнение ${N} запросов POST /increment"
echo "==> ${STAGE}"
initial_count=$(get_count GET "/")
[ "$initial_count" = "0" ]
echo "    Начальное значение счётчика: ${initial_count}"

for i in $(seq 1 "$N"); do
    c=$(get_count POST "/increment")
    echo "    POST /increment #${i} -> count=${c}"
done

current_count=$(get_count GET "/")
[ "$current_count" = "$N" ]
echo "    Текущее значение счётчика подтверждено: ${current_count}"

STAGE="3. Пересоздание контейнера приложения и проверка сохранения счётчика"
echo "==> ${STAGE}"
docker compose -p "$PROJECT_NAME" up -d --force-recreate --no-deps app
wait_for_ready
after_recreate=$(get_count GET "/")
[ "$after_recreate" = "$N" ]
echo "    После пересоздания app значение счётчика сохранилось: ${after_recreate}"

STAGE="4. Проверка отключения и повторного запуска Redis"
echo "==> ${STAGE}"
docker compose -p "$PROJECT_NAME" stop redis

code_health=$(get_status GET "/healthz")
code_ready=$(get_status GET "/readyz")
code_inc=$(get_status POST "/increment")
echo "    При остановленном Redis: /healthz=${code_health}, /readyz=${code_ready}, POST /increment=${code_inc}"
[ "$code_health" = "200" ]
[ "$code_ready" = "503" ]
[ "$code_inc" = "503" ]

docker compose -p "$PROJECT_NAME" start redis
wait_for_ready

count_after_redis=$(get_count GET "/")
[ "$count_after_redis" = "$N" ]
expected_next=$((N + 1))
count_next=$(get_count POST "/increment")
[ "$count_next" = "$expected_next" ]
echo "    После запуска Redis без перезапуска app: GET / -> ${count_after_redis}, POST /increment -> ${count_next}"

STAGE="5. Создание согласованной резервной копии данных Redis"
echo "==> ${STAGE}"
mkdir -p "$BACKUP_DIR"
docker compose -p "$PROJECT_NAME" stop app redis
MSYS_NO_PATHCONV=1 docker run --rm \
    -v "${PROJECT_NAME}_redis_data:/data:ro" \
    redis:7.4-alpine \
    tar -czpf - -C /data . > "$BACKUP_FILE"
[ -s "$BACKUP_FILE" ]
echo "    Резервная копия создана: backups/redis_backup_${PROJECT_NAME}.tar.gz"

STAGE="6. Удаление исходного тестового проекта вместе с volumes (down -v)"
echo "==> ${STAGE}"
docker compose -p "$PROJECT_NAME" down -v
echo "    Проект ${PROJECT_NAME} и его volumes удалены"

STAGE="7. Восстановление из резервной копии в новый проект и проверка счётчика"
echo "==> ${STAGE}"
docker compose -p "$RESTORE_PROJECT" up --no-start
MSYS_NO_PATHCONV=1 docker run --rm -i \
    -v "${RESTORE_PROJECT}_redis_data:/data" \
    redis:7.4-alpine \
    tar -xzpf - -C /data < "$BACKUP_FILE"
docker compose -p "$RESTORE_PROJECT" up -d
wait_for_ready

restored_count=$(get_count GET "/")
[ "$restored_count" = "$expected_next" ]
echo "    Данные успешно восстановлены в ${RESTORE_PROJECT}: count=${restored_count}"

echo "==> Все проверки успешно пройдены!"
