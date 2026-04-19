# Задание 4. REPL RAG-бот на локальной Qwen через Ollama

## Что реализовано

RAG-слой поверх артефактов Task 3:

- `src/task4_rag.py` — ядро пайплайна;
- `scripts/task4_repl.py` — REPL и one-shot режим через `--query`.

Что делает один запрос:

1. Грузит FAISS-индекс из `artifacts/task3/faiss_index`.
2. Энкодит вопрос той же моделью, что и Task 3 (`sentence-transformers/all-MiniLM-L6-v2`).
3. Делает `similarity_search_with_score`, берёт `top_k=5`.
4. Применяет relevance-gate: в prompt идут максимум 3 чанка; если лучший `distance > 1.45`, бот сразу отвечает language-aware fallback без обращения к LLM.
5. Собирает prompt: system-часть с grounded-only правилами, два few-shot примера из synthetic KB, полные тексты выбранных чанков.
6. Отправляет в локальный `Ollama`.
7. Возвращает ответ в формате `Краткие шаги` → `Ответ` → `Источники`.

## Runtime и параметры

Дефолты (в `src/task4_rag.py`):

- модель: `qwen2.5:7b-instruct`
- `base_url`: `http://localhost:11434`
- `temperature`: `0.1`
- `num_ctx`: `4096`
- `num_predict`: `350`
- `timeout`: `120`

Флаги CLI: `--index-dir`, `--ollama-model`, `--ollama-base-url`, `--top-k`, `--score-threshold`, `--query`.

## Как запускать

Подготовка:

- поднять локальный `Ollama`;
- убедиться, что `qwen2.5:7b-instruct` загружен (`ollama pull qwen2.5:7b-instruct`);
- активировать `.venv`.

One-shot:

```
python -B scripts/task4_repl.py --ollama-model qwen2.5:7b-instruct --query "What is the Hollow Eclipse?"
```

Интерактивный REPL:

```
python -B scripts/task4_repl.py
```

## Verification Evidence

Скриншоты всех 10 прогонов лежат в корне репозитория (`01_success_*.png`–`10_fallback_*.png`). Текстовые снапшоты ниже сняты с тех же PNG один в один.

Важно: `Краткие шаги` и `Ответ` — это LLM output при `temperature=0.1`. Точный текст варьируется между запусками; стабильны формат, `Источники` и смысл ответа.

## Примеры успешных диалогов

### Диалог 1 — скрин `01_success_strongest_creature.png`

Q: `I want to know any strong creature's name`

A:

```
Краткие шаги:
1. Searched the knowledge base and selected the most relevant chunks.
2. Used the fragment Kaelor Rhun from the Overview section.
3. Formulated the answer using only retrieved context.

Ответ:
The name of a strong creature is The Hollow Eclipse.

Источники:
- Kaelor Rhun — knowledge_base/kaelor-rhun.md (Overview)
- The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Details)
- The Relicborn — knowledge_base/the-relicborn.md (Details)
```

Retrieval вытянул три довольно разных чанка (Kaelor Rhun, The Hollow Eclipse, The Relicborn), и LLM корректно выделил из них именно ту сущность, которая подходит под вопрос.

### Диалог 2 — скрин `02_success_hollow_eclipse.png`

Q: `What is the Hollow Eclipse?`

A:

```
Краткие шаги:
1. Searched the knowledge base and selected the most relevant chunks.
2. Used the fragment The Hollow Eclipse from the Details section.
3. Formulated the answer using only retrieved context.

Ответ:
The Hollow Eclipse is a large, whale-like creature with clawed arms and pectoral fin-like hind legs. It carries part of a city on its body and can create smaller monsters called Eclipseborn from its outer layer. Its final form includes purple-tipped wing-like protrusions.

Источники:
- The Hollow Eclipse — knowledge_base/the-hollow-eclipse.md (Details)
- Elyndra — knowledge_base/elyndra.md (Details)
- Elyndra — knowledge_base/elyndra.md (Details)
```

Источник `Elyndra (Details)` перечислен дважды — это два разных чанка одного файла, LLM указал оба. Внутреннее дедуплицирование по file+section не делалось сознательно, чтобы не прятать факт, что ответ опирался на два отдельных фрагмента.

### Диалог 3 — скрин `03_success_veilward_ritual.png`

Q: `What ritual sends souls to the Veilward?`

A:

```
Краткие шаги:
1. Searched the knowledge base and selected the most relevant chunks.
2. Used the fragment Elyra Noctis from the Details section.
3. Formulated the answer using only retrieved context.

Ответ:
The ritual that sends souls to the Veilward is performed by Elyra Noctis and involves her dancing and, at one point, walking on water's surface.

Источники:
- Elyra Noctis — knowledge_base/elyra-noctis.md (Details)
- The Luminous Order — knowledge_base/the-luminous-order.md (Details)
- Elyndra — knowledge_base/elyndra.md (Details)
```

### Диалог 4 — скрин `04_success_guardian.png`

