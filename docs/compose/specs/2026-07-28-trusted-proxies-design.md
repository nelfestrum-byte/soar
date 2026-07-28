# `server.trusted_proxies` for nginx-fronted Deploys (B4)

> Реализует B4 из `docs/concepts/BAGFIX_PLAN.md`. Блокер пилота —
> `deploy/prod`/`deploy/stage` ставят nginx перед оркестратором, но не
> заполняют `server.trusted_proxies`, из-за чего весь трафик через nginx
> схлопывается в один `client_ip`.

## [S1] Problem

`resolve_client_ip()` (`orchestrator/core/net.py:4-18`) доверяет
`X-Real-IP`/`X-Forwarded-For` только если TCP-пир (`request.client.host`)
входит в `config.server.trusted_proxies` — списочное сравнение строк, без
CIDR. Дефолт — `[]` (`orchestrator/config.py:76`, `ServerConfig`).

`deploy/prod/nginx.conf:15-17` (и `/docs`, `/openapi.json`) уже
проставляет `X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto` на
`proxy_pass http://orchestrator:8000/`. Но ни
`deploy/prod/config.yaml.template`, ни `deploy/stage/config.yaml` не
объявляют `server: trusted_proxies:` вообще — Pydantic-дефолт `[]`
побеждает молча. Итог: пир, с которым оркестратор физически видит
TCP-соединение — контейнер `ui` (в нём же живёт nginx, см.
`deploy/prod/docker-compose.yml` — сервис `ui`, `nginx.conf` копируется в
его образ), — никогда не совпадает с пустым списком, `X-Real-IP`
игнорируется всегда, `client_ip` = адрес контейнера `ui` на docker-сети
для абсолютно всех настоящих клиентов.

Последствия (уже описаны в `orchestrator/main.py`):
- логин-лимитер 5 req/60s (`main.py:267,279-282`) — глобальный по
  единственному наблюдаемому IP → 5 неудачных попыток входа от **любого**
  пользователя блокируют логин **всем** на 60 секунд. Тривиальный
  постоянный DoS аутентификации без аутентификации самого атакующего.
- общий rate-limit 120 req/60s — тоже общий лимит на весь трафик через
  nginx, не per-client.
- `AuditLog.client_ip` (`orchestrator/audit/service.py:35`) одинаков во
  всех записях — атрибуция по IP невозможна, обесценивает audit trail,
  который ведётся под комплаенс.

