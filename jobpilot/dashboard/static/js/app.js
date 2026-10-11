/* ═══════════════════════════════════════════════════════════
   JobPilot Dashboard — JavaScript Application
   ═══════════════════════════════════════════════════════════ */

const API_BASE = '';

// ─── State ──────────────────────────────────────────────
let currentView = 'dashboard';
let allJobs = [];

// ─── Initialization ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    loadJobs();

    // Auto-refresh every 60 seconds
    setInterval(() => {
        if (currentView === 'dashboard') loadDashboard();
    }, 60000);
});

// ─── Navigation ─────────────────────────────────────────
function switchView(viewName) {
    // Hide all views
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    // Show selected view
    const view = document.getElementById(`view-${viewName}`);
    const nav = document.getElementById(`nav-${viewName}`);
    if (view) view.classList.add('active');
    if (nav) nav.classList.add('active');

    currentView = viewName;

    // Update page title
    const titles = {
        dashboard: 'Dashboard',
        jobs: 'All Jobs',
        shortlisted: 'Shortlisted',
        applied: 'Applied',
        history: 'Scrape History',
    };
    document.getElementById('page-title').textContent = titles[viewName] || viewName;

    // Load data for the view
    switch (viewName) {
        case 'dashboard': loadDashboard(); break;
        case 'jobs': loadJobs(); break;
        case 'shortlisted': loadJobsByStatus('shortlisted', 'shortlisted-list'); break;
        case 'applied': loadJobsByStatus('applied', 'applied-list'); break;
        case 'history': loadHistory(); break;
    }
}

// Set up nav click handlers
document.querySelectorAll('.nav-item[data-view]').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        switchView(item.dataset.view);
    });
});

