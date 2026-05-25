(function () {
    'use strict';

    const STORE = 'rocksmith-sync-settings-v1';
    const hooks = window.__rocksmithSyncHooks = window.__rocksmithSyncHooks || {};
    if (hooks.pollTimer) clearInterval(hooks.pollTimer);
    if (hooks.loadingCueTimer) {
        clearInterval(hooks.loadingCueTimer);
        hooks.loadingCueTimer = null;
    }

    const defaults = {
        enabled: true,
        offsetMs: 0,
        deadbandMs: 70,
        songSelectionDelayMs: 750,
        showPlayerControls: true,
        playResyncCue: false
    };
    let settings = loadSettings();
    let currentRocksmithSong = '';
    let selectedAudio = '';
    let resolvingSong = false;
    let songReady = false;
    let polling = false;
    let controlGeneration = 0;
    let candidateSong = '';
    let candidateSongSince = 0;

    function loadSettings() {
        try {
            const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
            return {
                enabled: saved.enabled !== false,
                offsetMs: finiteNumber(saved.offsetMs, defaults.offsetMs),
                deadbandMs: Math.max(10, finiteNumber(saved.deadbandMs, defaults.deadbandMs)),
                songSelectionDelayMs: Math.max(0, finiteNumber(saved.songSelectionDelayMs, defaults.songSelectionDelayMs)),
                showPlayerControls: saved.showPlayerControls !== false,
                playResyncCue: saved.playResyncCue === true
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
        const existing = document.getElementById('rs-player-sync-controls');
        if (!settings.showPlayerControls) {
            if (existing) existing.remove();
            return;
        }
        if (!controls || existing) return;

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
                if (settings.enabled !== input.checked) controlGeneration += 1;
                settings.enabled = input.checked;
                saveSettings();
                if (!settings.enabled) {
                    stopLoadingCues(false);
                    text('[data-rs-load]', 'Sync disabled');
                } else {
                    currentRocksmithSong = '';
                    candidateSong = '';
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
        document.querySelectorAll('[data-rs-selection-delay]').forEach((input) => {
            if (document.activeElement !== input) input.value = String(settings.songSelectionDelayMs);
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            const updateDelay = () => {
                const value = Number(input.value);
                if (!Number.isFinite(value)) return;
                settings.songSelectionDelayMs = Math.max(0, value);
                saveSettings();
            };
            input.addEventListener('input', updateDelay);
            input.addEventListener('change', updateDelay);
        });
        document.querySelectorAll('[data-rs-show-player-controls]').forEach((input) => {
            input.checked = settings.showPlayerControls;
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            input.addEventListener('change', () => {
                settings.showPlayerControls = input.checked;
                saveSettings();
            });
        });
        document.querySelectorAll('[data-rs-resync-cue]').forEach((input) => {
            input.checked = settings.playResyncCue;
            if (input.dataset.bound) return;
            input.dataset.bound = '1';
            input.addEventListener('change', () => {
                settings.playResyncCue = input.checked;
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

    function mayControl(generation) {
        return settings.enabled && generation === controlGeneration;
    }

    async function togglePlayback(generation) {
        if (!mayControl(generation)) return false;
        if (typeof window.togglePlay === 'function') {
            await window.togglePlay();
            return true;
        }
        document.getElementById('btn-play')?.click();
        return true;
    }

    async function pausePlayback(generation) {
        if (!mayControl(generation)) return;
        if (isPlaybackActive()) await togglePlayback(generation);
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

    function playResyncCue() {
        void playCue([
            { frequency: 659.25, at: 0, duration: 0.065, gain: 0.035, type: 'sine' },
            { frequency: 880.00, at: 0.072, duration: 0.085, gain: 0.035, type: 'sine' }
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

    async function seekPlayback(audio, target, generation) {
        if (!mayControl(generation)) return false;
        const api = nativeBackingApi();
        if (api) {
            try {
                await api.seekBacking(target);
                return true;
            } catch (_) {
                // Fall back to the HTML media transport if native seeking fails.
            }
        }
        if (!mayControl(generation)) return false;
        audio.currentTime = target;
        return true;
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

    async function selectSong(songKey, generation) {
        if (!mayControl(generation)) return;
        resolvingSong = true;
        try {
            await pausePlayback(generation);
            if (!mayControl(generation)) return;
            stopLoadingCues(false);
            songReady = false;
            const result = await jsonFetch(`/api/plugins/rocksmith_sync/resolve/${encodeURIComponent(songKey)}`);
            if (!mayControl(generation)) return;
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
            if (!mayControl(generation)) return;
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
            candidateSong = '';
            await pausePlayback(controlGeneration);
            return;
        }

        if (candidateSong !== state.songKey) {
            candidateSong = state.songKey;
            candidateSongSince = Date.now();
            controlGeneration += 1;
            const generation = controlGeneration;
            stopLoadingCues(false);
            if (state.songKey !== currentRocksmithSong) {
                text('[data-rs-load]', 'Waiting for stable song selection...');
                await pausePlayback(generation);
                return;
            }
        }

        const generation = controlGeneration;
        const slopsmithSelection = String(window.slopsmith?.currentSong?.filename || '');
        const selectionWasOverridden = songReady && selectedAudio && slopsmithSelection && slopsmithSelection !== selectedAudio;
        if (state.songKey !== currentRocksmithSong) {
            const remainingMs = settings.songSelectionDelayMs - (Date.now() - candidateSongSince);
            if (remainingMs > 0) {
                text('[data-rs-load]', `Waiting to load (${Math.ceil(remainingMs)} ms)...`);
                return;
            }
            currentRocksmithSong = state.songKey;
            await selectSong(state.songKey, generation);
        } else if (selectionWasOverridden) {
            await selectSong(state.songKey, generation);
        }
        if (!mayControl(generation)) return;
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
            await pausePlayback(generation);
            return;
        }

        const target = targetSeconds(state);
        if (!state.playing) {
            const wasPlaying = isPlaybackActive();
            await pausePlayback(generation);
            if (!mayControl(generation)) return;
            const position = await playbackSeconds(audio);
            if (!mayControl(generation)) return;
            const driftMs = (position - target) * 1000;
            text('[data-rs-drift]', `${driftMs >= 0 ? '+' : ''}${Math.round(driftMs)} ms`);
            if (wasPlaying || Math.abs(driftMs) > settings.deadbandMs) {
                await seekPlayback(audio, target, generation);
            }
            return;
        }

        if (!isPlaybackActive()) {
            // Align before starting to avoid an audible burst at the previous pause point.
            if (!(await seekPlayback(audio, target, generation))) return;
            text('[data-rs-drift]', '+0 ms');
            await togglePlayback(generation);
            return;
        }

        const position = await playbackSeconds(audio);
        if (!mayControl(generation)) return;
        const driftMs = (position - target) * 1000;
        text('[data-rs-drift]', `${driftMs >= 0 ? '+' : ''}${Math.round(driftMs)} ms`);
        if (Math.abs(driftMs) > settings.deadbandMs) {
            if (await seekPlayback(audio, target, generation)) {
                if (settings.playResyncCue) playResyncCue();
            }
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
                if (settings.enabled) await pausePlayback(controlGeneration);
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
