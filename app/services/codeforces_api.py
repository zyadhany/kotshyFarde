"""
app/services/codeforces_api.py
──────────────────────────────
HTTP service and client for the Codeforces public & authenticated API (https://codeforces.com/api/).

Features
--------
* Class-based architecture (`CodeforcesService`) with connection pooling and reusable HTTP sessions.
* Optional SHA-512 request signing (`use_auth=True`).
* Built-in rate-limiter (min 2 s between requests) to avoid IP bans.
* Integrated with Kotchy's centralized CacheManager (`app.core.cache.cache`).
* Helper methods for handle verification, rating color/class lookup, submission querying,
  and contest-level problem-status aggregation.
* Singleton instance (`codeforces_service`) with exported module-level functional wrappers
  for 100% backwards compatibility across the application.
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

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────
_BASE_URL = "https://codeforces.com/api"
_MIN_REQUEST_INTERVAL: float = 2.0  # seconds between consecutive calls


# ── Forward declaration for test patching hook ───────────────
def _request(
    method_name: str,
    params: Optional[Dict[str, str]] = None,
    use_auth: bool = False,
) -> Any:
    """Execute a GET request against the Codeforces API and return the
    ``result`` field from the JSON response.

    Delegates to the singleton ``codeforces_service.request`` method,
    preserving compatibility with test suites that patch
    ``app.services.codeforces_api._request``.
    """
    return codeforces_service.request(method_name, params, use_auth=use_auth)


class CodeforcesService:
    """Encapsulates Codeforces API interactions, HTTP connection pooling,
    request signing, rate limiting, and result caching.
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        min_request_interval: float = _MIN_REQUEST_INTERVAL,
        timeout: float = 30.0,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.min_request_interval = min_request_interval
        self.timeout = timeout
        self.api_key = api_key
        self.api_secret = api_secret
        self._last_request_time: float = 0.0
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Lazy-loaded, reusable HTTPX client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the underlying HTTP client session if open."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __enter__(self) -> CodeforcesService:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ── Internal Request & Auth Helpers ─────────────────────────

    def rate_limit(self) -> None:
        """Block until at least ``min_request_interval`` seconds have elapsed
        since the previous request on this service instance."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.monotonic()

    def build_signed_params(self, method_name: str, params: Dict[str, str]) -> Dict[str, str]:
        """Return *params* augmented with ``apiKey``, ``time``, and ``apiSig``
        fields required by the Codeforces authenticated API.

        Signature algorithm (from CF docs):
            rand(6 digits) / methodName ? sorted-params # secret  → SHA-512
        """
        api_key = self.api_key or settings.CF_API_KEY
        api_secret = self.api_secret or settings.CF_API_SECRET
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

    def request(
        self,
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
        self.rate_limit()

        params_dict = dict(params or {})
        if use_auth:
            params_dict = self.build_signed_params(method_name, params_dict)

        url = f"{self.base_url}/{method_name}"
        logger.debug("CF API → GET %s  params=%s", url, params_dict)

        resp = self.client.get(url, params=params_dict)
        resp.raise_for_status()

        payload = resp.json()
        if payload.get("status") != "OK":
            comment = payload.get("comment", "unknown error")
            raise RuntimeError(f"Codeforces API error: {comment}")

        return payload.get("result")

    def _call_api(
        self,
        method_name: str,
        params: Optional[Dict[str, str]] = None,
        use_auth: bool = False,
    ) -> Any:
        """Invoke API request through the module-level `_request` function hook.
        This ensures test mocks on `app.services.codeforces_api._request` intercept
        service method calls seamlessly.
        """
        return _request(method_name, params, use_auth=use_auth)

    # ── User Profiles & Ratings ─────────────────────────────────

    def clear_user_ratings_cache(self) -> None:
        """Clear the in-memory user ratings and user info caches."""
        cache["user_ratings"].clear()
        cache["user_info"].clear()

    def get_user_info(
        self,
        handle: str,
        lifetime: Optional[int] = None,
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Fetch complete Codeforces user profile (rating, maxRating, rank, maxRank, etc.)
        and store in cache with lifetime (default: settings.CF_RATING_CACHE_LIFETIME = 1 hour).
        """
        if not handle or not handle.strip():
            return None

        clean_handle = handle.strip()
        cache_key = clean_handle.lower()
        effective_lifetime = lifetime if lifetime is not None else settings.CF_RATING_CACHE_LIFETIME

        if use_cache:
            cached = cache["user_info"].get(cache_key)
            if cached is not None:
                return cached if cached else None

        try:
            result = self._call_api("user.info", {"handles": clean_handle})
            if not result or not isinstance(result, list):
                return None
            user_info = result[0]
            if use_cache:
                cache["user_info"].add(cache_key, user_info, lifetime=effective_lifetime)
                rating = user_info.get("rating")
                if rating is not None:
                    cache["user_ratings"].add(cache_key, rating, lifetime=effective_lifetime)
            return user_info
        except (RuntimeError, httpx.HTTPStatusError) as exc:
            logger.warning("Failed to fetch user info for %s: %s", handle, exc)
            if use_cache:
                cache["user_info"].add(cache_key, {}, lifetime=effective_lifetime)
            return None

    def get_user_rating(
        self,
        handle: str,
        lifetime: Optional[int] = None,
        use_cache: bool = True,
    ) -> Optional[int]:
        """Fetch Codeforces rating for *handle* and store it in cache.

        Default lifetime is 1 hour (3600 seconds), loaded from ``settings.CF_RATING_CACHE_LIFETIME``.
        """
        if not handle or not handle.strip():
            return None

        clean_handle = handle.strip()
        cache_key = clean_handle.lower()
        effective_lifetime = lifetime if lifetime is not None else settings.CF_RATING_CACHE_LIFETIME

        if use_cache:
            cached = cache["user_ratings"].get(cache_key)
            if cached is not None:
                return cached

        info = self.get_user_info(clean_handle, lifetime=effective_lifetime, use_cache=use_cache)
        if info and "rating" in info:
            return info["rating"]
        return None

    def prefetch_cf_info(
        self,
        handles: List[str],
        lifetime: Optional[int] = None,
        use_cache: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """Batch-prefetch Codeforces user info for multiple handles in a single API call."""
        if not handles:
            return {}

        effective_lifetime = lifetime if lifetime is not None else settings.CF_RATING_CACHE_LIFETIME
        results: Dict[str, Dict[str, Any]] = {}
        missing_handles: List[str] = []

        for h in handles:
            if not h or not str(h).strip():
                continue
            clean = str(h).strip()
            key = clean.lower()
            if use_cache:
                cached = cache["user_info"].get(key)
                if cached is not None:
                    if cached:
                        results[key] = cached
                    continue
            if clean not in missing_handles:
                missing_handles.append(clean)

        if not missing_handles:
            return results

        # Codeforces user.info accepts semicolon-separated handles
        chunk_size = 500
        for i in range(0, len(missing_handles), chunk_size):
            chunk = missing_handles[i:i + chunk_size]
            handles_param = ";".join(chunk)
            try:
                api_res = self._call_api("user.info", {"handles": handles_param})
                if api_res and isinstance(api_res, list):
                    for user_data in api_res:
                        h_handle = str(user_data.get("handle", "")).strip().lower()
                        if h_handle:
                            results[h_handle] = user_data
                            if use_cache:
                                cache["user_info"].add(h_handle, user_data, lifetime=effective_lifetime)
                                rating = user_data.get("rating")
                                if rating is not None:
                                    cache["user_ratings"].add(h_handle, rating, lifetime=effective_lifetime)
            except Exception as exc:
                logger.warning("Failed to batch fetch CF user info: %s", exc)
                if len(chunk) > 1:
                    # If a combined batch fails (e.g. 1 invalid handle), try individually
                    for single_handle in chunk:
                        try:
                            single_res = self._call_api("user.info", {"handles": single_handle})
                            if single_res and isinstance(single_res, list) and single_res:
                                u_data = single_res[0]
                                h_handle = str(u_data.get("handle", "")).strip().lower()
                                if h_handle:
                                    results[h_handle] = u_data
                                    if use_cache:
                                        cache["user_info"].add(h_handle, u_data, lifetime=effective_lifetime)
                                        rating = u_data.get("rating")
                                        if rating is not None:
                                            cache["user_ratings"].add(h_handle, rating, lifetime=effective_lifetime)
                        except Exception:
                            if use_cache:
                                cache["user_info"].add(single_handle.lower(), {}, lifetime=effective_lifetime)
                elif len(chunk) == 1 and use_cache:
                    cache["user_info"].add(chunk[0].lower(), {}, lifetime=effective_lifetime)

        return results

    # ── Rating Styling & Badges ─────────────────────────────────

    @staticmethod
    def get_rating_class(rating: Any) -> str:
        """Return the Codeforces CSS color class for a given rating or rank.
        
        Pupil: Green (.cf-user-pupil)
        Specialist: Cyan (.cf-user-specialist)
        Expert: Blue (.cf-user-expert)
        """
        if rating is None or rating == "":
            return "cf-user-unrated"
        try:
            r = int(rating)
            if r < 1200:
                return "cf-user-newbie"
            if r < 1400:
                return "cf-user-pupil"
            if r < 1600:
                return "cf-user-specialist"
            if r < 1900:
                return "cf-user-expert"
            if r < 2100:
                return "cf-user-candidate-master"
            if r < 2300:
                return "cf-user-master"
            if r < 2400:
                return "cf-user-master"
            if r < 2600:
                return "cf-user-grandmaster"
            if r < 3000:
                return "cf-user-grandmaster"
            return "cf-user-legendary"
        except (ValueError, TypeError):
            pass

        rank_str = str(rating).strip().lower()
        if "legend" in rank_str or "tourist" in rank_str:
            return "cf-user-legendary"
        if "grandmaster" in rank_str:
            return "cf-user-grandmaster"
        if "candidate" in rank_str:
            return "cf-user-candidate-master"
        if "master" in rank_str:
            return "cf-user-master"
        if "expert" in rank_str:
            return "cf-user-expert"
        if "specialist" in rank_str:
            return "cf-user-specialist"
        if "pupil" in rank_str:
            return "cf-user-pupil"
        if "newbie" in rank_str:
            return "cf-user-newbie"
        return "cf-user-unrated"

    @staticmethod
    def get_rating_color(rating: Any) -> str:
        """Return the Codeforces hex color for a given rating or rank."""
        if rating is None or rating == "":
            return "#64748b"  # slate-500
        try:
            r = int(rating)
            if r < 1200:
                return "#808080"  # Newbie (gray)
            if r < 1400:
                return "#008000"  # Pupil (green)
            if r < 1600:
                return "#03a89e"  # Specialist (cyan)
            if r < 1900:
                return "#0000ff"  # Expert (blue)
            if r < 2100:
                return "#aa00aa"  # Candidate Master (purple)
            if r < 2400:
                return "#ff8c00"  # Master / IM (orange)
            return "#ff0000"      # Grandmaster / LGM (red)
        except (ValueError, TypeError):
            pass

        rank_str = str(rating).strip().lower()
        if "grandmaster" in rank_str or "legend" in rank_str or "tourist" in rank_str:
            return "#ff0000"
        if "candidate" in rank_str:
            return "#aa00aa"
        if "master" in rank_str:
            return "#ff8c00"
        if "expert" in rank_str:
            return "#0000ff"
        if "specialist" in rank_str:
            return "#03a89e"
        if "pupil" in rank_str:
            return "#008000"
        if "newbie" in rank_str:
            return "#808080"
        return "#64748b"

    @staticmethod
    def get_rating_title(rating: Any) -> str:
        """Return the Codeforces rank title for a given rating or rank."""
        if rating is None or rating == "":
            return "Unrated"
        try:
            r = int(rating)
            if r < 1200:
                return "Newbie"
            if r < 1400:
                return "Pupil"
            if r < 1600:
                return "Specialist"
            if r < 1900:
                return "Expert"
            if r < 2100:
                return "Candidate Master"
            if r < 2300:
                return "Master"
            if r < 2400:
                return "International Master"
            if r < 2600:
                return "Grandmaster"
            if r < 3000:
                return "International Grandmaster"
            return "Legendary Grandmaster"
        except (ValueError, TypeError):
            pass

        return str(rating).strip().title()

    def verify_handle(self, handle: str) -> bool:
        """Return ``True`` if *handle* corresponds to an existing Codeforces user."""
        info = self.get_user_info(handle)
        return info is not None

    @staticmethod
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

    @staticmethod
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

    # ── Submissions & Contests ──────────────────────────────────

    def clear_user_submissions_cache(self) -> None:
        """Clear the in-memory user submissions cache."""
        cache["user_submissions"].clear()
        cache["contest_submissions"].clear()

    def get_user_submissions(
        self,
        handle: str,
        use_auth: bool = False,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return the raw list of submissions for *handle*.

        Caches results in ``cache["user_submissions"]`` for ``settings.CF_SUBMISSIONS_CACHE_LIFETIME``
        (default: 30 seconds) to prevent hitting Codeforces rate limits during cohort checks.
        Set ``use_cache=False`` to bypass cache.
        """
        cache_key = (handle.strip().lower(), use_auth)
        if use_cache:
            cached = cache["user_submissions"].get(cache_key)
            if cached is not None:
                return cached

        try:
            submissions: List[Dict[str, Any]] = self._call_api(
                "user.status",
                {"handle": handle, "from": "1", "count": "10000"},
                use_auth=use_auth,
            )
            result = submissions or []
            if use_cache:
                cache["user_submissions"].add(
                    cache_key, result, lifetime=settings.CF_SUBMISSIONS_CACHE_LIFETIME
                )
            return result
        except (RuntimeError, httpx.HTTPStatusError) as exc:
            logger.warning("Failed to fetch submissions for %s: %s", handle, exc)
            return []

    def get_problem_solve_status(
        self,
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
            submissions = self.get_user_submissions(handle)

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
        self,
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
        info = self.get_problem_solve_status(
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
        self,
        handle: str,
        contest_id: int,
        use_auth: bool = False,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return the raw list of submissions for *handle* in a specific contest.

        For private/managed contests (use_auth=True), queries Codeforces' ``contest.status``
        endpoint directly, as ``user.status`` does not expose private/group contest submissions.
        Falls back to ``contest.status`` for public contests if ``user.status`` does not contain
        any submissions for this contest.
        """
        cache_key = (contest_id, handle.strip().lower(), use_auth)
        if use_cache:
            cached = cache["contest_submissions"].get(cache_key)
            if cached is not None:
                return cached

        if use_auth:
            try:
                status_resp = self._call_api(
                    "contest.status",
                    {"contestId": str(contest_id), "handle": handle},
                    use_auth=True,
                )
                result = status_resp if isinstance(status_resp, list) else []
                if use_cache:
                    cache["contest_submissions"].add(
                        cache_key, result, lifetime=settings.CF_SUBMISSIONS_CACHE_LIFETIME
                    )
                return result
            except Exception as exc:
                logger.warning(
                    "Failed to fetch contest submissions from contest.status for %s in contest %s: %s",
                    handle, contest_id, exc,
                )

        submissions = self.get_user_submissions(handle, use_auth=use_auth, use_cache=use_cache)
        matched = [
            s for s in submissions
            if s.get("problem", {}).get("contestId") == contest_id
        ]
        if not matched and not use_auth:
            try:
                status_resp = self._call_api(
                    "contest.status",
                    {"contestId": str(contest_id), "handle": handle},
                    use_auth=False,
                )
                if isinstance(status_resp, list) and status_resp:
                    matched = status_resp
            except Exception:
                pass

        if use_cache:
            cache["contest_submissions"].add(
                cache_key, matched, lifetime=settings.CF_SUBMISSIONS_CACHE_LIFETIME
            )
        return matched

    def clear_contest_submissions_cache(self) -> None:
        """Clear the in-memory contest submissions cache."""
        cache["contest_submissions"].clear()

    def clear_contest_problems_cache(self) -> None:
        """Clear the in-memory contest problems cache."""
        cache["contest_problems"].clear()

    def get_contest_problems(
        self,
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
        cache_key = (contest_id, use_auth)
        cached = cache["contest_problems"].get(cache_key)
        if cached is not None:
            return cached

        try:
            standings = self._call_api(
                "contest.standings",
                {"contestId": str(contest_id)},
                use_auth=use_auth,
            )
            raw_problems = standings.get("problems", []) if isinstance(standings, dict) else []
            result = [
                {"index": str(p.get("index", "")), "name": str(p.get("name", ""))}
                for p in raw_problems
            ]
            if result:
                cache["contest_problems"].add(
                    cache_key, result, lifetime=settings.CF_CONTEST_PROBLEMS_CACHE_LIFETIME
                )
            return result
        except Exception as exc:
            logger.warning("Failed to fetch problems for contest %s: %s", contest_id, exc)
            return []

    def get_contest_problems_status(
        self,
        handle: str,
        contest_id: int,
        use_auth: bool = False,
        deadline: Optional[datetime] = None,
        use_cache: bool = True,
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
        contest_subs = self.get_contest_submissions(handle, contest_id, use_auth=use_auth, use_cache=use_cache)

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
            contest_probs = self.get_contest_problems(contest_id, use_auth=use_auth)
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


# ── Global Singleton Service Instance ─────────────────────────
codeforces_service = CodeforcesService()


# ── Internal Compatibility Wrappers ───────────────────────────
def _rate_limit() -> None:
    codeforces_service.rate_limit()


def _build_signed_params(method_name: str, params: Dict[str, str]) -> Dict[str, str]:
    return codeforces_service.build_signed_params(method_name, params)


# ── Exported Module-level Functional Wrappers ──────────────────
clear_user_ratings_cache = codeforces_service.clear_user_ratings_cache
get_user_info = codeforces_service.get_user_info
get_user_rating = codeforces_service.get_user_rating
prefetch_cf_info = codeforces_service.prefetch_cf_info
get_rating_class = CodeforcesService.get_rating_class
get_rating_color = CodeforcesService.get_rating_color
get_rating_title = CodeforcesService.get_rating_title
verify_handle = codeforces_service.verify_handle
parse_problem_id = CodeforcesService.parse_problem_id
standardize_verdict = CodeforcesService.standardize_verdict
clear_user_submissions_cache = codeforces_service.clear_user_submissions_cache
get_user_submissions = codeforces_service.get_user_submissions
get_problem_solve_status = codeforces_service.get_problem_solve_status
check_problem_solved = codeforces_service.check_problem_solved
get_contest_submissions = codeforces_service.get_contest_submissions
clear_contest_submissions_cache = codeforces_service.clear_contest_submissions_cache
clear_contest_problems_cache = codeforces_service.clear_contest_problems_cache
get_contest_problems = codeforces_service.get_contest_problems
get_contest_problems_status = codeforces_service.get_contest_problems_status