// ─── Sidebar Toggle (Mobile) ────────────────────────────
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ─── Dashboard ──────────────────────────────────────────
async function loadDashboard() {
    try {
        const stats = await apiGet('/api/stats');

        // Update stat cards with animation
        animateValue('stat-total', stats.total_jobs || 0);
        animateValue('stat-today', stats.today_new || 0);
        document.getElementById('stat-avg-score').textContent = `${stats.avg_match_score || 0}%`;

        const applied = (stats.by_status || {}).applied || 0;
        animateValue('stat-applied', applied);

        // Update jobs count badge
        document.getElementById('jobs-count-badge').textContent = stats.total_jobs || 0;

        // Platform breakdown bars
        renderPlatformBars(stats.by_platform || {}, stats.total_jobs || 1);

        // Top matches
        const topJobs = await apiGet('/api/jobs?status=matched&min_score=50&limit=8');
        renderTopMatches(topJobs.jobs || []);

    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

function animateValue(elementId, endValue) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const startValue = parseInt(el.textContent) || 0;
    if (startValue === endValue) {
        el.textContent = endValue;
        return;
    }

    const duration = 600;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
        const current = Math.round(startValue + (endValue - startValue) * eased);
        el.textContent = current;
        if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
}

function renderPlatformBars(byPlatform, total) {
    const container = document.getElementById('platform-bars');
    const platforms = ['cutshort', 'wellfound', 'hirist', 'linkedin'];

    if (Object.keys(byPlatform).length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📊</div>
                <h3>No data yet</h3>
                <p>Run a scrape to see platform breakdown</p>
            </div>`;
        return;
    }

    container.innerHTML = platforms.map(p => {
        const count = byPlatform[p] || 0;
        const pct = total > 0 ? Math.round((count / total) * 100) : 0;
        return `
            <div class="platform-bar">
                <span class="platform-bar-label">${p}</span>
                <div class="platform-bar-track">
                    <div class="platform-bar-fill ${p}" style="width: ${Math.max(pct, 5)}%">
                        ${count}
                    </div>
                </div>
            </div>`;
    }).join('');
}

function renderTopMatches(jobs) {
    const container = document.getElementById('top-matches-list');

    if (jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🎯</div>
                <h3>No matched jobs yet</h3>
                <p>Scrape some jobs and run AI matching</p>
            </div>`;
        return;
    }

    container.innerHTML = jobs.map(job => createJobCard(job)).join('');
}

// ─── Jobs Table ─────────────────────────────────────────
async function loadJobs() {
    try {
        const platform = document.getElementById('filter-platform')?.value || 'all';
        const status = document.getElementById('filter-status')?.value || 'all';
        const minScore = document.getElementById('filter-min-score')?.value || '';

        let url = `/api/jobs?limit=200`;
        if (platform !== 'all') url += `&platform=${platform}`;
        if (status !== 'all') url += `&status=${status}`;
        if (minScore) url += `&min_score=${minScore}`;

        const data = await apiGet(url);
        allJobs = data.jobs || [];

        renderJobTable(allJobs);
    } catch (err) {
        console.error('Jobs load error:', err);
    }
}

function renderJobTable(jobs) {
    const tbody = document.getElementById('job-table-body');
    if (!tbody) return;

    if (jobs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7">
                    <div class="empty-state">
                        <div class="empty-icon">📭</div>
                        <h3>No jobs found</h3>
                        <p>Try adjusting your filters or run a scrape</p>
                    </div>
                </td>
            </tr>`;
        return;
    }

    tbody.innerHTML = jobs.map(job => {
        const scoreClass = getScoreClass(job.match_score);
        const scoreDisplay = job.match_score > 0 ? `${Math.round(job.match_score)}%` : '—';

        return `
            <tr onclick="openJobModal(${job.id})">
                <td><span class="score-badge ${scoreClass}">${scoreDisplay}</span></td>
                <td><strong>${escapeHtml(job.title)}</strong></td>
                <td>${escapeHtml(job.company)}</td>
                <td><span class="platform-badge ${job.platform}">${job.platform}</span></td>
                <td>${escapeHtml(job.location || '—')}</td>
                <td><span class="status-badge ${job.status}">${job.status}</span></td>
                <td>
                    <div class="job-actions" onclick="event.stopPropagation()">
                        ${job.status !== 'shortlisted' ? 
                            `<button class="btn btn-sm btn-warning" onclick="updateStatus(${job.id}, 'shortlisted')" title="Shortlist">⭐</button>` : ''}
                        ${job.status !== 'applied' ?
                            `<button class="btn btn-sm btn-success" onclick="updateStatus(${job.id}, 'applied')" title="Mark Applied">✅</button>` : ''}
                        ${job.status !== 'rejected' ?
                            `<button class="btn btn-sm btn-ghost" onclick="updateStatus(${job.id}, 'rejected')" title="Reject">✕</button>` : ''}
                    </div>
                </td>
            </tr>`;
    }).join('');
}

// ─── Jobs by Status ─────────────────────────────────────
async function loadJobsByStatus(status, containerId) {
    try {
        const data = await apiGet(`/api/jobs?status=${status}&limit=100`);
        const container = document.getElementById(containerId);
        const jobs = data.jobs || [];

        if (jobs.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">${status === 'shortlisted' ? '⭐' : '✅'}</div>
                    <h3>No ${status} jobs</h3>
                    <p>Jobs you ${status === 'shortlisted' ? 'shortlist' : 'apply to'} will appear here</p>
                </div>`;
            return;
        }

        container.innerHTML = jobs.map(job => createJobCard(job)).join('');
    } catch (err) {
        console.error(`Load ${status} error:`, err);
    }
}

// ─── Job Card Component ─────────────────────────────────
function createJobCard(job) {
    const scoreClass = getScoreClass(job.match_score);
    const scoreDisplay = job.match_score > 0 ? `${Math.round(job.match_score)}%` : '—';

    return `
        <div class="job-card" onclick="openJobModal(${job.id})">
            <div class="job-score ${scoreClass}">${scoreDisplay}</div>
            <div class="job-info">
                <div class="job-title">${escapeHtml(job.title)}</div>
                <div class="job-meta">
                    <span>${escapeHtml(job.company)}</span>
                    <span>•</span>
                    <span class="platform-badge ${job.platform}">${job.platform}</span>
                    ${job.location ? `<span>•</span><span>📍 ${escapeHtml(job.location)}</span>` : ''}
                </div>
            </div>
            <div class="job-actions" onclick="event.stopPropagation()">
                <button class="btn btn-sm btn-warning" onclick="updateStatus(${job.id}, 'shortlisted')" title="Shortlist">⭐</button>
                <button class="btn btn-sm btn-success" onclick="updateStatus(${job.id}, 'applied')" title="Applied">✅</button>
            </div>
        </div>`;
}

