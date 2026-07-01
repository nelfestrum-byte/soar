---
feature: export-import
status: delivered
specs:
  - docs/compose/plans/2026-07-01-export-import.md
plans:
  - docs/compose/plans/2026-07-01-export-import.md
---

# Export/Import сущностей — Final Report

## What Was Built

Реализована функциональность экспорта и импорта сущностей SOAR (connectors, actions, workflows) и их конфигов в zip-архив. Позволяет настроить инстанс, экспортировать все сущности, и импортировать на новом инстансе без дополнительных усилий.

## Architecture

### API Endpoints

| Endpoint | Method | Описание |
|----------|--------|----------|
| `/transfer/export` | POST | Возвращает zip-архив со всеми сущностями |
| `/transfer/import` | POST | Принимает zip, восстанавливает сущности. Поддерживает `force=true` для перезаписи |

### Архивная структура

```
soar-export-YYYYMMDD-HHMMSS/
├── manifest.json          # мета: версия, время, список сущностей
├── connectors/
│   └── ssh/
│       ├── code.py
│       └── config.yml
├── actions/
│   └── my_action.py
├── workflows/
│   └── my_workflow.py
└── state.yaml             # enabled/disabled workflows
```

### UI

Отдельная страница Settings (`/settings`) с кнопками Export и Import. При импорте конфликтов показывается предупреждение с возможностью перезаписи.

### Design Decisions

- Используется zip-формат для простоты и стандартности
- Manifest JSON для метаданных архива
- Conflict detection перед импортом с возможностью force overwrite
- Автоматический reload workflows после импорта

## Usage

### Export

```bash
curl -X POST http://localhost:8000/transfer/export -o export.zip
```

### Import

```bash
# Без force (проверка конфликтов)
curl -X POST http://localhost:8000/transfer/import -F "file=@export.zip"

# С force (перезапись)
curl -X POST "http://localhost:8000/transfer/import?force=true" -F "file=@export.zip"
```

### UI

1. Открыть http://localhost:3000/settings
2. Export: нажать "Download Archive"
3. Import: нажать "Select Archive", выбрать zip-файл

## Verification

- Все 169 тестов проходят
- Ruff lint: 0 ошибок в transfer.py
- Mypy: 0 ошибок в transfer.py
- Тесты transfer API: 4/4 проходят

## Journey Log

- [lesson] При импорте файлов из zip нужно использовать Path для работы с parent директориями
- [lesson] Тесты API должны использовать правильные URL пути (без /api/ префикса)
