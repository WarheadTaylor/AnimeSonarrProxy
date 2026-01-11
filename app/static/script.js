// Global state
let allMappings = [];

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadMappings();
    setupEventListeners();
});

function setupEventListeners() {
    // Form submission
    document.getElementById('override-form').addEventListener('submit', handleOverrideSubmit);

    // Search filter
    document.getElementById('search-mappings').addEventListener('input', filterMappings);
}

async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();

        document.getElementById('total-mappings').textContent = stats.total_mappings;
        document.getElementById('total-overrides').textContent = stats.total_overrides;

        if (stats.anime_db_last_update) {
            const date = new Date(stats.anime_db_last_update);
            document.getElementById('last-update').textContent = formatDate(date);
        }
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

async function loadMappings() {
    try {
        const response = await fetch('/api/mappings');
        allMappings = await response.json();

        renderMappings(allMappings);
    } catch (error) {
        console.error('Failed to load mappings:', error);
        document.getElementById('mappings-list').innerHTML =
            '<p style="color: red;">Failed to load mappings. Check console for errors.</p>';
    }
}

function renderMappings(mappings) {
    const container = document.getElementById('mappings-list');

    if (mappings.length === 0) {
        container.innerHTML = '<p>No mappings found. Search for an anime in Sonarr to create mappings.</p>';
        return;
    }

    const html = mappings.map(mapping => createMappingCard(mapping)).join('');
    container.innerHTML = html;
}

function createMappingCard(mapping) {
    const titles = getAllTitles(mapping);
    const overrideBadge = mapping.user_override
        ? '<span class="badge">USER OVERRIDE</span>'
        : '';

    return `
        <div class="mapping-card">
            <div class="mapping-header">
                <div class="mapping-title">
                    <h3>${escapeHtml(titles[0] || 'Unknown')}</h3>
                    ${overrideBadge}
                </div>
                ${mapping.user_override ? `
                    <button class="btn-danger" onclick="deleteOverride(${mapping.tvdb_id})">
                        Delete Override
                    </button>
                ` : ''}
            </div>

            <div class="mapping-ids">
                <span><strong>TVDB:</strong> ${mapping.tvdb_id}</span>
                ${mapping.anilist_id ? `<span><strong>AniList:</strong> ${mapping.anilist_id}</span>` : ''}
                ${mapping.mal_id ? `<span><strong>MAL:</strong> ${mapping.mal_id}</span>` : ''}
                ${mapping.total_episodes ? `<span><strong>Episodes:</strong> ${mapping.total_episodes}</span>` : ''}
            </div>

            <div class="mapping-titles">
                <h4>Search Titles:</h4>
                <div class="title-list">
                    ${titles.map(title => `<span class="title-tag">${escapeHtml(title)}</span>`).join('')}
                </div>
            </div>
        </div>
    `;
}

function getAllTitles(mapping) {
    const titles = new Set();

    if (mapping.titles.romaji) titles.add(mapping.titles.romaji);
    if (mapping.titles.english) titles.add(mapping.titles.english);
    if (mapping.titles.native) titles.add(mapping.titles.native);

    if (mapping.titles.synonyms) {
        mapping.titles.synonyms.forEach(s => titles.add(s));
    }

    return Array.from(titles);
}

function filterMappings() {
    const query = document.getElementById('search-mappings').value.toLowerCase();

    if (!query) {
        renderMappings(allMappings);
        return;
    }

    const filtered = allMappings.filter(mapping => {
        // Search by TVDB ID
        if (mapping.tvdb_id.toString().includes(query)) {
            return true;
        }

        // Search by any title
        const titles = getAllTitles(mapping);
        return titles.some(title => title.toLowerCase().includes(query));
    });

    renderMappings(filtered);
}

async function handleOverrideSubmit(event) {
    event.preventDefault();

    const tvdbId = parseInt(document.getElementById('tvdb-id').value);
    const anilistId = document.getElementById('anilist-id').value;
    const malId = document.getElementById('mal-id').value;
    const customTitles = document.getElementById('custom-titles').value
        .split('\n')
        .map(t => t.trim())
        .filter(t => t.length > 0);
    const notes = document.getElementById('notes').value;

    const override = {
        tvdb_id: tvdbId,
        anilist_id: anilistId ? parseInt(anilistId) : null,
        mal_id: malId ? parseInt(malId) : null,
        custom_titles: customTitles,
        notes: notes,
        season_episode_overrides: {}
    };

    try {
        const response = await fetch('/api/mappings/override', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(override)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save override');
        }

        showNotification('Override saved successfully!', 'success');

        // Reset form
        document.getElementById('override-form').reset();

        // Reload data
        await loadStats();
        await loadMappings();

    } catch (error) {
        console.error('Failed to save override:', error);
        showNotification(error.message, 'error');
    }
}

async function deleteOverride(tvdbId) {
    if (!confirm(`Delete override for TVDB ID ${tvdbId}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/mappings/override/${tvdbId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to delete override');
        }

        showNotification('Override deleted successfully!', 'success');

        // Reload data
        await loadStats();
        await loadMappings();

    } catch (error) {
        console.error('Failed to delete override:', error);
        showNotification(error.message, 'error');
    }
}

function showNotification(message, type = 'success') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type === 'error' ? 'error' : ''}`;

    // Auto-hide after 3 seconds
    setTimeout(() => {
        notification.className = 'notification hidden';
    }, 3000);
}

function formatDate(date) {
    const now = new Date();
    const diff = now - date;
    const hours = Math.floor(diff / 1000 / 60 / 60);

    if (hours < 24) {
        return `${hours}h ago`;
    }

    const days = Math.floor(hours / 24);
    if (days < 7) {
        return `${days}d ago`;
    }

    return date.toLocaleDateString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
