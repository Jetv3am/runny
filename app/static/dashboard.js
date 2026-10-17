const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const state = { goal: null, profile: null, activities: [], plan: null };
const GOALS = {
  '5k': { label: '5K', distance: '5 km' },
  '10k': { label: '10K', distance: '10 km' },
  'half_marathon': { label: 'Half marathon', distance: '21.1 km' },
  'marathon': { label: 'Marathon', distance: '42.2 km' }
};
const DAY_ORDER = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function fmtNumber(value, digits = 1) {
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}
function fmtDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!value) return 'Date not set';
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

function renderProfile(profile, status) {
  state.profile = profile;
  $('#weekly-distance').textContent = fmtNumber(profile.weekly_distance_km_last_7_days, 1);
  $('#run-count').textContent = fmtNumber(profile.runs_in_period, 0);
  $('#longest-run').textContent = fmtNumber(profile.longest_run_km, 1);
  $('#runs-per-week').textContent = `${fmtNumber(profile.average_runs_per_week, 1)} / week`;
  $('#distance-change').textContent = profile.distance_change_percent_week_over_week == null
    ? 'No prior week' : `${profile.distance_change_percent_week_over_week > 0 ? '+' : ''}${fmtNumber(profile.distance_change_percent_week_over_week, 0)}% vs prior week`;
  $('#longest-track').style.width = `${Math.min(100, Math.max(5, (Number(profile.longest_run_km) || 0) / 25 * 100))}%`;
  const vo2 = profile.vo2_max_latest;
  $('#vo2-value').textContent = vo2 ? fmtNumber(vo2.value, 1) : '—';
  $('#vo2-unit').textContent = vo2?.unit || 'ml/kg/min';
  $('#vo2-date').textContent = vo2 ? fmtDate(vo2.measured_at, { month:'short', day:'numeric' }) : 'Not imported';
  if (status && status.stored_activities > 0) {
    $('#connection-label').textContent = `${status.stored_activities} runs stored`;
    $('#connection-dot').classList.add('connected');
  } else {
    $('#connection-label').textContent = 'Awaiting import';
    $('#connection-dot').classList.remove('connected');
  }
}
function renderGoal(goal) {
  state.goal = goal;
  const hasGoal = !!goal;
  $('#goal-empty').classList.toggle('hidden', hasGoal);
  $('#goal-summary').classList.toggle('hidden', !hasGoal);
  if (!goal) return;
  const meta = GOALS[goal.goal_type] || { label: goal.goal_type, distance: '—' };
  $('#goal-name').textContent = meta.label;
  $('#goal-distance-label').textContent = meta.distance;
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
  $('#activity-rows').innerHTML = state.activities.slice(0, 8).map((run) => {
    const km = run.distance_m == null ? '—' : `${fmtNumber(run.distance_m / 1000, 2)} km`;
    const hr = run.average_heartrate == null ? '—' : `${Math.round(run.average_heartrate)} bpm`;
    return `<tr><td class="activity-name"><span class="run-icon">↗</span><span>${escapeHtml(run.name || 'Outdoor run')}<small>${escapeHtml(run.source_name || 'Apple Health')}</small></span></td><td>${escapeHtml(fmtDate(run.start_date, { month:'short', day:'numeric', year:'numeric' }))}</td><td>${km}</td><td>${fmtDuration(run.duration_s)}</td><td>${hr}</td></tr>`;
  }).join('');
}
function renderPlan(plan) {
  state.plan = plan;
  const sessions = plan?.sessions || [];
  $('#plan-empty').classList.toggle('hidden', sessions.length > 0);
  $('#plan-list').classList.toggle('hidden', sessions.length === 0);
  if (!sessions.length) {
    $('#plan-subheading').textContent = state.goal ? 'Your starter plan is ready when running data is available.' : 'Set a goal to generate your first training plan.';
    return;
  }
  $('#plan-subheading').textContent = `${plan.week_start ? `Week of ${fmtDate(plan.week_start, { month:'short', day:'numeric' })}` : 'This week'} · ${fmtNumber(plan.weekly_target_km,1)} km planned`;
  $('#plan-list').innerHTML = sessions.map((session) => {
    const date = session.date ? fmtDate(`${session.date}T12:00:00`, { weekday:'short', month:'short', day:'numeric' }) : session.day;
    const type = String(session.type || 'easy_run').replaceAll('_',' ');
    return `<article class="session-card"><div class="session-date">${escapeHtml(date)}</div><span class="session-type ${session.intensity === 'controlled' ? 'controlled' : ''}">${escapeHtml(type)}</span><h3>${escapeHtml(session.title || 'Run')}</h3><div class="session-distance">${fmtNumber(session.target_distance_km,1)} <small>km</small></div><p>${escapeHtml(session.instructions || '')}</p></article>`;
  }).join('');
  if (plan.message) $('#plan-subheading').textContent = plan.message;
}
async function refreshDashboard() {
  const results = await Promise.allSettled([
    api('/health/status'), api('/fitness/profile?days=28'), api('/activities?limit=100'), api('/goals')
  ]);
  const [statusResult, profileResult, activitiesResult, goalResult] = results;
  const status = statusResult.status === 'fulfilled' ? statusResult.value : null;
  if (profileResult.status === 'fulfilled') renderProfile(profileResult.value, status);
  if (activitiesResult.status === 'fulfilled') renderActivities(activitiesResult.value);
  if (goalResult.status === 'fulfilled') {
    renderGoal(goalResult.value);
    try { renderPlan(await api('/training/plan')); } catch { renderPlan(null); }
  } else {
    renderGoal(null); renderPlan(null);
  }
  if (status && status.stored_activities === 0 && status.stored_health_metrics === 0) {
    $('#connection-label').textContent = 'Awaiting import';
  }
}
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
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeGoalModal(); });
$$('.distance-option').forEach((button) => button.addEventListener('click', () => {
  $$('.distance-option').forEach((item) => item.classList.toggle('selected', item === button));
  $('#goal-type').value = button.dataset.goal;
}));
$('#goal-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const days = $$('#day-options input:checked').map((input) => input.value);
  const error = $('#goal-error');
  error.classList.add('hidden');
  if (!days.length) { error.textContent = 'Choose at least one day you can train.'; error.classList.remove('hidden'); return; }
  const h = Number($('#target-hours').value || 0), m = Number($('#target-minutes').value || 0), s = Number($('#target-seconds').value || 0);
  if (m > 59 || s > 59 || h < 0 || m < 0 || s < 0) { error.textContent = 'Enter a valid target time.'; error.classList.remove('hidden'); return; }
  const hasTime = $('#target-hours').value !== '' || $('#target-minutes').value !== '' || $('#target-seconds').value !== '';
  const payload = { goal_type: $('#goal-type').value, target_time_seconds: hasTime ? h * 3600 + m * 60 + s : null, race_date: $('#race-date').value || null, training_days: days };
  if (hasTime && payload.target_time_seconds <= 0) { error.textContent = 'Target time must be greater than zero.'; error.classList.remove('hidden'); return; }
  const submit = $('.save-goal-button'); submit.disabled = true; submit.firstElementChild.textContent = 'Saving…';
  try {
    const goal = await api('/goals', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    renderGoal(goal);
    try { renderPlan(await api('/training/plan')); } catch { renderPlan(null); }
    closeGoalModal(); setMessage('Your goal is saved. Your dashboard has been updated.');
  } catch (err) { error.textContent = err.message; error.classList.remove('hidden'); }
  finally { submit.disabled = false; submit.firstElementChild.textContent = 'Save my goal'; }
});

