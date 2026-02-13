#!/usr/bin/env python3
"""
Re-queue generation jobs for specific segments using the same public admin endpoints
so we reuse the exact pipeline (direct vs. auto-chunk) and prompt/difficulty payloads.

Intended use:
  - User fixed processed_pdfs structure for a few broken categories.
  - User deleted questions for those categories and cancelled previous jobs.
  - Re-queue those categories according to the original TUS distribution plan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import requests
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[3]  # medical_quiz_app
DB_PATH = PROJECT_ROOT / "shared" / "data" / "quiz_v2.db"


@dataclass(frozen=True)
class SegmentTarget:
    source: str
    segment_title: str
    target_questions: int


def _admin_token(secret: str, user_id: int, username: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _get_default_template(conn: sqlite3.Connection, table: str, value_col: str) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(f"SELECT {value_col} FROM {table} WHERE is_default = 1 ORDER BY updated_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row or not row[0]:
        return {}
    try:
        obj = json.loads(row[0])
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _fetch_manifest_segment(api_base: str, source: str, segment_title: str) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/pdfs/manifests"
    data = requests.get(url, timeout=60).json()
    subjects = data.get("subjects", {})
    subj = subjects.get(source)
    if not subj:
        raise RuntimeError(f"Source not found in manifests: {source}")
    for vol in subj.get("volumes", []):
        for seg in vol.get("segments", []):
            if seg.get("title") == segment_title:
                return seg
    raise RuntimeError(f"Segment not found in manifests: {source} / {segment_title}")


def _score_chunks(chunks: list[dict[str, Any]]) -> tuple[float, float, int, int]:
    # chunks is preview payload list where each has page_count
    sizes = [int(c.get("page_count", 0) or 0) for c in chunks] or [0]
    spread = float(max(sizes) - min(sizes))
    mean = sum(sizes) / len(sizes)
    variance = sum((x - mean) ** 2 for x in sizes) / len(sizes)
    stdev = math.sqrt(variance)
    chunk_count = len(sizes)
    min_pages = min(sizes)
    # Prefer avoiding tiny chunks; last-chunk rebalance is already enforced but mid-chunks can still be small.
    penalty = 0
    if min_pages < 9:
        penalty = (9 - min_pages) * 1000
    return (penalty, spread, stdev, chunk_count)


def _choose_best_target_pages(api_base: str, token: str, source: str, segment_title: str, sub_segments: list[dict[str, Any]], candidates: list[int]) -> tuple[int, list[dict[str, Any]]]:
    url = f"{api_base.rstrip('/')}/admin/preview-chunks"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    best_target = None
    best_chunks: list[dict[str, Any]] = []
    best_score: tuple[float, float, float, int] | None = None

    for target in candidates:
        payload = {
            "source_material": source,
            "segment_title": segment_title,
            "sub_segments": [
                {
                    "title": s.get("title", ""),
                    "file": s.get("file", ""),
                    "page_count": int(s.get("page_count", 0) or 0),
                    "source_pdfs_list": s.get("source_pdfs_list"),
                    "merged_topics": s.get("merged_topics"),
                }
                for s in sub_segments
            ],
            "count": 8,
            "difficulty": 1,
            "multiplier": 1,
            "target_pages": int(target),
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"preview-chunks failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        chunks = data.get("chunks", []) or []
        score = _score_chunks(chunks)
        if best_score is None or score < best_score:
            best_score = score
            best_target = target
            best_chunks = chunks

    if best_target is None:
        raise RuntimeError("No valid target_pages candidates")
    return int(best_target), best_chunks


def _queue_direct(
    api_base: str,
    token: str,
    *,
    source: str,
    segment_title: str,
    jobs: int,
    prompt_sections: dict[str, Any],
    difficulty_levels: dict[str, Any],
    difficulty: int,
    batch_size: int,
) -> list[int]:
    url = f"{api_base.rstrip('/')}/admin/generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    job_ids: list[int] = []
    for _ in range(int(jobs)):
        payload = {
            "topic": segment_title,
            "source_material": source,
            "count": batch_size,
            "difficulty": difficulty,
            "all_topics": [segment_title],
            "main_header": segment_title,
            "source_pdfs_list": None,
            "custom_prompt_sections": prompt_sections,
            "custom_difficulty_levels": difficulty_levels,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if not resp.ok:
            raise RuntimeError(f"/admin/generate failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        msg = data.get("message", "")
        # message is like "Job queued (ID: 123)"
        job_id = None
        if isinstance(msg, str) and "ID:" in msg:
            try:
                job_id = int(msg.split("ID:", 1)[1].strip().rstrip(")"))
            except Exception:
                job_id = None
        if job_id is None:
            raise RuntimeError(f"Could not parse job id from response: {data}")
        job_ids.append(job_id)
    return job_ids


def _queue_auto_chunk(
    api_base: str,
    token: str,
    *,
    source: str,
    segment_title: str,
    sub_segments: list[dict[str, Any]],
    multiplier: int,
    target_pages: int,
    prompt_sections: dict[str, Any],
    difficulty_levels: dict[str, Any],
    difficulty: int,
    batch_size: int,
) -> list[int]:
    url = f"{api_base.rstrip('/')}/admin/auto-chunk-generate"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "source_material": source,
        "segment_title": segment_title,
        "sub_segments": [
            {
                "title": s.get("title", ""),
                "file": s.get("file", ""),
                "page_count": int(s.get("page_count", 0) or 0),
                "source_pdfs_list": s.get("source_pdfs_list"),
                "merged_topics": s.get("merged_topics"),
            }
            for s in sub_segments
        ],
        "count": batch_size,
        "difficulty": difficulty,
        "multiplier": int(multiplier),
        "target_pages": int(target_pages),
        "custom_prompt_sections": prompt_sections,
        "custom_difficulty_levels": difficulty_levels,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"/admin/auto-chunk-generate failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    job_ids: list[int] = []
    for chunk in data.get("chunks", []) or []:
        for jid in chunk.get("job_ids", []) or []:
            try:
                job_ids.append(int(jid))
            except Exception:
                pass
    if not job_ids:
        raise RuntimeError(f"auto-chunk did not return any job ids: {data}")
    return job_ids


def _prioritize_jobs(job_ids: list[int], *, created_at: str) -> None:
    if not job_ids:
        return
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        cur = conn.cursor()
        placeholders = ",".join(["?"] * len(job_ids))
        cur.execute(
            f"""
            UPDATE background_jobs
            SET created_at = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [created_at, created_at, *job_ids],
        )
        conn.commit()
    finally:
        conn.close()


