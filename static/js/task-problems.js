/**
 * static/js/task-problems.js
 * ───────────────────────────
 * Common, reusable interactions for task problem sets and contest standings.
 * Works across Codeforces, AtCoder, CSES, and any problem sets from different sites.
 */

(function () {
  'use strict';

  window.Kotchy = window.Kotchy || {};

  const TaskProblems = {
    /**
     * Switch between task tabs (e.g., 'problems' vs 'standings').
     * @param {string} tabName - 'problems' | 'standings' | custom
     * @param {string} [prefix='contest'] - optional prefix for tab/button IDs
     */
    switchTab(tabName, prefix = 'contest') {
      const problemsPane = document.getElementById(`${prefix}-tab-problems`) || document.getElementById('contest-tab-problems');
      const standingsPane = document.getElementById(`${prefix}-tab-standings`) || document.getElementById('contest-tab-standings');
      const problemsBtn = document.getElementById(`tab-btn-problems`) || document.querySelector(`[data-tab="problems"]`);
      const standingsBtn = document.getElementById(`tab-btn-standings`) || document.querySelector(`[data-tab="standings"]`);

      if (!problemsPane || !standingsPane) return;

      if (tabName === 'standings') {
        problemsPane.style.setProperty('display', 'none', 'important');
        problemsPane.classList.add('hidden');
        standingsPane.style.setProperty('display', 'block', 'important');
        standingsPane.classList.remove('hidden');

        if (standingsBtn) {
          standingsBtn.classList.add('active');
          standingsBtn.setAttribute('aria-selected', 'true');
        }
        if (problemsBtn) {
          problemsBtn.classList.remove('active');
          problemsBtn.setAttribute('aria-selected', 'false');
        }
        try {
          history.replaceState(null, '', '#standings');
        } catch (e) {}
      } else {
        standingsPane.style.setProperty('display', 'none', 'important');
        standingsPane.classList.add('hidden');
        problemsPane.style.setProperty('display', 'block', 'important');
        problemsPane.classList.remove('hidden');

        if (problemsBtn) {
          problemsBtn.classList.add('active');
          problemsBtn.setAttribute('aria-selected', 'true');
        }
        if (standingsBtn) {
          standingsBtn.classList.remove('active');
          standingsBtn.setAttribute('aria-selected', 'false');
        }
        try {
          history.replaceState(null, '', '#problems');
        } catch (e) {}
      }
    },

    /**
     * Coach helper to filter/highlight solves for a specific student.
     * @param {string|number} studentId
     */
    switchStudent(studentId) {
      if (typeof Kotchy.switchContestStudent === 'function' && Kotchy.switchContestStudent !== TaskProblems.switchStudent) {
        Kotchy.switchContestStudent(studentId);
        return;
      }
      const url = new URL(window.location);
      if (studentId) {
        url.searchParams.set('student_id', studentId);
      } else {
        url.searchParams.delete('student_id');
      }
      window.location = url.toString();
    },

    /**
     * Toggle visibility of solved problems in the problems table.
     * @param {boolean} hide
     */
    setHideSolved(hide) {
      const solvedRows = document.querySelectorAll('.problem-row.is-solved, .problem-row[data-solved="true"]');
      solvedRows.forEach((row) => {
        if (hide) {
          row.style.setProperty('display', 'none', 'important');
        } else {
          row.style.removeProperty('display');
        }
      });

      // Show friendly empty state if all rows are hidden
      const allRows = document.querySelectorAll('.problem-row');
      const emptyRow = document.getElementById('all-problems-solved-message');
      const visibleRows = Array.from(allRows).filter((r) => r.style.display !== 'none');
      if (emptyRow) {
        if (allRows.length > 0 && visibleRows.length === 0 && hide) {
          emptyRow.classList.remove('hidden');
        } else {
          emptyRow.classList.add('hidden');
        }
      }

      // Persist state in localStorage
      try {
        localStorage.setItem('kotchy_hide_solved_problems', hide ? '1' : '0');
      } catch (e) {}

      // Keep checkbox element in sync
      const cb = document.getElementById('hide-solved-problems-checkbox');
      if (cb && cb.checked !== hide) {
        cb.checked = hide;
      }
    },

    /**
     * Initialize tab click listeners and auto-activate hash tab.
     */
    init() {
      const pBtn = document.getElementById('tab-btn-problems') || document.querySelector('[data-tab="problems"]');
      const sBtn = document.getElementById('tab-btn-standings') || document.querySelector('[data-tab="standings"]');

      if (pBtn) {
        pBtn.addEventListener('click', function (e) {
          e.preventDefault();
          TaskProblems.switchTab('problems');
        });
      }

      if (sBtn) {
        sBtn.addEventListener('click', function (e) {
          e.preventDefault();
          TaskProblems.switchTab('standings');
        });
      }

      // Checkbox for hiding solved problems
      const hideSolvedCb = document.getElementById('hide-solved-problems-checkbox');
      if (hideSolvedCb) {
        let saved = false;
        try {
          saved = localStorage.getItem('kotchy_hide_solved_problems') === '1';
        } catch (e) {}

        hideSolvedCb.checked = saved;
        if (saved) {
          TaskProblems.setHideSolved(true);
        }

        hideSolvedCb.addEventListener('change', function () {
          TaskProblems.setHideSolved(this.checked);
        });
      }

      // Auto-activate tab from URL hash if provided
      if (window.location.hash === '#standings') {
        TaskProblems.switchTab('standings');
      } else if (window.location.hash === '#problems') {
        TaskProblems.switchTab('problems');
      }
    },
  };

  // Expose on Kotchy namespace and global window for backward compatibility
  Kotchy.TaskProblems = TaskProblems;
  window.switchContestTab = TaskProblems.switchTab;
  Kotchy.switchContestTab = TaskProblems.switchTab;

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', TaskProblems.init);
  } else {
    TaskProblems.init();
  }
})();
