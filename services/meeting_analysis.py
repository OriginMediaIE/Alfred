"""Deterministic, local post-meeting analysis with source evidence.

This is a conservative baseline analyzer, not a claim of LLM-grade semantic
understanding.  It recognizes explicit statement markers and creates only
proposals.  Crucially, transcript strings are never interpreted as system or
tool instructions and no side-effecting dependency is available here.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from src.meeting_contract import (
    ClaimEvidence,
    GeneratedMeetingClaim,
    MeetingAnalysisRequest,
    MeetingAnalysisResult,
    TranscriptionCancelled,
)


_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("decision", re.compile(r"^\s*(?:\[?decision\]?|decided)\s*[:\-]\s*(.+)$", re.I)),
    (
        "action_item",
        re.compile(r"^\s*(?:\[?action(?:\s+item)?\]?|todo)\s*[:\-]\s*(.+)$", re.I),
    ),
    ("question", re.compile(r"^\s*\[?question\]?\s*[:\-]\s*(.+)$", re.I)),
    ("risk", re.compile(r"^\s*\[?risk\]?\s*[:\-]\s*(.+)$", re.I)),
    (
        "follow_up_draft",
        re.compile(r"^\s*\[?follow[ -]?up\]?\s*[:\-]\s*(.+)$", re.I),
    ),
)


def _clean_statement(value: str, *, limit: int = 4000) -> str:
    text = " ".join(str(value or "").replace("\x00", " ").split())
    return text[:limit].strip()


class RuleBasedMeetingAnalyzer:
    """Offline fallback that extracts explicitly marked meeting statements."""

    name = "rule-based-local"
    version = "1.0"

    def __init__(self, *, max_claims: int = 200) -> None:
        if not 1 <= max_claims <= 1000:
            raise ValueError("max_claims must be between 1 and 1000")
        self.max_claims = max_claims

    @staticmethod
    def _evidence(segment) -> ClaimEvidence:
        return ClaimEvidence(
            segment_id=segment.id,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            speaker_label=segment.speaker_label,
        )

    def analyze(
        self,
        request: MeetingAnalysisRequest,
        *,
        cancel_requested: Callable[[], bool],
    ) -> MeetingAnalysisResult:
        claims: list[GeneratedMeetingClaim] = []
        warnings: list[str] = []
        usable = [segment for segment in request.segments if segment.text.strip()]
        if not usable:
            return MeetingAnalysisResult(
                claims=(),
                warnings=("No non-empty transcript segments were available",),
                analyzer=self.name,
                analyzer_version=self.version,
            )

        # A concise extractive overview remains labelled inferred and cites
        # every segment it uses.  It is not fed back as executable model text.
        overview_segments = usable[: min(3, len(usable))]
        overview = _clean_statement(" ".join(segment.text for segment in overview_segments), limit=700)
        if overview:
            claims.append(
                GeneratedMeetingClaim(
                    kind="summary",
                    text=overview,
                    evidence=tuple(self._evidence(segment) for segment in overview_segments),
                    inferred=True,
                    metadata={"method": "extractive"},
                )
            )

        for segment in usable:
            if cancel_requested():
                raise TranscriptionCancelled("Meeting analysis was cancelled")
            # Split explicit markers on lines so ordinary prose containing the
            # word "action" is not promoted to a proposal.
            for line in str(segment.text).splitlines() or [segment.text]:
                for kind, pattern in _MARKERS:
                    match = pattern.match(line)
                    if not match:
                        continue
                    statement = _clean_statement(match.group(1))
                    if not statement:
                        continue
                    claims.append(
                        GeneratedMeetingClaim(
                            kind=kind,
                            text=statement,
                            evidence=(self._evidence(segment),),
                            inferred=True,
                            metadata={"method": "explicit_marker"},
                        )
                    )
                    break
                if len(claims) >= self.max_claims:
                    warnings.append("Claim limit reached; remaining marked statements were omitted")
                    break
            if len(claims) >= self.max_claims:
                break

        return MeetingAnalysisResult(
            claims=tuple(claims[: self.max_claims]),
            warnings=tuple(warnings),
            analyzer=self.name,
            analyzer_version=self.version,
        )