Q: `Who watches over Caelan Veyr?`

A:

```
Краткие шаги:
1. Searched the knowledge base and selected the most relevant chunks.
2. Used the fragment Caelan Veyr from the Details section.
3. Formulated the answer using only retrieved context.

Ответ:
Garron Vale watches over Caelan Veyr.

Источники:
- Caelan Veyr — knowledge_base/caelan-veyr.md (Details)
- Caelan Veyr — knowledge_base/caelan-veyr.md (Overview)
- Garron Vale — knowledge_base/garron-vale.md (Overview)
```

### Диалог 5 — скрин `05_success_skyball.png`

Q: `What is famous ball game?`

A:

```
Краткие шаги:
1. Searched the knowledge base and selected the most relevant chunks.
2. Used the fragment Skyball from the Details section.
3. Formulated the answer using only retrieved context.

Ответ:
Skyball is a famous ball game played in an open-air water sphere stadium with triangular goals at the north and south points, where teams compete for seven goal leads within one five-minute round.

Источники:
- Skyball — knowledge_base/skyball.md (Details)
```

Единственный источник — нестрогий вопрос («famous ball game»), максимум relevancy у одного чанка, остальные отсекает relevance-gate.

## Примеры fallback-ответов

Здесь собраны две разные ветки отказа. 06, 08, 09, 10 — это hardcoded short-circuit: лучший `distance > 1.45`, LLM не вызывается вообще. 07 — другое: retrieval вернул три чанка в пределах порога, LLM вызвана и сама отказалась отвечать. Пост-процессор [parse_model_response](../src/task4_rag.py#L950) распознал отказ через `is_no_answer_text` и унифицировал вывод: шаги, ответ и источники заменены на fallback-payload. Это защищает от ситуации, где «я не знаю» соседствует с тремя seemingly-связанными источниками и вводит пользователя в заблуждение.

### Fallback 1 — скрин `06_fallback_spira.png`

Q: `What is the capital of Spira?`

A:

```
Краткие шаги:
1. Searched the knowledge base.
2. Did not find relevant fragments for the answer.

Ответ:
I don't know.

Источники:
- no relevant context found
```

`Spira` — каноническое имя FFX, в synthetic KB подменено на `Elyndra`. Relevance-gate сработал.

### Fallback 2 — скрин `07_fallback_auron.png`

Q: `Who is Auron? He is one of the main characters`

A:

```
Краткие шаги:
1. Searched the knowledge base.
2. Did not find relevant fragments for the answer.

Ответ:
I don't know.

Источники:
- no relevant context found
```

Интереснее первого. Retrieval не отсекает запрос: 3 content-чанка (Isola Veyn, Maelor Voss, Arcton Veyr) проходят score-порог и попадают в prompt. LLM вызывается, читает контекст и сама возвращает grounded refusal — про `Auron` в фрагментах ничего нет. Затем пост-процессор через `is_no_answer_text` детектит отказ и переписывает секции `Краткие шаги` / `Ответ` / `Источники` на унифицированный fallback-payload. Итог: пользователю не показываются источники, которые фактически не поддержали ответ, а демонстрация в том, что grounded-only правила в system-prompt ловят случаи, где embedding-сходство обмануло relevance-gate.

### Fallback 3 — скрин `08_fallback_yuna.png`

Q: `Is Yuna the strongest summoner?`

A:

```
Краткие шаги:
1. Searched the knowledge base.
2. Did not find relevant fragments for the answer.

Ответ:
I don't know.

Источники:
- no relevant context found
```

### Fallback 4 — скрин `09_fallback_far_plain.png`

Q: `Far plain is what?`

A:

```
Краткие шаги:
1. Searched the knowledge base.
2. Did not find relevant fragments for the answer.

Ответ:
I don't know.

Источники:
- no relevant context found
```

### Fallback 5 — скрин `10_fallback_the_sin.png`

Q: `Who is actually The Sin?`

A:

```
Краткие шаги:
1. Searched the knowledge base.
2. Did not find relevant fragments for the answer.

Ответ:
I don't know.

Источники:
- no relevant context found
```

## Что всё это подтверждает

- FAISS-индекс грузится и работает end-to-end через тот же embedding-энкодер, что и в Task 3.
- Retrieval-gate отсекает явно нерелевантные запросы без вызова LLM.
- Grounded-only правила ловят случаи, где retrieval не отсёк, но контекст всё равно не отвечает на вопрос.
- Замены из Task 2 (`Spira → Elyndra`, `Yuna → Elyra Noctis`, `Sin → The Hollow Eclipse`, `Auron → Garron Vale`, `Farplane → Veilward`) реально скрывают канонический мир от модели — прямые запросы по каноническим именам не попадают в retrieval.
- Формат `Краткие шаги` / `Ответ` / `Источники` стабилен на всех десяти прогонах, в том числе когда fallback приходит с LLM-стороны, а не с hardcoded короткого замыкания.
