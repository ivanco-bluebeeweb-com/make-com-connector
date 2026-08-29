# Make.com Connector — UI component plan

Источники: `Docs/session-notes/UI_COMPONENT_VOCABULARY.md`, `UI_INTERFACE_STANDARD.md`,
`concepts/panels.md`. Основано на функционале `make-com-connector`.

## 1. Компоненты

| Экран | Примитивы | Почему именно эти |
|---|---|---|
| Sidebar (left) | `ui.Column`(align="start") + `ui.Text`(team/org) + `ui.Divider` + navigation `ui.ListItem`(Scenarios/Connections/Data Stores) + `ui.Button`("App settings") | Без карточек по стандарту. |
| Scenario List (center, `center_overlay=True`) | `ui.Stats`(Active/Paused/Ops used this month) + `ui.DataTable`(name, active Toggle-колонка, last run status Badge, ops; sortable) | Активация/пауза сценария прямо из таблицы через editable toggle-колонку. |
| Scenario Blueprint Viewer | Back-button + `ui.KeyValue`(scenario meta) + `ui.Graph`(nodes=modules, edges=flow order — реальная схема сценария) + `ui.Row`(Button "Run Now", "Clone") | `Graph` — единственный примитив, подходящий для визуализации графа модулей сценария Make. |
| Execution Log | `ui.DataTable`(started_at, status Badge success/error, ops consumed, duration; sortable) | Табличная история запусков сценария. |
| Incomplete Executions | `ui.List`(failed runs, с action "Retry" на каждом ListItem через `actions=[{...}]`) | `ListItem.actions` — встроенный способ дать hover-действие на строке без отдельной колонки. |
| Data Store Viewer | `ui.DataTable`(записи хранилища, колонки по схеме) | Data store Make — это буквально таблица записей. |
| Connections List | `ui.DataTable`(name, app, status Badge verified/broken) + `ui.Button`("Verify") | Список подключений сценариев к внешним сервисам. |
| Webhook/Hook Manager | `ui.List`(hooks: name, enabled Badge) + `ui.Button`("Создать hook") | Простой список инкаминг-хуков. |
| App Settings | `ui.Accordion`([Connections+Disconnect, Team Select, Outgoing Webhook URL]) | Централизованные настройки по стандарту. |

## 2. User flow (валидно по panel lifecycle)

1. **SESSION INIT** → `__panel__make_sidebar` рендерит team + разделы,
   `auto_action` открывает Scenario List для выбранной команды.
2. Scenario List: DataTable с editable toggle "Active" → `on_cell_edit` вызывает
   `set_scenario_active` напрямую (обратимо) → `refresh_panels`.
3. Клик на строку → `ui.Call(scenario_id=...)` → Scenario Blueprint Viewer на
   том же center handler — `Graph` рендерит модули из `get_scenario_blueprint`.
4. "Run Now" — прямой Call без Dialog. "Clone" — прямой Call, создаёт новый
   сценарий и сразу переключает `ui.Navigate` на него.
5. Execution Log / Incomplete Executions — читаемые списки с точечным retry
   на incomplete через `ListItem.actions`.
6. App Settings — единственная точка входа через кнопку в сайдбаре.

## 3. Экраны (конкретно, по файлам `panels.py`)

1. `make_sidebar` (`slot="left"`) — навигация, App settings button, Team Select
   (если несколько команд — `ui.Select` прямо в сайдбаре над списком).
2. `make_center` (`slot="center"`, `center_overlay=True`) — параметризован `view`
   (scenarios/blueprint/executions/incomplete/data_stores/connections/hooks).
3. `make_settings` (`slot="center"`, `panels_settings.py`) — Accordion с
   Connections/Team/Outgoing Webhook.
