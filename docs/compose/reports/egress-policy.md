# Report: egress-политика через конфиг

Spec: `docs/compose/specs/2026-08-06-egress-policy-design.md`
Plan: `docs/compose/plans/2026-08-06-egress-policy.md`

## Summary

Найдено на живом прогоне: попытка подключиться к SIEM на `192.168.1.51`
официальным `elasticsearch`-клиентом (мимо `http_client`, через `urllib3`)
падала с `PermissionError: egress to private address 192.168.1.51 blocked
by audit hook`. Разрешить это было нельзя нигде — ни в конфиге, ни в env,
ни в API.

Это была ошибка модели угроз (`ENTITY-MODEL.md`, решение 2), а не забытая
настройка: безусловный deny-private верен для SaaS (приватный диапазон —
чужая инфраструктура), но для он-прем SOC приватный диапазон — это вся
рабочая поверхность (SIEM, AD, FreeIPA, TrueConf). Реализован
настраиваемый allowlist поверх сегодняшнего deny-private, с двумя точками
enforcement, которые обязаны совпадать.

## Changes

### `soar/egress_policy.py` (новый)

`EgressPolicy` (`mode`, `allow: list[IPv4Network|IPv6Network]`) и `parse(cfg)`.
`is_allowed(ip)`: `observe` — всегда `True`; публичный адрес — всегда `True`;
приватный — только если попадает в `allow`. `_is_private_ip` (переехал из
`audit_hook.py`/`_net.py`, был продублирован побайтово) — теперь одна
реализация. `parse()` бросает `ValueError` на неизвестный `mode` или
непарсящийся CIDR/IP — без отката к пустому/deny-политике по умолчанию.

### `soar/audit_hook.py`

`install(policy)` захватывает политику в замыкание хука вместо чтения
глобала — контент не может её переписать (глобала для этого больше не
существует). `_handle(event, args, policy=None)` — `policy=None` даёт
сегодняшнее поведение (deny-private), нужно для обратной совместимости
существующих юнит-тестов, вызывающих `_handle` напрямую. Свой
`_is_private_ip` удалён.

### `soar/tools/_net.py`

Модуль-level `_policy` (дефолт — deny-private) + `set_policy(policy)`.
`_validate_external_url` консультируется с `_policy.is_allowed(...)` вместо
собственного `_is_private_ip`. Отдельная от хука копия политики — по
дизайну ([S2]): один и тот же конфиг, два независимых enforcement-объекта,
не общий мутируемый инстанс.

### `soar/runner.py`

Загрузка `config.yaml` (module-level, `yaml.safe_load`) переехала выше
`install_audit_hook()` — раньше хук ставился первым (под гейтом
`__name__ == "__main__"`), конфиг читался после, безусловно. Теперь: конфиг
→ (если `__main__`) хук с реальной политикой. `_build_http_client(config)`
парсит `config.get("egress", {})` и вызывает `_net.set_policy(...)` до
любого `*.init()` — оба enforcement-объекта получают политику из одного и
того же конфига, до того как контент успевает загрузиться. Малформед
`egress` бросает `ValueError` из `_build_http_client`, которая исполняется
безусловно на уровне модуля (не только под `__main__`) — падение громкое и
раньше, чем джоба успевает выполниться, независимо от того, реальный это
subprocess-запуск или прямой импорт модуля.

### `orchestrator/core/subprocess_runner.py::build_scoped_config`

`egress` копируется из `full_config` в scoped-конфиг тем же паттерном, что
уже есть для `http_client` — единственное место, пропуск которого дал бы
«настройка молча не применяется» (класс дефекта, на котором проект уже
горел 2026-07-29).

### `orchestrator/config.py`, `orchestrator/api/runtime.py`

Новый `EgressConfig` (`mode`, `allow`) в `OrchestratorConfig`. `GET /runtime`
отдаёт `egress: {mode, allow}` — читается ролью `agent` (та же `_RO`
группа, что и остальной ответ).

### `orchestrator/prompts/system_prompt.md`

Абзац в §6: egress ограничен на уровне платформы (любая библиотека, не
только `http_client`), проверять `GET /runtime` перед написанием коннектора
к внутренней системе, а не после первого падения джобы.

### Конфиги

`orchestrator/config.yaml`, `deploy/prod/config.yaml.template`,
`deploy/stage/config.yaml` — секция `egress` с комментарием про
`169.254.0.0/16` (cloud metadata endpoints). `deploy/prod/config.yaml`
(нетрекаемый локальный артефакт `soarctl init`) не тронут — не в git.

### Документация

`docs/concepts/ENTITY-MODEL.md` — решение 2 дополнено правкой 2026-08-06
(deny-private без исключений был ошибкой модели угроз для он-прем;
изоляционная модель — хук нельзя снять, запрещает по умолчанию — не менялась,
поменялось только то, что запрет настраиваем). `CHANGELOG.md` (v0.24).

## Testing

```
python -m pytest tests/soar/test_egress_policy.py tests/soar/test_audit_hook.py \
                 tests/soar/tools/test_egress_net.py tests/soar/test_runner.py \
                 tests/orchestrator/test_subprocess_runner_env.py \
                 tests/orchestrator/api/test_runtime.py -q
63 passed, 1 skipped

python -m pytest tests/ -q
851 passed, 3 failed, 9 skipped
```

Три падения — `tests/orchestrator/test_redis_integration.py`, требуют живой
Redis на `localhost:6379`, не связаны с этой правкой (тот же baseline, что
и в v0.23).

```
python -m ruff check soar/egress_policy.py soar/audit_hook.py soar/tools/_net.py \
                      soar/runner.py orchestrator/config.py orchestrator/api/runtime.py \
                      orchestrator/core/subprocess_runner.py
All checks passed!
```

### Ручная проверка (замена стенда — Docker недоступен в этой сессии)

Реальный `python -m soar.runner` subprocess, `SOAR_CONFIG` с
`egress: {mode: allowlist, allow: [127.0.0.1/32]}`, воркфлоу открывает два
raw-socket соединения:

- к `127.0.0.1` (в allowlist, реальный TCP-listener на эфемерном порту) —
  `CONNECTED`
- к `10.0.0.1` (приватный, вне allowlist) —
  `BLOCKED: egress to private address 10.0.0.1 blocked by audit hook`

Аудит-лог подтверждает оба события (`socket.connect` для разрешённого,
`socket.connect.blocked` для запрещённого). Полный вывод — в истории сессии;
скретч-директория удалена после проверки.

## Success criteria (plan §8)

- [x] `pytest` целиком зелёный (за вычетом преэкзистентных Redis-провалов)
- [x] Ручная проверка: allowlisted приватный адрес проходит, не-allowlisted
      падает с понятной ошибкой до и вместо тихого deny

## Что сознательно не сделано (см. [S5] спека)

Вывод allowlist из конфигов коннекторов, имена хостов в allowlist, egress
через API (вместо конфига на диске) — не в этом треке, обоснование в
спеке.
