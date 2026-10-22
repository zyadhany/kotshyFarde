"""
app/services/codeforces_api.py
──────────────────────────────
HTTP client for the Codeforces public API (https://codeforces.com/api/).

Features
--------
* Optional SHA-512 request signing (``use_auth=True``).
* Built-in rate-limiter (min 2 s between requests) to avoid IP bans.
* Helper functions for handle verification, submission querying, and
  contest-level problem-status aggregation.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from random import randint
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────
_BASE_URL = "https://codeforces.com/api"
_MIN_REQUEST_INTERVAL: float = 2.0  # seconds between consecutive calls

# Module-level timestamp of the last API call (simple rate-limiter)
_last_request_time: float = 0.0


# ── Internal helpers ──────────────────────────────────────────

def _rate_limit() -> None:
    """Block until at least ``_MIN_REQUEST_INTERVAL`` seconds have elapsed
    since the previous request."""
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


def _build_signed_params(method_name: str, params: Dict[str, str]) -> Dict[str, str]:
    """Return *params* augmented with ``apiKey``, ``time``, and ``apiSig``
    fields required by the Codeforces authenticated API.

    Signature algorithm (from CF docs):
        rand(6 digits) / methodName ? sorted-params # secret  → SHA-512
    """
    api_key = settings.CF_API_KEY
    api_secret = settings.CF_API_SECRET
    if not api_key or not api_secret:
        raise RuntimeError(
            "CF_API_KEY and CF_API_SECRET must be set in .env for authenticated requests."
        )

    rand = str(randint(100_000, 999_999))
    params["apiKey"] = api_key
    params["time"] = str(int(time.time()))

    # Sort params alphabetically by key
    sorted_params = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sig_raw = f"{rand}/{method_name}?{sorted_params}#{api_secret}"
    sig_hash = hashlib.sha512(sig_raw.encode("utf-8")).hexdigest()

    params["apiSig"] = f"{rand}{sig_hash}"
    return params


def _request(
    method_name: str,
    params: Optional[Dict[str, str]] = None,
    use_auth: bool = False,
) -> Any:
    """Execute a GET request against the Codeforces API and return the
    ``result`` field from the JSON response.

    Raises
    ------
    httpx.HTTPStatusError
        On non-2xx HTTP responses.
    RuntimeError
        When the CF API returns ``status != "OK"``.
    """
    _rate_limit()

    params = dict(params or {})
    if use_auth:
        params = _build_signed_params(method_name, params)

    url = f"{_BASE_URL}/{method_name}"
    logger.debug("CF API → GET %s  params=%s", url, params)

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()

    payload = resp.json()
    if payload.get("status") != "OK":
        comment = payload.get("comment", "unknown error")
        raise RuntimeError(f"Codeforces API error: {comment}")

    return payload.get("result")


# ── Public API ────────────────────────────────────────────────

def verify_handle(handle: str) -> bool:
    """Return ``True`` if *handle* corresponds to an existing Codeforces user."""
    try:
        result = _request("user.info", {"handles": handle})
        return bool(result)
    except (RuntimeError, httpx.HTTPStatusError):
        return False


def parse_problem_id(problem_str: str) -> Tuple[int, str]:
    """Parse a problem string like ``"158A"`` or ``"4C"`` into
    ``(contest_id, index)``.

    Supports an optional ``/`` separator (e.g. ``"158/A"``).

    Raises
    ------
    ValueError
        If the string does not match the expected pattern.
    """
    problem_str = problem_str.strip().replace("/", "")
    match = re.match(r"^(\d+)([A-Za-z]\d*)$", problem_str)
    if not match:
        raise ValueError(f"Invalid problem identifier: {problem_str!r}")
    return int(match.group(1)), match.group(2).upper()


def standardize_verdict(verdict: str) -> str:
    """Map a raw Codeforces verdict string to a normalised internal label."""
    mapping: Dict[str, str] = {
        "OK": "ACCEPTED",
        "WRONG_ANSWER": "WRONG_ANSWER",
        "TIME_LIMIT_EXCEEDED": "TLE",
        "MEMORY_LIMIT_EXCEEDED": "MLE",
        "RUNTIME_ERROR": "RUNTIME_ERROR",
        "COMPILATION_ERROR": "COMPILATION_ERROR",
        "PRESENTATION_ERROR": "PRESENTATION_ERROR",
        "CHALLENGED": "CHALLENGED",
        "SKIPPED": "SKIPPED",
        "TESTING": "TESTING",
    }
    return mapping.get(verdict, verdict)


def get_user_submissions(
    handle: str,
    use_auth: bool = False,
) -> List[Dict[str, Any]]:
    """Return the raw list of submissions for *handle*."""
    try:
        submissions: List[Dict[str, Any]] = _request(
            "user.status",
            {"handle": handle, "from": "1", "count": "10000"},
            use_auth=use_auth,
        )
        return submissions or []
    except (RuntimeError, httpx.HTTPStatusError) as exc:
        logger.warning("Failed to fetch submissions for %s: %s", handle, exc)
        return []


def get_problem_solve_status(
    handle: str,
    contest_id: int,
    index: str,
    deadline: Optional[datetime] = None,
    submissions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Check if *handle* solved the problem, and whether it was solved after *deadline*.

    Returns
    -------
    dict
        {
            "solved": bool,
            "after_deadline": bool,
            "solved_at": Optional[str],
        }
    """
    if submissions is None:
        submissions = get_user_submissions(handle)

    ok_submissions = []
    for sub in submissions:
        if sub.get("verdict") != "OK":
            continue
        prob = sub.get("problem", {})
        if prob.get("contestId") != contest_id:
            continue
        if prob.get("index", "").upper() != index.upper():
            continue
        ok_submissions.append(sub)

    if not ok_submissions:
        return {
            "solved": False,
            "after_deadline": False,
            "solved_at": None,
        }

    # Find earliest accepted submission timestamp
    earliest_sec = min(sub.get("creationTimeSeconds", 0) for sub in ok_submissions)
    solved_time = datetime.fromtimestamp(earliest_sec, tz=timezone.utc)

    after_deadline = False
    if deadline is not None:
        d = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=timezone.utc)
        # If any accepted submission was on or before deadline, it was solved on time
        has_ontime_solve = any(
            datetime.fromtimestamp(s.get("creationTimeSeconds", 0), tz=timezone.utc) <= d
            for s in ok_submissions
        )
        after_deadline = not has_ontime_solve

    return {
        "solved": True,
        "after_deadline": after_deadline,
        "solved_at": solved_time.isoformat(),
    }


