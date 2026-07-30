"""SOAR runtime v1 — версионированный контракт содержимого content-venv.

Источник версий пакетов — soar/requirements.txt (единственный, не
дублируется здесь). Этот модуль добавляет то, чего requirements.txt не
несёт: имя для импорта (может не совпадать с именем дистрибутива —
psycopg2-binary → import psycopg2) и границу "протокол или вендор" из
docs/concepts/ENTITY-MODEL.md, решение 1:

- протокольные библиотеки — платформа, конечны, меняются раз в годы;
- вендорские SDK — не платформа, по одному на интеграцию, версионируются
  вместе с чужим API.

Расширение набора — релиз платформы: правка requirements.txt +
CONTRACT здесь, в одном коммите, с тестами (см. [S6] в
docs/compose/specs/2026-07-30-runtime-boundary-design.md).
"""

RUNTIME_VERSION = "1"

CONTRACT: dict[str, dict] = {
    # dist name (как в requirements.txt / importlib.metadata) → метаданные
    "paramiko":         {"import_names": ["paramiko"],   "kind": "protocol"},
    "ldap3":             {"import_names": ["ldap3"],      "kind": "protocol"},
    "smbprotocol":       {"import_names": ["smbclient", "smbprotocol"], "kind": "protocol"},
    "pywinrm":           {"import_names": ["winrm"],      "kind": "protocol"},
    "psycopg2-binary":   {"import_names": ["psycopg2"],   "kind": "protocol"},
    "pymysql":           {"import_names": ["pymysql"],    "kind": "protocol"},
    "pymssql":           {"import_names": ["pymssql"],    "kind": "protocol"},
    "aiosmtplib":        {"import_names": ["aiosmtplib"], "kind": "protocol"},
    "httpx":             {"import_names": ["httpx"],      "kind": "protocol"},
    "requests":          {"import_names": ["requests"],   "kind": "protocol"},
    "pyyaml":            {"import_names": ["yaml"],       "kind": "protocol"},
    "loguru":            {"import_names": ["loguru"],     "kind": "protocol"},
    "elasticsearch":     {"import_names": ["elasticsearch"], "kind": "vendor"},
    "vt-py":             {"import_names": ["vt"],         "kind": "vendor"},
    "aiogram":           {"import_names": ["aiogram"],    "kind": "vendor"},
    "shodan":            {"import_names": ["shodan"],     "kind": "vendor"},
    "pymisp":            {"import_names": ["pymisp"],     "kind": "vendor"},
}
