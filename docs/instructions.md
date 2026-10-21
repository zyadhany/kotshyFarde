Kotshy Tracker - Instructions & Architecture Specification

1. Project Overview & Scope

Kotshy Tracker is a modular, local-first coaching and tracking platform tailored for mentoring a focused cohort (10–15 students) in Problem Solving (PS) and competitive programming (ICPC).

Scope Boundaries for MVP:

Local-First & Direct Execution: No external web servers, REST APIs, or frontend interfaces are implemented in this phase. Execution is strictly driven via scripts or entry-point workflows.

Core Focus: Establishing a clean database persistence layer, domain modeling with Object-Oriented inheritance, and reliable integration with Codeforces.

Deferred Modules: VJudge integration and submissions caching remain architectural placeholders.

2. Core Philosophy & Code Guidelines

Simplicity over Over-Engineering: Write transparent, self-explanatory code. Avoid unnecessary abstractions, reflection, or complex metaclasses.

Separation of Concerns:

Storage and ORM models belong in models/.

Business logic, checker rules, and domain entities belong in domain/.

External platform communication belongs in services/.

Global state and database initialization belong in core/.

Environment Agnostic (12-Factor App): All configurations, secrets, and database paths must be resolved strictly through environment variables via .env.

Serialization Transparency: Domain objects must clearly define serialization (to_dict()) and deserialization (from_dict()) mechanisms to seamlessly interact with database JSON payloads.

3. Directory & File Structure

kotchy/
├── docs/
│   ├── schema.md                  # Database schema specifications
│   └── instructions.md            # Architecture, developer guidelines, and standards
├── app/
│   ├── core/
│   │   ├── config.py              # Environment variables parser (.env)
│   │   └── database.py            # Engine initialization, session maker, DB setup
│   │
│   ├── models/                    # SQLModel / SQLAlchemy database models
│   │   ├── student.py             # Student entity
│   │   ├── task.py                # Task entity (Single Table with JSON config)
│   │   └── student_task.py        # StudentTask associative entity (Deadlines & status)
│   │
│   ├── domain/                    # Business logic and OOP Checkers
│   │   ├── base_task.py           # Abstract BaseTask with standard check() interface
│   │   ├── codeforces/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # CodeforcesBaseTask
│   │   │   ├── sheet.py           # CodeforcesSheetTask
│   │   │   └── contest.py         # CodeforcesContestTask
│   │   ├── vjudge/
│   │   │   └── __init__.py        # Placeholder for future VJudge implementation
│   │   └── factory.py             # TaskFactory to instantiate domain classes from DB records
│   │
│   ├── services/                  # Third-party platform integrations
│   │   ├── __init__.py
│   │   └── codeforces_api.py      # Codeforces API consumer, signing, and rate limiting
│   │
│   └── app.py                     # Primary entry-point for local execution and manual verification
├── .env                           # Local environment secrets (ignored by git)
├── .env.example                   # Template for environment configuration
└── requirements.txt               # Project dependencies


4. Configuration & Database Engine (app/core/)

config.py

Load .env using python-dotenv.

Expose typed configuration values:

DATABASE_URL: Defaults to sqlite:///./kotchy.db.

CF_API_KEY: Codeforces API key (optional for public operations).

CF_API_SECRET: Codeforces API secret (optional for public operations).

DEBUG: Boolean flag for debug logging.

database.py

Manage database engine creation dynamically based on DATABASE_URL.

Support SQLite configuration (connect_args={"check_same_thread": False}) while allowing transparent swapping to PostgreSQL.

Expose:

engine: Global SQLModel/SQLAlchemy engine.

get_session(): Context manager or generator providing an active Session.

init_db(): Helper function creating tables based on models metadata.

5. Domain Architecture & Checker Logic (app/domain/)

The system handles arbitrary task logic via Object-Oriented Polymorphism and the Factory Pattern.

       [BaseTask] (Abstract)
           ▲
           │
   [CodeforcesBaseTask]
     ▲              ▲
     │              │
[CodeforcesSheet]  [CodeforcesContest]


1. BaseTask (app/domain/base_task.py)

Abstract Base Class defining the contract:

task_type: str: Unique discriminator identifier.

to_dict() -> dict: Serializes object attributes to a JSON-compatible dictionary.

@classmethod from_dict(data: dict) -> BaseTask: Deserializes dictionary data into an object instance.

check(student, student_task, **kwargs) -> dict: Abstract method executing verification logic against external platforms or submissions. Must return a structured dictionary:

{
  "status": "completed", // or "in_progress", "pending", "failed"
  "details": {}
}


2. Codeforces Domain (app/domain/codeforces/)

CodeforcesBaseTask: Handles common Codeforces parsing logic and shared validation routines.

CodeforcesSheetTask (sheet.py):

Attributes: problems (list of strings, e.g., ["158A", "71A"]), min_solved_count (int).

Verification logic: Evaluates whether the student's Codeforces handle solved at least min_solved_count problems on or after student_task.start_date.

CodeforcesContestTask (contest.py):

Attributes: contest_id (int), min_solved (int), access_type (public, private_managed, private_restricted).

Behavior:

public: Scrapes or queries public standings/submissions without authentication.

private_managed: Instructs the service to sign requests using CF_API_KEY and CF_API_SECRET.

private_restricted: Reserved stub (raises NotImplementedError or logs warning).

3. Task Factory (app/domain/factory.py)

Implements TaskFactory.create(task_type: str, config: dict) -> BaseTask.

Maps discriminator strings (CF_SHEET, CF_CONTEST) to their respective classes and invokes from_dict(config).

6. Codeforces Service Layer (app/services/codeforces_api.py)

Handles raw HTTP communication, request signing, and rate limiting with Codeforces.

Core Functionalities

Authentication Signature (SHA-512):

When use_auth=True or private_managed tasks are invoked, requests must generate the required Codeforces apiSig hashing: rand + "/" + methodName + "?" + params + "#" + secret.

Safe Rate Limiting:

Enforce a minimum interval (e.g., 1.5 to 2.0 seconds) between requests to prevent temporary IP bans from Codeforces.

Essential Functions

verify_handle(handle: str) -> bool:

Validates whether a handle exists via user.info.

check_problem_solved(handle: str, contest_id: int, index: str, after_time: Optional[datetime] = None) -> bool:

Queries user.status for the given handle and checks if an accepted submission (verdict == 'OK') exists for the specified problem.

get_contest_problems_status(handle: str, contest_id: int, use_auth: bool = False) -> dict:

Returns a structured summary containing total contest problems, problems solved by the user, and per-problem breakdown.

Helper Functions

parse_problem_id(problem_str: str) -> tuple[int, str]:

Splits standard problem strings like "158A", "158/A", or "4C" into (contest_id: int, index: str).

standardize_verdict(verdict: str) -> str:

Maps raw platform verdicts to normalized internal representation.

7. Development Roadmap

Step 1: Establish configuration, engine, and database initialization (app/core/).

Step 2: Define database models in app/models/ matching docs/schema.md.

Step 3: Implement Codeforces API client and helpers in app/services/.

Step 4: Construct domain hierarchy (BaseTask, CodeforcesSheetTask, CodeforcesContestTask, and TaskFactory).

Step 5: Create an end-to-end integration test runner in app.py to register a test student, assign a Codeforces task, and verify submission status against live Codeforces API.