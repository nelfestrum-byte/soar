# План: egress-политика через конфиг

Спек: [`docs/compose/specs/2026-08-06-egress-policy-design.md`](../specs/2026-08-06-egress-policy-design.md)

Порядок test-first: сначала падающий тест, потом код.

## 1. Модуль политики

- [x] `tests/soar/test_egress_policy.py` — падающий: `parse({})` даёт
      политику, где `is_allowed("192.168.1.51")` = False, а
      `is_allowed("8.8.8.8")` = True
- [x] Тест: `parse({"allow": ["192.168.1.0/24"]})` → `192.168.1.51`
      разрешён, `10.0.0.1` — нет
- [x] Тест: `parse({"mode": "observe"})` → `is_allowed` True на всё
- [x] Тест: `parse({"allow": ["не-cidr"]})` → внятное исключение
- [x] Тест: `parse({"mode": "чушь"})` → внятное исключение
- [x] Тест: одиночный IP без маски (`"192.168.1.51"`) принимается
- [x] `soar/egress_policy.py` — `EgressPolicy`, `parse()`, `is_allowed()`,
      `_is_private_ip` (переезжает сюда)

## 2. Хук консультируется с политикой

- [x] `tests/soar/test_audit_hook.py`: существующие тесты `_handle`
      обновить под новую сигнатуру (политика — аргумент, не глобал)
- [x] Падающий тест: `_handle` с политикой `192.168.1.0/24` пропускает
      `192.168.1.51`, блокирует `10.0.0.1`
- [x] Падающий тест: `install(policy)` в subprocess с `allow: [127.0.0.1/32]`
      — коннект на loopback не даёт `PermissionError` (по образцу
      существующего `test_install_in_subprocess_blocks_private_connect`)
- [x] Тест: без политики (`install()` как раньше) поведение deny-private
      сохраняется — проверка обратной совместимости
- [x] `soar/audit_hook.py`: `install(policy)`, замыкание вместо глобала,
      свой `_is_private_ip` удалить

## 3. Единая политика для http_client

- [x] Падающий тест: `_validate_external_url("http://192.168.1.51/")` не
      бросает при политике, разрешающей эту подсеть
- [x] Тест: та же функция бросает `ValueError` для адреса вне allowlist
      (регрессия — pre-flight не должен ослабнуть)
- [x] `soar/tools/_net.py`: консультация с политикой, свой
      `_is_private_ip` удалить

## 4. Порядок в раннере

- [x] `soar/runner.py`: загрузка конфига поднимается выше
      `install_audit_hook()`; гейт `if __name__ == "__main__"` сохраняется
- [x] Политика парсится из `config.get("egress")` и передаётся в
      `install()` и в `_net`
- [x] Малформед `egress` → падение с внятным сообщением до исполнения
      воркфлоу (не тихий откат к deny)
- [x] Тест: отсутствие файла конфига — по-прежнему warning + deny-private

## 5. Проброс в scoped-конфиг

- [x] Падающий тест в `tests/orchestrator/` — `build_scoped_config` с
      `egress` в full_config кладёт ту же секцию в scoped-конфиг
      (единственное место, где ошибка даёт молча неработающую настройку)
- [x] Тест: без `egress` в full_config ключа в scoped-конфиге нет
- [x] `orchestrator/core/subprocess_runner.py::build_scoped_config` — по
      образцу существующего проброса `http_client` (строки 150-152)

## 6. Видимость через API

- [x] Падающий тест: `GET /runtime` содержит `egress.mode` и `egress.allow`
- [x] Тест: ручка доступна роли `agent` (список нужен пишущему коннектор)
- [x] `orchestrator/api/runtime.py` — блок `egress` из
      `request.app.state.config`
- [x] `orchestrator/prompts/system_prompt.md` — абзац: egress ограничен,
      политика платформенная (любая библиотека, не только `http_client`),
      актуальный список — в `GET /runtime`

## 7. Конфиги и документация

- [x] `orchestrator/config.yaml` — секция `egress` с комментариями,
      включая предупреждение про `169.254.169.254`
- [x] `deploy/prod/config.yaml.template`, `deploy/stage/config.yaml`
- [x] `CHANGELOG.md`
- [x] `docs/concepts/ENTITY-MODEL.md` — решение 2 правится: deny-private
      был ошибкой модели угроз для он-прем, политика стала настраиваемой
- [x] `AGENTS.md` — после выполнения, не заранее
- [x] `docs/compose/reports/egress-policy.md`

## 8. Проверка

- [x] `pytest` целиком зелёный
- [x] Ручная проверка на стенде: джоба с коннектором к приватному адресу
      из allowlist проходит; к адресу вне allowlist — падает
