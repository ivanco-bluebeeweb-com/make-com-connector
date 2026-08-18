# Pricing History — Make.com Connector

Обязательный журнал: каждое выставление или изменение цен на функции этого
приложения фиксируется здесь ДО публикации/ре-публикации — что изменилось,
почему, и на основании чего. Не переписывать прошлые записи — только
дописывать новые сверху.

---

## 2026-08-19 — первичное выставление цен (per_action), 53 функции

**Контекст:** после завершения полного функционального пост-аудита (см.
задачу #1915 в Imperal Cloud, раздел "Сквозной пост-аудит" — манифест ↔
схемы ↔ handlers ↔ клиент сверены на 100% функций, найденные баги
исправлены и задеплоены), приложение готово к выставлению цен как
последний шаг перед публикацией в Marketplace.

**Модель:** `per_action` — цена за вызов, а не подписка. Обоснование:
Make.com Connector — BYOK-коннектор (пользователь платит Make.com напрямую
за свою квоту сценариев), поэтому наша ценность — это сам факт удобного
доступа к API из чата/панели, а не инфраструктурные расходы на вызов;
плоская подписка не отражала бы то, что кто-то использует 2 функции в
месяц, а кто-то — 200.

**Платформенные дефолты по категориям** (если явно не переопределено):
`read=1`, `write=5`, `destructive=10` кредитов. Мы задали цену ЯВНО на
каждую из 53 функций (не полагаясь молча на дефолты) — чтобы цена
осмысленно отражала реальную ценность/риск действия, а не только его
технический тип, и чтобы будущее изменение платформенных дефолтов нас не
задело незаметно.

### Логика по уровням (обоснование конкретных чисел)

| Уровень | Цена | Категория функций | Почему |
|---|---|---|---|
| 1 | 1 | Все `read`-функции без исключения (list_*, get_*, verify_connection и т.п.) | Простое чтение состояния — минимальная себестоимость, максимальная частота использования (эти вызовы будут самыми частыми в любой сессии — низкая цена держит порог входа низким) |
| 2 | 2 | `preview_*` (preview_update/add/delete_blueprint_module) | Формально `read` (ничего не пишут), но делают больше работы, чем простой список — читают весь blueprint и считают state-hash. Чуть выше базового read. |
| 3 | 3 | `select_team`, `rename_connection` | Лёгкие, обратимые, не рискованные write-действия — косметика/навигация, не логика сценария. |
| 3 | 5 | Базовый `write`: `connect_make`, `disconnect_make`, `set_scenario_active`, `set_outgoing_webhook`, `send_webhook_event`, `set_hook_enabled`, `retry_incomplete_execution`, `restore_scenario`, `update_scheduling`, `set_buildtime_variable`, `stop_execution` | Стандартный платформенный дефолт для write, где действие обратимо или не создаёт/не удаляет ничего необратимого. |
| 4 | 6 | `create_data_store`, `delete_incomplete_executions`, `apply_update_blueprint_module`, `create_scenario`, `clone_scenario`, `delete_buildtime_variable`, `create_hook` | Создание нового объекта или подтверждённая (после preview) запись в blueprint — чуть выше базового write, т.к. либо создаёт постоянный ресурс, либо меняет логику сценария. |
| 5 | 7 | `apply_add_blueprint_module` | Подтверждённое добавление модуля в blueprint (после preview) — реальное изменение логики сценария пользователя. |
| 6 | 8 | `run_scenario`, `delete_connection`, `delete_data_store`, `delete_hook`, `delete_scenario`, `apply_delete_blueprint_module` | Необратимые или производящие реальные внешние эффекты действия: `run_scenario` реально выполняет все действия сценария в Make прямо сейчас (шлёт письма, пишет в подключённые сервисы) — платформенно это `write`, но по риску ближе к `destructive`; удаления `connection`/`data_store`/`hook`/`scenario`/blueprint-модуля ломают то, что на них ссылается. |
| 7 | 10 | `bulk_set_scenario_active`, `create_api_token`, `delete_api_token` | `bulk_*` — по определению умножает последствия на N целей за один вызов, всегда требует confirm. `create_api_token`/`delete_api_token` — управление настоящими, боевыми credential'ами пользователя в самом Make (не просто данными внутри коннектора) — заведомо самый чувствительный слой во всём приложении. |
| 8 | 12 | `bulk_run_scenarios`, `bulk_delete_connections`, `bulk_delete_hooks` | Наивысший уровень: bulk-версия необратимого/исполняющего действия — до N сценариев запускаются или до N connections/hooks удаляются одним вызовом. |

**Полная таблица (53/53 функций с ценой)** — источник истины: живой
`pricing_config.tool_prices` в Dev Portal (или `GET` через
`developer.get_earnings_by_app`/Dev Portal UI). Копия на момент этой
записи:

```
connect_make=5              disconnect_make=5           get_make_connection=1
list_make_teams=1           select_team=3               list_scenarios=1
run_scenario=8              set_scenario_active=5       set_outgoing_webhook=5
get_outgoing_webhook_status=1 send_webhook_event=5       get_scenario_blueprint=2
list_connections=1          delete_connection=8         rename_connection=3
verify_connection=1         list_data_stores=1          create_data_store=6
delete_data_store=8         list_hooks=1                set_hook_enabled=5
delete_hook=8               list_incomplete_executions=1 retry_incomplete_execution=5
delete_incomplete_executions=6 bulk_set_scenario_active=10 bulk_run_scenarios=12
bulk_delete_connections=12  bulk_delete_hooks=12        preview_update_blueprint_module=2
apply_update_blueprint_module=6 create_scenario=6       delete_scenario=8
restore_scenario=5          clone_scenario=6            update_scheduling=5
list_buildtime_variables=1  set_buildtime_variable=5    delete_buildtime_variable=6
get_scenario_usage=1        list_scenario_logs=1        get_execution_details=1
stop_execution=5            preview_add_blueprint_module=2 apply_add_blueprint_module=7
preview_delete_blueprint_module=2 apply_delete_blueprint_module=8 list_organizations=1
list_team_members=1         list_api_tokens=1           create_api_token=10
delete_api_token=10         create_hook=6
```

**Tier/split на момент записи:** developer tier = `explorer` (70/30
split, no payout yet — см. `/en/billing/developer-tiers/`). Не влияет на
цену, которую видит пользователь, только на долю, которую получает
разработчик.

**Кто принял решение:** Webbee, по прямому поручению пользователя
(vlad@bluebeeweb.com) — "выставить прайсинги на все функции когда
публикуем в Имперал" — как обязательный шаг ПОСЛЕ завершения
функционального пост-аудита (см. #1915).

**Следующий пересмотр:** при следующем изменении набора функций
(добавление/удаление tool'а) или по итогам первых реальных данных об
использовании (earnings/action_count через `get_earnings_by_app`) — тогда
здесь появится новая датированная запись с обоснованием, что именно
изменилось и почему.
