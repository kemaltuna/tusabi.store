# Generation Status Report (2026-02-13 09:06:14)

## Live Status
- Backend health: OK
- Batch job id range: 106318..108737
- Jobs: completed=1294, processing=1, pending=1125, failed=0 (total=2420)
- Questions in DB (current): 11992
- Generated so far in this batch (sum generated_count): 10352
- Requested total in this batch (sum payload.count): 19360
- Remaining requested (if all run): 9008
- Predicted final question total (assuming 8/8 continues): 21000

## Distribution Plan (From Queue Report)
- Queue report: reports/tus_queue_report_20260213_010721.json
- Distribution sum (your provided weights): 11215.0
- Existing questions at queue time: 1920
- Min desired total: 20008
- Desired total (rounded to multiple of batch size): 20008
- Total deficit (target-current across segments): 18290
- Estimated jobs: 2420 (batch_size=8)
- Auto-chunk targets tried: [10, 15, 20]
- Chunk target usage: {'20': 18, '10': 38, '15': 25}

## Mapping Coverage
- Segments in plan: 143
- Inferred topic mappings (count in report): 84
- Unresolved segments: 0 (script would have aborted otherwise)

## Prompt/Difficulty For Pending Jobs
- Pending jobs updated with custom_prompt_sections + custom_difficulty_levels: 1125/1125 prompts, 1125/1125 levels
- Prompt template used: Debahir
- Difficulty template used: varsayılan1

## Topic-Scoped History Check
- question_topic_links rows: 31426
- Latest scope=topic log: 2026-02-13 09:05:33,985 - root - INFO - 📜 [Job 107163] Found 55 previous question titles for context (scope=topic, topics=8, categories=['OTAKOİDLER']).
- Latest scope=category_fallback log: 2026-02-13 09:02:15,074 - root - INFO - 📜 [Job 107156] Found 55 previous question titles for context (scope=category_fallback, topics=1, categories=['OTAKOİDLER']).

## Inferred Topic List (From Report)
- Anatomi: 5
- Biyokimya: 5
- Dahiliye: 1
- Farmakoloji: 7
- Fizyoloji: 12
- Genel_Cerrahi: 18
- Kadin_Dogum: 3
- Kucuk_Stajlar: 8
- Mikrobiyoloji: 2
- Patoloji: 9
- Pediatri: 7
