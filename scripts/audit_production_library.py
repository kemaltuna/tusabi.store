#!/usr/bin/env python3
"""
Audit Production Library (processed_pdfs + manifests + medquiz_library.json)

Goal:
- Catch structural issues that break production generation/quiz flows:
  - Missing files referenced by manifests/library
  - Page-count mismatches between manifest ranges and actual PDFs
  - Sub-segment range overlaps/gaps/out-of-range
  - Orphan PDFs on disk not referenced by the corresponding manifest
  - Title mismatches: sub-segment title not found in the first N pages (heuristic)

Run (recommended):
  ./venv/bin/python scripts/audit_production_library.py --check-titles --title-pages 2
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _normalize_for_match(text: str) -> str:
    if not text:
        return ""
    # Normalize common unicode digits (subscript/superscript) that appear in anatomy PDFs.
    digit_map = {
        "\u2080": "0",  # subscript 0
        "\u2081": "1",  # subscript 1
        "\u2082": "2",  # subscript 2
        "\u2083": "3",  # subscript 3
        "\u2084": "4",  # subscript 4
        "\u2085": "5",  # subscript 5
        "\u2086": "6",  # subscript 6
        "\u2087": "7",  # subscript 7
        "\u2088": "8",  # subscript 8
        "\u2089": "9",  # subscript 9
        "\u2070": "0",  # superscript 0
        "\u00b9": "1",  # superscript 1
        "\u00b2": "2",  # superscript 2
        "\u00b3": "3",  # superscript 3
        "\u2074": "4",  # superscript 4
        "\u2075": "5",  # superscript 5
        "\u2076": "6",  # superscript 6
        "\u2077": "7",  # superscript 7
        "\u2078": "8",  # superscript 8
        "\u2079": "9",  # superscript 9
    }
    for k, v in digit_map.items():
        text = text.replace(k, v)
    tr_map = {
        "\u0131": "i",  # dotless i
        "\u0130": "i",  # dotted I
        "I": "i",
        "\u011f": "g",
        "\u011e": "g",
        "\u00fc": "u",
        "\u00dc": "u",
        "\u015f": "s",
        "\u015e": "s",
        "\u00f6": "o",
        "\u00d6": "o",
        "\u00e7": "c",
        "\u00c7": "c",
    }
    for k, v in tr_map.items():
        text = text.replace(k, v)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass(frozen=True)
class AuditIssue:
    issue_type: str
    severity: str  # "error" | "warn"
    manifest: str
    subject: str
    volume: str
    segment_title: str = ""
    subsegment_title: str = ""
    file: str = ""
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "manifest": self.manifest,
            "subject": self.subject,
            "volume": self.volume,
            "segment_title": self.segment_title,
            "subsegment_title": self.subsegment_title,
            "file": self.file,
            "details": self.details,
        }


def _iter_manifests(processed_dir: Path) -> Iterable[Path]:
    # Expected layout: shared/processed_pdfs/<Subject>/<Volume>/manifest.json
    for manifest in processed_dir.glob("*/*/manifest.json"):
        yield manifest


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf_open(path: Path):
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        raise RuntimeError(
            "PyMuPDF (fitz) not available. Run with venv: ./venv/bin/python scripts/audit_production_library.py"
        ) from e
    return fitz.open(path)


def _pdf_page_count(path: Path) -> Optional[int]:
    try:
        with _pdf_open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return None


def _pdf_first_pages_text(path: Path, pages: int) -> str:
    if pages <= 0:
        return ""
    try:
        with _pdf_open(path) as doc:
            n = min(int(doc.page_count), pages)
            out = []
            for i in range(n):
                out.append(doc.load_page(i).get_text("text") or "")
            return "\n".join(out)
    except Exception:
        return ""

def _extract_first_page_preview(path: Path, max_lines: int = 3, max_chars: int = 180) -> str:
    """
    Best-effort: extract a short, human-readable preview from the first page.
    Used to quickly spot 'wrong chapter inside PDF' cases.
    """
    raw = _pdf_first_pages_text(path, 1)
    if not raw:
        return ""

    skip_norm = {
        "tus hazirlik merkezleri",
        "yusuf kemal",
        "yusuf kemal tuna",
        "tuna",
    }

    lines: List[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        # Skip bullets / separators
        if s in {"\u2022", "-", "\u2013", "\u2014"}:
            continue
        n = _normalize_for_match(s)
        if not n:
            continue
        if n.isdigit():
            continue
        if n in skip_norm:
            continue
        # Skip long numeric IDs
        if len(n) >= 10 and n.isdigit():
            continue
        lines.append(s)
        if len(lines) >= max_lines:
            break

    preview = " | ".join(lines)
    if len(preview) > max_chars:
        preview = preview[: max_chars - 3].rstrip() + "..."
    return preview


def _range_len(rng: List[int]) -> Optional[int]:
    if not isinstance(rng, list) or len(rng) != 2:
        return None
    try:
        a = int(rng[0])
        b = int(rng[1])
    except Exception:
        return None
    if b < a:
        return None
    return b - a + 1


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def audit(
    project_root: Path,
    check_titles: bool,
    title_pages: int,
    max_manifests: Optional[int],
    include_orphans: bool,
) -> Tuple[Dict[str, Any], List[AuditIssue]]:
    shared_dir = project_root / "shared"
    processed_dir = shared_dir / "processed_pdfs"
    reports_dir = project_root / "reports"

    issues: List[AuditIssue] = []

    manifest_paths = sorted(_iter_manifests(processed_dir))
    if max_manifests:
        manifest_paths = manifest_paths[: max_manifests]

    referenced_files_by_volume: Dict[Tuple[str, str], set] = {}
    disk_pdfs_by_volume: Dict[Tuple[str, str], set] = {}

    # 1) Manifest-level checks
    for manifest_path in manifest_paths:
        subject = manifest_path.parent.parent.name
        volume = manifest_path.parent.name
        manifest_rel = _rel(manifest_path, project_root)

        try:
            manifest = _read_json(manifest_path)
        except Exception as e:
            issues.append(
                AuditIssue(
                    issue_type="manifest_json_error",
                    severity="error",
                    manifest=manifest_rel,
                    subject=subject,
                    volume=volume,
                    details=str(e),
                )
            )
            continue

        segments = manifest.get("segments", [])
        if not isinstance(segments, list):
            issues.append(
                AuditIssue(
                    issue_type="manifest_bad_structure",
                    severity="error",
                    manifest=manifest_rel,
                    subject=subject,
                    volume=volume,
                    details="manifest.segments is not a list",
                )
            )
            continue

        volume_key = (subject, volume)
        referenced = referenced_files_by_volume.setdefault(volume_key, set())

        for seg in segments:
            if not isinstance(seg, dict):
                continue
            seg_type = (seg.get("type") or "").strip().lower()
            # Keep non-main types visible: they tend to create phantom UI nodes.
            if seg_type and seg_type != "main":
                issues.append(
                    AuditIssue(
                        issue_type="unknown_segment_type",
                        severity="warn",
                        manifest=manifest_rel,
                        subject=subject,
                        volume=volume,
                        segment_title=str(seg.get("title") or ""),
                        details=f"segment.type={seg_type!r}",
                    )
                )
                continue

            seg_title = str(seg.get("title") or "")
            seg_file = str(seg.get("file") or "")
            if not seg_file:
                issues.append(
                    AuditIssue(
                        issue_type="segment_missing_file_field",
                        severity="error",
                        manifest=manifest_rel,
                        subject=subject,
                        volume=volume,
                        segment_title=seg_title,
                        details="segment.file is empty",
                    )
                )
                continue

            referenced.add(seg_file)
            seg_path = shared_dir / seg_file
            if not seg_path.exists():
                issues.append(
                    AuditIssue(
                        issue_type="missing_pdf",
                        severity="error",
                        manifest=manifest_rel,
                        subject=subject,
                        volume=volume,
                        segment_title=seg_title,
                        file=seg_file,
                        details="segment PDF does not exist on disk",
                    )
                )
                continue

            # Segment PDFs are sometimes extracted using pages_raw, sometimes pages_buffered.
            # Treat mismatch only if it matches neither.
            seg_expected_raw = _range_len(seg.get("pages_raw") or [])
            seg_expected_buf = _range_len(seg.get("pages_buffered") or [])
            seg_actual = _pdf_page_count(seg_path)
            if seg_actual and (
                (seg_expected_raw and seg_actual != seg_expected_raw)
                and (seg_expected_buf and seg_actual != seg_expected_buf)
                or ((seg_expected_raw is None) and seg_expected_buf and seg_actual != seg_expected_buf)
                or ((seg_expected_buf is None) and seg_expected_raw and seg_actual != seg_expected_raw)
            ):
                issues.append(
                    AuditIssue(
                        issue_type="page_count_mismatch",
                        severity="warn",
                        manifest=manifest_rel,
                        subject=subject,
                        volume=volume,
                        segment_title=seg_title,
                        file=seg_file,
                        details=(
                            f"segment expected_raw={seg_expected_raw}, expected_buffered={seg_expected_buf}, "
                            f"actual_pages={seg_actual}"
                        ),
                    )
                )

            if check_titles:
                title_norm = _normalize_for_match(seg_title)
                if title_norm:
                    text_norm = _normalize_for_match(_pdf_first_pages_text(seg_path, title_pages))
                    if text_norm and title_norm not in text_norm:
                        issues.append(
                            AuditIssue(
                                issue_type="title_mismatch",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                file=seg_file,
                                details=f"segment title not found in first {title_pages} page(s)",
                            )
                        )

            sub_segments = seg.get("sub_segments", []) or []
            if not isinstance(sub_segments, list):
                issues.append(
                    AuditIssue(
                        issue_type="segment_bad_sub_segments",
                        severity="error",
                        manifest=manifest_rel,
                        subject=subject,
                        volume=volume,
                        segment_title=seg_title,
                        details="segment.sub_segments is not a list",
                    )
                )
                continue

            # Range validation: subsegments are expected to be inside pages_raw range (source-absolute).
            seg_raw = seg.get("pages_raw", []) or []
            seg_raw_start = seg_raw[0] if isinstance(seg_raw, list) and len(seg_raw) == 2 else None
            seg_raw_end = seg_raw[1] if isinstance(seg_raw, list) and len(seg_raw) == 2 else None

            # Collect ranges for overlap/gap checks
            ranges: List[Tuple[int, int, str, str]] = []

            for sub in sub_segments:
                if not isinstance(sub, dict):
                    continue
                sub_title = str(sub.get("title") or "")
                sub_file = str(sub.get("file") or "")
                sub_pages = sub.get("pages", []) or []

                if not sub_file:
                    issues.append(
                        AuditIssue(
                            issue_type="subsegment_missing_file_field",
                            severity="error",
                            manifest=manifest_rel,
                            subject=subject,
                            volume=volume,
                            segment_title=seg_title,
                            subsegment_title=sub_title,
                            details="subsegment.file is empty",
                        )
                    )
                    continue

                referenced.add(sub_file)
                sub_path = shared_dir / sub_file
                if not sub_path.exists():
                    issues.append(
                        AuditIssue(
                            issue_type="missing_pdf",
                            severity="error",
                            manifest=manifest_rel,
                            subject=subject,
                            volume=volume,
                            segment_title=seg_title,
                            subsegment_title=sub_title,
                            file=sub_file,
                            details="sub-segment PDF does not exist on disk",
                        )
                    )
                    continue

                expected = _range_len(sub_pages)
                actual = _pdf_page_count(sub_path)
                if expected and actual and expected != actual:
                    issues.append(
                        AuditIssue(
                            issue_type="page_count_mismatch",
                            severity="warn",
                            manifest=manifest_rel,
                            subject=subject,
                            volume=volume,
                            segment_title=seg_title,
                            subsegment_title=sub_title,
                            file=sub_file,
                            details=f"subsegment expected_pages={expected}, actual_pages={actual}",
                        )
                    )

                if check_titles:
                    title_norm = _normalize_for_match(sub_title)
                    if title_norm:
                        text_norm = _normalize_for_match(_pdf_first_pages_text(sub_path, title_pages))
                        if text_norm and title_norm not in text_norm:
                            preview = _extract_first_page_preview(sub_path)
                            issues.append(
                                AuditIssue(
                                    issue_type="title_mismatch",
                                    severity="warn",
                                    manifest=manifest_rel,
                                    subject=subject,
                                    volume=volume,
                                    segment_title=seg_title,
                                    subsegment_title=sub_title,
                                    file=sub_file,
                                    details=(
                                        f"subsegment title not found in first {title_pages} page(s)"
                                        + (f"; first_page_preview={preview!r}" if preview else "")
                                    ),
                                )
                            )

                if isinstance(sub_pages, list) and len(sub_pages) == 2:
                    try:
                        a = int(sub_pages[0])
                        b = int(sub_pages[1])
                        ranges.append((a, b, sub_title, sub_file))
                        if seg_raw_start is not None and a < int(seg_raw_start):
                            issues.append(
                                AuditIssue(
                                    issue_type="subsegment_out_of_range",
                                    severity="warn",
                                    manifest=manifest_rel,
                                    subject=subject,
                                    volume=volume,
                                    segment_title=seg_title,
                                    subsegment_title=sub_title,
                                    file=sub_file,
                                    details=f"subsegment starts before segment.pages_raw start ({a} < {seg_raw_start})",
                                )
                            )
                        if seg_raw_end is not None and b > int(seg_raw_end):
                            issues.append(
                                AuditIssue(
                                    issue_type="subsegment_out_of_range",
                                    severity="warn",
                                    manifest=manifest_rel,
                                    subject=subject,
                                    volume=volume,
                                    segment_title=seg_title,
                                    subsegment_title=sub_title,
                                    file=sub_file,
                                    details=f"subsegment ends after segment.pages_raw end ({b} > {seg_raw_end})",
                                )
                            )
                    except Exception:
                        issues.append(
                            AuditIssue(
                                issue_type="subsegment_bad_pages",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                subsegment_title=sub_title,
                                file=sub_file,
                                details=f"subsegment.pages is not a valid [start,end] pair: {sub_pages!r}",
                            )
                        )

            # Overlap / gap checks
            if ranges:
                ranges.sort(key=lambda x: (x[0], x[1], x[2]))
                prev_end = None
                for (a, b, sub_title, sub_file) in ranges:
                    if prev_end is not None and a <= prev_end:
                        issues.append(
                            AuditIssue(
                                issue_type="subsegment_overlap",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                subsegment_title=sub_title,
                                file=sub_file,
                                details=f"overlap: start={a} <= prev_end={prev_end}",
                            )
                        )
                    if prev_end is not None and a > prev_end + 1:
                        issues.append(
                            AuditIssue(
                                issue_type="subsegment_gap",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                subsegment_title=sub_title,
                                file=sub_file,
                                details=f"gap: start={a} > prev_end+1={prev_end + 1}",
                            )
                        )
                    prev_end = max(prev_end or b, b)

                # Coverage heuristic: ranges should start/end at segment.pages_raw
                try:
                    if seg_raw_start is not None and ranges[0][0] != int(seg_raw_start):
                        issues.append(
                            AuditIssue(
                                issue_type="subsegment_coverage",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                details=f"first subsegment start={ranges[0][0]} != segment.pages_raw start={seg_raw_start}",
                            )
                        )
                    if seg_raw_end is not None and ranges[-1][1] != int(seg_raw_end):
                        issues.append(
                            AuditIssue(
                                issue_type="subsegment_coverage",
                                severity="warn",
                                manifest=manifest_rel,
                                subject=subject,
                                volume=volume,
                                segment_title=seg_title,
                                details=f"last subsegment end={ranges[-1][1]} != segment.pages_raw end={seg_raw_end}",
                            )
                        )
                except Exception:
                    pass

        if include_orphans:
            # Snapshot disk PDFs for this volume for orphan detection.
            volume_dir = manifest_path.parent
            all_pdfs = set()
            for pdf in volume_dir.rglob("*.pdf"):
                # Store as manifest-style relative path: processed_pdfs/...
                try:
                    rel = pdf.relative_to(shared_dir)
                    all_pdfs.add(str(rel).replace("\\", "/"))
                except Exception:
                    continue
            disk_pdfs_by_volume[volume_key] = all_pdfs

    # 2) Orphan PDF checks per volume
    if include_orphans:
        for volume_key, disk_set in disk_pdfs_by_volume.items():
            referenced = referenced_files_by_volume.get(volume_key, set())
            subject, volume = volume_key
            # Ignore manifest files list itself; just compare PDFs.
            orphans = sorted(p for p in disk_set if p not in referenced)
            for orphan in orphans:
                issues.append(
                    AuditIssue(
                        issue_type="orphan_pdf",
                        severity="warn",
                        manifest=f"shared/processed_pdfs/{subject}/{volume}/manifest.json",
                        subject=subject,
                        volume=volume,
                        file=orphan,
                        details="PDF exists on disk but is not referenced by manifest.json",
                    )
                )

    # 3) medquiz_library.json sanity
    lib_path = shared_dir / "data" / "medquiz_library.json"
    if lib_path.exists():
        try:
            lib = _read_json(lib_path)
        except Exception as e:
            issues.append(
                AuditIssue(
                    issue_type="library_json_error",
                    severity="error",
                    manifest=_rel(lib_path, project_root),
                    subject="",
                    volume="",
                    details=str(e),
                )
            )
            lib = None

        if isinstance(lib, dict):
            seen_paths = Counter()
            for source, payload in lib.items():
                topics = (payload or {}).get("topics", [])
                if not isinstance(topics, list):
                    continue
                for t in topics:
                    if not isinstance(t, dict):
                        continue
                    path = t.get("path") or ""
                    if not path:
                        issues.append(
                            AuditIssue(
                                issue_type="library_missing_path",
                                severity="warn",
                                manifest=_rel(lib_path, project_root),
                                subject=source,
                                volume="",
                                file="",
                                details=f"topic={t.get('topic')!r} missing path",
                            )
                        )
                        continue
                    seen_paths[path] += 1
                    if not str(path).startswith("shared/processed_pdfs/"):
                        issues.append(
                            AuditIssue(
                                issue_type="library_bad_path_prefix",
                                severity="warn",
                                manifest=_rel(lib_path, project_root),
                                subject=source,
                                volume="",
                                file=str(path),
                                details="topic path should start with shared/processed_pdfs/",
                            )
                        )
                    abs_path = project_root / str(path)
                    if not abs_path.exists():
                        issues.append(
                            AuditIssue(
                                issue_type="library_missing_pdf",
                                severity="error",
                                manifest=_rel(lib_path, project_root),
                                subject=source,
                                volume="",
                                file=str(path),
                                details=f"topic={t.get('topic')!r} file missing on disk",
                            )
                        )

            for path, count in seen_paths.items():
                if count > 1:
                    issues.append(
                        AuditIssue(
                            issue_type="library_duplicate_path",
                            severity="warn",
                            manifest=_rel(lib_path, project_root),
                            subject="",
                            volume="",
                            file=str(path),
                            details=f"path appears {count} times in medquiz_library.json",
                        )
                    )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "processed_dir": str((project_root / "shared" / "processed_pdfs").resolve()),
        "manifests_scanned": len(manifest_paths),
        "issues_total": len(issues),
        "issues_by_type": dict(Counter(i.issue_type for i in issues)),
        "issues_by_severity": dict(Counter(i.severity for i in issues)),
    }
    return summary, issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production library for structural PDF/manifest issues.")
    parser.add_argument("--check-titles", action="store_true", help="Heuristic: verify titles appear in first N pages.")
    parser.add_argument("--title-pages", type=int, default=2, help="How many pages to scan for the title (default: 2).")
    parser.add_argument("--max-manifests", type=int, default=0, help="Limit manifest scan (0 = no limit).")
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help="Report PDFs on disk that are not referenced by manifest.json (can be noisy).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="Output report path (default: reports/library_audit_<timestamp>.json).",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    max_manifests = args.max_manifests or None

    summary, issues = audit(
        project_root=project_root,
        check_titles=bool(args.check_titles),
        title_pages=int(args.title_pages),
        max_manifests=max_manifests,
        include_orphans=bool(args.include_orphans),
    )

    out_path = Path(args.out) if args.out else (project_root / "reports" / f"library_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary,
        "issues": [i.to_dict() for i in issues],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Console summary
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nReport written: {out_path}")

    # Non-zero exit only on hard errors
    hard_errors = [i for i in issues if i.severity == "error"]
    return 1 if hard_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