def _read_segment_targets_from_report(report_path: Path, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], int]:
    obj = json.loads(report_path.read_text("utf-8"))
    targets: dict[tuple[str, str], int] = {}
    for seg in obj.get("segments", []) or []:
        key = (seg.get("source"), seg.get("segment_title"))
        if key in wanted:
            targets[key] = int(seg.get("target", 0) or 0)
    missing = [k for k in wanted if k not in targets]
    if missing:
        raise RuntimeError(f"Targets not found in report for: {missing}")
    return targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-base", default=os.getenv("MEDQUIZ_API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--jwt-secret", default=os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production"))
    ap.add_argument("--admin-user-id", type=int, default=1)
    ap.add_argument("--admin-username", default="admin")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--difficulty", type=int, default=1)
    ap.add_argument("--candidates", default="10,15,20")
    ap.add_argument("--queue-report", default=str(PROJECT_ROOT / "reports" / "tus_queue_report_20260213_010721.json"))
    ap.add_argument("--nsaii-questions", type=int, default=16)
    ap.add_argument("--prioritize-created-at", default="2026-02-13 00:00:01")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    candidates = [int(x.strip()) for x in args.candidates.split(",") if x.strip()]
    if not candidates:
        candidates = [15]

    wanted = {
        ("Farmakoloji", "OTAKOİDLER"),
        ("Kucuk_Stajlar", "Kulak-Burun-Boğaz Hastalıkları"),
        ("Kadin_Dogum", "Jinekolojik Onkoloji"),
    }
    targets = _read_segment_targets_from_report(Path(args.queue_report), wanted)

    # Load default templates so new jobs are deterministic (even if defaults later change).
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        prompt_sections = _get_default_template(conn, "prompt_templates", "sections")
        difficulty_levels = _get_default_template(conn, "difficulty_templates", "levels")
    finally:
        conn.close()

    token = _admin_token(args.jwt_secret, args.admin_user_id, args.admin_username)

    all_new_job_ids: list[int] = []

    # 1) Re-queue distribution-driven segments.
    for (source, segment_title), target_questions in targets.items():
        seg = _fetch_manifest_segment(args.api_base, source, segment_title)
        current = int(seg.get("question_count", 0) or 0)
        deficit = max(0, int(target_questions) - current)
        if deficit <= 0:
            continue

        sub_segments = seg.get("sub_segments") or []
        page_count = int(seg.get("page_count", 0) or 0)
        has_chunk = page_count > 20 and isinstance(sub_segments, list) and len(sub_segments) > 0

        if not has_chunk:
            jobs = int(math.ceil(deficit / args.batch_size))
            job_ids = _queue_direct(
                args.api_base,
                token,
                source=source,
                segment_title=segment_title,
                jobs=jobs,
                prompt_sections=prompt_sections,
                difficulty_levels=difficulty_levels,
                difficulty=args.difficulty,
                batch_size=args.batch_size,
            )
            all_new_job_ids.extend(job_ids)
            continue

        best_target_pages, preview_chunks = _choose_best_target_pages(
            args.api_base, token, source, segment_title, sub_segments, candidates
        )
        chunk_count = max(1, len(preview_chunks))
        multiplier = int(math.ceil(deficit / (args.batch_size * chunk_count)))
        job_ids = _queue_auto_chunk(
            args.api_base,
            token,
            source=source,
            segment_title=segment_title,
            sub_segments=sub_segments,
            multiplier=multiplier,
            target_pages=best_target_pages,
            prompt_sections=prompt_sections,
            difficulty_levels=difficulty_levels,
            difficulty=args.difficulty,
            batch_size=args.batch_size,
        )
        all_new_job_ids.extend(job_ids)

    # 2) Ensure NSAİİ exists (not part of distribution list; queue a small baseline).
    nsaii_target = max(0, int(args.nsaii_questions))
    if nsaii_target:
        seg = _fetch_manifest_segment(args.api_base, "Farmakoloji", "NSAİİ")
        current = int(seg.get("question_count", 0) or 0)
        deficit = max(0, nsaii_target - current)
        if deficit > 0:
            jobs = int(math.ceil(deficit / args.batch_size))
            job_ids = _queue_direct(
                args.api_base,
                token,
                source="Farmakoloji",
                segment_title="NSAİİ",
                jobs=jobs,
                prompt_sections=prompt_sections,
                difficulty_levels=difficulty_levels,
                difficulty=args.difficulty,
                batch_size=args.batch_size,
            )
            all_new_job_ids.extend(job_ids)

    # Prioritize these jobs ahead of the older pending queue.
    _prioritize_jobs(all_new_job_ids, created_at=args.prioritize_created_at)

    print(json.dumps({"queued_job_ids": all_new_job_ids, "count": len(all_new_job_ids)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

