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

  // Checkbox toggles
  document.querySelectorAll('.checkbox-item').forEach(item => {
    item.addEventListener('click', () => {
      const cb = item.querySelector('input[type="checkbox"]');
      cb.checked = !cb.checked;
      item.classList.toggle('checked', cb.checked);
    });
  });

  const saveBtn = document.getElementById('save-settings-btn');
  if (!saveBtn) return;

  saveBtn.addEventListener('click', async () => {
    const platforms = Array.from(
      document.querySelectorAll('.checkbox-item.checked input')
    ).map(cb => cb.value);

    const payload = {
      must_have: mustInput.getValues(),
      nice_to_have: niceInput.getValues(),
      best_match: parseInt(document.getElementById('best-threshold')?.value || 40),
      medium_match: parseInt(document.getElementById('medium-threshold')?.value || 15),
      days_ago: parseInt(document.getElementById('days-ago')?.value || 15),
      location: document.getElementById('search-location')?.value || 'Germany',
      job_titles: jobTitlesInput.getValues(),
      platforms,
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
