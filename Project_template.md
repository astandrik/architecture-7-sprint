# Project Template

## Общая информация

- Проект: `architecture-7-sprint`
- Репозиторий: `git@github.com:astandrik/architecture-7-sprint.git`
- Рабочая ветка: `rag`
- Формат интерфейса в текущей реализации: `REPL` + one-shot CLI
- Основной runtime для live-демонстраций: `Ollama / qwen2.5:7b-instruct`
- Docker packaging route: `rag-bot` в контейнере, `Ollama` на хосте macOS

## Задание 1. Исследование моделей и инфраструктуры

- Итоговый отчёт: `Task1/task_1_research.md`
- Сравнены LLM:
  - `Ollama + qwen2.5:7b-instruct`
  - `OpenAI gpt-5-mini`
  - `YandexGPT Lite / Pro`
- Сравнены эмбеддинги:
  - `sentence-transformers/all-MiniLM-L6-v2`
  - `text-embedding-3-small`
- Сравнены векторные БД:
  - `FAISS`
  - `ChromaDB`
- Выбранный стек для реализации:
  - embeddings: `sentence-transformers/all-MiniLM-L6-v2`
  - vector DB: `FAISS`
  - production-like recommendation: `gpt-5-mini + local retrieval`
  - фактическая локальная реализация: `Ollama / qwen2.5:7b-instruct`
- Рекомендуемая пилотная инфраструктура: `8 vCPU / 16 GB RAM / 100 GB NVMe / без GPU`

## Задание 2. Подготовка базы знаний

- Итоговый документ: `Task2/task_2_kb.md`
- Источник synthetic KB: `Final Fantasy X`
- Количество сущностей: `32`
- Основные артефакты:
  - `Task2/source_manifest.json`
  - `Task2/terms_map.json`
  - `knowledge_base/*.md`
  - `knowledge_base/terms_map.json`
- Скрипты:
  - `scripts/fetch_ffx_sources.py`
  - `scripts/build_synthetic_kb.py`
  - `scripts/validate_task2_kb.py`
- Текущий статус:
  - корпус собран и проходит `scripts/validate_task2_kb.py`
  - прямые канонические термины и часть residual markers удалены
  - строгий eval полной семантической неузнаваемости не реализован

## Задание 3. Векторный индекс

- Итоговый документ: `Task3/task_3_index.md`
- Скрипты:
  - `scripts/build_index.py`
  - `scripts/query_index.py`
  - `src/task3_indexing.py`
- Артефакты:
  - `artifacts/task3/faiss_index/index.faiss`
  - `artifacts/task3/faiss_index/index.pkl`
  - `artifacts/task3/chunks.jsonl`
  - `artifacts/task3/index_build_report.json`
- Параметры индекса:
  - embedding model: `sentence-transformers/all-MiniLM-L6-v2`
  - embedding dimension: `384`
  - chunk size: `220`
  - chunk overlap: `40`
  - chunks count: `69`
  - build seconds: `10.659`

## Задание 4. RAG-бот

- Итоговый документ: `Task4/task_4_rag.md`
- Основной код:
  - `src/task4_rag.py`
  - `scripts/task4_repl.py`
- Возможности:
  - загрузка FAISS-индекса
  - retrieval тем же энкодером, что и в Task 3
  - prompt assembly с few-shot
  - CoT-формат через блок `Краткие шаги`
  - language-aware fallback
- Зафиксированные демонстрации:
  - `5` успешных one-shot диалогов
  - `2` fallback-кейса

## Задание 5. Prompt injection demo

- Итоговый документ: `Task5/task_5_demo.md`
- Вредоносный документ: `Task5/malicious_document.md`
- Скрипты:
  - `scripts/build_task5_demo_index.py`
  - `scripts/run_task5_demo.py`
