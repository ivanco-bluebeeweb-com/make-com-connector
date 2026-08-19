# Scenario Tests (PST) — Make.com Connector

Метод: `Docs/session-notes/SCENARIO_TESTING_STANDARD.md`. Дополняет (не
заменяет) `POST_AUDIT_LOG.md`: пост-аудит сверяет статическую
согласованность (manifest↔schemas↔handler↔client), PST реально
**вызывает** код через `imperal_sdk.testing.MockContext` и ловит то, что
статическая сверка структурно не видит.

---

## Прогон 2026-08-19

**Персона.** Единственная функциональная роль — владелец Make-аккаунта
(PREPARATION.md §3): подключает свой API-токен, видит/запускает свои
сценарии, настраивает исходящий вебхук Imperal → Make. Разнообразие
сценариев — по классам данных (пустой/типичный/пограничный/невалидный/
экзотический аккаунт: multi-zone discovery, отсутствие team-scope,
router-ветки в blueprint, конкурентные правки blueprint) и по 5
обязательным веткам (happy/error/blocked/recovery/adversarial).

**Харнесс:** `tests/conftest.py` (`ctx`, `ctx_connected`, `ctx_scoped`
fixtures на `imperal_sdk.testing.MockContext`/`MockSecretStore`, team-scope
засеивается напрямую в `MockStore._data` — синхронный dict, без риска
конфликта event loop с `pytest-asyncio`) и `tests/test_pst_scenarios.py`
(17 тестов, покрывающие все основные группы из 53 функций: connect/team
discovery, scenario CRUD+run+bulk, connections, data stores, hooks,
incomplete executions, blueprint preview/apply, outgoing webhook, usage
report).

**Предварительный шаг:** AST-сверка всех вызовов `mc.*` в `handlers.py`
против сигнатур `make_client.py` (тот же метод, что нашёл баг в n8n
Connector) — 60 вызовов, 0 несовпадений по количеству аргументов. Хорошо,
но недостаточно: этот класс багов (несовпадение сигнатур) здесь отсутствовал,
а другой — присутствовал в изобилии (см. ниже), и статическая сверка сигнатур
его не видит вообще.

### Находка — системный баг, 16 моделей / 24 места вызова (исправлено)

**Что было не так:** `imperal_sdk.sdl.Entity` требует `id: str | int` и
`title: str` БЕЗ дефолтных значений (см. `imperal_sdk/sdl/entity.py`) —
любой субкласс, который сам не переобъявляет эти два поля со значением по
умолчанию, обязан получать `id=` и `title=` при каждом конструировании.
16 классов в `schemas.py` этого не делали:

`OutgoingWebhookStatus`, `WebhookDeliveryResult`, `ConnectionVerifyResult`,
`DeleteResult` (не хватало только `title`, `id` уже был), `BulkDeleteResult`,
`BulkScenarioStateResult`, `BulkRunResult`, `BlueprintModuleFieldPreview`,
`BlueprintModuleUpdateResult`, `SchedulingResult`, `BuildtimeVariable`,
`UsageDay`, `BlueprintModuleAddPreview`, `BlueprintModuleAddResult`,
`BlueprintModuleDeletePreview`, `BlueprintModuleDeleteResult`.

Все 24 места вызова этих классов в `handlers.py` конструируют их БЕЗ
передачи `id=`/`title=` (они не относятся к сущностям с естественным ID —
это флаги статуса, отчёты, превью) → каждое из них гарантированно бросало
`pydantic_core.ValidationError` при первом реальном вызове. Затронутые
функции включают `set_outgoing_webhook`, `send_webhook_event`,
`verify_connection`, `delete_connection`, все 6 `delete_*`/`bulk_delete_*`,
`bulk_set_scenario_active`, `bulk_run_scenarios`,
`preview_update_blueprint_module`, `apply_update_blueprint_module`,
`update_scheduling`, `set_buildtime_variable`, `get_scenario_usage`,
`preview_add_blueprint_module`, `apply_add_blueprint_module`,
`preview_delete_blueprint_module`, `apply_delete_blueprint_module` —
практически каждая функция, возвращающая статус операции, а не
существующую сущность Make.

**Метод обнаружения:** 4 теста упали сразу на первом прогоне
(`ValidationError: title Field required` и т.п.); вместо точечного фикса
только этих 4 я прогнала AST-сверку ВСЕХ субклассов `sdl.Entity` в
`schemas.py` против фактических вызовов конструктора в `handlers.py` —
нашла 16 классов / 24 сайта, а не 4. Точечный фикс поймал бы только 4 из
16 — остальные 12 остались бы латентными до первого реального
использования пользователем той конкретной функции.

**Фикс:** добавлено `id: str = ""` и/или `title: str = ""` (со значением
по умолчанию) в каждый из 16 классов — они не относятся к
"настоящим" сущностям с естественным идентификатором, так что пустая
строка по умолчанию корректна и не меняет наблюдаемое поведение уже
рабочих путей.

### Итог прогона

```
24 passed in 0.36s
```

**Действие после этого прогона:** приложение передеплоено, чтобы фикс
попал в продакшн — 16 из 53 функций были фактически неработоспособны в
уже задеплоенном и уже прайсированном коде до этого прогона.