// ─── Job Detail Modal ───────────────────────────────────
async function openJobModal(jobId) {
    try {
        const job = await apiGet(`/api/jobs/${jobId}`);
        const scoreClass = getScoreClass(job.match_score);
        const scoreDisplay = job.match_score > 0 ? `${Math.round(job.match_score)}%` : '—';

        const skills = job.skills ? job.skills.split(',').filter(s => s.trim()) : [];
        const skillsHtml = skills.length > 0
            ? `<div class="skill-tags">${skills.map(s => `<span class="skill-tag">${escapeHtml(s.trim())}</span>`).join('')}</div>`
            : '<span style="color: var(--text-muted)">Not specified</span>';

        document.getElementById('modal-body').innerHTML = `
            <h2>${escapeHtml(job.title)}</h2>
            <div class="modal-company">${escapeHtml(job.company)}</div>

            <div class="modal-detail-grid">
                <div class="modal-detail">
                    <div class="modal-detail-label">Match Score</div>
                    <div class="modal-detail-value"><span class="score-badge ${scoreClass}">${scoreDisplay}</span></div>
                </div>
                <div class="modal-detail">
                    <div class="modal-detail-label">Platform</div>
                    <div class="modal-detail-value"><span class="platform-badge ${job.platform}">${job.platform}</span></div>
                </div>
                <div class="modal-detail">
                    <div class="modal-detail-label">Location</div>
                    <div class="modal-detail-value">${escapeHtml(job.location || 'Not specified')}</div>
                </div>
                <div class="modal-detail">
                    <div class="modal-detail-label">Status</div>
                    <div class="modal-detail-value"><span class="status-badge ${job.status}">${job.status}</span></div>
                </div>
                ${job.salary ? `
                <div class="modal-detail">
                    <div class="modal-detail-label">Salary</div>
                    <div class="modal-detail-value">${escapeHtml(job.salary)}</div>
                </div>` : ''}
                ${job.experience ? `
                <div class="modal-detail">
                    <div class="modal-detail-label">Experience</div>
                    <div class="modal-detail-value">${escapeHtml(job.experience)}</div>
                </div>` : ''}
            </div>

            <div class="modal-section">
                <h3>Skills</h3>
                ${skillsHtml}
            </div>

            ${job.match_reason ? `
            <div class="modal-section">
                <h3>AI Match Analysis</h3>
                <p>${escapeHtml(job.match_reason)}</p>
            </div>` : ''}

            ${job.description ? `
            <div class="modal-section">
                <h3>Job Description</h3>
                <p>${escapeHtml(job.description).substring(0, 1000)}</p>
            </div>` : ''}

            ${job.generated_cover_letter ? `
            <div class="modal-section">
                <h3>Generated Cover Letter</h3>
                <p style="white-space: pre-wrap;">${escapeHtml(job.generated_cover_letter)}</p>
            </div>` : ''}

            <div class="modal-actions">
                <a href="${escapeHtml(job.url)}" target="_blank" class="btn btn-primary">
                    🔗 Open Job Listing
                </a>
                <button class="btn btn-warning" onclick="updateStatus(${job.id}, 'shortlisted'); closeJobModal()">
                    ⭐ Shortlist
                </button>
                <button class="btn btn-success" onclick="updateStatus(${job.id}, 'applied'); closeJobModal()">
                    ✅ Mark Applied
                </button>
                <button class="btn btn-secondary" onclick="generateCoverLetter(${job.id})">
                    ✍️ Generate Cover Letter
                </button>
                <button class="btn btn-ghost" onclick="updateStatus(${job.id}, 'rejected'); closeJobModal()">
                    ✕ Reject
                </button>
            </div>
        `;

        document.getElementById('job-modal').classList.add('active');
    } catch (err) {
        showToast('Failed to load job details', 'error');
    }
}

function closeJobModal() {
    document.getElementById('job-modal').classList.remove('active');
}

function closeModal(event) {
    if (event.target === event.currentTarget) {
        closeJobModal();
    }
}

// Close modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeJobModal();
});

