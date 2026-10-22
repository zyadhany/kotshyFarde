/**
 * static/js/main.js
 * ─────────────────
 * Lightweight, dependency-free client controller for Kotchy.
 * Handles modals, comma-separated assignment parsing, async CF checks, and toasts.
 */

const Kotchy = {
  // ── Toast Notifications ─────────────────────────────────────
  showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-enter flex items-center justify-between gap-3 px-3.5 py-2.5 rounded-lg border text-xs font-medium shadow-sm max-w-sm pointer-events-auto transition-all';

    let colorClasses = 'bg-zinc-900 text-zinc-100 border-zinc-800';
    let dotColor = 'bg-emerald-400';

    if (type === 'error') {
      colorClasses = 'bg-rose-950 text-rose-100 border-rose-800';
      dotColor = 'bg-rose-400';
    } else if (type === 'warning') {
      colorClasses = 'bg-amber-950 text-amber-100 border-amber-800';
      dotColor = 'bg-amber-400';
    }

    toast.className += ` ${colorClasses}`;
    toast.innerHTML = `
      <div class="flex items-center gap-2 min-w-0">
        <span class="w-1.5 h-1.5 rounded-full ${dotColor} flex-shrink-0"></span>
        <span class="truncate">${message}</span>
      </div>
      <button type="button" class="text-zinc-400 hover:text-zinc-200 ml-2" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 200);
    }, 3500);
  },

  // ── Modals ──────────────────────────────────────────────────
  openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.classList.add('overflow-hidden');
  },

  closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    const openModals = document.querySelectorAll('.kotchy-modal:not(.hidden)');
    if (openModals.length === 0) {
      document.body.classList.remove('overflow-hidden');
    }
  },

  // ── Student Controller ──────────────────────────────────────
  Student: {
    async submitAdd(event) {
      event.preventDefault();
      const form = event.target;
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      const payload = {
        username: form.username.value.trim(),
        email: form.email.value.trim(),
        password_hash: 'placeholder_hash',
        cf_handle: form.cf_handle.value.trim() || null,
        vjudge_handle: form.vjudge_handle.value.trim() || null,
      };

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Saving...`;

        const res = await fetch('/students/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to add student.');

        Kotchy.showToast(`Student ${data.username} added successfully.`);
        Kotchy.closeModal('add-student-modal');
        form.reset();
        setTimeout(() => window.location.reload(), 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    },

    async delete(studentId, username) {
      if (!confirm(`Are you sure you want to remove student "${username}"?`)) return;

      try {
        const res = await fetch(`/students/${studentId}`, { method: 'DELETE' });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Delete failed.');
        }

        Kotchy.showToast(`Student ${username} removed.`);
        const row = document.getElementById(`student-row-${studentId}`);
        if (row) row.remove();
        else setTimeout(() => window.location.reload(), 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      }
    }
  },

  // ── Task Controller ─────────────────────────────────────────
  Task: {
    toggleTypeFields(type, formPrefix = '') {
      const sheetBox = document.getElementById(`${formPrefix}sheet-fields`);
      const contestBox = document.getElementById(`${formPrefix}contest-fields`);
      if (type === 'CF_SHEET') {
        if (sheetBox) sheetBox.classList.remove('hidden');
        if (contestBox) contestBox.classList.add('hidden');
      } else {
        if (sheetBox) sheetBox.classList.add('hidden');
        if (contestBox) contestBox.classList.remove('hidden');
      }
    },

    async submitCreate(event) {
      event.preventDefault();
      const form = event.target;
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      const taskType = form.task_type.value;
      let config = {};

      if (taskType === 'CF_SHEET') {
        const raw = form.problems.value.trim();
        const problems = raw
          .split(/[\s,;\n]+/)
          .map(p => p.trim())
          .filter(p => p.length > 0);

        if (problems.length === 0) {
          Kotchy.showToast('Please provide at least one problem code.', 'warning');
          return;
        }

        const minSolved = parseInt(form.min_solved_count.value) || problems.length;
        config = { problems, min_solved_count: minSolved };
      } else {
        const contestId = parseInt(form.contest_id.value);
        if (isNaN(contestId)) {
          Kotchy.showToast('Please enter a valid numeric Contest ID.', 'warning');
          return;
        }
        const minSolved = parseInt(form.contest_min_solved.value) || 1;
        const accessType = form.access_type.value || 'public';
        config = { contest_id: contestId, min_solved: minSolved, access_type: accessType };
      }

      const payload = {
        title: form.title.value.trim(),
        description: form.description.value.trim() || null,
        task_type: taskType,
        config: config,
      };

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Creating...`;

        const res = await fetch('/tasks/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to create task.');

        Kotchy.showToast(`Task "${data.title}" created.`);
        Kotchy.closeModal('create-task-modal');
        form.reset();
        setTimeout(() => window.location.reload(), 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    },

    async delete(taskId, title) {
      if (!confirm(`Are you sure you want to delete task "${title}"?`)) return;

      try {
        const res = await fetch(`/tasks/${taskId}`, { method: 'DELETE' });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Delete failed.');
        }

        Kotchy.showToast(`Task "${title}" deleted.`);
        setTimeout(() => {
          if (window.location.pathname.includes('/tasks-page/')) {
            window.location.href = '/tasks-page';
          } else {
            window.location.reload();
          }
        }, 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      }
    }
  },

  // ── Assignment & Checker Controller ─────────────────────────
  Assignment: {
    toggleSelectAllStudents(checkbox) {
      const boxes = document.querySelectorAll('.student-assign-checkbox');
      boxes.forEach(b => { b.checked = checkbox.checked; });
    },

    async submitBatchAssign(event, taskId) {
      event.preventDefault();
      const form = event.target;
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      // 1. Collect checked student IDs
      const checkedBoxes = Array.from(document.querySelectorAll('.student-assign-checkbox:checked'));
      const studentIds = new Set(checkedBoxes.map(b => parseInt(b.value)));

      // 2. Parse comma-separated usernames if provided
      const rawUsernames = form.usernames_input?.value.trim() || '';
      if (rawUsernames && window.ALL_STUDENTS) {
        const names = rawUsernames
          .split(/[\s,;\n]+/)
          .map(n => n.trim().toLowerCase())
          .filter(n => n.length > 0);

        const lookup = {};
        window.ALL_STUDENTS.forEach(s => {
          lookup[s.username.toLowerCase()] = s.id;
          if (s.cf_handle) lookup[s.cf_handle.toLowerCase()] = s.id;
        });

        names.forEach(name => {
          if (lookup[name]) {
            studentIds.add(lookup[name]);
          } else {
            Kotchy.showToast(`Username "${name}" not found in cohort.`, 'warning');
          }
        });
      }

      if (studentIds.size === 0) {
        Kotchy.showToast('Please select at least one student or enter valid usernames.', 'warning');
        return;
      }

      const startDate = form.start_date.value ? new Date(form.start_date.value).toISOString() : null;
      const deadline = form.deadline.value ? new Date(form.deadline.value).toISOString() : null;

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Assigning ${studentIds.size} student(s)...`;

        let successCount = 0;
        for (const studentId of studentIds) {
          const payload = {
            student_id: studentId,
            task_id: taskId,
            start_date: startDate,
            deadline: deadline,
          };

          const res = await fetch('/assignments/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });

          if (res.ok) successCount++;
        }

        Kotchy.showToast(`Assigned ${successCount} student(s) to this task.`);
        setTimeout(() => window.location.reload(), 500);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    },

    async checkAssignment(assignmentId, btnEl) {
      if (!btnEl) btnEl = document.querySelector(`[data-check-id="${assignmentId}"]`);
      let originalHtml = '';
      if (btnEl) {
        originalHtml = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = `<span class="spinner"></span>`;
      }

      try {
        const res = await fetch(`/assignments/${assignmentId}/check`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Check failed.');

        const solvedCount = data.checker_result?.solved_count ?? 0;
        const status = data.status;

        Kotchy.showToast(`Check finished: ${status} (${solvedCount} solved)`);

        // Inline DOM update if matching elements exist
        const badgeEl = document.getElementById(`assignment-badge-${assignmentId}`);
        if (badgeEl) {
          if (status === 'completed') {
            badgeEl.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium text-emerald-700 bg-emerald-50 border border-emerald-200';
            badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Solved`;
          } else if (status === 'late') {
            badgeEl.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium text-amber-700 bg-amber-50 border border-amber-200';
            badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Late`;
          } else if (status === 'in_progress') {
            badgeEl.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium text-zinc-700 bg-zinc-100 border border-zinc-200';
            badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-zinc-400"></span> In Progress`;
          } else {
            badgeEl.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-medium text-zinc-500 bg-zinc-50 border border-zinc-200';
            badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-zinc-300"></span> Pending`;
          }
        }

        const countEl = document.getElementById(`assignment-solved-${assignmentId}`);
        if (countEl) {
          countEl.textContent = `${solvedCount} solved`;
        }
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = originalHtml;
        }
      }
    }
  },

  // ── Tab Filters ─────────────────────────────────────────────
  filterItems(category, selector, attribute = 'data-status') {
    const items = document.querySelectorAll(selector);
    items.forEach(el => {
      const val = el.getAttribute(attribute);
      if (category === 'all' || val === category) {
        el.style.display = '';
      } else {
        el.style.display = 'none';
      }
    });

    // Update active tab buttons
    const tabBtns = document.querySelectorAll('.filter-tab-btn');
    tabBtns.forEach(btn => {
      if (btn.getAttribute('data-filter') === category) {
        btn.className = 'filter-tab-btn px-2.5 py-1 text-xs font-medium rounded-md bg-zinc-900 text-white';
      } else {
        btn.className = 'filter-tab-btn px-2.5 py-1 text-xs font-medium rounded-md text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100';
      }
    });
  },

  // ── Contest View Tabs (Problems vs Standings) ─────────────
  switchContestTab(tabName) {
    const problemsPane = document.getElementById('contest-tab-problems');
    const standingsPane = document.getElementById('contest-tab-standings');
    const problemsBtn = document.getElementById('tab-btn-problems');
    const standingsBtn = document.getElementById('tab-btn-standings');

    if (!problemsPane || !standingsPane) return;

    if (tabName === 'problems') {
      problemsPane.style.setProperty('display', 'block', 'important');
      problemsPane.classList.remove('hidden');
      standingsPane.style.setProperty('display', 'none', 'important');
      standingsPane.classList.add('hidden');

      if (problemsBtn) {
        problemsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-semibold rounded-t-md border-b-2 border-sky-600 text-sky-700 bg-white shadow-xs transition-all flex items-center gap-1.5 cursor-pointer';
      }
      if (standingsBtn) {
        standingsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-medium rounded-t-md border-b-2 border-transparent text-slate-600 hover:text-slate-900 hover:bg-white/60 transition-all flex items-center gap-1.5 cursor-pointer';
      }
      try {
        history.replaceState(null, '', '#problems');
      } catch (e) {}
    } else {
      standingsPane.style.setProperty('display', 'block', 'important');
      standingsPane.classList.remove('hidden');
      problemsPane.style.setProperty('display', 'none', 'important');
      problemsPane.classList.add('hidden');

      if (standingsBtn) {
        standingsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-semibold rounded-t-md border-b-2 border-sky-600 text-sky-700 bg-white shadow-xs transition-all flex items-center gap-1.5 cursor-pointer';
      }
      if (problemsBtn) {
        problemsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-medium rounded-t-md border-b-2 border-transparent text-slate-600 hover:text-slate-900 hover:bg-white/60 transition-all flex items-center gap-1.5 cursor-pointer';
      }
      try {
        history.replaceState(null, '', '#standings');
      } catch (e) {}
    }
  },

  // ── Global Initializer ──────────────────────────────────────
  init() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modals = document.querySelectorAll('.kotchy-modal:not(.hidden)');
        modals.forEach(m => Kotchy.closeModal(m.id));
      }
    });

    document.querySelectorAll('.kotchy-modal').forEach(modal => {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) Kotchy.closeModal(modal.id);
      });
    });
  }
};

window.Kotchy = Kotchy;
window.switchContestTab = Kotchy.switchContestTab;

document.addEventListener('DOMContentLoaded', () => Kotchy.init());
