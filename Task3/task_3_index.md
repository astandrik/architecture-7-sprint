# Задание 3. Создание векторного индекса базы знаний

## Что было сделано

Для Task 3 выбран стек, зафиксированный в Task 1:

- embedding-модель: `sentence-transformers/all-MiniLM-L6-v2`
- ссылка на модель: `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2`
- размер эмбеддингов: `384`
- векторная БД: `FAISS`
- входная база знаний: `knowledge_base/`

Индекс строится скриптом:

- `scripts/build_index.py`

Проверочный retrieval по готовому индексу выполняется скриптом:

- `scripts/query_index.py`

## Как устроена индексация

В индексацию попадают только файлы `knowledge_base/*.md`. Служебные файлы вроде `terms_map.json` и `.gitkeep` в индекс не включаются.

Каждый документ сначала валидируется по ожидаемой структуре:

- заголовок `# Title`
- строка `Type: ...`
- секции `Overview`, `Details`, `Related entities`

Векторизуются только `Overview` и `Details`. Секция `Related entities` не превращается в отдельный чанк, а сохраняется в metadata, чтобы не добавлять шум в similarity search.

Для каждого чанка в индекс добавляется контекстный префикс:

- `Title: ...`
- `Type: ...`
- `Section: ...`

Используется section-aware chunking:

- короткие секции сохраняются как один чанк;
- длинные секции режутся через `RecursiveCharacterTextSplitter.from_tiktoken_encoder`.

Параметры чанкинга:

- `chunk_size=220`
- `chunk_overlap=40`
- `separators=["\n\n", "\n", ". ", " ", ""]`
- encoder: `cl100k_base`

Для каждого чанка сохраняются metadata:

- `chunk_id`
- `source_path`
- `title`
- `entity_type`
- `section`
- `chunk_index`
- `char_start`
- `char_end`
- `word_count`
- `related_entities`

## Результат сборки

Собранные артефакты лежат в `artifacts/task3/`:

- `artifacts/task3/faiss_index/index.faiss`
- `artifacts/task3/faiss_index/index.pkl`
- `artifacts/task3/chunks.jsonl`
- `artifacts/task3/index_build_report.json`

Фактический результат текущей пересборки после дополнительной очистки Task 2:

- документов в KB: `32`
- чанков в индексе: `69`
- время сборки индекса: `11.845` секунды
- `knowledge_base_dir` в отчёте: `knowledge_base`

## Примеры retrieval-запросов

### 1. `Who is Caelan Veyr's father?`

Top-1:

- `knowledge_base/caelan-veyr.md`
- section: `Details`
- chunk: `caelan-veyr::details::000`

Найденный чанк явно ведёт к ответу про `Darius Veyr`.

### 2. `What is the Hollow Eclipse?`

Top-1:

- `knowledge_base/the-hollow-eclipse.md`
- section: `Overview`
- chunk: `the-hollow-eclipse::overview::000`

Top-2:

- `knowledge_base/the-hollow-eclipse.md`
- section: `Details`
- chunk: `the-hollow-eclipse::details::000`

По этому запросу ожидаемая сущность возвращается сразу двумя первыми результатами.

### 3. `What ritual sends souls to the Veilward?`

Top-3 содержит чанк с целевым ответом:

- `knowledge_base/elyra-noctis.md`
- section: `Details`
- chunk: `elyra-noctis::details::002`

При этом top-1 и top-2 заняты самой сущностью `Veilward`, что для текущего baseline-retrieval ожидаемо: запрос семантически тянет и на концепт места, и на ритуал, связанный с ним.

## Краткий вывод

Task 3 закрыт в формате `скрипт + отчёт`:

- индекс собран и сохранён;
- есть код сборки и код запроса к индексу;
- retrieval sanity-check повторно пройден после очистки synthetic KB;
- структура артефактов уже пригодна для прямого переиспользования в Task 4.
