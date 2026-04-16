# Задание 4. REPL RAG-бот на локальной Qwen через Ollama

## Что реализовано

Для Task 4 добавлен отдельный RAG-слой поверх артефактов Task 3:

- `src/task4_rag.py` — ядро пайплайна;
- `scripts/task4_repl.py` — консольный интерфейс и one-shot режим через `--query`.

Пайплайн работает так:

1. Загружает FAISS-индекс из `artifacts/task3/faiss_index`.
2. Использует ту же embedding-модель, что и в Task 3: `sentence-transformers/all-MiniLM-L6-v2`.
3. Выполняет `similarity_search_with_score`.
4. Применяет relevance-gate:
   - `top_k=5`
   - в prompt идут максимум `3` чанка
   - если лучший `distance > 1.45`, бот сразу отвечает language-aware fallback на языке вопроса.
5. Собирает prompt с:
   - system prompt с grounded-only правилами;
   - двумя few-shot примерами из synthetic KB;
   - полными текстами выбранных чанков.
6. Отправляет prompt в локальный `Ollama`.
7. Возвращает ответ в формате:
   - `Краткие шаги`
   - `Ответ`
   - `Источники`

## Runtime и параметры

Дефолтные параметры Task 4:

- модель `Ollama`: `qwen2.5:7b-instruct`
- `base_url`: `http://localhost:11434`
- `temperature`: `0.1`
- `num_ctx`: `4096`
- `num_predict`: `350`
- `timeout`: `120`

Для живых диалогов и демонстрации Task 4 используется `qwen2.5:7b-instruct` как стабильный локальный runtime.

Поддержанные CLI-флаги:

- `--index-dir`
- `--ollama-model`
- `--ollama-base-url`
- `--top-k`
- `--score-threshold`
- `--query`

## Как запускать

Подготовка:

- запустить локальный `Ollama` сервис;
- убедиться, что локальная Qwen-модель уже загружена;
- активировать `.venv`.

Реально проверенная команда one-shot:

- `python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "Who is Caelan Veyr's father?"`

Интерактивный REPL:

- `python -B scripts/task4_repl.py`

Если нужен конкретный локальный tag:

- `python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "What is the Hollow Eclipse?"`

## Verification Evidence

### 1. Live fallback smoke-check

Команда:

- `python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "What is the capital of France?"`

Полученный вывод:

- `Краткие шаги:`
- `1. Searched the knowledge base.`
- `2. Did not find relevant fragments for the answer.`
- `Ответ:`
- `I don't know.`
- `Источники:`
- `no relevant context found`

Это подтверждает:

- загрузку индекса;
- работу retrieval-gate;
- short-circuit без генерации;
- финальный формат fallback-ответа.

### 2. Live happy-path smoke-check

Команда:

- `python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "Who is Caelan Veyr's father?"`

Полученный вывод:

- `Краткие шаги:`
- `1. Проверил контекст про Caelan Veyr и его родителей.`
- `2. Нашел информацию о его отце в первом контексте.`
- `3. Сформулировал ответ на основе найденной информации.`
- `Ответ:`
- `Caelan Veyr's father is Darius Veyr.`
- `Источники:`
- `Caelan Veyr — knowledge_base/caelan-veyr.md (Details)`
- `Garron Vale — knowledge_base/garron-vale.md (Overview)`
- `Arcton Veyr — knowledge_base/arcton-veyr.md (Details)`

Это подтверждает:

- корректную загрузку FAISS-индекса;
- retrieval по реальному индексу с тем же embedding-энкодером, что и в Task 3;
- сборку prompt с few-shot и grounded-only правилами;
- end-to-end вызов локального `Ollama`;
- финальный формат ответа с `Краткие шаги`, `Ответ` и `Источники`.

## Примеры успешных диалогов

Ниже — реальные one-shot прогоны через:

- `python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "..."`

### Диалог 1

Q: `Who is Caelan Veyr's father?`

