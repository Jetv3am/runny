const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const KM_TO_MILES = 0.621371;
let currentUnit = localStorage.getItem('stride_unit') || 'metric';

const GOALS = {
  '5k': { label: '5K', km: '5 km', mi: '3.1 mi' },
  '10k': { label: '10K', km: '10 km', mi: '6.2 mi' },
  'half_marathon': { label: 'Half marathon', km: '21.1 km', mi: '13.1 mi' },
  'marathon': { label: 'Marathon', km: '42.2 km', mi: '26.2 mi' }
};
const DAY_ORDER = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

function formatDistance(km, digits = 1) {
  if (km === null || km === undefined || !Number.isFinite(Number(km))) return '—';
  const val = currentUnit === 'imperial' ? Number(km) * KM_TO_MILES : Number(km);
  return fmtNumber(val, digits);
}

function getUnitLabel() {
  return currentUnit === 'imperial' ? 'mi' : 'km';
}

function formatPace(paceStr) {
  if (!paceStr || paceStr === '—') return '—';
  if (currentUnit === 'metric') return paceStr;
  // Convert /km pace strings (e.g. "5:05 /km" or "7:00 /km to 7:34 /km") to /mi
  const convertSingle = (p) => {
    const match = p.match(/(\d+):(\d{2})/);
    if (!match) return p;
    const totalSecsPerKm = parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
    const totalSecsPerMile = Math.round(totalSecsPerKm / KM_TO_MILES);
    const m = Math.floor(totalSecsPerMile / 60);
    const s = totalSecsPerMile % 60;
    return `${m}:${String(s).padStart(2, '0')} /mi`;
  };

  if (paceStr.includes(' to ')) {
    const parts = paceStr.split(' to ');
    return `${convertSingle(parts[0])} to ${convertSingle(parts[1])}`;
  }
  return convertSingle(paceStr);
}

