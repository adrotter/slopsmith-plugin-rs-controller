(function () {
    'use strict';

    const STORE = 'rocksmith-sync-settings-v1';
    const hooks = window.__rocksmithSyncHooks = window.__rocksmithSyncHooks || {};
    if (hooks.pollTimer) clearInterval(hooks.pollTimer);
    if (hooks.loadingCueTimer) {
        clearInterval(hooks.loadingCueTimer);
        hooks.loadingCueTimer = null;
    }

    const defaults = { enabled: true, offsetMs: 0, deadbandMs: 70 };
    let settings = loadSettings();
    let currentRocksmithSong = '';
    let selectedAudio = '';
    let resolvingSong = false;
    let songReady = false;
    let polling = false;

    function loadSettings() {
        try {
            const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
            return {
                enabled: saved.enabled !== false,
                offsetMs: finiteNumber(saved.offsetMs, defaults.offsetMs),
                deadbandMs: Math.max(10, finiteNumber(saved.deadbandMs, defaults.deadbandMs))
            };
        } catch (_) {
            return { ...defaults };
        }
    }

    function finiteNumber(value, fallback) {
        const number = Number(value);
        return Number.isFinite(number) ? number : fallback;
    }

    function saveSettings() {
        localStorage.setItem(STORE, JSON.stringify(settings));
        bindSettingsControls();
    }

    function text(selector, value) {
        document.querySelectorAll(selector).forEach((el) => {
            el.textContent = value;
        });
    }

    function ensurePlayerSyncControls() {
        const controls = document.getElementById('player-controls');
        if (!controls || document.getElementById('rs-player-sync-controls')) return;

        const group = document.createElement('div');
        group.id = 'rs-player-sync-controls';
        group.className = 'flex items-center gap-2 rounded-lg bg-dark-600 px-3 py-1.5 text-xs text-gray-300';

        const syncLabel = document.createElement('label');
        syncLabel.className = 'flex items-center gap-2';
        syncLabel.title = 'Let Rocksmith control this Slopsmith player';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.setAttribute('data-rs-enabled', '');
        checkbox.className = 'rounded';

        syncLabel.appendChild(checkbox);
        syncLabel.appendChild(document.createTextNode('Rocksmith Sync'));
        group.appendChild(syncLabel);

        const offsetLabel = document.createElement('label');
        offsetLabel.className = 'flex items-center gap-1 text-gray-400';
        offsetLabel.title = 'Positive makes Slopsmith play ahead of Rocksmith';
        offsetLabel.appendChild(document.createTextNode('Offset'));

        const offset = document.createElement('input');
        offset.type = 'number';
        offset.step = '1';
        offset.setAttribute('data-rs-offset', '');
        offset.className = 'w-20 rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-slate-100';
        offsetLabel.appendChild(offset);
        offsetLabel.appendChild(document.createTextNode('ms'));
        group.appendChild(offsetLabel);

        const closeButton = controls.querySelector(':scope > button[onclick*="showScreen"]');
        if (closeButton) controls.insertBefore(group, closeButton);
        else controls.appendChild(group);
    }

    function bindSettingsControls() {
        ensurePlayerSyncControls();
        document.querySelectorAll('[data-rs-enabled]').forEach((input) => {
            input.checked = settings.enabled;
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            input.addEventListener('change', () => {
                settings.enabled = input.checked;
                saveSettings();
                if (!settings.enabled) {
                    stopLoadingCues(false);
                    text('[data-rs-load]', 'Sync disabled');
                } else {
                    currentRocksmithSong = '';
                }
            });
        });
        document.querySelectorAll('[data-rs-offset]').forEach((input) => {
            if (document.activeElement !== input) input.value = String(settings.offsetMs);
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            const updateOffset = () => {
                const value = Number(input.value);
                if (!Number.isFinite(value)) return;
                settings.offsetMs = value;
                saveSettings();
            };
            input.addEventListener('input', updateOffset);
            input.addEventListener('change', updateOffset);
        });
        document.querySelectorAll('[data-rs-deadband]').forEach((input) => {
            if (document.activeElement !== input) input.value = String(settings.deadbandMs);
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            input.addEventListener('change', () => {
                settings.deadbandMs = Math.max(10, finiteNumber(input.value, defaults.deadbandMs));
                saveSettings();
            });
        });
        bindActions();
    }

    function bindActions() {
        document.querySelectorAll('[data-rs-rescan]').forEach((button) => {
            if (button.dataset.bound) return;
            button.dataset.bound = '1';
            button.addEventListener('click', async () => {
                const result = await jsonFetch('/api/plugins/rocksmith_sync/rescan', { method: 'POST' });
                showMessage(result ? `Found ${result.files} audio packages.` : 'DLC rescan failed.');
                currentRocksmithSong = '';
            });
        });
        document.querySelectorAll('[data-rs-map-save]').forEach((button) => {
            if (button.dataset.bound) return;
            button.dataset.bound = '1';
            button.addEventListener('click', async () => {
                const panel = button.closest('section');
                const songKey = panel?.querySelector('[data-rs-map-key]')?.value.trim() || '';
                const filename = panel?.querySelector('[data-rs-map-file]')?.value.trim() || '';
                if (!songKey || !filename) {
                    showMessage('Enter both a Rocksmith song key and a DLC-relative file path.');
                    return;
                }
                const response = await jsonFetch('/api/plugins/rocksmith_sync/mappings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ songKey, filename })
                });
                showMessage(response ? 'Mapping saved.' : 'Mapping could not be saved. Check the file path.');
                if (songKey === currentRocksmithSong) currentRocksmithSong = '';
            });
        });
    }

    function showMessage(message) {
        text('[data-rs-message]', message);
    }

    async function jsonFetch(url, init) {
        try {
            const response = await fetch(url, init);
            if (!response.ok) return null;
            return await response.json();
        } catch (_) {
            return null;
        }
    }

    function playerAudio() {
        return document.getElementById('audio');
    }

    function isPlaybackActive() {
        const audio = playerAudio();
        if (audio && typeof audio.paused === 'boolean') {
            return !audio.paused;
        }
        return window.slopsmith?.isPlaying === true;
    }

    async function togglePlayback() {
        if (typeof window.togglePlay === 'function') {
            await window.togglePlay();
            return;
        }
        document.getElementById('btn-play')?.click();
    }

    async function pausePlayback() {
        if (isPlaybackActive()) await togglePlayback();
    }

    function cueContext() {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) return null;
        if (!hooks.cueContext) hooks.cueContext = new Context();
        return hooks.cueContext;
    }

    async function playCue(notes) {
        const context = cueContext();
        if (!context) return;
        try {
            await context.resume();
        } catch (_) {
            return;
        }
        if (context.state !== 'running') return;

        notes.forEach((note) => {
            const start = context.currentTime + note.at;
            const end = start + note.duration;
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.type = note.type || 'triangle';
            oscillator.frequency.setValueAtTime(note.frequency, start);
            gain.gain.setValueAtTime(0.0001, start);
            gain.gain.exponentialRampToValueAtTime(note.gain || 0.06, start + 0.012);
            gain.gain.exponentialRampToValueAtTime(0.0001, end);
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.start(start);
            oscillator.stop(end + 0.01);
        });
    }

    function playLoadingCue() {
        void playCue([
            { frequency: 523.25, at: 0, duration: 0.085, gain: 0.045, type: 'square' },
            { frequency: 392.00, at: 0.095, duration: 0.11, gain: 0.04, type: 'triangle' }
        ]);
    }

    function playReadyCue() {
        void playCue([
            { frequency: 392.00, at: 0, duration: 0.12, gain: 0.05 },
            { frequency: 523.25, at: 0.09, duration: 0.14, gain: 0.055 },
            { frequency: 783.99, at: 0.19, duration: 0.24, gain: 0.06 }
        ]);
    }

    function startLoadingCues() {
        if (hooks.loadingCueTimer) return;
        playLoadingCue();
        hooks.loadingCueTimer = setInterval(playLoadingCue, 1000);
    }

    function stopLoadingCues(ready) {
        if (hooks.loadingCueTimer) {
            clearInterval(hooks.loadingCueTimer);
            hooks.loadingCueTimer = null;
        }
        if (ready) playReadyCue();
    }

    function targetSeconds(state) {
        return Math.max(0, finiteNumber(state.positionSeconds, 0) + settings.offsetMs / 1000);
    }

    function nativeBackingApi() {
        if (window._juceMode !== true) return null;
        const api = window.slopsmithDesktop?.audio;
        return api && typeof api.getBackingPosition === 'function' && typeof api.seekBacking === 'function'
            ? api
            : null;
    }

    async function playbackSeconds(audio) {
        const api = nativeBackingApi();
        if (api) {
            try {
                return finiteNumber(await api.getBackingPosition(), 0);
            } catch (_) {
                return 0;
            }
        }
        return finiteNumber(audio.currentTime, 0);
    }

    async function seekPlayback(audio, target) {
        const api = nativeBackingApi();
        if (api) {
            try {
                await api.seekBacking(target);
                return;
            } catch (_) {
                // Fall back to the HTML media transport if native seeking fails.
            }
        }
        audio.currentTime = target;
    }

    async function ensureNativeAudio() {
        const api = window.slopsmithDesktop?.audio;
        if (!api || typeof api.isAudioRunning !== 'function') {
            return false;
        }
        try {
            if (!(await api.isAudioRunning())) await api.startAudio();
            return (await api.isAudioRunning()) === true;
        } catch (_) {
            return false;
        }
    }

    function songInfo() {
        const highway = window.highway || window._slopsmithHighway;
        try {
            return typeof highway?.getSongInfo === 'function' ? highway.getSongInfo() : null;
        } catch (_) {
            return null;
        }
    }

    function audioReadiness() {
        const currentFilename = String(window.slopsmith?.currentSong?.filename || '');
        if (!selectedAudio || currentFilename !== selectedAudio) {
            return { ready: false, status: 'Opening selected song...' };
        }

        const info = songInfo();
        if (!info || !Array.isArray(info.stems)) {
            return { ready: false, status: 'Reading audio manifest...' };
        }

        if (info.stems.length > 0 && typeof window.stems?.getState === 'function') {
            let decodedStems = [];
            try {
                decodedStems = window.stems.getState() || [];
            } catch (_) {
                decodedStems = [];
            }
            if (decodedStems.length > 0) {
                return { ready: true, status: `Ready (${decodedStems.length} stems)` };
            }
            return { ready: false, status: `Loading ${info.stems.length} stems...` };
        }

        if (nativeBackingApi()) {
            return { ready: true, status: 'Ready (native backing)' };
        }

        const audio = playerAudio();
        if (audio && audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
            return { ready: true, status: 'Ready (backing audio)' };
        }
        return { ready: false, status: 'Buffering backing audio...' };
    }

    async function selectSong(songKey) {
        resolvingSong = true;
        try {
            await pausePlayback();
            stopLoadingCues(false);
            songReady = false;
            const result = await jsonFetch(`/api/plugins/rocksmith_sync/resolve/${encodeURIComponent(songKey)}`);
            const match = result?.match;
            if (!match) {
                selectedAudio = '';
                text('[data-rs-audio]', 'No matching .sloppak or .psarc');
                text('[data-rs-load]', 'No audio package selected');
                showMessage(`No Slopsmith package matches "${songKey}". Add a manual mapping below.`);
                return;
            }
            selectedAudio = match.filename;
            text('[data-rs-audio]', `${match.filename} (${match.format})`);
            text('[data-rs-load]', 'Opening selected song...');
            startLoadingCues();
            await ensureNativeAudio();
            if (typeof window.playSong === 'function') {
                await window.playSong(encodeURIComponent(match.filename));
            } else {
                stopLoadingCues(false);
                text('[data-rs-load]', 'Player API unavailable');
                showMessage('Slopsmith player API is not available.');
            }
        } finally {
            resolvingSong = false;
        }
    }

    async function synchronize(state) {
        if (!settings.enabled) return;
        if (!state || !state.songKey) {
            await pausePlayback();
            return;
        }
        const slopsmithSelection = String(window.slopsmith?.currentSong?.filename || '');
        const selectionWasOverridden = songReady && selectedAudio && slopsmithSelection && slopsmithSelection !== selectedAudio;
        if (state.songKey !== currentRocksmithSong || selectionWasOverridden) {
            currentRocksmithSong = state.songKey;
            await selectSong(state.songKey);
        }
        if (!selectedAudio || resolvingSong) return;
        if (!songReady) {
            const readiness = audioReadiness();
            text('[data-rs-load]', readiness.status);
            if (!readiness.ready) {
                startLoadingCues();
                return;
            }
            songReady = true;
            stopLoadingCues(true);
        }
        const audio = playerAudio();
        if (!audio) return;
        if (!state.inSong) {
            await pausePlayback();
            return;
        }

        const target = targetSeconds(state);
        if (!state.playing) {
            const wasPlaying = isPlaybackActive();
            await pausePlayback();
            const position = await playbackSeconds(audio);
            const driftMs = (position - target) * 1000;
            text('[data-rs-drift]', `${driftMs >= 0 ? '+' : ''}${Math.round(driftMs)} ms`);
            if (wasPlaying || Math.abs(driftMs) > settings.deadbandMs) {
                await seekPlayback(audio, target);
            }
            return;
        }

        if (!isPlaybackActive()) {
            // Align before starting to avoid an audible burst at the previous pause point.
            await seekPlayback(audio, target);
            text('[data-rs-drift]', '+0 ms');
            await togglePlayback();
            return;
        }

        const position = await playbackSeconds(audio);
        const driftMs = (position - target) * 1000;
        text('[data-rs-drift]', `${driftMs >= 0 ? '+' : ''}${Math.round(driftMs)} ms`);
        if (Math.abs(driftMs) > settings.deadbandMs) {
            await seekPlayback(audio, target);
        }
    }

    async function poll() {
        if (polling) return;
        polling = true;
        try {
            bindSettingsControls();
            const snapshot = await jsonFetch('/api/plugins/rocksmith_sync/state');
            if (!snapshot?.connected) {
                text('[data-rs-status]', snapshot?.status || 'Start Rocksmith 2014');
                text('[data-rs-song]', '-');
                text('[data-rs-time]', '-');
                stopLoadingCues(false);
                if (settings.enabled) await pausePlayback();
                return;
            }
            const state = snapshot.state;
            text('[data-rs-status]', settings.enabled ? (snapshot.status || 'Connected') : 'Disabled');
            text('[data-rs-song]', state.songKey || '-');
            text('[data-rs-time]', Number.isFinite(Number(state.positionSeconds)) ? `${Number(state.positionSeconds).toFixed(3)} s` : '-');
            await synchronize(state);
        } finally {
            polling = false;
        }
    }

    window.addEventListener('slopsmith:plugin:settings', bindSettingsControls);
    bindSettingsControls();
    hooks.pollTimer = setInterval(() => void poll(), 75);
    void poll();
})();
