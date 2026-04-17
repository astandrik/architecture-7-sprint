# Задание 3. Создание векторного индекса базы знаний

## Что было сделано

Стек зафиксирован в Task 1:

- embedding-модель: `sentence-transformers/all-MiniLM-L6-v2` (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- размер эмбеддингов: 384
- векторная БД: `FAISS`
- вход: `knowledge_base/`

Сборка — `scripts/build_index.py`. Проверка retrieval — `scripts/query_index.py`.

## Как устроена индексация

В индекс идут только `knowledge_base/*.md`; `terms_map.json`, `.gitkeep` и прочая служебка отфильтровывается.

Перед чанкингом документ валидируется по ожидаемой структуре: заголовок `# Title`, строка `Type:`, секции `Overview`, `Details`, `Related entities`.

Векторизуются только `Overview` и `Details`. `Related entities` живёт в metadata — в similarity search его не пускаю, там всё равно короткий список имён, который без контекста ломает scoring.

К тексту каждого чанка добавляется префикс:

```
Title: ...
Type: ...
Section: ...
```

Это нужно, чтобы при top-k retrieval на стороне Task 4 модель видела, в какой сущности сидит фрагмент, даже если сам чанк про это явно не говорит.

Chunking — section-aware: короткая секция остаётся одним чанком, длинная режется через `RecursiveCharacterTextSplitter.from_tiktoken_encoder` с параметрами:

- `chunk_size=220`
- `chunk_overlap=40`
- `separators=["\n\n", "\n", ". ", " ", ""]`
- encoder: `cl100k_base`

С каждым чанком в индекс уходят metadata: `chunk_id`, `source_path`, `title`, `entity_type`, `section`, `chunk_index`, `char_start`, `char_end`, `word_count`, `related_entities`. Это то, что потом нужно Task 4 для цитирования и диагностики.

## Результат сборки

Артефакты в `artifacts/task3/`:

- `faiss_index/index.faiss`
- `faiss_index/index.pkl`
- `chunks.jsonl`
- `index_build_report.json`

После пересборки на обновлённой KB:

- документов: 32
- чанков: 69
- время сборки: 10.659 с

## Примеры retrieval-запросов

### 1. `Who is Caelan Veyr's father?`

Top-1 — `caelan-veyr.md / Details / caelan-veyr::details::000`. Чанк упоминает отца явно, ответ `Darius Veyr` достаётся без второго хопа.

### 2. `What is the Hollow Eclipse?`

Top-1 и top-2 — оба из `the-hollow-eclipse.md`: сначала Overview, потом Details. Сущность возвращается двумя первыми результатами.

### 3. `What ritual sends souls to the Veilward?`

Top-1 и top-2 заняты самой сущностью `Veilward` (её страница). Целевой чанк про ритуал сидит в top-3 — `elyra-noctis.md / Details / elyra-noctis::details::002`. Для baseline-retrieval это ожидаемо: embedding тянет и на место, и на связанный с ним ритуал, и оба тянут сильнее, чем описание самого ритуала в карточке персонажа.

## Вывод

Индекс собран и воспроизводим из KB. Sanity-check на трёх разных типах запросов проходит: прямой факт, определение сущности, факт через связанную страницу. Артефакты в `artifacts/task3/` Task 4 использует напрямую, отдельной пересборки под него не нужно.
