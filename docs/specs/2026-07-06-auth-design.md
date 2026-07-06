# Спек: Аутентификация SOAR API

**Версия:** 1.0  
**Дата:** 2026-07-06  
**Контекст:** внешний Vue.js SPA (SOC Core) и M2M-клиент (SOC Core backend) работают через SOAR API

---

## 1. Два механизма аутентификации

### 1.1 JWT — для SPA-пользователей

```
POST /auth/login    →  { access_token, refresh_token }
POST /auth/refresh  →  { access_token, refresh_token }   # rotation
POST /auth/logout   →  revoke refresh_token
GET  /auth/me       →  { id, username, role }
```

- **Access token**: JWT HS256, TTL **30 мин**  
  Payload: `{ sub: user_id, role, type: "user", exp }`
- **Refresh token**: opaque UUID, TTL **7 дней**  
  Хранится хешем SHA-256 в PostgreSQL. Ротируется при каждом `/auth/refresh`.
- SPA хранит токены в `localStorage` (кросс-доменный SPA без shared TLS)

### 1.2 API Key — для M2M (SOC Core backend)

```
Authorization: Bearer soar_<32-byte-hex>
```

- Статический долгоживущий токен
- Хранится как `SHA-256(key)` в таблице `api_keys`
- Создаётся через `POST /auth/keys` (только `admin`)
- Маппится на роль `service`
- Поле `last_used_at` обновляется при каждом запросе

**Middleware**: `Authorization: Bearer <token>` → пробуем декодировать как JWT, если невалидный — ищем в `api_keys` по хешу.

---

## 2. Роли (RBAC)

| Роль | Назначение |
|---|---|
| `admin` | Полный доступ. SOAR-администратор |
| `analyst` | Чтение + запуск workflow/jobs |
| `viewer` | Read-only |
| `service` | M2M: SOC Core backend |

### Матрица доступа

| Endpoint | viewer | analyst | service | admin |
|---|---|---|---|---|
| `GET /status` | ✓ | ✓ | ✓ | ✓ |
| `GET /workflows`, `GET /jobs`, `GET /logs/*` | ✓ | ✓ | ✓ | ✓ |
| `POST /jobs` | — | ✓ | ✓ | ✓ |
| `POST /workflows/*/enable\|disable` | — | ✓ | — | ✓ |
| `POST /webhooks/*` | — | — | ✓ | ✓ |
| `GET /actions`, `GET /connectors` | ✓ | ✓ | — | ✓ |
| `PUT /workflows/*/code`, `PUT /connectors/*` | — | — | — | ✓ |
| `DELETE /workflows/*/code` | — | — | — | ✓ |
| `POST /transfer/export\|import` | — | — | — | ✓ |
| `POST /auth/keys` | — | — | — | ✓ |
| `GET /auth/keys` | — | — | — | ✓ |
| `DELETE /auth/keys/{id}` | — | — | — | ✓ |

> **Webhooks**: существующий `X-Webhook-Token` per-workflow сохраняется как альтернативный
> путь для входящих вебхуков (SOC Core fire-and-forget → SOAR). Параллельно с Bearer.

---

## 3. PostgreSQL схема

```sql
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL,     -- bcrypt cost=12
    role          VARCHAR(32) NOT NULL DEFAULT 'analyst',
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL,        -- SHA-256(raw_token), hex
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ                  -- null = активен
);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash)
    WHERE revoked_at IS NULL;

CREATE TABLE api_keys (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(128) NOT NULL,      -- "soc-core-service"
    key_prefix   VARCHAR(12) NOT NULL,       -- "soar_a1b2c3" для показа в UI
    key_hash     VARCHAR(64) NOT NULL,       -- SHA-256(full_key), hex
    role         VARCHAR(32) NOT NULL DEFAULT 'service',
    is_active    BOOLEAN NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ                 -- null = бессрочный
);
CREATE UNIQUE INDEX idx_api_keys_hash ON api_keys(key_hash);
```

---

## 4. Конфиг (`config.yaml`)

```yaml
auth:
  secret_key: ""              # JWT-секрет, мин. 32 символа — ОБЯЗАТЕЛЕН
  access_token_ttl: 1800      # секунды (30 мин)
  refresh_token_ttl: 604800   # секунды (7 дней)
  algorithm: HS256
  cors_origins:               # список разрешённых origins вместо "*"
    - "http://localhost:3000"

database:
  url: "postgresql+asyncpg://soar:pass@localhost:5432/soar"
  pool_size: 10
  max_overflow: 20
```

---

## 5. Структура новых файлов

```
orchestrator/
├── auth/
│   ├── __init__.py
│   ├── models.py        # SQLAlchemy ORM: User, RefreshToken, ApiKey
│   ├── schemas.py       # Pydantic: LoginRequest, TokenResponse, UserOut, ApiKeyOut
│   ├── service.py       # verify_password, create_tokens, rotate_refresh, revoke
│   ├── dependencies.py  # get_current_user, require_role(...)
│   └── router.py        # /auth/* эндпоинты
├── db/
│   ├── __init__.py
│   ├── base.py          # DeclarativeBase
│   ├── session.py       # AsyncSessionLocal, get_db dependency
│   └── migrations/      # Alembic: env.py + versions/
```

---

## 6. Изменения в существующих файлах

### `orchestrator/config.py`
Добавить `AuthConfig` и `DatabaseConfig` в `OrchestratorConfig`.

### `orchestrator/main.py`
- CORS: `allow_origins=config.auth.cors_origins`, `allow_credentials=True`
- Rate limiter: `/auth/login` — отдельный лимит 5 req/мин per IP (брутфорс-защита)
- Подключить `auth_router`
- При старте — проверить `secret_key` (ValueError если пуст)

### Все API-роутеры (`orchestrator/api/*.py`)
Добавить `Depends(require_role(...))` к каждому эндпоинту согласно матрице доступа (§2).

---

## 7. Зависимости

```toml
# pyproject.toml / requirements
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
alembic>=1.13
```

---

## 8. CLI: создание первого admin

```bash
python -m orchestrator.auth.cli create-user --username admin --role admin
# выведет: созданный пользователь + запрос пароля интерактивно
```

---

## 9. Что не меняется

- `POST /webhooks/{workflow_name}` — `X-Webhook-Token` per-workflow работает как есть
- Вся бизнес-логика workflow/jobs/connectors — без изменений, добавляется только `Depends`
- SOAR не пишет в PostgreSQL SOC Core напрямую (контракт §2)

---

## 10. Открытые вопросы

1. **Первый admin**: через CLI (§8) или seed-миграция с паролем из env?
2. **Refresh token**: тело ответа или `httpOnly` cookie? Cookie безопаснее, но требует HTTPS + `SameSite=None` для кросс-доменного SPA.
3. **Webhook `/webhooks/irp-events`**: оставить на per-workflow токене или унифицировать под `service` API key?
