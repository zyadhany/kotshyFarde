# Database Schema Specification

This document details the database schema architecture for the **Kotshy Tracker** project—a local-first coaching and tracking platform designed for Problem Solving and ICPC training.

The schema is architected to run seamlessly on a local **SQLite** database while maintaining 100% compatibility for direct migration to managed **PostgreSQL** providers (such as Supabase or Neon) without schema redesign.

---

## 1. Users Table (`users`)

Stores core profile credentials, handles for competitive programming, and role ("Student" or "coash").

| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique user identifier |
| `username` | `VARCHAR(50)` | `NOT NULL, UNIQUE` | Login handle/username |
| `email` | `VARCHAR(100)` | `NOT NULL, UNIQUE` | Contact email address |
| `password_hash` | `VARCHAR(255)` | `NOT NULL` | Securely hashed password |
| `role` | `VARCHAR(20)` | `NOT NULL, DEFAULT 'Student'` | Role: `Student` or `coash` (coach) |
| `phone_number` | `VARCHAR(20)` | `NULLABLE` | WhatsApp / mobile contact number |
| `cf_handle` | `VARCHAR(50)` | `NULLABLE, INDEX` | Codeforces handle |
| `vjudge_handle` | `VARCHAR(50)` | `NULLABLE` | VJudge handle |
| `atcoder_handle` | `VARCHAR(50)` | `NULLABLE` | AtCoder handle |
| `cses_id` | `VARCHAR(50)` | `NULLABLE` | CSES account ID/username |
| `linkedin_url` | `VARCHAR(255)` | `NULLABLE` | LinkedIn profile URL |
| `description` | `TEXT` | `NULLABLE` | User background, notes, and current skill level |
| `created_at` | `DATETIME` | `DEFAULT CURRENT_TIMESTAMP` | Account creation timestamp |
| `updated_at` | `DATETIME` | `DEFAULT CURRENT_TIMESTAMP` | Last profile update timestamp |

---

## 2. Tasks Table (`tasks`)

Defines assignable assignments and utilizes the **Single Table Inheritance** pattern via the `task_type` discriminator column and dynamic JSON `config`.

| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique task identifier |
| `title` | `VARCHAR(150)` | `NOT NULL` | Task title (e.g., `Sheet 1 - Binary Search`) |
| `description` | `TEXT` | `NULLABLE` | Detailed instructions, prerequisites, or resource links |
| `task_type` | `VARCHAR(50)` | `NOT NULL` | Discriminator mapping to OOP checker class (`CF_SHEET`, `CF_CONTEST`, `VJUDGE_CONTEST`, `MANUAL`) |
| `config` | `JSON` | `NOT NULL` | Task configuration payload and validation rules |
| `created_at` | `DATETIME` | `DEFAULT CURRENT_TIMESTAMP` | Task creation timestamp |

### Sample `config` Payloads:

* **Codeforces Sheet (`CF_SHEET`):**
  ```json
  {
    "problems": ["158A", "71A", "231A"],
    "min_solved_count": 3
  }
  ```

* **Codeforces Contest (`CF_CONTEST`):**
  ```json
  {
    "contest_id": 1941,
    "min_solved": 4
  }
  ```

---

## 3. Student Tasks Table (`student_tasks`)

Associative junction table linking students to tasks (Many-to-Many). Manages individualized schedules, deadlines, statuses, and verification outputs.

| Field | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique assignment identifier |
| `student_id` | `INTEGER` | `FOREIGN KEY (users.id) NOT NULL` | References the student (user) |
| `task_id` | `INTEGER` | `FOREIGN KEY (tasks.id) NOT NULL` | References the assigned task |
| `start_date` | `DATETIME` | `NOT NULL` | Start timestamp for this student |
| `deadline` | `DATETIME` | `NOT NULL` | Due date and submission deadline for this student |
| `status` | `VARCHAR(20)` | `DEFAULT 'pending'` | Workflow state (`pending`, `in_progress`, `completed`, `late`) |
| `checker_result` | `JSON` | `NULLABLE` | Detailed execution output from the checker strategy |
| `completed_at` | `DATETIME` | `NULLABLE` | Timestamp when the task was verified as completed |

---

## 4. Submissions Cache Table (`submissions_cache`) — [Deferred / Placeholder]

> **Note:** This table is reserved as an architectural placeholder and will not be implemented in the initial MVP. Its future role will be caching remote platform submission histories (e.g., Codeforces / VJudge API poll results) to eliminate redundant external network calls and avoid rate limits.