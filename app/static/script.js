// Global state
let allMappings = [];
let allMovieMappings = [];
let currentEpisodeMappings = {};  // {"S01E01": 1, "S01E02": 2, ...}
let currentSeasonRanges = [];     // [{season: 1, episodes: 12, start_absolute: 1}]
let editingTvdbId = null;         // null = create mode, number = edit mode
let editingTmdbId = null;         // null = create mode, number = edit mode (for movies)
let currentTab = 'tv';            // 'tv' or 'movies'

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadMappings();
    loadMovieMappings();
    setupEventListeners();
    renderEpisodeMappings();
});

function setupEventListeners() {
    // Form submission
    document.getElementById('override-form').addEventListener('submit', handleOverrideSubmit);
    document.getElementById('movie-override-form').addEventListener('submit', handleMovieOverrideSubmit);

    // Search filters
    document.getElementById('search-mappings').addEventListener('input', filterMappings);
    document.getElementById('search-movie-mappings').addEventListener('input', filterMovieMappings);
}

function switchTab(tab) {
    currentTab = tab;

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tab}-tab`);
    });
}

async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();

        document.getElementById('total-mappings').textContent = stats.total_mappings;
        document.getElementById('total-overrides').textContent = stats.total_overrides;
        document.getElementById('total-movie-mappings').textContent = stats.total_movie_mappings || 0;
        document.getElementById('total-movie-overrides').textContent = stats.total_movie_overrides || 0;

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

    // Load episode override info for user overrides
    mappings.filter(m => m.user_override).forEach(mapping => {
        loadEpisodeOverrideInfo(mapping.tvdb_id);
    });
}

function createMappingCard(mapping) {
    const titles = getAllTitles(mapping);
    const overrideBadge = mapping.user_override
        ? '<span class="badge">USER OVERRIDE</span>'
        : '';

    // Check if this override has episode mappings
    let episodeOverrideInfo = '';
    if (mapping.user_override) {
        // We'll need to fetch the override details to show episode count
        // For now, just indicate it's an override
        episodeOverrideInfo = `<div class="episode-override-info" id="episode-info-${mapping.tvdb_id}">Loading episode mappings...</div>`;
    }

    return `
        <div class="mapping-card" data-tvdb-id="${mapping.tvdb_id}">
            <div class="mapping-header">
                <div class="mapping-title">
                    <h3>${escapeHtml(titles[0] || 'Unknown')}</h3>
                    ${overrideBadge}
                </div>
                <div class="mapping-actions">
                    <button class="btn-edit" onclick="editMapping(${mapping.tvdb_id})">
                        Edit
                    </button>
                    ${mapping.user_override ? `
                        <button class="btn-danger" onclick="deleteOverride(${mapping.tvdb_id})">
                            Delete
                        </button>
                    ` : ''}
                </div>
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

            ${episodeOverrideInfo}
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
        season_episode_overrides: currentEpisodeMappings,
        season_ranges: currentSeasonRanges
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

        const action = editingTvdbId ? 'updated' : 'saved';
        showNotification(`Override ${action} successfully!`, 'success');

        // Reset form and state
        clearForm();

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

// ==========================================
// Episode Mapping Functions
// ==========================================

function renderEpisodeMappings() {
    const tbody = document.getElementById('episode-table-body');
    const countEl = document.getElementById('episode-mapping-count');

    const entries = Object.entries(currentEpisodeMappings).sort((a, b) => {
        // Sort by season then episode
        const parseKey = (key) => {
            const match = key.match(/S(\d+)E(\d+)/);
            return match ? { s: parseInt(match[1]), e: parseInt(match[2]) } : { s: 0, e: 0 };
        };
        const aKey = parseKey(a[0]);
        const bKey = parseKey(b[0]);
        if (aKey.s !== bKey.s) return aKey.s - bKey.s;
        return aKey.e - bKey.e;
    });

    if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="color: #888; font-style: italic;">No episode mappings yet. Add a season range or individual episodes above.</td></tr>';
    } else {
        tbody.innerHTML = entries.map(([key, absolute]) => {
            const match = key.match(/S(\d+)E(\d+)/);
            const season = match ? match[1] : '?';
            const episode = match ? match[2] : '?';
            return `
                <tr>
                    <td>${season}</td>
                    <td>${episode}</td>
                    <td>${absolute}</td>
                    <td><button type="button" class="btn-small remove" onclick="removeEpisodeMapping('${key}')">&times;</button></td>
                </tr>
            `;
        }).join('');
    }

    countEl.textContent = entries.length;
}

