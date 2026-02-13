# Generation Status Report (2026-02-13 09:07:41)

## Live Status
- Backend health: OK
- Batch job id range: 106318..108737
- Jobs: completed=1296, processing=1, pending=1123, failed=0 (total=2420)
- Questions in DB (current): 12008
- Generated so far in this batch (sum generated_count): 10368
- Requested total in this batch (sum payload.count): 19360
- Remaining requested (if all run): 8992
- Predicted final question total (assuming 8/8 continues): 21000

## Distribution
- Sum of weights (your list): 11215.0
- Distribution items: 149
- Items marked inferred (approx mapping): 80

## Mapping Coverage
- Unique segments in plan (need deficit): 143
- Missing segments right now: 0
- Full mapping export: reports/tus_distribution_mapping_20260213_090741.json

## Plan (From Queue Report)
- Queue report: reports/tus_queue_report_20260213_010721.json
- Existing questions at queue time: 1920
- Min desired total: 20008
- Desired total (rounded to multiple of batch size): 20008
- Total deficit (target-current across segments): 18290
- Estimated jobs: 2420 (batch_size=8)
- Auto-chunk targets tried: [10, 15, 20]
- Chunk target usage: {'20': 18, '10': 38, '15': 25}

## Prompt/Difficulty For Pending Jobs
- Pending jobs updated with custom_prompt_sections + custom_difficulty_levels: 1123/1123 prompts, 1123/1123 levels
- Prompt template used: Debahir
- Difficulty template used: varsayılan1

## Topic-Scoped History Check
- question_topic_links rows: 31498
- Evidence:
  - Logs show scope=topic for chunk jobs (topics>1) and scope=category_fallback when topic links are missing.
  - question_topic_links rows include chunk sub-topics + merged topic per generated question.