- Артефакты:
  - `artifacts/task5/demo_log.md`
  - `artifacts/task5/attack_preview.json`
  - `artifacts/task5/faiss_index/index.faiss`
  - `artifacts/task5/faiss_index/index.pkl`
- Protection modes:
  - `none`
  - `preprompt`
  - `sanitize`
  - `postfilter`
  - `full`
- Демонстрационный пакет:
  - `5` успешных ответов в `full`
  - `5` safe-negative случаев в `full`

## Задание 6. Ежедневное обновление базы знаний

- Итоговый документ: `Task6/task_6_update.md`
- Архитектурная диаграмма:
  - `Task6/task_6_architecture.puml`
  - `Task6/task_6_architecture.png`
- Скрипт обновления: `scripts/update_index.py`
- Лог: `artifacts/task6/update_log.jsonl`
- Источник данных: `docs/`
- Стратегия: `manifest diff + full rebuild`
- Расписание: ежедневно в `06:00`
- Статусы pipeline:
  - `success`
  - `no_changes`
  - `partial_failure`
  - `failed`

## Задание 7. Аналитика покрытия и качества

- Итоговый документ: `Task7/task_7_coverage.md`
- Golden set:
  - `Task7/golden_questions.json`
  - `Task7/golden_questions.txt`
- Скрипты:
  - `scripts/build_task7_eval_corpus.py`
  - `scripts/evaluate_task7.py`
  - `src/task7_eval.py`
- Eval runtime:
  - `scripts/evaluate_task7.py` фиксирует `temperature=0.0` для воспроизводимого golden-set прогона
- Артефакты:
  - `artifacts/task7/logs.jsonl`
  - `artifacts/task7/eval_summary.json`
  - `Task7/task_7_sequence.puml`
  - `Task7/task_7_sequence.png`
- Текущее состояние по рабочему дереву:
  - `total_questions = 12`
  - `final_pass = 12`
  - `final_fail = 0`
  - `final_review_needed = 0`

## Проверки

- Базовые unit-тесты:
  - `./.venv/bin/python -m unittest tests/test_task2_kb_pipeline.py tests/test_task4_rag.py tests/test_update_index.py tests/test_task7_evaluate.py`
- Task 2 validation:
  - `./.venv/bin/python scripts/validate_task2_kb.py`
- Read-only retrieval checks:
  - `./.venv/bin/python -B scripts/query_index.py --index-dir artifacts/task3/faiss_index --query "Who is Caelan Veyr's father?" --top-k 3`
  - `./.venv/bin/python -B scripts/query_index.py --index-dir artifacts/task3/faiss_index --query "What is the Hollow Eclipse?" --top-k 3`

## Submission checklist

- `Project_template.md` — готово
- `Dockerfile` — готово
- `compose.yml` — готово
- `10` скриншотов — готово
  - `01_success_strongest_creature.png`
  - `02_success_hollow_eclipse.png`
  - `03_success_veilward_ritual.png`
  - `04_success_guardian.png`
  - `05_success_skyball.png`
  - `06_fallback_spira.png`
  - `07_fallback_auron.png`
- `08_fallback_yuna.png`
- `09_fallback_far_plain.png`
- `10_fallback_the_sin.png`

## Примечание по Docker

- Практичная схема для macOS / Apple Silicon:
  - `rag-bot` запускается в Docker
  - `Ollama` запускается на хосте macOS
- Причина:
  - хостовый `Ollama` на macOS использует Metal / Apple GPU
  - containerized `Ollama` в Colima/Docker шёл по CPU-path и был слишком тяжёлым для `qwen2.5:7b-instruct`
  - поэтому `compose.yml` подключает контейнер к хостовому endpoint `Ollama`, а не поднимает отдельный `ollama` service
- Проверенный compose-сценарий:
  - `ollama serve` на хосте macOS
  - `docker-compose -f compose.yml run --rm rag-bot ...`
  - one-shot запрос `Who is Caelan Veyr's father?` успешно отрабатывает через `host.docker.internal`