function addSeasonRange() {
    const seasonNum = parseInt(document.getElementById('season-num').value);
    const episodeCount = parseInt(document.getElementById('episode-count').value);
    const startAbsolute = parseInt(document.getElementById('start-absolute').value);

    if (isNaN(seasonNum) || isNaN(episodeCount) || isNaN(startAbsolute)) {
        showNotification('Please fill in all season range fields', 'error');
        return;
    }

    if (episodeCount < 1) {
        showNotification('Episode count must be at least 1', 'error');
        return;
    }

    if (startAbsolute < 1) {
        showNotification('Start absolute must be at least 1', 'error');
        return;
    }

    // Check for conflicts
    const conflicts = [];
    for (let i = 0; i < episodeCount; i++) {
        const key = `S${String(seasonNum).padStart(2, '0')}E${String(i + 1).padStart(2, '0')}`;
        const newAbsolute = startAbsolute + i;
        if (currentEpisodeMappings[key] !== undefined && currentEpisodeMappings[key] !== newAbsolute) {
            conflicts.push({
                key: key,
                oldValue: currentEpisodeMappings[key],
                newValue: newAbsolute
            });
        }
    }

    if (conflicts.length > 0) {
        const conflictList = conflicts.slice(0, 5).map(c =>
            `${c.key}: ${c.oldValue} -> ${c.newValue}`
        ).join('\n');
        const moreText = conflicts.length > 5 ? `\n...and ${conflicts.length - 5} more` : '';

        if (!confirm(`This will overwrite ${conflicts.length} existing mapping(s):\n\n${conflictList}${moreText}\n\nContinue anyway?`)) {
            return;
        }
    }

    // Add the mappings
    for (let i = 0; i < episodeCount; i++) {
        const key = `S${String(seasonNum).padStart(2, '0')}E${String(i + 1).padStart(2, '0')}`;
        currentEpisodeMappings[key] = startAbsolute + i;
    }

    // Track the season range
    currentSeasonRanges.push({
        season: seasonNum,
        episodes: episodeCount,
        start_absolute: startAbsolute
    });

    renderEpisodeMappings();
    showNotification(`Added ${episodeCount} episodes for Season ${seasonNum}`, 'success');

    // Update start absolute for next season (convenience)
    document.getElementById('season-num').value = seasonNum + 1;
    document.getElementById('start-absolute').value = startAbsolute + episodeCount;
}