A:

- `Краткие шаги:`
- `1. Проверил контекст про Caelan Veyr и его родителей.`
- `2. Нашел информацию о его отце в первом контексте.`
- `3. Сформулировал ответ.`
- `Ответ:`
- `Caelan Veyr's father is Darius Veyr.`
- `Источники:`
- `Caelan Veyr — knowledge_base/caelan-veyr.md (Details)`
- `Garron Vale — knowledge_base/garron-vale.md (Overview)`
- `Arcton Veyr — knowledge_base/arcton-veyr.md (Details)`

### Диалог 2

Q: `What is the Hollow Eclipse?`

A:

- `Краткие шаги:`
- `1. Проверил overview и details по сущности The Hollow Eclipse.`
- `2. Собрал основные характеристики из описания.`
- `3. Формулировал ответ на основе найденной информации.`
- `Ответ:`
- `The Hollow Eclipse is a large, whale-like creature with a city on its back and the ability to create smaller monsters called Eclipseborn from its outer layer. It can move using clawed arms and pectoral fin-like hind legs, and has a long tail covered in scales that it can shed into Eclipse shards.`
- `Источники:`
- `The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Overview)`
- `The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Details)`
- `Elyndra — knowledge_base/elyndra.md (Details)`

### Диалог 3

Q: `What ritual sends souls to the Veilward?`

A:

- `Краткие шаги:`
- `1. Проверил retrieved-фрагменты на информацию о ритуале отправки душ.`
- `2. Нашел описание ритуала в контексте Elyra Noctis.`
- `Ответ:`
- `The sending ritual involves Elyra Noctis dancing and, at one point, walking on the water's surface to send souls of the deceased to Veilward.`
- `Источники:`
- `Veilward — knowledge_base/veilward.md (Overview)`
- `Veilward — knowledge_base/veilward.md (Details)`
- `Elyra Noctis — knowledge_base/elyra-noctis.md (Details)`

### Диалог 4

Q: `Who watches over Caelan Veyr?`

A:

- `Краткие шаги:`
- `1. Проверил контекст Garron Vale о его роли в жизни Caelan Veyr.`
- `2. Увидел, что Garron Vale следит за Caelan Veyr и помогает ему.`
- `Ответ:`
- `Garron Vale watches over Caelan Veyr.`
- `Источники:`
- `Caelan Veyr — knowledge_base/caelan-veyr.md (Details)`
- `Caelan Veyr — knowledge_base/caelan-veyr.md (Overview)`
- `Garron Vale — knowledge_base/garron-vale.md (Overview)`

### Диалог 5

Q: `What is Skyball?`

A:

- `Краткие шаги:`
- `1. Проверил overview и details по сущности Skyball.`
- `2. Собрал основные характеристики игры из описания.`
- `3. Формулировал ответ на основе найденной информации.`
- `Ответ:`
- `Skyball is a traditional Elyndran sport played in an open-air water sphere stadium with triangular goals at opposing points. The game consists of two five-minute periods, and the team with the highest score wins. In certain conditions, such as during the Endless Truce, a team leading by seven goals can win immediately.`
- `Источники:`
- `Skyball — knowledge_base/skyball.md (Overview)`
- `Skyball — knowledge_base/skyball.md (Details)`
- `Elyndra — knowledge_base/elyndra.md (Details)`

## Примеры fallback-ответов

### Fallback 1

Q: `What is the capital of France?`

A:

- `Краткие шаги:`
- `1. Searched the knowledge base.`
- `2. Did not find relevant fragments for the answer.`
- `Ответ:`
- `I don't know.`
- `Источники:`
- `no relevant context found`

### Fallback 2

Q: `Who wrote The Lord of the Rings?`

A:

- `Краткие шаги:`
- `1. Searched the knowledge base.`
- `2. Did not find relevant fragments for the answer.`
- `Ответ:`
- `I don't know.`
- `Источники:`
- `no relevant context found`
