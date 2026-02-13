# Generation Status Report (2026-02-13 09:27:55)

## Live Status
- Backend health: OK
- Batch job id range: 106318..108737
- Jobs: completed=1334, processing=1, pending=1085, failed=0 (total=2420)
- Questions in DB (current): 12309
- Generated so far in this batch (sum generated_count): 10672
- Requested total in this batch (sum payload.count): 19360
- Remaining requested: 8688
- Predicted final question total (assuming 8/8 continues): 20997

## Distribution
- Sum of weights (your list): 11215.0
- Distribution items: 149
- Items marked inferred (approx mapping): 80

## Mapping Coverage
- Unique segments in plan (need deficit): 143
- Missing mappings: 0
- Full mapping export: reports/tus_distribution_mapping_20260213_090741.json

## Plan (From Queue Report)
- Queue report: reports/tus_queue_report_20260213_010721.json
- Existing questions at queue time: 1920
- Min desired total: 20008
- Total deficit (target-current across segments): 18290
- Estimated jobs: 2420 (batch_size=8)
- Auto-chunk targets tried: [10, 15, 20]
- Chunk target usage: {'20': 18, '10': 38, '15': 25}

## Prompt/Difficulty For Pending Jobs
- Pending jobs with custom_prompt_sections: 1085/1085
- Pending jobs with custom_difficulty_levels: 1085/1085
- Prompt template used (default): Debahir
- Difficulty template used (default): varsayılan1

## Topic-Scoped History Check
- question_topic_links rows: 32849
- Evidence:
  - backend.log includes lines like: scope=topic (topics>1) for chunk jobs, and scope=category_fallback as needed.
  - Recent questions show multiple topic links per question (chunk topic set).