function addSingleEpisode() {
    const season = parseInt(document.getElementById('add-season').value);
    const episode = parseInt(document.getElementById('add-episode').value);
    const absolute = parseInt(document.getElementById('add-absolute').value);

    if (isNaN(season) || isNaN(episode) || isNaN(absolute)) {
        showNotification('Please fill in all episode fields', 'error');
        return;
    }

    const key = `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;

    if (currentEpisodeMappings[key] !== undefined && currentEpisodeMappings[key] !== absolute) {
        if (!confirm(`${key} already maps to ${currentEpisodeMappings[key]}. Overwrite with ${absolute}?`)) {
            return;
        }
    }

    currentEpisodeMappings[key] = absolute;
    renderEpisodeMappings();

    // Increment episode for next entry (convenience)
    document.getElementById('add-episode').value = episode + 1;
    document.getElementById('add-absolute').value = absolute + 1;
}

function removeEpisodeMapping(key) {
    delete currentEpisodeMappings[key];
    renderEpisodeMappings();
}

// ==========================================
// Edit Mode Functions
// ==========================================

async function editMapping(tvdbId) {
    try {
        // Try to fetch existing override
        let override = null;
        try {
            const response = await fetch(`/api/mappings/override/${tvdbId}`);
            if (response.ok) {
                override = await response.json();
            }
        } catch (e) {
            // No existing override, that's fine
        }

        // Set edit mode
        editingTvdbId = tvdbId;

        // Populate form
        document.getElementById('tvdb-id').value = tvdbId;
        document.getElementById('tvdb-id').readOnly = true;

        if (override) {
            document.getElementById('anilist-id').value = override.anilist_id || '';
            document.getElementById('mal-id').value = override.mal_id || '';
            document.getElementById('custom-titles').value = (override.custom_titles || []).join('\n');
            document.getElementById('notes').value = override.notes || '';

            // Load episode mappings
            currentEpisodeMappings = override.season_episode_overrides || {};
            currentSeasonRanges = override.season_ranges || [];
        } else {
            // No override exists yet, just populate TVDB ID
            document.getElementById('anilist-id').value = '';
            document.getElementById('mal-id').value = '';
            document.getElementById('custom-titles').value = '';
            document.getElementById('notes').value = '';
            currentEpisodeMappings = {};
            currentSeasonRanges = [];
        }

        renderEpisodeMappings();

        // Update UI for edit mode
        document.getElementById('submit-btn').textContent = 'Update Override';
        document.getElementById('cancel-btn').style.display = 'inline-block';

        // Scroll to form
        document.getElementById('override-form').scrollIntoView({ behavior: 'smooth', block: 'start' });

        showNotification(`Editing mapping for TVDB ${tvdbId}`, 'success');

    } catch (error) {
        console.error('Failed to load mapping for editing:', error);
        showNotification('Failed to load mapping for editing', 'error');
    }
}

function cancelEdit() {
    clearForm();
    showNotification('Edit cancelled', 'success');
}

function clearForm() {
    // Reset form fields
    document.getElementById('override-form').reset();
    document.getElementById('tvdb-id').readOnly = false;

    // Reset state
    editingTvdbId = null;
    currentEpisodeMappings = {};
    currentSeasonRanges = [];

    // Reset UI
    document.getElementById('submit-btn').textContent = 'Save Override';
    document.getElementById('cancel-btn').style.display = 'none';

    // Reset season range inputs to defaults
    document.getElementById('season-num').value = 1;
    document.getElementById('episode-count').value = 12;
    document.getElementById('start-absolute').value = 1;

    // Reset single episode inputs
    document.getElementById('add-season').value = 1;
    document.getElementById('add-episode').value = 1;
    document.getElementById('add-absolute').value = 1;

    renderEpisodeMappings();
}

async function loadEpisodeOverrideInfo(tvdbId) {
    const infoEl = document.getElementById(`episode-info-${tvdbId}`);
    if (!infoEl) return;

    try {
        const response = await fetch(`/api/mappings/override/${tvdbId}`);
        if (response.ok) {
            const override = await response.json();
            const episodeCount = Object.keys(override.season_episode_overrides || {}).length;

            if (episodeCount > 0) {
                infoEl.textContent = `${episodeCount} episode mapping(s) configured`;
            } else {
                infoEl.textContent = 'No episode mappings (titles/IDs only)';
                infoEl.style.background = '#fff3cd';
                infoEl.style.color = '#856404';
            }
        } else {
            infoEl.remove();
        }
    } catch (error) {
        infoEl.remove();
    }
}

// ==========================================
// Movie Mapping Functions
// ==========================================

async function loadMovieMappings() {
    try {
        const response = await fetch('/api/movies/mappings');
        allMovieMappings = await response.json();

        renderMovieMappings(allMovieMappings);
    } catch (error) {
        console.error('Failed to load movie mappings:', error);
        document.getElementById('movie-mappings-list').innerHTML =
            '<p style="color: red;">Failed to load movie mappings. Check console for errors.</p>';
    }
}

function renderMovieMappings(mappings) {
    const container = document.getElementById('movie-mappings-list');

    if (mappings.length === 0) {
        container.innerHTML = '<p>No movie mappings found. Search for an anime movie in Radarr to create mappings.</p>';
        return;
    }

    const html = mappings.map(mapping => createMovieMappingCard(mapping)).join('');
    container.innerHTML = html;
}

function createMovieMappingCard(mapping) {
    const titles = getAllTitles(mapping);
    const overrideBadge = mapping.user_override
        ? '<span class="badge">USER OVERRIDE</span>'
        : '';

    return `
        <div class="mapping-card" data-tmdb-id="${mapping.tmdb_id}">
            <div class="mapping-header">
                <div class="mapping-title">
                    <h3>${escapeHtml(titles[0] || 'Unknown')}</h3>
                    ${overrideBadge}
                </div>
                <div class="mapping-actions">
                    <button class="btn-edit" onclick="editMovieMapping(${mapping.tmdb_id})">
                        Edit
                    </button>
                    ${mapping.user_override ? `
                        <button class="btn-danger" onclick="deleteMovieOverride(${mapping.tmdb_id})">
                            Delete
                        </button>
                    ` : ''}
                </div>
            </div>

            <div class="mapping-ids">
                <span><strong>TMDB:</strong> ${mapping.tmdb_id}</span>
                ${mapping.imdb_id ? `<span><strong>IMDb:</strong> ${mapping.imdb_id}</span>` : ''}
                ${mapping.anilist_id ? `<span><strong>AniList:</strong> ${mapping.anilist_id}</span>` : ''}
                ${mapping.mal_id ? `<span><strong>MAL:</strong> ${mapping.mal_id}</span>` : ''}
                ${mapping.year ? `<span><strong>Year:</strong> ${mapping.year}</span>` : ''}
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

function filterMovieMappings() {
    const query = document.getElementById('search-movie-mappings').value.toLowerCase();

    if (!query) {
        renderMovieMappings(allMovieMappings);
        return;
    }

    const filtered = allMovieMappings.filter(mapping => {
        // Search by TMDB ID
        if (mapping.tmdb_id.toString().includes(query)) {
            return true;
        }

        // Search by IMDb ID
        if (mapping.imdb_id && mapping.imdb_id.toLowerCase().includes(query)) {
            return true;
        }

        // Search by any title
        const titles = getAllTitles(mapping);
        return titles.some(title => title.toLowerCase().includes(query));
    });

    renderMovieMappings(filtered);
}

async function handleMovieOverrideSubmit(event) {
    event.preventDefault();

    const tmdbId = parseInt(document.getElementById('tmdb-id').value);
    const imdbId = document.getElementById('movie-imdb-id').value.trim() || null;
    const anilistId = document.getElementById('movie-anilist-id').value;
    const malId = document.getElementById('movie-mal-id').value;
    const year = document.getElementById('movie-year').value;
    const customTitles = document.getElementById('movie-custom-titles').value
        .split('\n')
        .map(t => t.trim())
        .filter(t => t.length > 0);
    const notes = document.getElementById('movie-notes').value;

    const override = {
        tmdb_id: tmdbId,
        imdb_id: imdbId,
        anilist_id: anilistId ? parseInt(anilistId) : null,
        mal_id: malId ? parseInt(malId) : null,
        year: year ? parseInt(year) : null,
        custom_titles: customTitles,
        notes: notes
    };

    try {
        const response = await fetch('/api/movies/mappings/override', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(override)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save movie override');
        }

        const action = editingTmdbId ? 'updated' : 'saved';
        showNotification(`Movie override ${action} successfully!`, 'success');

        // Reset form and state
        clearMovieForm();

        // Reload data
        await loadStats();
        await loadMovieMappings();

    } catch (error) {
        console.error('Failed to save movie override:', error);
        showNotification(error.message, 'error');
    }
}

async function deleteMovieOverride(tmdbId) {
    if (!confirm(`Delete override for TMDB ID ${tmdbId}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/movies/mappings/override/${tmdbId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            throw new Error('Failed to delete movie override');
        }

        showNotification('Movie override deleted successfully!', 'success');

        // Reload data
        await loadStats();
        await loadMovieMappings();

    } catch (error) {
        console.error('Failed to delete movie override:', error);
        showNotification(error.message, 'error');
    }
}

async function editMovieMapping(tmdbId) {
    try {
        // Try to fetch existing override
        let override = null;
        try {
            const response = await fetch(`/api/movies/mappings/override/${tmdbId}`);
            if (response.ok) {
                override = await response.json();
            }
        } catch (e) {
            // No existing override, that's fine
        }

        // Set edit mode
        editingTmdbId = tmdbId;

        // Populate form
        document.getElementById('tmdb-id').value = tmdbId;
        document.getElementById('tmdb-id').readOnly = true;

        if (override) {
            document.getElementById('movie-imdb-id').value = override.imdb_id || '';
            document.getElementById('movie-anilist-id').value = override.anilist_id || '';
            document.getElementById('movie-mal-id').value = override.mal_id || '';
            document.getElementById('movie-year').value = override.year || '';
            document.getElementById('movie-custom-titles').value = (override.custom_titles || []).join('\n');
            document.getElementById('movie-notes').value = override.notes || '';
        } else {
            // No override exists yet, just populate TMDB ID
            document.getElementById('movie-imdb-id').value = '';
            document.getElementById('movie-anilist-id').value = '';
            document.getElementById('movie-mal-id').value = '';
            document.getElementById('movie-year').value = '';
            document.getElementById('movie-custom-titles').value = '';
            document.getElementById('movie-notes').value = '';
        }

        // Update UI for edit mode
        document.getElementById('movie-submit-btn').textContent = 'Update Movie Override';
        document.getElementById('movie-cancel-btn').style.display = 'inline-block';

        // Make sure we're on the movies tab
        switchTab('movies');

        // Scroll to form
        document.getElementById('movie-override-form').scrollIntoView({ behavior: 'smooth', block: 'start' });

        showNotification(`Editing movie mapping for TMDB ${tmdbId}`, 'success');

    } catch (error) {
        console.error('Failed to load movie mapping for editing:', error);
        showNotification('Failed to load movie mapping for editing', 'error');
    }
}

function cancelMovieEdit() {
    clearMovieForm();
    showNotification('Edit cancelled', 'success');
}

function clearMovieForm() {
    // Reset form fields
    document.getElementById('movie-override-form').reset();
    document.getElementById('tmdb-id').readOnly = false;

    // Reset state
    editingTmdbId = null;

    // Reset UI
    document.getElementById('movie-submit-btn').textContent = 'Save Movie Override';
    document.getElementById('movie-cancel-btn').style.display = 'none';
}