const fileInput = $('#health-file');
$('#choose-file').addEventListener('click', () => { if (fileInput.files?.[0]) $('#import-form').requestSubmit(); else fileInput.click(); });
$('.upload-zone').addEventListener('click', (event) => { if (!event.target.closest('button')) fileInput.click(); });
$('#sidebar-import').addEventListener('click', () => { $('#import').scrollIntoView({ behavior:'smooth', block:'center' }); setTimeout(() => fileInput.click(), 300); });
fileInput.addEventListener('change', () => {
  const file = fileInput.files?.[0];
  if (file) { $('#upload-title').textContent = file.name; $('#upload-subtitle').textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB · Ready to import`; $('#choose-file').textContent = 'Import file'; }
});
const dropZone = $('.upload-zone');
['dragenter','dragover'].forEach((name) => dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.add('dragover'); }));
['dragleave','drop'].forEach((name) => dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.remove('dragover'); }));
dropZone.addEventListener('drop', (event) => { const file = event.dataTransfer.files?.[0]; if (file && /\.(xml|zip)$/i.test(file.name)) { fileInput.files = event.dataTransfer.files; fileInput.dispatchEvent(new Event('change')); } else { setImportStatus('Please choose an Apple Health .xml or .zip export.', true); } });
$('#import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = fileInput.files?.[0];
  if (!file) { setImportStatus('Choose your Apple Health export first.', true); return; }
  const submit = $('#choose-file'); submit.disabled = true; submit.textContent = 'Importing…';
  setImportStatus(`Importing ${file.name}. Large Apple Health exports can take a little while…`);
  hideImportWarning();
  const formData = new FormData(); formData.append('file', file);
  try {
    const result = await api('/health/import', { method:'POST', body:formData });
    const runCount = Number(result.running_workouts_processed || 0);
    const vo2Count = Number(result.vo2_max_samples_processed || 0);
    setImportStatus(`Import finished: ${runCount.toLocaleString()} running workouts and ${vo2Count.toLocaleString()} VO₂ max samples imported.`, false);
    if (runCount === 0 && ((result.diagnostics?.workout_activity_types?.HKWorkoutActivityTypeRunning || 0) > 0)) {
      showImportWarning(`Apple Health reports ${result.diagnostics.workout_activity_types.HKWorkoutActivityTypeRunning.toLocaleString()} running workout records, but the parser saved none. The export contains your data; the importer still needs a parser fix. Your dashboard is showing only records already saved in the database.`);
    }
    if (runCount > 0 && vo2Count === 0 && (result.diagnostics?.vo2_like_record_types?.HKQuantityTypeIdentifierVO2Max || 0) > 0) {
      showImportWarning('VO₂ max records were found in the export but not saved. Running workouts imported; VO₂ max parsing still needs a fix.');
    }
    await refreshDashboard();
    if (runCount > 0 || vo2Count > 0) setMessage('Health data imported and your dashboard refreshed.');
  } catch (err) { setImportStatus(`Import failed: ${err.message}`, true); }
  finally { submit.disabled = false; submit.textContent = fileInput.files?.[0] ? 'Import file' : 'Choose file'; }
});
$('#refresh-plan').addEventListener('click', async () => {
  const button = $('#refresh-plan'); button.disabled = true; button.textContent = 'Refreshing…';
  try {
    if (!state.goal) { setMessage('Set a running goal first to generate your plan.', 'warning'); openGoalModal(); return; }
    renderPlan(await api('/training/plan'));
    setMessage('Training plan refreshed.');
  } catch (err) { setMessage(err.message, 'warning'); }
  finally { button.disabled = false; button.textContent = '↻ Refresh plan'; }
});

refreshDashboard().catch((err) => showImportWarning(`Could not load dashboard data: ${err.message}`));
