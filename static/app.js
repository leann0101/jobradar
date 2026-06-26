// ── Toast notification ─────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 3500) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || '💬'}</span><span>${message}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

// ── Scrape trigger ─────────────────────────────────────────────────────────
async function triggerScrape() {
  const btn = document.getElementById('scrape-btn');
  if (!btn) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scraping...';

  try {
    const res = await fetch('/api/scrape', { method: 'POST' });
    if (res.status === 409) {
      showToast('Scrape already running. Please wait.', 'info');
      btn.disabled = false;
      btn.innerHTML = '🔍 Run Scraper Now';
      return;
    }
    if (!res.ok) throw new Error('Request failed');
    showToast('Scrape started! This may take several minutes.', 'success', 5000);
    // Poll until done
    pollScrapeStatus(btn);
  } catch (e) {
    showToast('Failed to start scraper: ' + e.message, 'error');
    btn.disabled = false;
    btn.innerHTML = '🔍 Run Scraper Now';
  }
}

async function pollScrapeStatus(btn) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch('/api/scrape/status');
      const data = await res.json();
      if (!data.is_scraping) {
        clearInterval(interval);
        showToast('Scrape complete! Refreshing page...', 'success');
        setTimeout(() => window.location.reload(), 1500);
      }
    } catch (e) {
      clearInterval(interval);
    }
  }, 4000);
}

// ── Delete job ─────────────────────────────────────────────────────────────
async function deleteJob(jobId, cardEl) {
  if (!confirm('Remove this job from your list?')) return;
  try {
    const res = await fetch(`/api/jobs/delete/${jobId}`, { method: 'DELETE' });
    if (res.ok) {
      cardEl.style.transition = 'all 0.3s ease';
      cardEl.style.opacity = '0';
      cardEl.style.transform = 'scale(0.95)';
      setTimeout(() => cardEl.remove(), 300);
      showToast('Job removed', 'success');
    }
  } catch (e) {
    showToast('Failed to remove job', 'error');
  }
}

// ── Translate Job Description ────────────────────────────────────────────────
async function translateJD(jobId) {
  const btn = document.getElementById('translate-btn');
  const jdContainer = document.querySelector('.detail-jd');
  if (!btn || !jdContainer) return;
  
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Translating...';
  
  try {
    const res = await fetch(`/api/job/translate/${jobId}`, { method: 'POST' });
    if (!res.ok) throw new Error('Translation request failed');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    
    jdContainer.style.opacity = '0';
    setTimeout(() => {
      jdContainer.innerHTML = data.translated_text.replace(/\n/g, '<br>');
      jdContainer.style.opacity = '1';
      btn.innerHTML = '✅ Translated to English';
    }, 300);
  } catch (e) {
    showToast('Failed to translate: ' + e.message, 'error');
    btn.disabled = false;
    btn.innerHTML = '🌐 Translate to English';
  }
}

// ── Tag input manager ──────────────────────────────────────────────────────
class TagInput {
  constructor(containerId, hiddenInputId, tagClass = '') {
    this.container = document.getElementById(containerId);
    this.hiddenInput = document.getElementById(hiddenInputId);
    this.tagClass = tagClass;
    this.tags = [];

    if (!this.container) return;

    // Load existing tags from hidden input
    try {
      const existing = JSON.parse(this.hiddenInput?.value || '[]');
      existing.forEach(t => this.addTag(t));
    } catch (e) {}

    // Create text input
    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.className = 'tag-text-input';
    this.input.placeholder = 'Type and press Enter...';
    this.container.appendChild(this.input);

    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        const val = this.input.value.trim().replace(/,$/, '');
        if (val) { this.addTag(val); this.input.value = ''; }
      } else if (e.key === 'Backspace' && !this.input.value && this.tags.length) {
        this.removeTag(this.tags[this.tags.length - 1]);
      }
    });

    this.container.addEventListener('click', () => this.input.focus());
  }

  addTag(text) {
    if (!text || this.tags.includes(text)) return;
    this.tags.push(text);
    this.renderTag(text);
    this.sync();
  }

  renderTag(text) {
    const tag = document.createElement('span');
    tag.className = `tag-item ${this.tagClass}`;
    tag.innerHTML = `${text}<button class="tag-remove" data-tag="${text}">×</button>`;
    tag.querySelector('.tag-remove').addEventListener('click', (e) => {
      e.stopPropagation();
      this.removeTag(text);
    });
    this.container.insertBefore(tag, this.input);
  }

  removeTag(text) {
    this.tags = this.tags.filter(t => t !== text);
    this.container.querySelectorAll('.tag-item').forEach(el => {
      if (el.querySelector('[data-tag]')?.dataset.tag === text) el.remove();
    });
    this.sync();
  }

  sync() {
    if (this.hiddenInput) {
      this.hiddenInput.value = JSON.stringify(this.tags);
    }
  }

  getValues() { return this.tags; }
}

