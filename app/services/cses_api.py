"""
app/services/cses_api.py
────────────────────────
CSES Problem Set scraping, session authentication, problem metadata caching,
and student solve checking.
Integrated with Kotchy's centralized CacheManager (`app.core.cache.cache`)
in the same pattern as `app/services/codeforces_api.py`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

from app.core.cache import cache
from app.core.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ── Dynamic Cache Namespaces ──────────────────────────────────
# cache["cses_problem_names"]: pid -> problem name
# cache["cses_user_solved"]: cses_id -> list of solved task IDs


class _ProblemNamesCacheProxy(dict):
    """Dictionary-compatible proxy over `cache['cses_problem_names']`."""

    def __getitem__(self, key: Any) -> str:
        val = cache["cses_problem_names"].get(str(key))
        if val is None:
            raise KeyError(key)
        return val

    def get(self, key: Any, default: Any = None) -> Any:
        val = cache["cses_problem_names"].get(str(key))
        return val if val is not None else default

    def __setitem__(self, key: Any, value: Any) -> None:
        cache["cses_problem_names"].add(
            str(key),
            value,
            lifetime=settings.CSES_PROBLEM_NAMES_CACHE_LIFETIME,
        )

    def __contains__(self, key: Any) -> bool:
        return cache["cses_problem_names"].has(str(key))

    def __len__(self) -> int:
        prefix = "cses_problem_names:"
        store = getattr(cache.backend, "_store", {})
        return sum(1 for k in store if k.startswith(prefix))

    def clear(self) -> None:
        cache["cses_problem_names"].clear()


class _UserSolvedCacheProxy(dict):
    """Dictionary-compatible proxy over `cache['cses_user_solved']`."""

    def __getitem__(self, key: Any) -> Any:
        val = cache["cses_user_solved"].get(str(key))
        if val is None:
            raise KeyError(key)
        return (0.0, set(val))

    def get(self, key: Any, default: Any = None) -> Any:
        val = cache["cses_user_solved"].get(str(key))
        if val is not None:
            return (0.0, set(val))
        return default

    def __setitem__(self, key: Any, value: Any) -> None:
        if isinstance(value, tuple) and len(value) == 2:
            _, s = value
            data = list(s)
        else:
            data = list(value)
        cache["cses_user_solved"].add(
            str(key),
            data,
            lifetime=settings.CSES_SOLVED_CACHE_LIFETIME,
        )

    def __contains__(self, key: Any) -> bool:
        return cache["cses_user_solved"].has(str(key))

    def clear(self) -> None:
        cache["cses_user_solved"].clear()


# Export proxies for backwards compatibility
_PROBLEM_NAMES_CACHE = _ProblemNamesCacheProxy()
_USER_SOLVED_CACHE = _UserSolvedCacheProxy()


# ── Cache Management Helpers ──────────────────────────────────

def clear_problem_names_cache() -> None:
    """Clear the cached CSES problem names."""
    cache["cses_problem_names"].clear()


def clear_user_solved_cache() -> None:
    """Clear the cached CSES student solved problems."""
    cache["cses_user_solved"].clear()


def clear_cses_cache() -> None:
    """Clear all CSES-related cached namespaces."""
    clear_problem_names_cache()
    clear_user_solved_cache()


class CSESService:
    """Manages CSES session authentication, problemset metadata, and solve checking."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._logged_in = False
        self._warmed_up = False

    # ── Authentication & Session Management ─────────────────────

    def login(self) -> bool:
        """Authenticate with CSES using coach/bot credentials."""
        username = settings.CSES_USERNAME
        password = settings.CSES_PASSWORD

        if not username or not password:
            logger.warning("CSES credentials (CSES_USERNAME, CSES_PASSWORD) are not configured.")
            return False

        try:
            # 1. Fetch CSRF token from login page
            login_page_url = "https://cses.fi/login"
            resp = self.session.get(login_page_url, timeout=15)
            if resp.status_code != 200:
                logger.error("Failed to load CSES login page, status=%d", resp.status_code)
                return False

            soup = BeautifulSoup(resp.text, "html.parser")
            csrf_input = soup.find("input", {"name": "csrf_token"})
            if not csrf_input or not csrf_input.get("value"):
                logger.error("Could not find csrf_token on CSES login page.")
                return False

            csrf_token = csrf_input["value"]

            # 2. POST login payload
            payload = {
                "csrf_token": csrf_token,
                "nick": username,
                "pass": password,
            }
            post_resp = self.session.post(
                login_page_url,
                data=payload,
                allow_redirects=True,
                timeout=15,
            )

            # 3. Verify login success
            resp_html = post_resp.text
            if "Logout" in resp_html or "Log out" in resp_html or "/logout" in resp_html:
                self._logged_in = True
                logger.info("Successfully authenticated with CSES as %s.", username)
                return True

            logger.warning("CSES login failed. Check CSES_USERNAME and CSES_PASSWORD.")
            self._logged_in = False
            return False

        except Exception as exc:
            logger.error("Exception during CSES login: %s", exc)
            self._logged_in = False
            return False

    def _authenticated_get(self, url: str) -> requests.Response:
        """Perform a GET request, auto-healing the session via login() if redirected."""
        try:
            resp = self.session.get(url, allow_redirects=False, timeout=15)

            # Check if redirected to login or needs auth
            location = resp.headers.get("Location", "")
            needs_login = (
                resp.status_code in (301, 302, 303, 307) and "/login" in location
            ) or (
                resp.status_code == 200 and "Please login to see the statistics" in resp.text
            ) or resp.status_code in (401, 403)

            if needs_login:
                logger.info("CSES session expired or unauthenticated; attempting login.")
                if self.login():
                    resp = self.session.get(url, allow_redirects=True, timeout=15)
                else:
                    logger.warning("Could not re-authenticate with CSES.")
                    if resp.status_code in (301, 302, 303, 307):
                        resp = self.session.get(url, allow_redirects=True, timeout=15)
            elif resp.status_code in (301, 302, 303, 307):
                # Follow redirect
                resp = self.session.get(url, allow_redirects=True, timeout=15)

            return resp

        except Exception as exc:
            logger.error("HTTP error during GET %s: %s", url, exc)
            raise

    # ── Problem Name Resolution & Caching ───────────────────────

    def warmup_problem_names(
        self,
        use_cache: bool = True,
        lifetime: Optional[int] = None,
    ) -> None:
        """Fetch all problems from https://cses.fi/problemset/ in a single request."""
        try:
            url = "https://cses.fi/problemset/"
            resp = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if resp.status_code != 200:
                logger.warning("Failed to fetch CSES problemset list, status=%d", resp.status_code)
                return

            effective_lifetime = (
                lifetime
                if lifetime is not None
                else settings.CSES_PROBLEM_NAMES_CACHE_LIFETIME
            )

            soup = BeautifulSoup(resp.text, "html.parser")
            tasks = soup.find_all("li", class_="task")
            count = 0
            for t in tasks:
                a = t.find("a")
                if a and a.get("href"):
                    href = a.get("href")
                    m = re.search(r"/problemset/task/(\d+)", href)
                    if m:
                        pid = m.group(1)
                        name = a.get_text(strip=True)
                        if use_cache:
                            cache["cses_problem_names"].add(
                                pid, name, lifetime=effective_lifetime
                            )
                        count += 1

            self._warmed_up = True
            logger.info("Warmed up %d CSES problem names in cache['cses_problem_names'].", count)
        except Exception as exc:
            logger.warning("Error warming up CSES problem names: %s", exc)

    def get_problem_name(
        self,
        problem_id: str | int,
        use_cache: bool = True,
        lifetime: Optional[int] = None,
    ) -> str:
        """Resolve a CSES problem ID to its title using `cache['cses_problem_names']` and fallbacks."""
        pid = str(problem_id).strip()
        if not pid:
            return "CSES Problem"

        effective_lifetime = (
            lifetime
            if lifetime is not None
            else settings.CSES_PROBLEM_NAMES_CACHE_LIFETIME
        )

        if use_cache:
            cached_name = cache["cses_problem_names"].get(pid)
            if cached_name is not None:
                return cached_name

        if not self._warmed_up:
            self.warmup_problem_names(use_cache=use_cache, lifetime=effective_lifetime)
            if use_cache:
                cached_name = cache["cses_problem_names"].get(pid)
                if cached_name is not None:
                    return cached_name

        # Fallback: scrape individual task page
        try:
            url = f"https://cses.fi/problemset/task/{pid}"
            resp = self.session.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(strip=True)
                    if title:
                        if use_cache:
                            cache["cses_problem_names"].add(
                                pid, title, lifetime=effective_lifetime
                            )
                        return title
                # Try title tag
                if soup.title and soup.title.string:
                    raw_title = soup.title.string.strip()
                    # e.g., "CSES - Weird Algorithm"
                    if "-" in raw_title:
                        title = raw_title.split("-", 1)[-1].strip()
                        if use_cache:
                            cache["cses_problem_names"].add(
                                pid, title, lifetime=effective_lifetime
                            )
                        return title
        except Exception as exc:
            logger.debug("Could not resolve individual CSES task #%s: %s", pid, exc)

        fallback = f"CSES #{pid}"
        if use_cache:
            cache["cses_problem_names"].add(pid, fallback, lifetime=effective_lifetime)
        return fallback

    def get_problems_metadata(
        self,
        problem_ids: List[str | int],
        use_cache: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """Return bulk metadata dict: {pid: {"id": pid, "name": name, "url": url}}."""
        results: Dict[str, Dict[str, Any]] = {}
        for raw_pid in problem_ids:
            pid = str(raw_pid).strip()
            if not pid:
                continue
            name = self.get_problem_name(pid, use_cache=use_cache)
            results[pid] = {
                "id": pid,
                "name": name,
                "url": f"https://cses.fi/problemset/task/{pid}",
            }
        return results

    # ── Student Solved Tasks Checker & Cache ──────────────────────

    def get_user_solved_set(
        self,
        cses_id: str,
        force_refresh: bool = False,
        use_cache: bool = True,
        lifetime: Optional[int] = None,
    ) -> Set[str]:
        """Fetch and parse all solved task IDs for a given CSES user ID.

        Results are cached in `cache['cses_user_solved']` for `settings.CSES_SOLVED_CACHE_LIFETIME`
        (default 60 seconds). Set `force_refresh=True` or `use_cache=False` to bypass cache.
        """
        cid = str(cses_id).strip()
        if not cid:
            return set()

        effective_lifetime = (
            lifetime if lifetime is not None else settings.CSES_SOLVED_CACHE_LIFETIME
        )

        if use_cache and not force_refresh:
            cached_data = cache["cses_user_solved"].get(cid)
            if cached_data is not None:
                return set(cached_data)

        url = f"https://cses.fi/problemset/user/{cid}/"
        resp = self._authenticated_get(url)

        if resp.status_code != 200:
            logger.warning("Failed to fetch CSES user profile for #%s, status=%d", cid, resp.status_code)
            return set()

        solved_set: Set[str] = set()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check all elements with class 'full' (full-score indicators)
        for el in soup.find_all(class_=re.compile(r"\bfull\b")):
            # If element is an <a> tag
            if el.name == "a" and el.get("href"):
                m = re.search(r"/problemset/task/(\d+)", el.get("href"))
                if m:
                    solved_set.add(m.group(1))
                    continue

            # If element contains an <a> tag
            a_child = el.find("a", href=re.compile(r"/problemset/task/(\d+)"))
            if a_child and a_child.get("href"):
                m = re.search(r"/problemset/task/(\d+)", a_child.get("href"))
                if m:
                    solved_set.add(m.group(1))
                    continue

            # Look up ancestors for associated task link
            parent = el.parent
            while parent and parent.name not in ("body", "html", "[document]"):
                a_tag = parent.find("a", href=re.compile(r"/problemset/task/(\d+)"))
                if a_tag and a_tag.get("href"):
                    m = re.search(r"/problemset/task/(\d+)", a_tag.get("href"))
                    if m:
                        solved_set.add(m.group(1))
                        break
                parent = parent.parent

        # Also search direct links with full class
        for a in soup.find_all("a", href=re.compile(r"/problemset/task/(\d+)")):
            classes = a.get("class") or []
            if any("full" in c for c in classes) or a.find(class_=re.compile(r"\bfull\b")):
                m = re.search(r"/problemset/task/(\d+)", a.get("href"))
                if m:
                    solved_set.add(m.group(1))

        if use_cache:
            cache["cses_user_solved"].add(
                cid,
                list(solved_set),
                lifetime=effective_lifetime,
            )

        return solved_set

    def check_user_solved_problems(
        self,
        user_or_cses_id: Any,
        problem_ids: List[str],
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Check which of the requested problems are solved by the student."""
        cses_id = (
            getattr(user_or_cses_id, "cses_id", None)
            if hasattr(user_or_cses_id, "cses_id")
            else user_or_cses_id
        )

        clean_pids = [str(p).strip() for p in problem_ids if str(p).strip()]

        if not cses_id or not str(cses_id).strip():
            return {
                "solved": [],
                "unsolved": clean_pids,
                "error": "Student has no CSES ID configured.",
            }

        solved_set = self.get_user_solved_set(
            str(cses_id),
            force_refresh=force_refresh,
            use_cache=use_cache,
        )

        solved: List[str] = []
        unsolved: List[str] = []

        for pid in clean_pids:
            if pid in solved_set:
                solved.append(pid)
            else:
                unsolved.append(pid)

        return {
            "solved": solved,
            "unsolved": unsolved,
        }


# Singleton service instance
cses_service = CSESService()

# Exported module-level helpers
login = cses_service.login
get_problem_name = cses_service.get_problem_name
get_problems_metadata = cses_service.get_problems_metadata
get_user_solved_set = cses_service.get_user_solved_set
check_user_solved_problems = cses_service.check_user_solved_problems
warmup_problem_names = cses_service.warmup_problem_names
