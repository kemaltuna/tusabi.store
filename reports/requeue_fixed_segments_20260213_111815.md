# Requeue Fixed Segments Report (2026-02-13 11:18:15)

## Queued
Re-queued via the same pipeline endpoints:
- /admin/auto-chunk-generate (Parçala)
- /admin/generate (direct category)

Job ranges:
- Farmakoloji / OTAKOİDLER: 108738..108753 (16 job => 128 soru)
- Kadın_Doğum / Jinekolojik Onkoloji: 108754..108777 (24 job => 192 soru)
- Küçük_Stajlar / Kulak-Burun-Boğaz Hastalıkları: 108778..108788 (11 job => 88 soru)
- Farmakoloji / NSAİİ: 108789..108790 (2 job => 16 soru, baseline)

## Priority
- Set created_at=updated_at='2026-02-13 00:00:01' for 108738..108790 so worker picks these next.

## Templates
- Prompt template: Debahir (default) embedded into each new job payload
- Difficulty template: varsayılan1 (default) embedded
- difficulty=1 (ORTA), count/job=8

## Live Status (This Requeue Set)
- status breakdown: completed=5, pending=47, processing=1
- failures: 0
- total questions in DB now: 13336

Per-category statuses:
- Jinekolojik Onkoloji: pending=24
- Kulak-Burun-Boğaz Hastalıkları: pending=11
- NSAİİ: pending=2
- OTAKOİDLER: completed=5
- OTAKOİDLER: pending=10
- OTAKOİDLER: processing=1