const state = { goal: null, profile: null, mlProfile: null, history: null, activities: [], plan: null };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function fmtNumber(value, digits = 1) {
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}
function fmtDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!value) return 'Date not set';
  if (typeof value === 'string' && value.length >= 10 && value.includes('-')) {
    const parts = value.slice(0, 10).split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10) - 1;
      const day = parseInt(parts[2], 10);
      const date = new Date(year, month, day, 12, 0, 0);
      return date.toLocaleDateString(undefined, options);
    }
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date not set' : date.toLocaleDateString(undefined, options);
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '—';
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours ? `${hours}:${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}` : `${mins}:${String(secs).padStart(2,'0')}`;
}
function setMessage(text, type = 'success') {
  const el = $('#global-message');
  el.textContent = text;
  el.classList.toggle('notice-success', type === 'success');
  el.classList.toggle('hidden', !text);
  if (text) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function setImportStatus(text, error = false) {
  const el = $('#import-status');
  el.textContent = text;
  el.classList.remove('hidden');
  el.classList.toggle('error', error);
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return payload;
}
function showImportWarning(message) {
  const el = $('#import-warning');
  el.textContent = message;
  el.classList.remove('hidden');
}
function hideImportWarning() { $('#import-warning').classList.add('hidden'); }

/* --- RENDER PROFILES (Basic & ML) --- */
function renderProfile(basicProfile, mlProfile, status) {
  state.profile = basicProfile;
  state.mlProfile = mlProfile;
  const unit = getUnitLabel();

  // Basic overview metrics
  $('#weekly-distance').textContent = formatDistance(basicProfile?.weekly_distance_km_last_7_days, 1);
  const wUnit = $('#weekly-distance-unit');
  if (wUnit) wUnit.textContent = unit;
  $('#run-count').textContent = fmtNumber(basicProfile?.runs_in_period, 0);
  $('#longest-run').textContent = formatDistance(basicProfile?.longest_run_km, 1);
  const lUnit = $('#longest-run-unit');
  if (lUnit) lUnit.textContent = unit;
  $('#runs-per-week').textContent = `${fmtNumber(basicProfile?.average_runs_per_week, 1)} / week`;
  $('#distance-change').textContent = basicProfile?.distance_change_percent_week_over_week == null
    ? 'No prior week' : `${basicProfile.distance_change_percent_week_over_week > 0 ? '+' : ''}${fmtNumber(basicProfile.distance_change_percent_week_over_week, 0)}% vs prior week`;
  $('#longest-track').style.width = `${Math.min(100, Math.max(5, (Number(basicProfile?.longest_run_km) || 0) / 25 * 100))}%`;

  // Connection indicator
  if (status && status.stored_activities > 0) {
    $('#connection-label').textContent = `${status.stored_activities} runs stored`;
    $('#connection-dot').classList.add('connected');
  } else {
    $('#connection-label').textContent = 'Awaiting import';
    $('#connection-dot').classList.remove('connected');
  }

  // --- ML PHYSIOLOGY RENDERING ---
  if (!mlProfile) return;

  const vdot = mlProfile.vdot || {};
  const vdotVal = vdot.estimated_vdot;
  const load = mlProfile.training_load || {};
  const readiness = mlProfile.readiness || {};
  const trend = mlProfile.pace_trend || {};

  // Top card: VDOT
  $('#vdot-score-display').textContent = vdotVal != null ? fmtNumber(vdotVal, 1) : '—';
  $('#vdot-trend-chip').textContent = vdot.trend ? `↗ ${vdot.trend}` : 'Needs data';
  $('#vdot-quality-chip').textContent = `${vdot.confidence || 'low'} conf`;
  $('#vdot-conf-label').textContent = `${vdot.sample_count || 0} quality runs modeled`;

  // Coach Banner: Readiness & Form
  const score = readiness.score != null ? Math.round(readiness.score) : null;
  $('#readiness-score').textContent = score != null ? score : '—';
  const ringFill = $('#readiness-ring-fill');
  if (ringFill) {
    // Circumference = 2 * PI * 32 = 201.06
    const offset = score != null ? Math.max(0, 201 - (score / 100 * 201)) : 201;
    ringFill.style.strokeDashoffset = offset;
    ringFill.style.stroke = score >= 75 ? '#b9f36b' : score >= 50 ? '#f0a83a' : '#e85741';
  }
  $('#readiness-badge').textContent = readiness.label ? readiness.label.replace('_', ' ') : 'Awaiting data';
  $('#readiness-form').textContent = `Form (TSB): ${load.tsb_form != null ? (load.tsb_form > 0 ? '+' : '') + fmtNumber(load.tsb_form, 1) : '—'}`;
  $('#coach-recommendation').textContent = readiness.recommendation || 'Sync your Apple Health running workouts to calculate your physiological training baseline.';
  $('#chip-vdot').textContent = `VDOT: ${vdotVal != null ? vdotVal : '—'}`;
  $('#chip-load').textContent = `Status: ${load.status || 'baseline'}`;
  $('#chip-trend').textContent = `Pace: ${trend.direction || 'stable'}`;

  // Physiology Panel: VDOT Race Predictions
  $('#vdot-big-badge').textContent = vdotVal != null ? `VDOT ${vdotVal}` : 'VDOT —';
  const preds = vdot.race_predictions || {};
  $('#pred-5k').textContent = preds['5k'] || '—:—';
  $('#pred-10k').textContent = preds['10k'] || '—:—';
  $('#pred-half').textContent = preds['half_marathon'] || '—:—';
  $('#pred-marathon').textContent = preds['marathon'] || '—:—';

  // Pace Zones
  const zones = vdot.pace_zones || {};
  $('#zone-easy').textContent = formatPace(zones['easy'] || '—');
  $('#zone-marathon').textContent = formatPace(zones['marathon'] || '—');
  $('#zone-tempo').textContent = formatPace(zones['tempo'] || '—');
  $('#zone-interval').textContent = formatPace(zones['interval'] || '—');
  $('#zone-repetition').textContent = formatPace(zones['repetition'] || '—');

  // Banister Load Stats
  $('#load-ctl').textContent = load.ctl_fitness != null ? fmtNumber(load.ctl_fitness, 1) : '—';
  $('#load-atl').textContent = load.atl_fatigue != null ? fmtNumber(load.atl_fatigue, 1) : '—';
  $('#load-tsb').textContent = load.tsb_form != null ? `${load.tsb_form > 0 ? '+' : ''}${fmtNumber(load.tsb_form, 1)}` : '—';
  const badge = $('#load-status-badge');
  if (badge) {
    badge.textContent = load.status || 'absorbing';
    badge.className = `status-badge ${load.status || ''}`;
  }
  $('#load-monotony').textContent = load.monotony != null ? fmtNumber(load.monotony, 2) : '—';
  $('#load-strain').textContent = load.strain != null ? fmtNumber(load.strain, 0) : '—';
  const paceRate = trend.rate_sec_per_km_per_week;
  $('#load-pace-trend').textContent = paceRate != null
    ? `${trend.direction} (${paceRate > 0 ? '+' : ''}${fmtNumber(paceRate, 1)}s/km/wk)`
    : (trend.direction || '—');

  // Race Readiness in Goal Card
  renderRaceReadiness(mlProfile.race_prediction);
}

function renderRaceReadiness(racePred) {
  const box = $('#race-readiness-box');
  if (!box) return;
  if (!racePred) {
    box.classList.add('hidden');
    return;
  }
  box.classList.remove('hidden');
  const prob = racePred.probability != null ? Math.round(racePred.probability * 100) : null;
  const chip = $('#race-prob-badge');
  if (chip) {
    chip.textContent = prob != null ? `${prob}% ${racePred.probability_label || ''}` : (racePred.probability_label || '—');
    chip.className = `prob-chip ${racePred.probability_label || ''}`;
  }
  $('#race-pred-time').textContent = racePred.predicted_time || '—';
  const gap = racePred.vdot_gap;
  $('#race-vdot-gap').textContent = gap != null ? `${gap > 0 ? '+' : ''}${fmtNumber(gap, 1)} VDOT` : '—';
  $('#race-assessment').textContent = racePred.assessment || 'Analyzing race preparation...';
}

/* --- SVG LOAD CHART RENDERING --- */
function renderLoadChart(history) {
  state.history = history;
  if (!history || !Array.isArray(history.daily_loads) || history.daily_loads.length < 2) return;

  const loads = history.daily_loads;
  const n = loads.length;
  const width = 500;
  const height = 130;
  const pad = 10;

  let maxVal = 10;
  let minVal = -5;
  loads.forEach(pt => {
    maxVal = Math.max(maxVal, pt.ctl || 0, pt.atl || 0, pt.tsb || 0);
    minVal = Math.min(minVal, pt.tsb || 0, 0);
  });
  const range = (maxVal - minVal) || 1;

  const getX = (idx) => (idx / (n - 1)) * width;
  const getY = (val) => height - pad - (((val - minVal) / range) * (height - 2 * pad));

  let ctlPath = '';
  let atlPath = '';
  let tsbPath = '';
  let ctlArea = '';

  loads.forEach((pt, i) => {
    const x = getX(i);
    const yCtl = getY(pt.ctl || 0);
    const yAtl = getY(pt.atl || 0);
    const yTsb = getY(pt.tsb || 0);

    const cmd = i === 0 ? 'M' : 'L';
    ctlPath += `${cmd} ${x.toFixed(1)} ${yCtl.toFixed(1)} `;
    atlPath += `${cmd} ${x.toFixed(1)} ${yAtl.toFixed(1)} `;
    tsbPath += `${cmd} ${x.toFixed(1)} ${yTsb.toFixed(1)} `;
  });

  const zeroY = getY(0);
  ctlArea = `${ctlPath} L ${width} ${zeroY.toFixed(1)} L 0 ${zeroY.toFixed(1)} Z`;

  const ctlEl = $('#chart-ctl-path');
  const atlEl = $('#chart-atl-path');
  const tsbEl = $('#chart-tsb-path');
  const areaEl = $('#chart-ctl-area');

  if (ctlEl) ctlEl.setAttribute('d', ctlPath);
  if (atlEl) atlEl.setAttribute('d', atlPath);
  if (tsbEl) tsbEl.setAttribute('d', tsbPath);
  if (areaEl) areaEl.setAttribute('d', ctlArea);
}

function renderGoal(goal) {
  state.goal = goal;
  const hasGoal = !!goal;
  $('#goal-empty').classList.toggle('hidden', hasGoal);
  $('#goal-summary').classList.toggle('hidden', !hasGoal);
  if (!goal) return;
  const meta = GOALS[goal.goal_type] || { label: goal.goal_type, km: '—', mi: '—' };
  $('#goal-name').textContent = meta.label;
  $('#goal-distance-label').textContent = currentUnit === 'imperial' ? (meta.mi || meta.km) : (meta.km || meta.mi);
  $('#goal-date').textContent = goal.race_date ? fmtDate(`${goal.race_date}T12:00:00`) : 'Race date not set';
  $('#goal-time').textContent = goal.target_time_seconds ? fmtDuration(goal.target_time_seconds) : 'No target time';
  $('#goal-training-days').textContent = (goal.training_days || []).join(' · ') || 'No training days';
  if (goal.race_date) {
    const days = Math.ceil((new Date(`${goal.race_date}T23:59:59`) - new Date()) / 86400000);
    $('#days-to-race').textContent = days < 0 ? 'Date passed' : days === 0 ? 'Race day!' : `${days} days to go`;
    $('#race-progress-fill').style.width = `${days < 0 ? 100 : Math.max(4, Math.min(100, 100 - days / 180 * 100))}%`;
  } else {
    $('#days-to-race').textContent = 'Date not set';
    $('#race-progress-fill').style.width = '0%';
  }
  $('#goal-type').value = goal.goal_type;
}

function renderActivities(activities) {
  state.activities = activities || [];
  const hasActivities = state.activities.length > 0;
  $('#activities-empty').classList.toggle('hidden', hasActivities);
  $('#activity-table-wrap').classList.toggle('hidden', !hasActivities);
  const unit = getUnitLabel();
  $('#activity-rows').innerHTML = state.activities.slice(0, 8).map((run) => {
    const dist = run.distance_m == null ? '—' : `${formatDistance(run.distance_m / 1000, 2)} ${unit}`;
    const hr = run.average_heartrate == null ? '—' : `${Math.round(run.average_heartrate)} bpm`;
    const localDateStr = fmtDate(run.start_date, { month:'short', day:'numeric', year:'numeric' });
    const runTitle = (run.name && !run.name.startsWith('Run — '))
      ? run.name
      : `Run — ${fmtDate(run.start_date, { month:'short', day:'numeric' })}`;
    return `<tr><td class="activity-name"><span class="run-icon">↗</span><span>${escapeHtml(runTitle)}<small>${escapeHtml(run.source_name || 'Apple Health')}</small></span></td><td>${escapeHtml(localDateStr)}</td><td>${dist}</td><td>${fmtDuration(run.duration_s)}</td><td>${hr}</td></tr>`;
  }).join('');

}

function renderPlan(plan) {
  state.plan = plan;
  const sessions = plan?.sessions || [];
  $('#plan-empty').classList.toggle('hidden', sessions.length > 0);
  $('#plan-list').classList.toggle('hidden', sessions.length === 0);
  if (!sessions.length) {
    $('#plan-subheading').textContent = state.goal ? 'Your adaptive plan is ready when running data is available.' : 'Set a goal to generate your first training plan.';
    return;
  }
  const unit = getUnitLabel();
  const targetKm = plan.weekly_target_km != null ? formatDistance(plan.weekly_target_km, 1) : '—';
  $('#plan-subheading').textContent = `${plan.coach_focus || 'Adaptive Week'} · ${targetKm} ${unit} total target`;

  $('#plan-list').innerHTML = sessions.map((session) => {
    const date = session.date ? fmtDate(`${session.date}T12:00:00`, { weekday:'short', month:'short', day:'numeric' }) : session.day;
    const type = String(session.type || 'easy_run').replaceAll('_',' ');
    const dist = session.target_distance_km != null ? `${formatDistance(session.target_distance_km, 1)} <small>${unit}</small>` : '';
    const pace = session.target_pace ? `<span class="session-pace-chip">🎯 ${escapeHtml(formatPace(session.target_pace))}</span>` : '';
    const rationale = session.coach_rationale ? `<div class="session-rationale">✧ ${escapeHtml(session.coach_rationale)}</div>` : '';

    return `<article class="session-card">
      <div class="session-date">${escapeHtml(date)}</div>
      <span class="session-type ${session.intensity === 'hard' || session.intensity === 'moderate_hard' ? 'controlled' : ''}">${escapeHtml(type)}</span>
      <h3>${escapeHtml(session.title || 'Run')}</h3>
      <div class="session-distance">${dist}</div>
      ${pace}
      <p>${escapeHtml(session.instructions || '')}</p>
      ${rationale}
    </article>`;
  }).join('');
}

async function refreshDashboard() {
  const results = await Promise.allSettled([
    api('/health/status'),
    api('/fitness/profile/basic?days=28'),
    api('/fitness/profile?days=42'),
    api('/fitness/history?days=42'),
    api('/activities?limit=100'),
    api('/goals')
  ]);
  const [statusResult, basicProfileRes, mlProfileRes, historyRes, activitiesResult, goalResult] = results;
  const status = statusResult.status === 'fulfilled' ? statusResult.value : null;
  const basicProfile = basicProfileRes.status === 'fulfilled' ? basicProfileRes.value : null;
  const mlProfile = mlProfileRes.status === 'fulfilled' ? mlProfileRes.value : null;

  renderProfile(basicProfile, mlProfile, status);

  if (historyRes.status === 'fulfilled') renderLoadChart(historyRes.value);
  if (activitiesResult.status === 'fulfilled') renderActivities(activitiesResult.value);

  if (goalResult.status === 'fulfilled') {
    renderGoal(goalResult.value);
    try { renderPlan(await api('/training/plan')); } catch { renderPlan(null); }
  } else {
    renderGoal(null); renderPlan(null);
  }
}

/* --- GOAL MODAL HANDLERS --- */
function openGoalModal() {
  $('#goal-error').classList.add('hidden');
  if (state.goal) {
    $('#goal-type').value = state.goal.goal_type;
    $$('.distance-option').forEach((button) => button.classList.toggle('selected', button.dataset.goal === state.goal.goal_type));
    $('#race-date').value = state.goal.race_date || '';
    const seconds = Number(state.goal.target_time_seconds || 0);
    $('#target-hours').value = seconds ? Math.floor(seconds / 3600) : '';
    $('#target-minutes').value = seconds ? Math.floor((seconds % 3600) / 60) : '';
    $('#target-seconds').value = seconds ? seconds % 60 : '';
    $$('#day-options input').forEach((input) => { input.checked = (state.goal.training_days || []).includes(input.value); });
  }
  $('#goal-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}
function closeGoalModal() { $('#goal-modal').classList.add('hidden'); document.body.style.overflow = ''; }

$('#hero-goal-button').addEventListener('click', openGoalModal);
$('#edit-goal-button').addEventListener('click', openGoalModal);
$('#empty-goal-button').addEventListener('click', openGoalModal);
$('#goal-edit-inline').addEventListener('click', openGoalModal);
$('#plan-set-goal').addEventListener('click', openGoalModal);
$('#close-goal-modal').addEventListener('click', closeGoalModal);
$('#goal-modal').addEventListener('click', (event) => { if (event.target === $('#goal-modal')) closeGoalModal(); });

$$('.distance-option').forEach((button) => button.addEventListener('click', () => {
  $$('.distance-option').forEach((item) => item.classList.toggle('selected', item === button));
  $('#goal-type').value = button.dataset.goal;
}));

$('#goal-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const goalType = $('#goal-type').value;
  const hours = parseInt($('#target-hours').value || '0', 10);
  const minutes = parseInt($('#target-minutes').value || '0', 10);
  const seconds = parseInt($('#target-seconds').value || '0', 10);
  const targetTimeSeconds = (hours * 3600) + (minutes * 60) + seconds || null;
  const raceDate = $('#race-date').value || null;
  const trainingDays = $$('#day-options input:checked').map((input) => input.value);
  if (!trainingDays.length) {
    $('#goal-error').textContent = 'Please choose at least one day you can run.';
    $('#goal-error').classList.remove('hidden');
    return;
  }
  try {
    const savedGoal = await api('/goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal_type: goalType,
        target_time_seconds: targetTimeSeconds,
        race_date: raceDate,
        training_days: trainingDays
      })
    });
    closeGoalModal();
    setMessage('Goal saved! Updating your adaptive training plan...');
    renderGoal(savedGoal);
    await refreshDashboard();
  } catch (error) {
    $('#goal-error').textContent = error.message;
    $('#goal-error').classList.remove('hidden');
  }
});