Отдельная причина, почему просто скопировать `["127.0.0.1"]` из
`orchestrator/config.yaml:28` (комментарий: "when running behind nginx in
**same container**") не работает: в `deploy/prod`/`deploy/stage` nginx и
оркестратор — **разные** контейнеры (`ui` и `orchestrator`), соединённые
через docker bridge-сеть, а не через loopback одного контейнера. Пир —
IP контейнера `ui` на этой сети, не `127.0.0.1`.

## [S2] Solution

`resolve_client_ip()` не меняется — точечное сравнение с
`trusted_proxies` уже корректно работает, если список содержит верный
IP (см. существующее покрытие в
`tests/orchestrator/api/test_rate_limiter.py`). Проблема полностью в
том, что этот IP никогда не задавался для многоконтейнерного деплоя, и в
том, что дефолтная docker bridge-сеть не даёт **гарантированного**
статического IP контейнеру `ui` (назначение по порядку создания —
исторически стабильно на практике, но не документированная гарантия
Docker; полагаться на это для блокера пилота неприемлемо).

Фикс — закрепить IP контейнера `ui` детерминированно через
пользовательскую docker-сеть с фиксированной подсетью и явным
`ipv4_address`, затем указать этот же IP в `trusted_proxies`:

1. **`deploy/prod/docker-compose.yml`** — добавить сеть с IPAM-подсетью,
   подключить `ui` к ней со статическим адресом; остальные сервисы
   (`redis`/`postgres`/`orchestrator`) остаются на той же сети (нужны друг
   другу), но без явного `ipv4_address` — их адрес не участвует в доверии:

   ```yaml
   networks:
     soar-net:
       ipam:
         config:
           - subnet: 172.28.0.0/24

   services:
     ...
     ui:
       ...
       networks:
         soar-net:
           ipv4_address: 172.28.0.10
     # остальные сервисы: networks: [soar-net] без ipv4_address
   ```

   (Все сервисы должны явно перечислить `networks: [soar-net]`, иначе
   compose создаст для них отдельную дефолтную сеть — стандартное
   поведение при добавлении top-level `networks:` в файл, где раньше его
   не было.)

2. **`deploy/prod/config.yaml.template`** — новая секция с тем же IP и
   комментарием, откуда он взялся:

   ```yaml
   server:
     # IP контейнера ui (nginx) на docker-сети soar-net — см.
     # deploy/prod/docker-compose.yml networks.soar-net.ipam и
     # ui.networks.soar-net.ipv4_address. Держать оба места в синхроне при
     # правке сети. Без этого resolve_client_ip() видит IP nginx как
     # client_ip для всего трафика — глобальный login-rate-limit и
     # бесполезный AuditLog.client_ip, см. B4 в BAGFIX_PLAN.md.
     trusted_proxies: ["172.28.0.10"]
   ```

3. **`deploy/stage/config.yaml`** — то же самое, синхронизировано со
   своей копией `docker-compose.yml`. `deploy/stage/Dockerfile.ui`
   собирает тот же `nginx:alpine` с `deploy/stage/nginx.conf` — идентичный
   паттерн reverse-proxy к `orchestrator:8000`, просто отдельный
   compose-профиль (`build:` вместо `image:`). Тот же networks-блок,
   тот же статический IP на `ui`.

4. **`deploy/prod/README.md`** — пункт чеклиста рядом с существующим
   напоминанием про `auth.cors_origins` (P17, `README.md:35-39`):

   ```markdown
   Проверить `server.trusted_proxies` в `config.yaml` — должен содержать
   IP контейнера `ui` на `soar-net` (см. `docker-compose.yml`). Не менять
   один без другого: рассинхрон делает rate-limiter/audit либо снова
   глобальным (если IP не совпал), либо доверяющим не тому пиру (если
   подсеть менялась вручную).
   ```

## [S3] Альтернативы, рассмотренные и отклонённые

- **Держать nginx и оркестратор в одном контейнере** (как подсказывает
  старый комментарий в `orchestrator/config.yaml:28`) — устранило бы саму
  проблему (`127.0.0.1`, гарантированно стабильный loopback), но требует
  пересобрать образы `soar-ui`/`soar-orchestrator` в один, ломает текущую
  модель `soarctl package`/`docker compose` (раздельные health check,
  раздельное масштабирование). Слишком дорого для точечного фикса.
- **Доверять всей подсети docker-сети** (`trusted_proxies` как CIDR,
  например `172.28.0.0/24`), а не одному IP — упростило бы конфиг (не
  нужен статический `ipv4_address`), но `resolve_client_ip()` сейчас
  делает точное строковое сравнение, не CIDR-матчинг; и что важнее —
  порт `orchestrator` также публикуется напрямую на хост
  (`docker-compose.yml`, `ports: ["8000:8000"]`, см. M11) — если бы
  оркестратор доверял всей подсети `redis`/`postgres`-контейнеров тоже,
  а не только `ui`, это расширяет доверенную поверхность без необходимости
  (ни один из этих сервисов не должен подделывать client IP). Точный IP
  одного нужного пира — более узкая и явная граница доверия.
- **CIDR-поддержка в `resolve_client_ip()`** (код, не конфиг) — решило бы
  и предыдущий пункт, и общую хрупкость к пересозданию сети с другим
  IP-планом. Не выбрано для этого трека, т.к. BAGFIX_PLAN явно
  классифицирует B4 как конфигурационный фикс; можно поднять отдельной
  спекой, если статический IP на практике окажется недостаточно
  устойчивым (например при миграции на Swarm/k8s, где IP пода не
  статичен по другой причине — там нужен другой механизм целиком,
  например trusted network namespace, не этот список).

## [S4] Testing Strategy

- `tests/orchestrator/core/test_net.py` (или где лежит текущее покрытие
  `resolve_client_ip`) — подтвердить, что уже существующий тест "берёт
  `X-Real-IP` только когда пир в `trusted_proxies`" покрывает и точный
  IP-матчинг (не только `127.0.0.1`) — при необходимости добавить кейс с
  IP вида `172.28.0.10`, чтобы явно не полагаться на то, что `127.0.0.1`
  как тестовый пример — единственный protected path.
- Ручная/deploy-проверка (не unit-тест, фиксируется в плане как
  верификационный шаг, не в pytest): `docker compose up` с новым
  `docker-compose.yml`, `docker inspect soar-ui` → `NetworkSettings.
  Networks.soar-net.IPAddress` совпадает с `trusted_proxies` в
  примонтированном `config.yaml`; повторить `docker compose up` (рестарт
  без пересоздания сети) → IP не меняется (статический `ipv4_address`
  переживает рестарт контейнера, в отличие от дефолтной динамической
  аллокации).

## [S5] Success Criteria

- [ ] `deploy/prod/docker-compose.yml`/`deploy/stage/docker-compose.yml` —
      `ui` имеет статический IP на выделенной подсети
- [ ] `deploy/prod/config.yaml.template`/`deploy/stage/config.yaml` —
      `server.trusted_proxies` содержит этот же IP, с комментарием,
      объясняющим происхождение и синхронизацию с compose-файлом
- [ ] `deploy/prod/README.md` — пункт чеклиста запуска рядом с
      `auth.cors_origins`
- [ ] Логин-лимитер и общий rate-limit становятся per-real-client-IP на
      деплое через nginx, не глобальными
- [ ] `AuditLog.client_ip` отражает реальный IP клиента, не IP `ui`
- [ ] `resolve_client_ip()` не меняется — фикс полностью в конфиге деплоя
