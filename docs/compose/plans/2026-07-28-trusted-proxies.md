# Plan: `server.trusted_proxies` for nginx-fronted deploys (B4)

Спека: `docs/compose/specs/2026-07-28-trusted-proxies-design.md`

## Tests first

- [x] Добавить `tests/orchestrator/core/test_net.py` с прямым (не через
      ASGI-приложение) юнит-тестом `resolve_client_ip()`: сконструировать
      mock `Request` с `client.host = "172.28.0.10"` и
      `app.state.config.server.trusted_proxies = ["172.28.0.10"]`,
      подтвердить, что `X-Real-IP` используется — доказывает точный
      IP-матчинг работает не только для `127.0.0.1` (единственный peer,
      который может представить `httpx.ASGITransport` в существующих
      тестах `test_rate_limiter.py`/`test_access_log_middleware.py`).
      Добавить также негативный кейс: тот же `client.host`, но
      `trusted_proxies=["10.0.0.1"]` (не совпадает) → `X-Real-IP`
      игнорируется, возвращается TCP-пир.
- [x] Запустить новый тест — должен пройти на текущем, неизменённом
      `resolve_client_ip()` (спека не меняет код, только подтверждает
      покрытие — это не test-first в смысле "падает до фикса", фикс тут
      конфигурационный, а не кодовый).

## Implementation (config only, per spec S2)

- [x] `deploy/prod/docker-compose.yml` — добавить top-level `networks:`
      с `soar-net` и IPAM `subnet: 172.28.0.0/24`; каждый сервис
      (`redis`, `postgres`, `orchestrator`, `ui`) получает
      `networks: [soar-net]`; `ui` дополнительно закрепляет
      `ipv4_address: 172.28.0.10` на этой сети.
- [x] `deploy/stage/docker-compose.yml` — то же самое (тот же subnet и
      тот же статический IP на `ui`, синхронно с prod).
- [x] `deploy/prod/config.yaml.template` — секция `server:` с
      `trusted_proxies: ["172.28.0.10"]` и комментарием, объясняющим
      происхождение IP и необходимость держать его в синхроне с
      `docker-compose.yml` (см. спека S2.2).
- [x] `deploy/stage/config.yaml` — та же секция `server:`.
- [x] `deploy/prod/README.md` — пункт чеклиста про `server.trusted_proxies`
      рядом с существующим напоминанием про `auth.cors_origins`
      (см. спека S2.4 за точной формулировкой).

## Verification

- [x] `python -m pytest tests/orchestrator/core/test_net.py -v` — новые
      тесты зелёные.
- [x] `python -m pytest tests/orchestrator/api/test_rate_limiter.py
      tests/orchestrator/api/test_access_log_middleware.py -v` —
      существующее покрытие не сломано (код `resolve_client_ip()` не
      менялся).
- [x] Полный `python -m pytest tests/ -q` — единственный уже известный
      несвязанный фейл `tests/soar/tools/test_openapi.py::test_generate_config`,
      новых регрессий нет.
- [x] Ручная/deploy-проверка из спеки S4 (docker inspect на статический
      IP `ui`, стабильность IP после рестарта) — не выполнима в этой
      среде (нет доступа к `docker compose`), фиксируется в отчёте как
      manual/deploy-time шаг, не pytest.

## Report

- [x] Написать `docs/compose/reports/trusted-proxies.md` после
      завершения.