/* --- AI COACH CHAT MODAL --- */
function openCoachModal() {
  $('#coach-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  $('#coach-user-input').focus();
}
function closeCoachModal() {
  $('#coach-modal').classList.add('hidden');
  document.body.style.overflow = '';
}

$('#header-coach-btn')?.addEventListener('click', openCoachModal);
$('#ask-coach-hero-btn')?.addEventListener('click', openCoachModal);
$('#open-coach-chat-btn')?.addEventListener('click', openCoachModal);
$('#close-coach-modal')?.addEventListener('click', closeCoachModal);
$('#coach-modal')?.addEventListener('click', (event) => { if (event.target === $('#coach-modal')) closeCoachModal(); });

function appendChatMessage(role, text) {
  const history = $('#coach-chat-history');
  const msg = document.createElement('div');
  msg.className = `chat-msg ${role}`;
  msg.innerHTML = `
    <span class="chat-avatar">${role === 'user' ? 'R' : '✧'}</span>
    <div class="chat-bubble">${escapeHtml(text)}</div>
  `;
  history.appendChild(msg);
  history.scrollTop = history.scrollHeight;
}

async function handleCoachQuery(query) {
  if (!query || !query.trim()) return;
  appendChatMessage('user', query);
  $('#coach-user-input').value = '';

  const typingId = 'typing-' + Date.now();
  const history = $('#coach-chat-history');
  const typingMsg = document.createElement('div');
  typingMsg.className = 'chat-msg coach';
  typingMsg.id = typingId;
  typingMsg.innerHTML = `
    <span class="chat-avatar">✧</span>
    <div class="chat-bubble">Thinking based on your training data...</div>
  `;
  history.appendChild(typingMsg);
  history.scrollTop = history.scrollHeight;

  try {
    const res = await api('/coaching/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    $(`#${typingId}`)?.remove();
    appendChatMessage('coach', res.answer || "I couldn't process that query.");
  } catch (err) {
    $(`#${typingId}`)?.remove();
    appendChatMessage('coach', `Unable to contact coach: ${err.message}`);
  }
}

$('#coach-chat-form')?.addEventListener('submit', (e) => {
  e.preventDefault();
  const input = $('#coach-user-input');
  handleCoachQuery(input.value);
});

$$('.prompt-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    const prompt = chip.dataset.prompt;
    if (prompt) handleCoachQuery(prompt);
  });
});

