# Задание 6. Ежедневное обновление базы знаний

## Что выбрано

- источник данных: локальная папка `docs/`;
- рабочий индексируемый корпус: `knowledge_base/`;
- стратегия обновления: `manifest diff + full rebuild`;
- расписание: ежедневно в `06:00`;
- логирование: append-only `JSONL`.

## Как работает pipeline

`scripts/update_index.py` сканирует `docs/`, считает `sha256` для каждого `*.md` и сравнивает текущее состояние с `artifacts/task6/update_state.json`.

После сравнения job делит документы на:

- `new`
- `changed`
- `deleted`
- `unchanged`

Для `new` и `changed` файлов применяется та же схема, что и в Task 3:

- `# Title`
- `Type: ...`
- `## Overview`
- `## Details`
- `## Related entities`

Если в новых или изменённых документах есть невалидный markdown, job завершает запуск со статусом `partial_failure`, не обновляет `knowledge_base/`, не пересобирает индекс и не переписывает state.

Если изменения валидны:

1. новые и изменённые документы копируются из `docs/` в `knowledge_base/`;
2. ранее отслеживаемые, но удалённые из `docs/`, файлы удаляются из `knowledge_base/`;
3. Task 3 индекс пересобирается целиком в `artifacts/task3/`;
4. новый `update_state.json` сохраняется только после успешной пересборки.

Если изменений нет, rebuild пропускается и в лог пишется запись со статусом `no_changes`.

## Команды запуска

Основной CLI:

```bash
./.venv/bin/python -B scripts/update_index.py
```

Поддерживаемые параметры:

```bash
./.venv/bin/python -B scripts/update_index.py \
  --source-dir docs \
  --kb-dir knowledge_base \
  --index-output-dir artifacts/task3 \
  --state-path artifacts/task6/update_state.json \
  --log-path artifacts/task6/update_log.jsonl
```

CLI contract:

- exit `0` для `success` и `no_changes`;
- non-zero exit для `partial_failure` и `failed`;
- stdout печатает краткий summary вида:
  - `status=success new=1 changed=0 deleted=0 rebuild=True log=...`

## Состояние и логи

`artifacts/task6/update_state.json` хранит:

- `source_dir`
- `kb_dir`
- `last_successful_run_at`
- `files`
  - `sha256`
  - `size_bytes`
  - `synced_to`
  - `last_seen_at`

`artifacts/task6/update_log.jsonl` хранит по одной записи на запуск:

- `run_started_at`
- `run_finished_at`
- `status`
- `source_dir`
- `kb_dir`
- `index_output_dir`
- `new_files_count`
- `changed_files_count`
- `deleted_files_count`
- `unchanged_files_count`
- `files_scanned_count`
- `documents_after_sync_count`
- `chunks_after_rebuild_count`
- `index_size_bytes`
- `errors`
- `warnings`

Пример сценариев:

- первый запуск с новыми документами → `success`;
- повторный запуск без изменений → `no_changes`;
- невалидный новый документ → `partial_failure`;
- сбой на rebuild/save → `failed`.

## Cron

Зафиксированный пример ежедневного запуска:

```cron
0 6 * * * cd <repo-root> && ./.venv/bin/python -B scripts/update_index.py >> artifacts/task6/cron_stdout.log 2>&1
```

Политика:

- запуск каждый день в `06:00`;
- stdout и stderr пишутся в `artifacts/task6/cron_stdout.log`;
- каждая попытка дополнительно попадает в `artifacts/task6/update_log.jsonl`;
- автоматический retry не добавляется, следующая cron-итерация повторяет попытку.