// ─── History ────────────────────────────────────────────
async function loadHistory() {
    try {
        const data = await apiGet('/api/history');
        const tbody = document.getElementById('history-table-body');
        const history = data.history || [];

        if (history.length === 0) {
            tbody.innerHTML = `
                <tr><td colspan="6">
                    <div class="empty-state">
                        <div class="empty-icon">📜</div>
                        <h3>No scrape history</h3>
                        <p>Run your first scrape to see history here</p>
                    </div>
                </td></tr>`;
            return;
        }

        tbody.innerHTML = history.map(h => `
            <tr>
                <td><span class="platform-badge ${h.platform}">${h.platform}</span></td>
                <td>${h.jobs_found}</td>
                <td style="color: var(--accent-success)">${h.jobs_new}</td>
                <td style="color: var(--text-muted)">${h.jobs_duplicate}</td>
                <td>${h.success ? '✅' : '❌'}</td>
                <td style="color: var(--text-muted)">${formatDate(h.completed_at || h.started_at)}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('History load error:', err);
    }
}

// ─── Actions ────────────────────────────────────────────
async function updateStatus(jobId, status) {
    try {
        await apiPost(`/api/jobs/${jobId}/status`, { status });
        showToast(`Job marked as ${status}`, 'success');

        // Refresh current view
        if (currentView === 'dashboard') loadDashboard();
        else if (currentView === 'jobs') loadJobs();
        else if (currentView === 'shortlisted') loadJobsByStatus('shortlisted', 'shortlisted-list');
        else if (currentView === 'applied') loadJobsByStatus('applied', 'applied-list');
    } catch (err) {
        showToast('Failed to update status', 'error');
    }
}

async function triggerScrape() {
    const btn = document.getElementById('btn-scrape');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Scraping...';
    showToast('Scraping started... this may take a few minutes', 'info');

    try {
        const data = await apiPost('/api/scrape', { platform: 'all' });
        const results = data.results || [];

        let totalNew = 0;
        results.forEach(r => { totalNew += r.jobs_new || 0; });
        showToast(`Scrape complete! ${totalNew} new jobs found`, 'success');

        loadDashboard();
        loadJobs();
    } catch (err) {
        showToast('Scrape failed: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>🔍</span> Scrape Now';
    }
}

async function triggerMatch() {
    const btn = document.getElementById('btn-match');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Matching...';
    showToast('AI matching started...', 'info');

    try {
        const data = await apiPost('/api/match');
        showToast(`AI matching complete! Scored ${data.scored} jobs`, 'success');
        loadDashboard();
        loadJobs();
    } catch (err) {
        showToast('Matching failed: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>🤖</span> AI Match';
    }
}

async function triggerAutoApply() {
    const btn = document.getElementById('btn-apply');
    if (!confirm('Start auto-applying to Cutshort jobs matching your profile?')) return;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Applying...';
    }
    showToast('Auto-apply started for Cutshort jobs...', 'info');

    try {
        const data = await apiPost('/api/apply', { dry_run: false, limit: 15 });
        showToast(`Auto-apply finished: ${data.applied || 0} applied, ${data.already_applied || 0} already applied`, 'success');
        loadDashboard();
        loadJobs();
    } catch (err) {
        showToast('Auto-apply failed: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span>🚀</span> Auto Apply';
        }
    }
}


async function generateCoverLetter(jobId) {
    showToast('Generating cover letter...', 'info');
    try {
        const data = await apiPost(`/api/jobs/${jobId}/cover-letter`);
        if (data.cover_letter) {
            showToast('Cover letter generated!', 'success');
            openJobModal(jobId); // Refresh modal
        } else {
            showToast('Failed to generate cover letter', 'error');
        }
    } catch (err) {
        showToast('Cover letter error: ' + err.message, 'error');
    }
}

// ─── Search ─────────────────────────────────────────────
let searchTimeout;
function handleSearch(event) {
    clearTimeout(searchTimeout);
    const query = event.target.value.trim();

    searchTimeout = setTimeout(async () => {
        if (query.length < 2) {
            loadJobs();
            return;
        }

        try {
            const data = await apiGet(`/api/jobs?search=${encodeURIComponent(query)}`);
            renderJobTable(data.jobs || []);
            switchView('jobs');
        } catch (err) {
            console.error('Search error:', err);
        }
    }, 300);
}

// ─── API Helpers ────────────────────────────────────────
async function apiGet(url) {
    const res = await fetch(API_BASE + url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiPost(url, body = {}) {
    const res = await fetch(API_BASE + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

// ─── Utilities ──────────────────────────────────────────
function getScoreClass(score) {
    if (!score || score === 0) return 'none';
    if (score >= 70) return 'high';
    if (score >= 50) return 'medium';
    return 'low';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-IN', {
            day: 'numeric',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return dateStr;
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span> ${escapeHtml(message)}`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
