# Task 7 Coverage Report

## Summary

- generated_at: `2026-04-16T12:33:25.995722+00:00`
- removed_documents: `elyra-noctis.md, the-hollow-eclipse.md, skyball.md`
- total_questions: `12`
- final_pass: `12`
- final_fail: `0`
- final_review_needed: `0`

## Well-covered topics

- `Who is Caelan Veyr's father?`
- `Who watches over Caelan Veyr?`
- `What is the Truce of Ash?`
- `What is the central temple of The Luminous Order?`
- `What is kept inside a Chamber of the Dreambound?`
- `Which island hosts the Wardens of Dawn lodge?`
- `Which leader's teachings were implemented by Veylspire to maintain order?`

## Gap findings

- `What ritual sends souls to the Veilward?` correctly fell back after removing the supporting document.
- `Какого цвета глаза у Elyra Noctis?` correctly fell back after removing the supporting document.
- `What creatures does the Hollow Eclipse create from its outer layer?` correctly fell back after removing the supporting document.
- `What kind of stadium is Skyball played in?` correctly fell back after removing the supporting document.
- `Сколько раундов играют в Skyball во время Endless Truce?` correctly fell back after removing the supporting document.

## Poorly covered topics

- No poorly covered topics detected in the current golden set.

## Irrelevant or weak sources

- No obvious source-mismatch cases detected for grounded answers.

## Recommendations

- Вернуть в рабочую KB документы по Elyra Noctis, The Hollow Eclipse и Skyball, если эти темы считаются обязательными для production-покрытия.
- Добавить явные golden-вопросы на соседние документы, где знания сейчас хранятся фрагментарно и retrieval легко уходит в косвенные источники.
- Если positive-кейсы продолжают уходить в review или fail из-за источников, ужесточить критерии выбора top-k или расширить фактическое описание в оставшихся документах.
