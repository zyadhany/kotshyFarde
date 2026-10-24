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
        cf_handle: form.cf_handle.value.trim() || null,
        vjudge_handle: form.vjudge_handle.value.trim() || null,
      };

      if (form.password && form.password.value.trim()) {
        payload.password = form.password.value.trim();
      }

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Saving...`;

        const res = await fetch('/api/students/', {
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

    async submitEdit(event, studentId) {
      event.preventDefault();
      const form = event.target;
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      const payload = {
        username: form.username.value.trim(),
        email: form.email.value.trim(),
        role: form.role ? form.role.value : 'student',
        is_active: form.is_active ? form.is_active.value === 'true' : true,
        phone_number: form.phone_number?.value.trim() || null,
        cf_handle: form.cf_handle?.value.trim() || null,
        vjudge_handle: form.vjudge_handle?.value.trim() || null,
        atcoder_handle: form.atcoder_handle?.value.trim() || null,
        cses_id: form.cses_id?.value.trim() || null,
        linkedin_url: form.linkedin_url?.value.trim() || null,
        description: form.description?.value.trim() || null,
      };

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Saving...`;

        const res = await fetch(`/api/students/${studentId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to update student profile.');

        Kotchy.showToast(`User ${data.username} updated successfully.`);
        Kotchy.closeModal('edit-student-modal');
        setTimeout(() => window.location.reload(), 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    },

    async resetPassword(studentId, username) {
      const resetBtn = document.getElementById('reset-pwd-btn');
      const feedbackDiv = document.getElementById('reset-pwd-feedback');
      const valueSpan = document.getElementById('reset-pwd-value');
      const box = document.getElementById('reset-pwd-box');
      const originalBtnText = resetBtn ? resetBtn.innerHTML : null;

      if (resetBtn) {
        resetBtn.disabled = true;
        resetBtn.innerHTML = `<span class="spinner mr-1.5"></span> Resetting...`;
      }

      try {
        const res = await fetch(`/api/students/${studentId}/reset-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to reset password.');

        const defPwd = data.default_password || '12345678';

        // Reveal prominent feedback in the modal
        if (feedbackDiv) {
          feedbackDiv.classList.remove('hidden');
          if (valueSpan) valueSpan.textContent = defPwd;
        }

        // Highlight the card with clear emerald styling
        if (box) {
          box.classList.remove('bg-amber-50', 'bg-amber-50/80', 'border-amber-200');
          box.classList.add('bg-emerald-50', 'border-emerald-300');
        }

        // Update button state to success badge
        if (resetBtn) {
          resetBtn.className = 'px-3 py-1.5 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs transition-colors whitespace-nowrap flex items-center justify-center gap-1.5';
          resetBtn.innerHTML = `✓ Password Reset!`;
        }

        Kotchy.showToast(`Password for ${username} reset to default: "${defPwd}"`);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
        if (resetBtn && originalBtnText) {
          resetBtn.disabled = false;
          resetBtn.innerHTML = originalBtnText;
        }
      }
    },

    async delete(studentId, username) {
      if (!confirm(`Are you sure you want to remove student "${username}"?`)) return;

      try {
        const res = await fetch(`/api/students/${studentId}`, { method: 'DELETE' });
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
        const parsedMinSolved = parseInt(form.contest_min_solved.value, 10);
        const minSolved = isNaN(parsedMinSolved) ? 1 : Math.max(0, parsedMinSolved);
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

        const res = await fetch('/api/tasks/', {
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
        const res = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || 'Delete failed.');
        }

        Kotchy.showToast(`Task "${title}" deleted.`);
        setTimeout(() => {
          if (window.location.pathname.startsWith('/tasks/') || window.location.pathname.includes('/tasks-page/')) {
            window.location.href = '/tasks';
          } else {
            window.location.reload();
          }
        }, 400);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      }
    },

    async update(event, taskId) {
      event.preventDefault();
      const form = event.target;
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.innerHTML;

      const taskType = form.task_type.value;
      const config = {};

      if (taskType === 'CF_CONTEST') {
        const contestId = parseInt(form.contest_id.value, 10);
        if (isNaN(contestId) || contestId <= 0) {
          Kotchy.showToast('Please enter a valid numeric Contest ID.', 'error');
          return;
        }
        config.contest_id = contestId;
        const parsedMin = parseInt(form.min_solved.value, 10);
        config.min_solved = isNaN(parsedMin) ? 1 : Math.max(0, parsedMin);
        config.access_type = form.access_type?.value || 'public';
      } else if (taskType === 'CF_SHEET') {
        const rawProblems = form.problems?.value.trim() || '';
        const problems = rawProblems.split(/[\s,;\n]+/).filter(p => p.length > 0);
        if (problems.length === 0) {
          Kotchy.showToast('Please provide at least one problem identifier (e.g. 455A).', 'error');
          return;
        }
        config.problems = problems;
        config.min_solved_count = parseInt(form.min_solved_count?.value, 10) || problems.length;
      }

      const payload = {
        title: form.title.value.trim(),
        description: form.description.value.trim() || null,
        task_type: taskType,
        config: config,
      };

      try {
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner mr-1.5"></span> Saving...`;

        const res = await fetch(`/api/tasks/${taskId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to update task.');

        Kotchy.showToast(`Task "${data.title}" updated successfully.`);
        Kotchy.closeModal('edit-task-modal');
        setTimeout(() => window.location.reload(), 300);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    },

    async checkAll(taskId, btnEl) {
      if (!btnEl) btnEl = document.querySelector(`[data-recheck-task-id="${taskId}"]`);
      let originalHtml = '';
      if (btnEl) {
        originalHtml = btnEl.innerHTML;
        btnEl.disabled = true;
        btnEl.innerHTML = `<span class="spinner mr-1.5"></span> Rechecking...`;
      }

      try {
        Kotchy.showToast('Running recheck on all enrolled students...', 'info');
        const res = await fetch(`/api/tasks/${taskId}/check-all`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Recheck failed.');

        Kotchy.showToast(data.message || 'All students rechecked successfully.');
        setTimeout(() => window.location.reload(), 500);
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
        if (btnEl) {
          btnEl.disabled = false;
          btnEl.innerHTML = originalHtml;
        }
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

        const payload = {
          task_id: taskId,
          student_ids: Array.from(studentIds),
          start_date: startDate,
          deadline: deadline,
        };

        const res = await fetch('/api/assignments/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to assign students to task.');

        Kotchy.showToast(`Assigned ${data.assigned_count} student(s) to this task.`);
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
        const res = await fetch(`/api/assignments/${assignmentId}/check`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Check failed.');

        const solvedCount = data.checker_result?.solved_count ?? 0;
        const status = data.status;

        Kotchy.showToast(`Check finished: ${status} (${solvedCount} solved)`);

        if (window.location.pathname.startsWith('/tasks') || window.location.pathname.startsWith('/students') || window.location.pathname.includes('/my-profile')) {
          setTimeout(() => window.location.reload(), 450);
          return;
        }
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
    },

    async deleteAssignment(assignmentId, label = '') {
      const promptText = label ? `Remove / unenroll assignment for "${label}"?` : 'Are you sure you want to remove this assignment?';
      if (!confirm(promptText)) return;

      try {
        const res = await fetch(`/api/assignments/${assignmentId}`, { method: 'DELETE' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to delete assignment.');

        Kotchy.showToast(data.message || 'Assignment deleted successfully.');
        const row = document.getElementById(`assignment-row-${assignmentId}`);
        if (row) {
          row.style.transition = 'all 0.3s ease';
          row.style.opacity = '0';
          row.style.transform = 'scale(0.95)';
          setTimeout(() => {
            row.remove();
            if (typeof filterAssignments === 'function') {
              filterAssignments();
            } else {
              window.location.reload();
            }
          }, 300);
        } else {
          setTimeout(() => window.location.reload(), 400);
        }
      } catch (err) {
        Kotchy.showToast(err.message, 'error');
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
        problemsBtn.setAttribute('aria-selected', 'true');
      }
      if (standingsBtn) {
        standingsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-medium rounded-t-md border-b-2 border-transparent text-slate-600 hover:text-slate-900 hover:bg-white/60 transition-all flex items-center gap-1.5 cursor-pointer';
        standingsBtn.setAttribute('aria-selected', 'false');
      }
      try {
        history.replaceState(null, '', '#problems');
      } catch (e) { }
    } else {
      standingsPane.style.setProperty('display', 'block', 'important');
      standingsPane.classList.remove('hidden');
      problemsPane.style.setProperty('display', 'none', 'important');
      problemsPane.classList.add('hidden');

      if (standingsBtn) {
        standingsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-semibold rounded-t-md border-b-2 border-sky-600 text-sky-700 bg-white shadow-xs transition-all flex items-center gap-1.5 cursor-pointer';
        standingsBtn.setAttribute('aria-selected', 'true');
      }
      if (problemsBtn) {
        problemsBtn.className = 'contest-tab-btn px-3.5 py-1.5 text-xs font-medium rounded-t-md border-b-2 border-transparent text-slate-600 hover:text-slate-900 hover:bg-white/60 transition-all flex items-center gap-1.5 cursor-pointer';
        problemsBtn.setAttribute('aria-selected', 'false');
      }
      try {
        history.replaceState(null, '', '#standings');
      } catch (e) { }
    }
  },

  switchContestStudent(studentId) {
    const url = new URL(window.location.href);
    if (studentId) {
      url.searchParams.set('student_id', studentId);
    } else {
      url.searchParams.delete('student_id');
    }
    window.location.href = url.toString();
  },

  // ── Deadline Timer Controller ───────────────────────────────
  initDeadlineTimers() {
    const timerEls = document.querySelectorAll('[data-deadline]');
    if (!timerEls.length) return;

    function formatTimeRemaining(diff) {
      if (diff <= 0) return null;
      const seconds = Math.floor((diff / 1000) % 60);
      const minutes = Math.floor((diff / (1000 * 60)) % 60);
      const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
      const days = Math.floor(diff / (1000 * 60 * 60 * 24));

      if (days > 0) {
        return `${days}d ${hours}h ${minutes}m ${seconds}s`;
      }
      if (hours > 0) {
        return `${hours}h ${minutes}m ${seconds}s`;
      }
      if (minutes > 0) {
        return `${minutes}m ${seconds}s`;
      }
      return `${seconds}s`;
    }

    function applyTimerState(el, state) {
      // states: 'normal', 'warning', 'urgent', 'passed', 'completed'
      el.classList.remove(
        'bg-zinc-50', 'border-zinc-200', 'text-zinc-700',
        'bg-amber-50', 'border-amber-200', 'text-amber-800',
        'bg-rose-50', 'border-rose-200', 'text-rose-700',
        'bg-emerald-50', 'border-emerald-200', 'text-emerald-800'
      );
      const iconEl = el.querySelector('.timer-icon');
      if (iconEl) {
        iconEl.classList.remove(
          'text-zinc-500', 'text-amber-500', 'text-rose-500', 'text-emerald-500', 'animate-pulse'
        );
      }

      if (state === 'completed') {
        el.classList.add('bg-emerald-50', 'border-emerald-200', 'text-emerald-800');
        if (iconEl) iconEl.classList.add('text-emerald-500');
      } else if (state === 'passed') {
        el.classList.add('bg-rose-50', 'border-rose-200', 'text-rose-700');
        if (iconEl) iconEl.classList.add('text-rose-500');
      } else if (state === 'urgent') {
        el.classList.add('bg-rose-50', 'border-rose-200', 'text-rose-700');
        if (iconEl) iconEl.classList.add('text-rose-500', 'animate-pulse');
      } else if (state === 'warning') {
        el.classList.add('bg-amber-50', 'border-amber-200', 'text-amber-800');
        if (iconEl) iconEl.classList.add('text-amber-500');
      } else {
        el.classList.add('bg-zinc-50', 'border-zinc-200', 'text-zinc-700');
        if (iconEl) iconEl.classList.add('text-zinc-500');
      }
    }

    function updateTimers() {
      const now = Date.now();

      timerEls.forEach(el => {
        const deadlineStr = el.getAttribute('data-deadline');
        if (!deadlineStr) return;

        const deadline = new Date(deadlineStr).getTime();
        if (isNaN(deadline)) return;

        const isCompleted = el.getAttribute('data-completed') === 'true';
        const diff = deadline - now;
        const valEl = el.querySelector('.timer-value');
        const labelEl = el.querySelector('.timer-label');

        if (diff <= 0) {
          if (labelEl) labelEl.textContent = 'Deadline:';
          if (valEl) valEl.textContent = 'Passed';
          applyTimerState(el, isCompleted ? 'completed' : 'passed');
          return;
        }

        const formatted = formatTimeRemaining(diff);
        if (labelEl) labelEl.textContent = 'Time Left:';
        if (valEl) valEl.textContent = formatted;

        if (isCompleted) {
          applyTimerState(el, 'completed');
        } else if (diff < 1000 * 60 * 60) {
          applyTimerState(el, 'urgent');
        } else if (diff < 1000 * 60 * 60 * 24) {
          applyTimerState(el, 'warning');
        } else {
          applyTimerState(el, 'normal');
        }
      });
    }

    updateTimers();
    setInterval(updateTimers, 1000);
  },

  // ── Global Initializer ──────────────────────────────────────
  init() {
    this.initDeadlineTimers();
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

    // Delegated click listeners for assignment actions
    document.addEventListener('click', (e) => {
      const delBtn = e.target.closest('.delete-assignment-btn');
      if (delBtn) {
        e.preventDefault();
        const id = delBtn.getAttribute('data-delete-id');
        const label = delBtn.getAttribute('data-delete-label') || '';
        if (id) Kotchy.Assignment.deleteAssignment(parseInt(id, 10), label);
        return;
      }

      const checkBtn = e.target.closest('.check-assignment-btn');
      if (checkBtn) {
        e.preventDefault();
        const id = checkBtn.getAttribute('data-check-id');
        if (id) Kotchy.Assignment.checkAssignment(parseInt(id, 10), checkBtn);
        return;
      }

      const recheckBtn = e.target.closest('.recheck-all-btn');
      if (recheckBtn) {
        e.preventDefault();
        const taskId = recheckBtn.getAttribute('data-recheck-task-id');
        if (taskId) Kotchy.Task.checkAll(parseInt(taskId, 10), recheckBtn);
        return;
      }
    });
  }
};

window.Kotchy = Kotchy;
window.switchContestTab = Kotchy.switchContestTab;

document.addEventListener('DOMContentLoaded', () => Kotchy.init());