/* --- UNIT TOGGLE (Metric / Imperial) --- */
$('#unit-toggle').addEventListener('click', () => {
  currentUnit = currentUnit === 'metric' ? 'imperial' : 'metric';
  localStorage.setItem('stride_unit', currentUnit);
  $$('.unit-opt').forEach((opt) => opt.classList.toggle('active', opt.dataset.unit === currentUnit));
  refreshDashboard();
});

/* --- FILE UPLOAD HANDLERS --- */
const uploadForm = $('#import-form');
const fileInput = $('#health-file');
$('#choose-file').addEventListener('click', () => fileInput.click());
$('#sidebar-import').addEventListener('click', () => {
  $('#import').scrollIntoView({ behavior: 'smooth' });
  fileInput.click();
});
['dragenter', 'dragover'].forEach(name => uploadForm.addEventListener(name, (e) => { e.preventDefault(); uploadForm.classList.add('dragover'); }));
['dragleave', 'drop'].forEach(name => uploadForm.addEventListener(name, (e) => { e.preventDefault(); uploadForm.classList.remove('dragover'); }));

uploadForm.addEventListener('drop', (e) => {
  if (e.dataTransfer.files.length) handleFileUpload(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files.length) handleFileUpload(fileInput.files[0]);
});

async function handleFileUpload(file) {
  const formData = new FormData();
  formData.append('file', file);
  setImportStatus(`Importing ${file.name}... parsing running workouts & VO₂ max...`);
  try {
    const res = await api('/health/import', { method: 'POST', body: formData });
    setImportStatus(`Successfully imported ${res.running_workouts_processed} running workouts!`);
    setMessage(`Import complete! ${res.running_workouts_processed} runs processed.`);
    await refreshDashboard();
  } catch (err) {
    setImportStatus(err.message, true);
  }
}

$('#refresh-plan')?.addEventListener('click', async () => {
  try {
    renderPlan(await api('/training/plan'));
    setMessage('Plan refreshed with latest readiness and fatigue load.');
  } catch (err) {
    setMessage(`Could not refresh plan: ${err.message}`, 'error');
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeGoalModal();
    closeCoachModal();
  }
});

// Set initial unit toggle state
$$('.unit-opt').forEach((opt) => opt.classList.toggle('active', opt.dataset.unit === currentUnit));

// Initialize dashboard
refreshDashboard();