// ── Settings form ──────────────────────────────────────────────────────────
function initSettingsPage() {
  const mustInput = new TagInput('must-have-input', 'must-have-hidden', 'must');
  const niceInput = new TagInput('nice-to-have-input', 'nice-to-have-hidden', 'nice');
  const jobTitlesInput = new TagInput('job-titles-input', 'job-titles-hidden', 'job-title');

  // Checkbox toggles with safe double-toggle prevention
  document.querySelectorAll('.checkbox-item').forEach(item => {
    item.addEventListener('click', (e) => {
      const cb = item.querySelector('input[type="checkbox"]');
      if (e.target !== cb) {
        e.preventDefault();
        cb.checked = !cb.checked;
      }
      item.classList.toggle('checked', cb.checked);
    });
  });

  // Resume Analysis Logic
  const analyzeBtn = document.getElementById('analyze-resume-btn');
  const resumeTextarea = document.getElementById('resume-text');
  const recPanel = document.getElementById('recommendations-panel');
  const recTitlesDiv = document.getElementById('rec-job-titles');
  const recKeywordsDiv = document.getElementById('rec-keywords');

  if (analyzeBtn && resumeTextarea) {
    analyzeBtn.addEventListener('click', async () => {
      const resumeText = resumeTextarea.value.trim();
      if (!resumeText) {
        showToast('Please paste your resume text first.', 'error');
        return;
      }

      analyzeBtn.disabled = true;
      analyzeBtn.innerHTML = '<span class="spinner"></span> Analyzing...';
      recPanel.style.display = 'none';

      try {
        const res = await fetch('/api/resume/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ resume_text: resumeText })
        });
        
        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.error || 'Analysis failed');
        }

        const data = await res.json();
        
        // Render Job Titles
        recTitlesDiv.innerHTML = '';
        if (data.recommended_titles && data.recommended_titles.length > 0) {
          data.recommended_titles.forEach(title => {
            const badge = document.createElement('span');
            badge.className = 'keyword-tag';
            badge.style.cursor = 'pointer';
            badge.style.background = 'rgba(79, 142, 247, 0.15)';
            badge.style.borderColor = 'rgba(79, 142, 247, 0.3)';
            badge.style.color = 'var(--accent-blue)';
            badge.innerHTML = `+ ${title}`;
            badge.addEventListener('click', () => {
              jobTitlesInput.addTag(title);
              showToast(`Added title: "${title}"`, 'success');
            });
            recTitlesDiv.appendChild(badge);
          });
        } else {
          recTitlesDiv.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No title recommendations</span>';
        }

        // Render Keywords
        recKeywordsDiv.innerHTML = '';
        if (data.recommended_keywords && data.recommended_keywords.length > 0) {
          data.recommended_keywords.forEach(kw => {
            const badge = document.createElement('span');
            badge.className = 'keyword-tag';
            badge.style.cursor = 'pointer';
            badge.style.background = 'rgba(167, 139, 250, 0.15)';
            badge.style.borderColor = 'rgba(167, 139, 250, 0.3)';
            badge.style.color = 'var(--accent-purple)';
            badge.innerHTML = `+ ${kw}`;
            badge.addEventListener('click', () => {
              mustInput.addTag(kw);
              showToast(`Added keyword: "${kw}"`, 'success');
            });
            recKeywordsDiv.appendChild(badge);
          });
        } else {
          recKeywordsDiv.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No keyword recommendations</span>';
        }

        recPanel.style.display = 'block';
        showToast('Resume analysis complete!', 'success');
      } catch (e) {
        showToast('Error analyzing resume: ' + e.message, 'error');
      } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = '🔍 Analyze Resume with AI';
      }
    });
  }

  const saveBtn = document.getElementById('save-settings-btn');
  if (!saveBtn) return;

  saveBtn.addEventListener('click', async () => {
    // Helper to get checked values inside a container ID
    const getCheckedList = (containerId) => {
      const container = document.getElementById(containerId);
      if (!container) return [];
      return Array.from(
        container.querySelectorAll('.checkbox-item.checked input')
      ).map(cb => cb.value);
    };

    const platforms = Array.from(
      document.querySelectorAll('input[id^="platform-"]:checked')
    ).map(cb => cb.value);

    const payload = {
      must_have: mustInput.getValues(),
      nice_to_have: niceInput.getValues(),
      best_match: parseInt(document.getElementById('best-threshold')?.value || 80),
      medium_match: parseInt(document.getElementById('medium-threshold')?.value || 60),
      career_objective: {
        target_archetype: document.getElementById('target-archetype')?.value || '',
        target_trajectory: document.getElementById('target-trajectory')?.value || '',
      },
      override_rules: {
        min_problem_space: parseInt(document.getElementById('min-problem-space')?.value || 1),
        min_product_stage: parseInt(document.getElementById('min-product-stage')?.value || 3),
        min_decision_power: parseInt(document.getElementById('min-decision-power')?.value || 3),
        min_customer_interaction: parseInt(document.getElementById('min-customer-interaction')?.value || 1),
        min_problem_definition_clarity: parseInt(document.getElementById('min-problem-definition-clarity')?.value || 1),
      },
      days_ago: parseInt(document.getElementById('days-ago')?.value || 15),
      location: document.getElementById('search-location')?.value || 'Germany',
      job_titles: jobTitlesInput.getValues(),
      platforms,
      experience_levels: getCheckedList('experience-levels-group'),
      location_types: getCheckedList('location-types-group'),
      employment_types: getCheckedList('employment-types-group'),
      languages: getCheckedList('languages-group'),
      resume_text: resumeTextarea ? resumeTextarea.value.trim() : "",
    };

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
      const res = await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('Settings saved!', 'success');
      } else {
        showToast('Failed to save settings', 'error');
      }
    } catch (e) {
      showToast('Network error', 'error');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save Settings';
    }
  });
}

// ── Page init ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Init scrape button
  const scrapeBtn = document.getElementById('scrape-btn');
  if (scrapeBtn) scrapeBtn.addEventListener('click', triggerScrape);

  // Init settings page
  if (document.querySelector('.settings-grid')) initSettingsPage();

  // Mobile Menu Toggle
  const menuToggle = document.getElementById('menu-toggle');
  const mobileNav = document.getElementById('mobile-nav');
  if (menuToggle && mobileNav) {
    menuToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      mobileNav.classList.toggle('open');
      menuToggle.textContent = mobileNav.classList.contains('open') ? '✕' : '☰';
    });

    // Close menu when clicking outside
    document.addEventListener('click', () => {
      if (mobileNav.classList.contains('open')) {
        mobileNav.classList.remove('open');
        menuToggle.textContent = '☰';
      }
    });
  }

  // Animate cards on load
  document.querySelectorAll('.job-card').forEach((card, i) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(16px)';
    setTimeout(() => {
      card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, i * 60);
  });
});