def check_problem_solved(
    handle: str,
    contest_id: int,
    index: str,
    after_time: Optional[datetime] = None,
    deadline: Optional[datetime] = None,
    submissions: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """Return ``True`` if *handle* has an accepted submission for the given
    problem, optionally restricted to submissions **on or after** *after_time*.
    """
    info = get_problem_solve_status(
        handle=handle,
        contest_id=contest_id,
        index=index,
        deadline=deadline,
        submissions=submissions,
    )
    if not info["solved"]:
        return False
    if after_time is not None and info["solved_at"]:
        solved_time = datetime.fromisoformat(info["solved_at"])
        at = after_time if after_time.tzinfo is not None else after_time.replace(tzinfo=timezone.utc)
        if solved_time < at:
            return False
    return True


def get_contest_submissions(
    handle: str,
    contest_id: int,
    use_auth: bool = False,
) -> List[Dict[str, Any]]:
    """Return the raw list of submissions for *handle* in a specific contest."""
    submissions = get_user_submissions(handle, use_auth=use_auth)
    return [
        s for s in submissions
        if s.get("problem", {}).get("contestId") == contest_id
    ]


def get_contest_problems(
    contest_id: int,
    use_auth: bool = False,
) -> List[Dict[str, str]]:
    """Fetch the list of problems in a contest from Codeforces.

    Returns
    -------
    list of dicts
        Each element is a dict with ``{"index": <str>, "name": <str>}``,
        e.g. ``[{"index": "A", "name": "Theatre Square"}, ...]``.
    """
    try:
        standings = _request(
            "contest.standings",
            {"contestId": str(contest_id)},
            use_auth=use_auth,
        )
        raw_problems = standings.get("problems", []) if isinstance(standings, dict) else []
        return [
            {"index": str(p.get("index", "")), "name": str(p.get("name", ""))}
            for p in raw_problems
        ]
    except Exception as exc:
        logger.warning("Failed to fetch problems for contest %s: %s", contest_id, exc)
        return []


def get_contest_problems_status(
    handle: str,
    contest_id: int,
    use_auth: bool = False,
    deadline: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return a structured summary of problems solved by *handle* in a contest.

    Returns
    -------
    dict
        {
            "contest_id": int,
            "total_problems": int | None,
            "solved_count": int,
            "solved_problems": ["A", "B", ...],
            "after_deadline": bool,
            "per_problem": {"A": {"solved": bool, "attempts": int, "after_deadline": bool, "solved_at": str | None}, ...}
        }
    """
    contest_subs = get_contest_submissions(handle, contest_id, use_auth=use_auth)

    d = None
    if deadline is not None:
        d = deadline if deadline.tzinfo is not None else deadline.replace(tzinfo=timezone.utc)

    per_problem: Dict[str, Dict[str, Any]] = {}
    for sub in contest_subs:
        idx = sub.get("problem", {}).get("index", "?")
        entry = per_problem.setdefault(
            idx,
            {"solved": False, "attempts": 0, "after_deadline": False, "solved_at": None},
        )
        entry["attempts"] += 1
        if sub.get("verdict") == "OK":
            sub_time = datetime.fromtimestamp(sub.get("creationTimeSeconds", 0), tz=timezone.utc)
            curr_ts = entry.get("_earliest_ts")
            sub_ts = sub.get("creationTimeSeconds", 0)
            if not entry["solved"] or (curr_ts is not None and sub_ts < curr_ts):
                entry["solved"] = True
                entry["_earliest_ts"] = sub_ts
                entry["solved_at"] = sub_time.isoformat()
            if d is not None:
                # If at least one OK submission occurred on or before deadline, after_deadline is False
                if sub_time <= d:
                    entry["_has_ontime"] = True

    for entry in per_problem.values():
        entry.pop("_earliest_ts", None)
        if entry["solved"] and d is not None:
            entry["after_deadline"] = not entry.pop("_has_ontime", False)
        else:
            entry.pop("_has_ontime", None)

    solved = [idx for idx, info in per_problem.items() if info["solved"]]
    any_late = any(info.get("after_deadline", False) for info in per_problem.values() if info["solved"])

    # Try to fetch the total number of problems from contest.standings
    total_problems: Optional[int] = None
    try:
        contest_probs = get_contest_problems(contest_id, use_auth=use_auth)
        total_problems = len(contest_probs) if contest_probs else None
    except Exception:
        logger.debug("Could not fetch standings for contest %s", contest_id)

    return {
        "contest_id": contest_id,
        "total_problems": total_problems,
        "solved_count": len(solved),
        "solved_problems": sorted(solved),
        "after_deadline": any_late,
        "per_problem": per_problem,
    }
