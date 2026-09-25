/**
 * SmartCaja v2.1 — Frontend Application
 * Motor Financiero Modular con estilos CCS Brand
 */

// ============================================================================
// Estado Global
// ============================================================================
const API = '';
let state = {
  companyId: null,
  companyName: '',
  companySector: '',
  sessionId: '',
  cashflow: null,
  companies: [],
  charts: {},
  generationTaskId: null,
  mcTaskId: null,
  currentPage: 'home',
  wizardStep: 1,
  focusTopic: null,
  currentTopic: null,
  interviewStages: null,
  glossaryTerms: null,
  availableSkills: [],
  installedModels: [],
};

// ============================================================================
// Inicialización
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
  checkOllama();
  loadCompanies();
});

async function checkOllama() {
  try {
    const r = await fetch(`${API}/api/readiness`);
    const data = await r.json();
    const dot = document.getElementById('ollamaDot');
    const text = document.getElementById('ollamaStatusText');
    renderRamWarning(data);

    if (data.ready) {
      dot.className = 'status-dot online';
      text.textContent = `Ollama OK (${data.models_count} modelos)`;
      showReadinessBanner(true);
    } else {
      dot.className = 'status-dot loading';
      text.textContent = 'Preparando...';
      showReadinessBanner(false, data.issues ? data.issues[0]?.message : 'Preparando modelos...');
      pollOllama();
    }
  } catch(e) {
    document.getElementById('ollamaDot').className = 'status-dot';
    document.getElementById('ollamaStatusText').textContent = 'Desconectado';
    showReadinessBanner(false, 'No se pudo conectar con el servidor');
  }
}

function pollOllama() {
  const poll = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/readiness`);
      const d = await r.json();
      renderRamWarning(d);
      if (d.ready) {
        clearInterval(poll);
        document.getElementById('ollamaDot').className = 'status-dot online';
        document.getElementById('ollamaStatusText').textContent = `Ollama OK (${d.models_count} modelos)`;
        document.getElementById('readinessBanner').innerHTML = '';
      }
    } catch(e) {}
  }, 4000);
}

function renderRamWarning(data) {
  const el = document.getElementById('ramWarnBanner');
  if (!el) return;
  const access = data && data.access ? data.access : {};
  if (access.level !== 'warn') {
    el.innerHTML = '';
    return;
  }
  const ram = (typeof access.ram_gb === 'number') ? access.ram_gb.toFixed(1) + ' GB' : 'poca RAM';
  el.innerHTML = `<div class="readiness-banner not-ready" style="margin-top:8px">
    <div style="font-size:20px;">&#9888;&#65039;</div>
    <div>
      <div style="font-weight:700;">Perfil Estándar</div>
      <div style="font-size:12px;opacity:0.8;">Este equipo tiene ${escapeHtml(ram)}. SmartCaja usa un modelo compacto. Cierra Chrome o Teams mientras generas; los textos largos tardan más.</div>
    </div>
  </div>`;
}

function showReadinessBanner(ready, message) {
  const el = document.getElementById('readinessBanner');
  if (ready) {
    el.innerHTML = '';
  } else {
    el.innerHTML = `<div class="readiness-banner not-ready">
      <div style="font-size:20px;">&#9888;&#65039;</div>
      <div><div style="font-weight:700;">Sistema prepar\u00e1ndose</div><div style="font-size:12px;opacity:0.8;">${escapeHtml(message || 'Verificando modelos de IA...')}</div></div>
    </div>`;
  }
}

// ============================================================================
// Navegación
// ============================================================================
function navigateTo(page) {
  state.currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.getElementById(`nav-${page}`);
  if (navEl) navEl.classList.add('active');

  const titles = {
    home: 'Inicio',
    companies: 'Mis Empresas',
    interview: 'Entrevista Financiera',
    dashboard: 'Dashboard — Flujo de Caja',
    simulation: 'Simulación Interactiva',
    montecarlo: 'Simulación Monte Carlo',
    scenarios: 'Escenarios y Versiones',
    metrics: 'Métricas Financieras',
    agents: 'Agentes & Skills',
    tokens: 'Uso de Tokens',
    settings: 'Configuración',
  };
  document.getElementById('pageTitle').textContent = titles[page] || page;

  // Load data for specific pages
  if (page === 'dashboard' && state.companyId) loadCashflow();
  if (page === 'scenarios' && state.companyId) loadVersions();
  if (page === 'metrics' && state.companyId) loadMetrics();
  if (page === 'simulation' && state.companyId) renderSimulationControls();
  if (page === 'agents') loadAgents();
  if (page === 'tokens') loadTokenStats();
  if (page === 'settings') loadSettings();
}

// ============================================================================
// Empresas
// ============================================================================
async function loadCompanies() {
  try {
    const r = await fetch(`${API}/api/companies`);
    const data = await r.json();
    state.companies = data.companies || [];
    document.getElementById('companiesBadge').textContent = state.companies.length;
    renderCompaniesGrid();
    renderHomeCompanies();

    // Auto-select if only one
    if (state.companies.length === 1 && !state.companyId) {
      selectCompany(state.companies[0].id);
    }
  } catch(e) { console.error('Error loading companies:', e); }
}

function renderCompaniesGrid() {
  const grid = document.getElementById('companiesGrid');
  if (!state.companies.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;">
      <div class="empty-icon"><i class="fas fa-building"></i></div>
      <div class="empty-title">No hay empresas registradas</div>
      <div class="empty-desc">Crea tu primera empresa para comenzar a proyectar flujos de caja</div>
      <button class="btn btn-primary" onclick="openModal('newCompanyModal')"><i class="fas fa-plus"></i> Crear Empresa</button>
    </div>`;
    return;
  }

  grid.innerHTML = state.companies.map(c => {
    const initial = escapeHtml((c.name || '?')[0].toUpperCase());
    const statusClass = c.status === 'complete' ? 'status-complete' : c.status === 'interviewing' ? 'status-interviewing' : 'status-pending';
    const statusText = c.status === 'complete' ? 'Cashflow listo' : c.status === 'interviewing' ? 'En entrevista' : 'Pendiente';
    const selected = c.id === state.companyId ? 'selected' : '';
    return `<div class="company-card ${selected}" onclick="selectCompany('${escapeHtml(c.id)}')">
      <div class="company-avatar">${initial}</div>
      <div class="company-name">${escapeHtml(c.name)}</div>
      <div class="company-sector">${escapeHtml(c.sector || 'Sin sector')}</div>
      <div class="company-status ${statusClass}">${statusText}</div>
    </div>`;
  }).join('');
}

function renderHomeCompanies() {
  const el = document.getElementById('homeCompaniesList');
  if (!state.companies.length) { el.innerHTML = ''; return; }

  el.innerHTML = `<div class="card">
    <div class="card-header">
      <div><div class="card-title">Tus Empresas</div><div class="card-subtitle">Selecciona una empresa para continuar</div></div>
      <button class="btn btn-sm btn-secondary" onclick="navigateTo('companies')">Ver todas</button>
    </div>
    <div class="grid-3">${state.companies.slice(0, 3).map(c => {
      const initial = escapeHtml((c.name || '?')[0].toUpperCase());
      const statusClass = c.status === 'complete' ? 'status-complete' : c.status === 'interviewing' ? 'status-interviewing' : 'status-pending';
      const statusText = c.status === 'complete' ? 'Cashflow listo' : c.status === 'interviewing' ? 'En entrevista' : 'Pendiente';
      return `<div class="company-card" onclick="selectCompany('${escapeHtml(c.id)}')">
        <div class="company-avatar">${initial}</div>
        <div class="company-name">${escapeHtml(c.name)}</div>
        <div class="company-sector">${escapeHtml(c.sector || 'Sin sector')}</div>
        <div class="company-status ${statusClass}">${statusText}</div>
      </div>`;
    }).join('')}</div>
  </div>`;
}

async function selectCompany(id) {
  if (!id) return;
  state.companyId = id;
  state.sessionId = '';

  showGlobalLoading('Cargando empresa...');

  try {
    const r = await fetch(`${API}/api/companies/${id}`);
    const company = await r.json();
    state.companyName = company.name;
    state.companySector = company.sector;

    // Show company tools in sidebar
    document.getElementById('companyToolsSection').style.display = 'block';
    document.getElementById('activeCompanyLabel').textContent = company.name;
    document.getElementById('interviewCompanyName').textContent = `— ${company.name}`;

    // Load sessions
    const sr = await fetch(`${API}/api/companies/${id}/sessions`);
    const sessions = await sr.json();
    const interviewSessions = (sessions.sessions || []).filter(s => s.type === 'interview' || s.type === 'interview_v2');

    if (interviewSessions.length > 0) {
      const lastSession = interviewSessions[interviewSessions.length - 1];
      state.sessionId = lastSession.id;
      await loadSession(id, lastSession.id);
    } else {
      const chatDiv = document.getElementById('chatMessages');
      const bits = [];
      if (company.sector) bits.push(`sector <strong>${escapeHtml(company.sector)}</strong>`);
      if (company.employees) bits.push(`${escapeHtml(String(company.employees))} empleado(s)`);
      if (company.initial_cash) bits.push(`caja ${formatCurrency(company.initial_cash)}`);
      if (company.country) bits.push(`${escapeHtml(company.country)} / ${escapeHtml(company.currency || '')}`);
      const resumen = bits.length
        ? `Ya registramos ${bits.join(', ')}. Confírmalos o ajústalos; no hace falta repetirlos. Haz clic en un tema del panel o responde aquí.`
        : 'Sigue el orden del panel o haz clic en un tema. El flujo se genera solo cuando pulses <strong>Generar Cashflow</strong>.';
      chatDiv.innerHTML = `<div class="chat-message system-msg">Bienvenido. Soy tu analista financiero de la CCS para <strong>${escapeHtml(company.name)}</strong>. ${resumen}</div>`;
    }

    // Enable chat
    document.getElementById('chatInput').disabled = false;
    document.getElementById('btnSendChat').disabled = false;

    // Load cashflow if exists
    if (company.status === 'complete') {
      await loadCashflow();
    }

    // Restaurar progreso de entrevista persistido
    await restoreInterviewProgress(id);
    renderCompaniesGrid();
    hideGlobalLoading();

    // Navigate to interview
    navigateTo('interview');
    notify('success', `Empresa "${company.name}" seleccionada`);
  } catch(e) {
    hideGlobalLoading();
    notify('error', 'Error cargando la empresa');
  }
}

async function loadSession(companyId, sessionId) {
  try {
    const r = await fetch(`${API}/api/companies/${companyId}/sessions/${sessionId}`);
    const session = await r.json();
    const chatDiv = document.getElementById('chatMessages');
    chatDiv.innerHTML = '';
    (session.messages || []).forEach(msg => {
      addChatBubble(msg.role, msg.content);
    });
    chatDiv.scrollTop = chatDiv.scrollHeight;
  } catch(e) {}
}

// ============================================================================
// Wizard de Creación de Empresa
// ============================================================================
function wizardNext(step) {
  if (step === 1) {
    const name = document.getElementById('companyName').value.trim();
    const sector = document.getElementById('companySector').value;
    if (!name) { notify('error', 'Ingresa el nombre de la empresa'); return; }
    if (!sector) { notify('error', 'Selecciona un sector'); return; }
  }

  if (step === 2) {
    renderCompanySummary();
  }

  // Update wizard UI
  document.getElementById(`wizardStep${step}`).style.display = 'none';
  document.getElementById(`wizardStep${step + 1}`).style.display = 'block';
  document.getElementById(`ws-${step}`).className = 'wizard-step done';
  document.getElementById(`wc-${step}`).className = 'wizard-connector done';
  document.getElementById(`ws-${step + 1}`).className = 'wizard-step active';
  state.wizardStep = step + 1;
}

function wizardBack(step) {
  document.getElementById(`wizardStep${step}`).style.display = 'none';
  document.getElementById(`wizardStep${step - 1}`).style.display = 'block';
  document.getElementById(`ws-${step}`).className = 'wizard-step';
  document.getElementById(`wc-${step - 1}`).className = 'wizard-connector';
  document.getElementById(`ws-${step - 1}`).className = 'wizard-step active';
  state.wizardStep = step - 1;
}

function renderCompanySummary() {
  const name = document.getElementById('companyName').value.trim();
  const sector = document.getElementById('companySector').value;
  const size = document.getElementById('companySize').value;
  const country = document.getElementById('companyCountry').value;
  const currency = document.getElementById('companyCurrency').value;
  const cash = document.getElementById('companyInitialCash').value;
  const employees = document.getElementById('companyEmployees').value;
  const age = document.getElementById('companyAge').value;

  const sizeLabels = { micro: 'Micro (1-9)', pequena: 'Pequeña (10-49)', mediana: 'Mediana (50-199)' };
  const ageLabels = { nuevo: 'Menos de 1 año', joven: '1-3 años', establecido: '3-5 años', maduro: 'Más de 5 años' };

  document.getElementById('companySummary').innerHTML = `
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:12px;">
      <div><span style="color:var(--text-muted);">Nombre:</span> <strong>${escapeHtml(name)}</strong></div>
      <div><span style="color:var(--text-muted);">Sector:</span> <strong>${escapeHtml(sector)}</strong></div>
      ${size ? `<div><span style="color:var(--text-muted);">Tamaño:</span> <strong>${escapeHtml(sizeLabels[size] || size)}</strong></div>` : ''}
      ${country ? `<div><span style="color:var(--text-muted);">País:</span> <strong>${escapeHtml(country)}</strong></div>` : ''}
      ${currency ? `<div><span style="color:var(--text-muted);">Moneda:</span> <strong>${escapeHtml(currency)}</strong></div>` : ''}
      ${cash ? `<div><span style="color:var(--text-muted);">Caja inicial:</span> <strong>${formatCurrency(cash)}</strong></div>` : ''}
      ${employees ? `<div><span style="color:var(--text-muted);">Empleados:</span> <strong>${escapeHtml(String(employees))}</strong></div>` : ''}
      ${age ? `<div><span style="color:var(--text-muted);">Antigüedad:</span> <strong>${escapeHtml(ageLabels[age] || age)}</strong></div>` : ''}
    </div>`;
}

async function createCompany() {
  const name = document.getElementById('companyName').value.trim();
  const sector = document.getElementById('companySector').value;
  const size = document.getElementById('companySize').value;
  const desc = document.getElementById('companyDescription').value.trim();
  const country = document.getElementById('companyCountry').value;
  const currency = document.getElementById('companyCurrency').value;
  const cash = document.getElementById('companyInitialCash').value;
  const employees = document.getElementById('companyEmployees').value;
  const age = document.getElementById('companyAge').value;

  if (!name) { notify('error', 'Ingresa el nombre de la empresa'); return; }

  showGlobalLoading('Creando empresa...', 'Preparando el entorno de análisis financiero');

  try {
    const r = await fetch(`${API}/api/companies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, sector, size, description: desc,
        country, currency, initial_cash: cash ? parseFloat(cash) : 0,
        employees: employees ? parseInt(employees) : 0, age
      })
    });
    const company = await r.json();

    // Reset wizard
    closeModal('newCompanyModal');
    resetWizard();

    // Reload and select
    await loadCompanies();
    hideGlobalLoading();
    await selectCompany(company.id);

    notify('success', `Empresa "${name}" creada exitosamente`);
  } catch(e) {
    hideGlobalLoading();
    notify('error', 'Error creando la empresa');
  }
}

function resetWizard() {
  state.wizardStep = 1;
  document.getElementById('wizardStep1').style.display = 'block';
  document.getElementById('wizardStep2').style.display = 'none';
  document.getElementById('wizardStep3').style.display = 'none';
  document.getElementById('ws-1').className = 'wizard-step active';
  document.getElementById('ws-2').className = 'wizard-step';
  document.getElementById('ws-3').className = 'wizard-step';
  document.getElementById('wc-1').className = 'wizard-connector';
  document.getElementById('wc-2').className = 'wizard-connector';
  // Clear fields
  document.getElementById('companyName').value = '';
  document.getElementById('companySector').value = '';
  document.getElementById('companySize').value = '';
  document.getElementById('companyDescription').value = '';
  document.getElementById('companyInitialCash').value = '';
  document.getElementById('companyEmployees').value = '';
  document.getElementById('companyAge').value = '';
}

// ============================================================================
// Chat / Entrevista
// ============================================================================
function handleChatKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

const MAX_MESSAGE_LENGTH = 10000;

async function sendMessage(overrideMsg, focusTopic) {
  const input = document.getElementById('chatInput');
  const msg = (overrideMsg != null ? String(overrideMsg) : input.value).trim();
  if (!msg || !state.companyId) return;
  if (msg.length > MAX_MESSAGE_LENGTH) {
    addChatBubble('assistant', `El mensaje es demasiado largo (máximo ${MAX_MESSAGE_LENGTH} caracteres).`);
    return;
  }

  if (overrideMsg == null) {
    input.value = '';
    input.style.height = 'auto';
  }
  addChatBubble('user', msg);
  const typingId = showTyping();
  const topic = focusTopic || state.focusTopic || null;

  try {
    const r = await fetch(`${API}/api/chat/interview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: state.companyId,
        message: msg,
        session_id: state.sessionId,
        focus_topic: topic || undefined,
      })
    });
    const data = await r.json();
    state.sessionId = data.session_id;
    state.focusTopic = null;

    removeTyping(typingId);
    addChatBubble('assistant', data.response);

    if (data.progress) {
      updateInterviewProgressFromData(data.progress);
    }

    const btnGen = document.getElementById('btnGenerateCashflow');
    if (btnGen) {
      btnGen.style.display = 'inline-flex';
      btnGen.style.opacity = (data.has_enough_data || data.is_complete) ? '1' : '0.85';
      if (data.is_complete) {
        btnGen.classList.add('pulse-animation');
        btnGen.innerHTML = '<i class="fas fa-rocket"></i> Generar Cashflow';
      }
    }

    updateInterviewTopics(data.progress?.topics_covered || [], data.progress || {});
  } catch(e) {
    removeTyping(typingId);
    console.error('[SmartCaja] Chat error:', e);
    addChatBubble('system-msg', 'Error comunicando con el servidor. Verifica que Ollama esté activo.');
  }
}

async function restoreInterviewProgress(companyId) {
  try {
    const r = await fetch(`${API}/api/companies/${companyId}/interview-progress`);
    if (!r.ok) { updateInterviewTopics([]); return; }
    const data = await r.json();
    if (data.progress) {
      updateInterviewProgressFromData(data.progress);
    }
    updateInterviewTopics(data.topics_covered || data.progress?.topics_covered || [], data.progress || {});
  } catch(e) {
    console.error('[SmartCaja] Error restoring interview progress:', e);
    updateInterviewTopics([]);
  }
}

function updateInterviewProgressFromData(progress) {
  const pctEl = document.getElementById('interviewPct');
  const covered = progress.covered || 0;
  const total = progress.total_topics || 0;
  const pct = Math.round(progress.progress_pct || 0);
  if (pctEl) {
    pctEl.textContent = `${pct}%`;
    pctEl.style.color = progress.is_complete ? 'var(--ccs-verde)' : 'var(--ccs-azul)';
  }
  const labelEl = document.getElementById('interviewProgressLabel');
  if (labelEl && total) {
    labelEl.innerHTML = `Progreso: <strong id="interviewPct" style="color:${progress.is_complete ? 'var(--ccs-verde)' : 'var(--ccs-azul)'};">${pct}%</strong> <span style="color:var(--text-muted);">(${covered} de ${total})</span>`;
  }
  const barEl = document.getElementById('interviewBar');
  if (barEl) barEl.style.width = `${progress.progress_pct || 0}%`;
  const hint = document.getElementById('interviewHint');
  if (hint && progress.complete_hint) {
    hint.textContent = progress.complete_hint + ' Haz clic en un tema para saltar a él.';
  }
  if (progress.stages) state.interviewStages = progress.stages;
  if (progress.current_topic) state.currentTopic = progress.current_topic;
}

function jumpToInterviewTopic(topicId, label) {
  if (!state.companyId || !topicId) return;
  state.focusTopic = topicId;
  state.currentTopic = topicId;
  updateInterviewTopics(state.lastCoveredTopics || [], { current_topic: topicId, stages: state.interviewStages });
  sendMessage('Quiero hablar del tema: ' + label, topicId);
}

function updateInterviewTopics(coveredTopics = [], progress = {}) {
  state.lastCoveredTopics = coveredTopics;
  const stages = progress.stages || state.interviewStages;
  const current = progress.current_topic || state.currentTopic;
  const container = document.getElementById('interviewTopics');
  if (!container) return;

  const renderItem = (t) => {
    const covered = coveredTopics.includes(t.id);
    const isCurrent = current === t.id;
    const icon = covered ? 'fa-check-circle' : (t.icon || 'fa-circle');
    return `<div class="topic-item ${covered ? 'covered' : ''} ${isCurrent ? 'current' : ''}" role="button" tabindex="0"
        onclick='jumpToInterviewTopic(${JSON.stringify(t.id)}, ${JSON.stringify(t.label)})'>
      <span class="topic-icon"><i class="fas ${icon}" style="${covered ? 'color:var(--ccs-verde)' : ''}"></i></span>
      <span style="flex:1;">${escapeHtml(t.label)}</span>
      <button type="button" class="topic-help" title="¿Qué es esto?" onclick='event.stopPropagation(); openGlossary(${JSON.stringify(t.id)})'><i class="fas fa-question-circle"></i></button>
    </div>`;
  };

  if (stages && stages.length) {
    container.innerHTML = stages.map(stage => `
      <div class="topic-stage">${escapeHtml(stage.label)}</div>
      ${(stage.topics || []).map(renderItem).join('')}
    `).join('');
    return;
  }

  const fallback = [
    { id: 'tipo_negocio', label: 'Tipo de negocio', icon: 'fa-store' },
    { id: 'productos_servicios', label: 'Productos/Servicios', icon: 'fa-box' },
    { id: 'segmentos_clientes', label: 'Segmentos de clientes', icon: 'fa-users' },
    { id: 'modelo_ingresos', label: 'Modelo de ingresos', icon: 'fa-dollar-sign' },
    { id: 'precios_volumen', label: 'Precios y volúmenes', icon: 'fa-tag' },
    { id: 'crecimiento', label: 'Crecimiento esperado', icon: 'fa-chart-line' },
    { id: 'estacionalidad', label: 'Estacionalidad', icon: 'fa-calendar' },
    { id: 'costos_variables', label: 'Costos variables', icon: 'fa-receipt' },
    { id: 'costos_fijos', label: 'Costos fijos', icon: 'fa-building' },
    { id: 'salarios', label: 'Salarios', icon: 'fa-user-tie' },
    { id: 'caja_inicial', label: 'Caja inicial', icon: 'fa-piggy-bank' },
    { id: 'deuda', label: 'Deuda', icon: 'fa-credit-card' },
    { id: 'riesgos', label: 'Riesgos principales', icon: 'fa-shield-alt' },
  ];
  container.innerHTML = fallback.map(renderItem).join('');
}

async function openGlossary(topicId) {
  openModal('glossaryModal');
  const box = document.getElementById('glossaryContent');
  if (!state.glossaryTerms) {
    box.innerHTML = '<p style="color:var(--text-muted);">Cargando glosario...</p>';
    try {
      const r = await fetch(`${API}/api/glossary`);
      const data = await r.json();
      state.glossaryTerms = data.terms || [];
    } catch (e) {
      box.innerHTML = '<p>No se pudo cargar el glosario.</p>';
      return;
    }
  }
  renderGlossary(topicId);
}

function renderGlossary(focusId) {
  const box = document.getElementById('glossaryContent');
  const terms = state.glossaryTerms || [];
  const ordered = focusId
    ? [...terms.filter(t => t.id === focusId), ...terms.filter(t => t.id !== focusId)]
    : terms;
  box.innerHTML = ordered.map(t => {
    const calc = t.calculator === 'fixed_costs' ? glossaryCalcFixed()
      : t.calculator === 'variable_pct' ? glossaryCalcVariable()
      : t.calculator === 'salary_chile' ? glossaryCalcSalary()
      : '';
    return `<div class="glossary-term" id="glossary-${t.id}">
      <h4>${escapeHtml(t.title || t.id)}</h4>
      <p style="font-size:13px;">${escapeHtml(t.definition || '')}</p>
      ${t.formula ? `<div class="glossary-formula">${escapeHtml(t.formula)}</div>` : ''}
      ${calc}
    </div>`;
  }).join('');
  if (focusId) {
    const el = document.getElementById('glossary-' + focusId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function glossaryCalcFixed() {
  return `<div class="calc-box">
    <div style="font-size:12px; font-weight:700; color:var(--ccs-azul-oscuro); margin-bottom:8px;">Calculadora de costo fijo mensual</div>
    <div class="form-row">
      <div class="form-group"><label>Arriendo</label><input type="number" id="calcArriendo" oninput="runFixedCalc()"></div>
      <div class="form-group"><label>Servicios</label><input type="number" id="calcServicios" oninput="runFixedCalc()"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>Seguros</label><input type="number" id="calcSeguros" oninput="runFixedCalc()"></div>
      <div class="form-group"><label>Software y otros</label><input type="number" id="calcOtrosFijos" oninput="runFixedCalc()"></div>
    </div>
    <div class="calc-result" id="calcFixedResult">Total: $0</div>
  </div>`;
}

function glossaryCalcVariable() {
  return `<div class="calc-box">
    <div style="font-size:12px; font-weight:700; color:var(--ccs-azul-oscuro); margin-bottom:8px;">Calculadora de % costo variable</div>
    <div class="form-row">
      <div class="form-group"><label>Costo de producir o comprar (mes)</label><input type="number" id="calcCostoProd" oninput="runVariableCalc()"></div>
      <div class="form-group"><label>Ventas del mes</label><input type="number" id="calcVentasMes" oninput="runVariableCalc()"></div>
    </div>
    <div class="calc-result" id="calcVarResult">% costo variable: —</div>
  </div>`;
}

function glossaryCalcSalary() {
  return `<div class="calc-box">
    <div style="font-size:12px; font-weight:700; color:var(--ccs-azul-oscuro); margin-bottom:8px;">Sueldo líquido / bruto (Chile, estimación)</div>
    <p style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">Descuenta AFP ~10,77%, salud 7%, cesantía 0,6% e impuesto único simplificado. No reemplaza una liquidación oficial.</p>
    <div class="form-row">
      <div class="form-group"><label>Sueldo bruto</label><input type="number" id="calcBruto" oninput="runSalaryCalc('bruto')"></div>
      <div class="form-group"><label>Sueldo líquido</label><input type="number" id="calcLiquido" oninput="runSalaryCalc('liquido')"></div>
    </div>
    <div class="calc-result" id="calcSalaryResult">Completa un campo para estimar el otro.</div>
  </div>`;
}

function runFixedCalc() {
  const n = (id) => parseFloat(document.getElementById(id)?.value || 0) || 0;
  const total = n('calcArriendo') + n('calcServicios') + n('calcSeguros') + n('calcOtrosFijos');
  const el = document.getElementById('calcFixedResult');
  if (el) el.textContent = 'Total: ' + formatCurrency(total);
}

function runVariableCalc() {
  const costo = parseFloat(document.getElementById('calcCostoProd')?.value || 0) || 0;
  const ventas = parseFloat(document.getElementById('calcVentasMes')?.value || 0) || 0;
  const el = document.getElementById('calcVarResult');
  if (!el) return;
  if (ventas <= 0) { el.textContent = '% costo variable: —'; return; }
  el.textContent = '% costo variable: ' + ((costo / ventas) * 100).toFixed(1) + '%';
}

function chilePayroll(bruto) {
  const afp = bruto * 0.1077;
  const salud = bruto * 0.07;
  const cesantia = bruto * 0.006;
  const imponible = Math.max(0, bruto - afp - salud - cesantia);
  let tax = 0;
  if (imponible > 3200000) tax = imponible * 0.135 - 280000;
  else if (imponible > 1800000) tax = imponible * 0.08 - 90000;
  else if (imponible > 900000) tax = imponible * 0.04 - 25000;
  tax = Math.max(0, tax);
  return { afp, salud, cesantia, tax, liquido: bruto - afp - salud - cesantia - tax };
}

function runSalaryCalc(source) {
  const brutoEl = document.getElementById('calcBruto');
  const liqEl = document.getElementById('calcLiquido');
  const out = document.getElementById('calcSalaryResult');
  if (!brutoEl || !liqEl || !out) return;
  if (source === 'bruto') {
    const bruto = parseFloat(brutoEl.value || 0) || 0;
    if (!bruto) { out.textContent = 'Completa un campo para estimar el otro.'; return; }
    const p = chilePayroll(bruto);
    liqEl.value = Math.round(p.liquido);
    out.textContent = `AFP ${formatCurrency(p.afp)} · Salud ${formatCurrency(p.salud)} · Cesantía ${formatCurrency(p.cesantia)} · Impuesto ${formatCurrency(p.tax)} · Líquido ${formatCurrency(p.liquido)}`;
  } else {
    const neto = parseFloat(liqEl.value || 0) || 0;
    if (!neto) { out.textContent = 'Completa un campo para estimar el otro.'; return; }
    let lo = neto, hi = neto * 1.9;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (chilePayroll(mid).liquido < neto) lo = mid; else hi = mid;
    }
    const bruto = (lo + hi) / 2;
    brutoEl.value = Math.round(bruto);
    const p = chilePayroll(bruto);
    out.textContent = `Bruto estimado ${formatCurrency(bruto)} · descuentos ${formatCurrency(bruto - p.liquido)}`;
  }
}

function addChatBubble(role, content) {
  const chatDiv = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-message ${role}`;
  // Sanitizar primero con DOMPurify, luego aplicar markdown básico
  var safeContent = typeof DOMPurify !== 'undefined'
    ? DOMPurify.sanitize(content, { ALLOWED_TAGS: ['strong', 'em', 'br', 'p', 'ul', 'ol', 'li', 'code'], ALLOWED_ATTR: [] })
    : escapeHtml(content);
  // Markdown básico sobre contenido ya saneado
  safeContent = safeContent
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
  div.innerHTML = safeContent;
  chatDiv.appendChild(div);
  chatDiv.scrollTop = chatDiv.scrollHeight;
}

function showTyping() {
  const chatDiv = document.getElementById('chatMessages');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'chat-message assistant';
  div.id = id;
  div.innerHTML = '<div class="loading-spinner" style="width:14px;height:14px;border-width:2px;"></div> <span style="font-size:12px;color:var(--text-muted);margin-left:6px;">Analizando...</span>';
  chatDiv.appendChild(div);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

// ============================================================================
// Generación de Cashflow
// ============================================================================
async function generateCashflow() {
  if (!state.companyId) return;

  navigateTo('dashboard');
  const panel = document.getElementById('genProgressPanel');
  panel.style.display = 'block';
  document.getElementById('genBar').style.width = '0%';
  document.getElementById('genPct').textContent = '0%';
  document.getElementById('genStep').textContent = 'Iniciando generación...';
  document.getElementById('genNotifications').innerHTML = '';

  try {
    const r = await fetch(`${API}/api/v2/companies/${state.companyId}/generate-cashflow`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ months: 12, use_market_data: true, run_monte_carlo: true, monte_carlo_iterations: 500 })
    });
    const data = await r.json();

    if (data.task_id) {
      state.generationTaskId = data.task_id;
      pollGenerationProgress(data.task_id);
    }
  } catch(e) {
    // Fallback to V1
    try {
      const r = await fetch(`${API}/api/companies/${state.companyId}/generate-cashflow`, { method: 'POST' });
      const data = await r.json();
      if (data.task_id) {
        state.generationTaskId = data.task_id;
        pollGenerationProgressV1(data.task_id);
      }
    } catch(e2) {
      document.getElementById('genStep').textContent = 'Error iniciando generación';
      notify('error', 'Error al generar el flujo de caja');
    }
  }
}

function pollGenerationProgress(taskId) {
  const poll = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/v2/generation/${taskId}/progress`);
      const data = await r.json();

      // Backend V2 retorna: { status, progress, step, phase, notifications: [{message, timestamp}], error }
      const pct = data.progress || 0;
      document.getElementById('genBar').style.width = `${pct}%`;
      document.getElementById('genPct').textContent = `${Math.round(pct)}%`;
      document.getElementById('genStep').textContent = data.step || 'Procesando...';

      // Add notifications - cada notificación es {message, timestamp}
      if (data.notifications && data.notifications.length > 0) {
        const container = document.getElementById('genNotifications');
        const existing = container.querySelectorAll('.notification-item').length;
        data.notifications.slice(existing).forEach(n => {
          const msg = (typeof n === 'string') ? n : (n.message || JSON.stringify(n));
          container.innerHTML += `<div class="notification-item"><i class="fas fa-info-circle" style="color:var(--ccs-azul);margin-right:6px;"></i>${escapeHtml(msg)}</div>`;
        });
        container.scrollTop = container.scrollHeight;
      }

      if (data.status === 'done' || pct >= 100) {
        clearInterval(poll);
        document.getElementById('genProgressPanel').style.display = 'none';
        loadCashflow();
        notify('success', 'Flujo de caja generado exitosamente');
      } else if (data.status === 'error') {
        clearInterval(poll);
        document.getElementById('genStep').textContent = 'Error: ' + (data.error || 'Error desconocido');
        notify('error', 'Error en la generación: ' + (data.error || ''));
      }
    } catch(e) {
      console.error('[SmartCaja] Error polling generation progress:', e);
    }
  }, 2000);
}

function pollGenerationProgressV1(taskId) {
  const poll = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/generation/${taskId}/progress`);
      const data = await r.json();
      const pct = data.progress || 0;
      document.getElementById('genBar').style.width = `${pct}%`;
      document.getElementById('genPct').textContent = `${Math.round(pct)}%`;
      document.getElementById('genStep').textContent = data.step || 'Procesando...';

      if (data.status === 'completed' || pct >= 100) {
        clearInterval(poll);
        document.getElementById('genProgressPanel').style.display = 'none';
        loadCashflow();
        notify('success', 'Flujo de caja generado');
      }
    } catch(e) {}
  }, 3000);
}

// ============================================================================
// Dashboard
// ============================================================================
async function loadCashflow() {
  try {
    const r = await fetch(`${API}/api/companies/${state.companyId}/cashflow`);
    const data = await r.json();
    state.cashflow = data;
    renderDashboard(data);
  } catch(e) {
    document.getElementById('dashboardStats').innerHTML = `<div class="empty-state" style="grid-column:1/-1;">
      <div class="empty-icon"><i class="fas fa-chart-line"></i></div>
      <div class="empty-title">Sin flujo de caja</div>
      <div class="empty-desc">Completa la entrevista y genera el flujo de caja para ver el dashboard</div>
    </div>`;
  }
}

function renderDashboard(data) {
  const months = data.months || data.cashflow?.months || [];
  if (!months.length) return;

  // Stats
  const totalIncome = months.reduce((s, m) => s + (m.income?.total || m.income_total || 0), 0);
  const totalExpenses = months.reduce((s, m) => s + (m.expenses?.total || m.expenses_total || 0), 0);
  const lastBalance = months[months.length - 1]?.cumulative_balance || 0;
  const netFlow = totalIncome - totalExpenses;

  document.getElementById('dashboardStats').innerHTML = `
    <div class="stat-card"><div class="stat-label">Ingresos Totales</div><div class="stat-value">${formatCurrencyShort(totalIncome)}</div><div class="stat-sub">12 meses</div></div>
    <div class="stat-card green"><div class="stat-label">Flujo Neto</div><div class="stat-value ${netFlow >= 0 ? 'positive' : 'negative'}">${formatCurrencyShort(netFlow)}</div><div class="stat-sub">acumulado</div></div>
    <div class="stat-card blue"><div class="stat-label">Saldo Final</div><div class="stat-value">${formatCurrencyShort(lastBalance)}</div><div class="stat-sub">proyectado</div></div>
    <div class="stat-card celeste"><div class="stat-label">Gastos Totales</div><div class="stat-value">${formatCurrencyShort(totalExpenses)}</div><div class="stat-sub">12 meses</div></div>
  `;

  // Charts
  renderCashflowChart(months);
  renderIncomeExpenseChart(months);
  renderDashboardTable(months);
}

function renderCashflowChart(months) {
  const ctx = document.getElementById('chartCashflow');
  if (state.charts.cashflow) state.charts.cashflow.destroy();

  state.charts.cashflow = new Chart(ctx, {
    type: 'line',
    data: {
      labels: months.map(m => m.label || m.month),
      datasets: [{
        label: 'Saldo Acumulado',
        data: months.map(m => m.cumulative_balance),
        borderColor: '#002558',
        backgroundColor: 'rgba(0,37,88,0.08)',
        fill: true,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: '#00D53A',
        pointBorderColor: '#002558',
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { ticks: { callback: v => formatCurrencyShort(v) } }
      }
    }
  });
}

function renderIncomeExpenseChart(months) {
  const ctx = document.getElementById('chartIncomeExpense');
  if (state.charts.incomeExpense) state.charts.incomeExpense.destroy();

  state.charts.incomeExpense = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months.map(m => m.label || m.month),
      datasets: [
        { label: 'Ingresos', data: months.map(m => m.income?.total || m.income_total || 0), backgroundColor: 'rgba(0,213,58,0.7)', borderRadius: 4 },
        { label: 'Gastos', data: months.map(m => m.expenses?.total || m.expenses_total || 0), backgroundColor: 'rgba(220,38,38,0.6)', borderRadius: 4 },
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { position: 'top' } },
      scales: { y: { ticks: { callback: v => formatCurrencyShort(v) } } }
    }
  });
}

function renderDashboardTable(months) {
  const container = document.getElementById('dashboardTable');
  container.innerHTML = `<table class="data-table">
    <thead><tr><th>Mes</th><th>Ingresos</th><th>Gastos</th><th>Flujo Neto</th><th>Saldo</th></tr></thead>
    <tbody>${months.map(m => {
      const income = m.income?.total || m.income_total || 0;
      const expenses = m.expenses?.total || m.expenses_total || 0;
      const net = m.net_flow || (income - expenses);
      return `<tr>
        <td><strong>${m.label || m.month}</strong></td>
        <td>${formatCurrency(income)}</td>
        <td>${formatCurrency(expenses)}</td>
        <td class="${net >= 0 ? 'positive' : 'negative'}">${formatCurrency(net)}</td>
        <td><strong>${formatCurrency(m.cumulative_balance)}</strong></td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ============================================================================
// Simulación
// ============================================================================
function renderSimulationControls() {
  const container = document.getElementById('simulationControls');
  container.innerHTML = `
    <div class="slider-group"><label><span>Variación de ventas</span><span id="sliderSalesVal">0%</span></label>
      <input type="range" min="-50" max="100" value="0" id="sliderSales" oninput="document.getElementById('sliderSalesVal').textContent=this.value+'%'"></div>
    <p class="slider-hint">Sobre las ventas actuales. +20% = vendes un 20% más que en tu flujo de caja.</p>
    <div class="slider-group"><label><span>Costos variables</span><span id="sliderCostsVal">0%</span></label>
      <input type="range" min="-30" max="50" value="0" id="sliderCosts" oninput="document.getElementById('sliderCostsVal').textContent=this.value+'%'"></div>
    <p class="slider-hint">Costo de producir o comprar lo que vendes, respecto de hoy.</p>
    <div class="slider-group"><label><span>Costos fijos</span><span id="sliderFixedVal">0%</span></label>
      <input type="range" min="-20" max="40" value="0" id="sliderFixed" oninput="document.getElementById('sliderFixedVal').textContent=this.value+'%'"></div>
    <p class="slider-hint">Arriendo, servicios, seguros, etc. 0% = se mantienen.</p>
    <div class="slider-group"><label><span>Inflación anual</span><span id="sliderInflVal">0%</span></label>
      <input type="range" min="0" max="30" value="0" id="sliderInfl" oninput="document.getElementById('sliderInflVal').textContent=this.value+'%'"></div>
    <p class="slider-hint">Alza de precios en 12 meses. 0% = sin inflación extra en la simulación.</p>
    <div class="slider-group"><label><span>Nuevos clientes</span><span id="sliderClientsVal">0%</span></label>
      <input type="range" min="-20" max="50" value="0" id="sliderClients" oninput="document.getElementById('sliderClientsVal').textContent=this.value+'%'"></div>
    <p class="slider-hint">Crecimiento extra de cartera. −20% = se pierde una quinta parte de los clientes.</p>
  `;
}

function resetSliders() {
  ['Sales','Costs','Fixed','Infl','Clients'].forEach(s => {
    const el = document.getElementById(`slider${s}`);
    if (el) { el.value = 0; document.getElementById(`slider${s}Val`).textContent = '0%'; }
  });
}

async function applySimulation() {
  if (!state.companyId) return;

  // Leer valores de sliders y convertir % a multiplicador
  const salesPct = parseFloat(document.getElementById('sliderSales')?.value || 0);
  const costsPct = parseFloat(document.getElementById('sliderCosts')?.value || 0);
  const fixedPct = parseFloat(document.getElementById('sliderFixed')?.value || 0);
  const inflPct = parseFloat(document.getElementById('sliderInfl')?.value || 0);
  const clientsPct = parseFloat(document.getElementById('sliderClients')?.value || 0);

  // Backend V2 custom-scenario espera: nombre, sales_mult, costs_mult, growth_mult, fixed_costs_mult
  const v2Body = {
    nombre: `Simulaci\u00f3n: ventas ${salesPct > 0 ? '+' : ''}${salesPct}%`,
    sales_mult: 1 + (salesPct / 100),
    costs_mult: 1 + (costsPct / 100),
    growth_mult: 1 + (clientsPct / 100),
    fixed_costs_mult: 1 + (fixedPct / 100),
  };

  showGlobalLoading('Simulando...', 'Calculando escenario personalizado');

  try {
    const r = await fetch(`${API}/api/v2/companies/${state.companyId}/custom-scenario`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(v2Body)
    });
    const data = await r.json();
    hideGlobalLoading();

    if (data.detail) {
      // Error del backend
      console.error('[SmartCaja] Simulation error:', data.detail);
      notify('error', 'Error: ' + data.detail);
      return;
    }

    // V2 retorna: { scenario_id, result: { months/meses, caja_final, ... } }
    const months = data.result?.months || data.result?.meses || data.months || [];
    if (months.length > 0) {
      renderSimulationChart(months);
      const cajaFinal = data.result?.caja_final || months[months.length - 1]?.balance || months[months.length - 1]?.cumulative_balance;
      document.getElementById('simImpact').innerHTML = `
        <div class="stat-card green">
          <div class="stat-label">Caja Final Simulada</div>
          <div class="stat-value">${formatCurrencyShort(cajaFinal || 0)}</div>
        </div>
        <div class="stat-card blue">
          <div class="stat-label">Escenario</div>
          <div class="stat-value" style="font-size:14px;">${v2Body.nombre}</div>
        </div>
      `;
      notify('success', 'Simulaci\u00f3n aplicada exitosamente');
    } else {
      notify('error', 'No se obtuvieron datos de simulaci\u00f3n');
    }
  } catch(e) {
    hideGlobalLoading();
    console.error('[SmartCaja] Simulation error:', e);
    // Fallback to V1
    try {
      const v1Params = {
        instruction: `Simular con ventas ${salesPct}%, costos ${costsPct}%`,
        params: {
          sales_change_pct: salesPct,
          costs_change_pct: costsPct,
          fixed_costs_change_pct: fixedPct,
          inflation_annual_pct: inflPct,
        }
      };
      const r = await fetch(`${API}/api/companies/${state.companyId}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(v1Params)
      });
      const data = await r.json();
      if (data.task_id) {
        pollSimulationV1(data.task_id);
      }
    } catch(e2) {
      notify('error', 'Error en simulaci\u00f3n');
    }
  }
}

function pollSimulationV1(taskId) {
  const poll = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/generation/${taskId}/progress`);
      const data = await r.json();
      if (data.status === 'completed') {
        clearInterval(poll);
        hideGlobalLoading();
        if (data.scenario_id) {
          const sr = await fetch(`${API}/api/scenarios/${data.scenario_id}`);
          const scenario = await sr.json();
          if (scenario.months) renderSimulationChart(scenario.months);
        }
        notify('success', 'Simulaci\u00f3n V1 completada');
      }
    } catch(e) {}
  }, 2000);
}

function renderSimulationChart(months) {
  const ctx = document.getElementById('chartSimulation');
  if (state.charts.simulation) state.charts.simulation.destroy();

  // Generar labels de meses si no vienen
  const labels = months.map((m, i) => m.label || m.month || `Mes ${i + 1}`);
  // Soportar tanto 'balance' (V2 scenario) como 'cumulative_balance' (V1)
  const balances = months.map(m => m.balance ?? m.cumulative_balance ?? 0);
  const netFlows = months.map(m => m.net_flow ?? m.netFlow ?? 0);

  state.charts.simulation = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Saldo Acumulado',
          data: balances,
          borderColor: '#3A89DA',
          backgroundColor: 'rgba(58,137,218,0.08)',
          fill: true,
          tension: 0.3,
        },
        {
          label: 'Flujo Neto Mensual',
          data: netFlows,
          borderColor: '#00D53A',
          backgroundColor: 'rgba(0,213,58,0.08)',
          fill: false,
          tension: 0.3,
          borderDash: [5, 5],
        }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true, position: 'top' } },
      scales: { y: { ticks: { callback: v => formatCurrencyShort(v) } } }
    }
  });
}

// ============================================================================
// Monte Carlo
// ============================================================================
async function runMonteCarlo() {
  if (!state.companyId) return;
  showGlobalLoading('Ejecutando Monte Carlo...', 'Simulando miles de escenarios probabilísticos');

  try {
    const iterations = Math.min(5000, Math.max(100, parseInt(document.getElementById('mcIterations')?.value || '1000', 10) || 1000));
    const r = await fetch(`${API}/api/v2/companies/${state.companyId}/monte-carlo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ iterations })
    });
    const data = await r.json();

    if (data.task_id) {
      // Es async — poll para resultados
      state.mcTaskId = data.task_id;
      pollMonteCarloProgress(data.task_id);
    } else if (data.probabilidad_insolvencia_pct !== undefined) {
      // Respuesta directa
      hideGlobalLoading();
      renderMonteCarloResults(data);
      notify('success', 'Simulación Monte Carlo completada');
    } else {
      hideGlobalLoading();
      notify('error', 'Respuesta inesperada del servidor');
    }
  } catch(e) {
    hideGlobalLoading();
    console.error('[SmartCaja] Monte Carlo error:', e);
    notify('error', 'Error ejecutando Monte Carlo');
  }
}

function pollMonteCarloProgress(taskId) {
  const poll = setInterval(async () => {
    try {
      const r = await fetch(`${API}/api/v2/generation/${taskId}/progress`);
      const data = await r.json();

      const pct = data.progress || 0;
      // Update loading text
      const loadingText = document.querySelector('.loading-text');
      if (loadingText) loadingText.textContent = data.step || `Monte Carlo: ${pct}%`;

      if (data.status === 'done') {
        clearInterval(poll);
        hideGlobalLoading();
        // El resultado está en data.result
        if (data.result) {
          renderMonteCarloResults(data.result);
        } else {
          // Cargar desde cashflow guardado
          const cr = await fetch(`${API}/api/companies/${state.companyId}/cashflow`);
          const cashflow = await cr.json();
          if (cashflow.monte_carlo) renderMonteCarloResults(cashflow.monte_carlo);
        }
        notify('success', 'Simulación Monte Carlo completada');
      } else if (data.status === 'error') {
        clearInterval(poll);
        hideGlobalLoading();
        notify('error', 'Error en Monte Carlo: ' + (data.error || ''));
      }
    } catch(e) {
      console.error('[SmartCaja] MC poll error:', e);
    }
  }, 2000);
}

function renderMonteCarloResults(data) {
  const nivel = formatRiskLevel(data.nivel_riesgo?.nivel);
  // Stats
  document.getElementById('mcStats').innerHTML = `
    <div class="stat-card ${data.probabilidad_insolvencia_pct > 20 ? 'red' : 'green'}">
      <div class="stat-label">Prob. Insolvencia</div>
      <div class="stat-value">${data.probabilidad_insolvencia_pct?.toFixed(1) || 0}%</div>
    </div>
    <div class="stat-card blue">
      <div class="stat-label">Nivel de Riesgo</div>
      <div class="stat-value" style="font-size:18px;">${escapeHtml(nivel)}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">VaR 95%</div>
      <div class="stat-value" style="font-size:16px;">${formatCurrencyShort(data.var_95 || 0)}</div>
    </div>
    <div class="stat-card celeste">
      <div class="stat-label">Iteraciones</div>
      <div class="stat-value">${data.iteraciones || 0}</div>
    </div>
  `;

  // Bands chart
  if (data.bandas_mensuales) {
    const ctx = document.getElementById('chartMC');
    if (state.charts.mc) state.charts.mc.destroy();

    const labels = data.bandas_mensuales.map((_, i) => `Mes ${i + 1}`);
    state.charts.mc = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: 'P95', data: data.bandas_mensuales.map(b => b.p95), borderColor: 'rgba(0,213,58,0.7)', fill: false, borderDash: [5,5], pointRadius: 0 },
          { label: 'P75', data: data.bandas_mensuales.map(b => b.p75), borderColor: 'rgba(0,213,58,0.45)', backgroundColor: 'rgba(0,213,58,0.08)', fill: '+1', pointRadius: 0 },
          { label: 'Mediana', data: data.bandas_mensuales.map(b => b.p50), borderColor: '#002558', borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#00D53A' },
          { label: 'P25', data: data.bandas_mensuales.map(b => b.p25), borderColor: 'rgba(206,17,38,0.35)', backgroundColor: 'rgba(206,17,38,0.06)', fill: '+1', pointRadius: 0 },
          { label: 'P5', data: data.bandas_mensuales.map(b => b.p5), borderColor: 'rgba(206,17,38,0.6)', fill: false, borderDash: [5,5], pointRadius: 0 },
        ]
      },
      options: { responsive: true, plugins: { legend: { position: 'bottom' } }, scales: { y: { ticks: { callback: v => formatCurrencyShort(v) } } } }
    });
  }
}

// ============================================================================
// Métricas
// ============================================================================
function formatRiskLevel(nivel) {
  const key = String(nivel || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const map = { bajo: 'Bajo', moderado: 'Moderado', alto: 'Alto', critico: 'Crítico' };
  if (map[key]) return map[key];
  if (!nivel) return 'N/A';
  const s = String(nivel);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

async function loadMetrics() {
  if (!state.companyId) return;
  try {
    const [mr, cr] = await Promise.all([
      fetch(`${API}/api/v2/companies/${state.companyId}/metrics`),
      fetch(`${API}/api/companies/${state.companyId}/cashflow`),
    ]);
    const data = await mr.json();
    let cashflow = null;
    if (cr.ok) cashflow = await cr.json();
    renderMetrics(data, cashflow);
  } catch(e) {
    document.getElementById('metricsContent').innerHTML = '<div class="empty-state"><div class="empty-title">Sin métricas disponibles</div><div class="empty-desc">Genera el flujo de caja primero</div></div>';
  }
}

function cashflowBaselines(cf) {
  const months = cf?.months || cf?.meses || [];
  if (!months.length) return { sales: 0, varCosts: 0, fixed: 0, caja: 0 };
  const n = months.length;
  const sales = months.reduce((s, m) => s + (m.income?.sales || m.income?.total || m.income_total || 0), 0) / n;
  const varCosts = months.reduce((s, m) => s + (m.expenses?.variable_costs || 0), 0) / n;
  const fixed = months.reduce((s, m) => s + (m.expenses?.fixed_costs || 0), 0) / n;
  const last = months[n - 1];
  const caja = last?.cumulative_balance ?? last?.balance ?? 0;
  return { sales, varCosts, fixed, caja };
}

function renderMetrics(data, cashflow) {
  const container = document.getElementById('metricsContent');
  const m = data.metrics || data;
  const base = cashflowBaselines(cashflow || state.cashflow || {});
  state.metricsBaseline = base;

  container.innerHTML = `
    <div class="grid-3" style="margin-bottom:16px;">
      ${renderMetricCard('Caja Mínima', formatCurrency(m.caja_minima?.valor || 0), m.caja_minima?.mes || '', m.caja_minima?.es_negativa ? 'red' : 'green')}
      ${renderMetricCard('Break-even', formatCurrency(m.break_even_operativo?.ventas_mensuales_necesarias || 0), 'ventas/mes necesarias', 'blue')}
      ${renderMetricCard('Runway', m.runway_meses?.meses === Infinity ? '∞' : (m.runway_meses?.meses || 0) + ' meses', m.runway_meses?.mensaje || '', 'celeste')}
    </div>
    <div class="grid-3" style="margin-bottom:16px;">
      ${renderMetricCard('Margen Bruto', (m.margen_bruto_pct?.pct || 0).toFixed(1) + '%', formatCurrency(m.margen_bruto_pct?.absoluto || 0), 'green')}
      ${renderMetricCard('Margen EBITDA', (m.margen_ebitda_pct?.pct || 0).toFixed(1) + '%', formatCurrency(m.margen_ebitda_pct?.absoluto || 0), 'blue')}
      ${renderMetricCard('Financiamiento', m.necesidad_financiamiento?.necesita_financiamiento ? formatCurrency(m.necesidad_financiamiento?.monto || 0) : 'No necesita', m.necesidad_financiamiento?.mensaje || '', m.necesidad_financiamiento?.necesita_financiamiento ? 'yellow' : 'green')}
    </div>
    ${m.resumen_ejecutivo ? `<div class="card"><div class="card-title" style="color:${m.resumen_ejecutivo.color || 'var(--ccs-azul-oscuro)'}"><i class="fas fa-heartbeat"></i> Salud Financiera: ${m.resumen_ejecutivo.salud} (${m.resumen_ejecutivo.score}/100)</div></div>` : ''}
    <div class="card" style="margin-top:16px;">
      <div class="card-title"><i class="fas fa-question-circle" style="color:var(--ccs-azul);"></i> Qué pasaría si…</div>
      <p class="slider-hint">Ingresa un escenario en montos. Calculamos el cambio respecto de tu flujo actual (${formatCurrency(base.sales)} ventas/mes, ${formatCurrency(base.fixed)} costos fijos).</p>
      <div class="form-row">
        <div class="form-group"><label>Ventas mensuales objetivo</label><input type="number" id="whatIfSales" value="${base.sales ? Math.round(base.sales) : ''}" placeholder="Ej: 8000000"></div>
        <div class="form-group"><label>Costo variable (% de ventas)</label><input type="number" id="whatIfVarPct" step="0.1" placeholder="Ej: 40"></div>
        <div class="form-group"><label>Costos fijos mensuales</label><input type="number" id="whatIfFixed" value="${base.fixed ? Math.round(base.fixed) : ''}" placeholder="Ej: 1500000"></div>
      </div>
      <div class="form-actions">
        <button class="btn btn-primary" onclick="runWhatIf()"><i class="fas fa-play"></i> Simular escenario</button>
      </div>
      <div id="whatIfResult"></div>
    </div>
  `;
}

async function runWhatIf() {
  if (!state.companyId) return;
  const base = state.metricsBaseline || { sales: 0, varCosts: 0, fixed: 0 };
  const sales = parseFloat(document.getElementById('whatIfSales')?.value || 0) || 0;
  const varPct = parseFloat(document.getElementById('whatIfVarPct')?.value || 0);
  const fixed = parseFloat(document.getElementById('whatIfFixed')?.value || 0) || 0;
  if (!base.sales) {
    notify('error', 'No hay un flujo de caja base para comparar');
    return;
  }
  const sales_mult = sales > 0 ? sales / base.sales : 1;
  let costs_mult = 1;
  if (!Number.isNaN(varPct) && document.getElementById('whatIfVarPct').value !== '') {
    const currentPct = base.sales ? (base.varCosts / base.sales) * 100 : 40;
    costs_mult = currentPct > 0 ? varPct / currentPct : 1;
  }
  const fixed_costs_mult = base.fixed > 0 && fixed > 0 ? fixed / base.fixed : 1;
  showGlobalLoading('Simulando escenario...', 'Qué pasaría si cambian ventas y costos');
  try {
    const r = await fetch(`${API}/api/v2/companies/${state.companyId}/custom-scenario`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nombre: 'Qué pasaría si',
        sales_mult,
        costs_mult,
        growth_mult: 1,
        fixed_costs_mult,
      })
    });
    const data = await r.json();
    hideGlobalLoading();
    if (data.detail) {
      notify('error', typeof data.detail === 'string' ? data.detail : 'Error en la simulación');
      return;
    }
    const months = data.result?.months || data.result?.meses || [];
    const cajaFinal = data.result?.caja_final || months[months.length - 1]?.balance || months[months.length - 1]?.cumulative_balance || 0;
    const el = document.getElementById('whatIfResult');
    if (el) {
      el.innerHTML = `
        <div class="grid-2" style="margin-top:12px;">
          <div class="stat-card green"><div class="stat-label">Caja final del escenario</div><div class="stat-value">${formatCurrencyShort(cajaFinal)}</div></div>
          <div class="stat-card blue"><div class="stat-label">Caja actual (referencia)</div><div class="stat-value">${formatCurrencyShort(base.caja || 0)}</div></div>
        </div>
        <p class="slider-hint">Ventas ×${sales_mult.toFixed(2)} · costos variables ×${costs_mult.toFixed(2)} · costos fijos ×${fixed_costs_mult.toFixed(2)}</p>
      `;
    }
    notify('success', 'Escenario calculado');
  } catch (e) {
    hideGlobalLoading();
    notify('error', 'No se pudo simular el escenario');
  }
}

function renderMetricCard(label, value, sub, color) {
  return `<div class="stat-card ${color}"><div class="stat-label">${label}</div><div class="stat-value" style="font-size:18px;">${value}</div><div class="stat-sub">${sub}</div></div>`;
}

// ============================================================================
// Versiones y Escenarios
// ============================================================================
async function loadVersions() {
  if (!state.companyId) return;
  try {
    const r = await fetch(`${API}/api/v2/companies/${state.companyId}/cashflow-versions`);
    const data = await r.json();
    renderVersions(data.versions || []);
  } catch(e) {}
}

function renderVersions(versions) {
  const container = document.getElementById('scenariosList');
  if (!versions.length) {
    container.innerHTML = '<div class="empty-state"><div class="empty-title">Sin versiones guardadas</div><div class="empty-desc">Guarda versiones del cashflow para comparar escenarios</div></div>';
    return;
  }
  container.innerHTML = versions.map(v => `
    <div class="card" style="margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div><strong>${v.name || v.id}</strong><br><span style="font-size:11px;color:var(--text-muted);">${v.created_at || ''}</span></div>
        <button class="btn btn-sm btn-secondary" onclick="restoreVersion('${v.id}')"><i class="fas fa-undo"></i> Restaurar</button>
      </div>
    </div>
  `).join('');
}

async function saveVersion() {
  if (!state.companyId) return;
  const name = prompt('Nombre de la versión:');
  if (!name) return;
  try {
    await fetch(`${API}/api/v2/companies/${state.companyId}/cashflow-versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    notify('success', 'Versión guardada');
    loadVersions();
  } catch(e) { notify('error', 'Error guardando versión'); }
}

async function restoreVersion(versionId) {
  if (!state.companyId) return;
  try {
    await fetch(`${API}/api/v2/companies/${state.companyId}/cashflow-versions/${versionId}/restore`, { method: 'PUT' });
    notify('success', 'Versión restaurada');
    loadCashflow();
  } catch(e) { notify('error', 'Error restaurando versión'); }
}

// ============================================================================
// Exportación
// ============================================================================
async function exportCSV() {
  if (!state.companyId) return;
  try {
    const r = await fetch(`${API}/api/companies/${state.companyId}/export/csv`);
    const blob = await r.blob();
    downloadBlob(blob, `cashflow_${state.companyName}.csv`);
  } catch(e) { notify('error', 'Error exportando CSV'); }
}

async function exportExcel() {
  if (!state.companyId) return;
  try {
    const r = await fetch(`${API}/api/companies/${state.companyId}/export/excel`);
    const blob = await r.blob();
    downloadBlob(blob, `cashflow_${state.companyName}.xlsx`);
  } catch(e) { notify('error', 'Error exportando Excel'); }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

// ============================================================================
// Settings
// ============================================================================
async function loadSettings() {
  try {
    const [agentsResp, modelsResp, statusResp] = await Promise.all([
      fetch(`${API}/api/agents`),
      fetch(`${API}/api/models/available`),
      fetch(`${API}/api/health`).catch(() => ({ json: () => ({ status: 'unknown' }) }))
    ]);
    const agentsData = await agentsResp.json();
    const modelsData = await modelsResp.json();
    const healthData = await statusResp.json();

    const models = modelsData.models || [];
    const agents = agentsData.agents || [];

    document.getElementById('settingsContent').innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:16px; margin-top:12px;">
        <!-- Acerca de -->
        <div class="card" style="padding:16px;">
          <h4 style="margin:0 0 12px; font-size:13px; color:var(--ccs-azul-oscuro);"><i class="fas fa-info-circle"></i> Acerca de</h4>
          <img src="logo-ccs.png" alt="Cámara de Comercio de Santiago" style="height:48px;width:auto;max-width:220px;object-fit:contain;margin:0 0 12px;">
          <div style="font-size:12px; line-height:1.8;">
            <div><strong>SmartCaja</strong> 2.0.0</div>
            <div>Cámara de Comercio de Santiago (CCS)</div>
          </div>
        </div>

        <!-- Estado del Sistema -->
        <div class="card" style="padding:16px;">
          <h4 style="margin:0 0 12px; font-size:13px; color:var(--ccs-azul-oscuro);"><i class="fas fa-server"></i> Estado del Sistema</h4>
          <div style="font-size:12px; line-height:2;">
            <div><strong>Ollama:</strong> <span style="color:${healthData.ollama ? 'var(--ccs-verde)' : '#EF4444'};">${healthData.ollama ? '\u2713 Conectado' : '\u2717 Desconectado'}</span></div>
            <div><strong>Modelos disponibles:</strong> ${models.length}</div>
            <div><strong>Agentes configurados:</strong> ${agents.length}</div>
            <div><strong>Versi\u00f3n:</strong> 2.0.0</div>
          </div>
        </div>

        <!-- Modelos Instalados -->
        <div class="card" style="padding:16px;">
          <h4 style="margin:0 0 12px; font-size:13px; color:var(--ccs-azul-oscuro);"><i class="fas fa-brain"></i> Modelos Instalados</h4>
          <div style="display:flex; flex-wrap:wrap; gap:6px;">
            ${models.length > 0 ? models.map(m => `
              <span style="padding:4px 10px; background:rgba(0,37,88,0.06); border:1px solid rgba(0,37,88,0.15); border-radius:12px; font-size:11px; color:var(--ccs-azul);">${escapeHtml(m)}</span>
            `).join('') : '<span style="color:var(--text-muted); font-size:12px;">No hay modelos instalados</span>'}
          </div>
        </div>

        <!-- Acciones R\u00e1pidas -->
        <div class="card" style="padding:16px;">
          <h4 style="margin:0 0 12px; font-size:13px; color:var(--ccs-azul-oscuro);"><i class="fas fa-tools"></i> Acciones R\u00e1pidas</h4>
          <div style="display:flex; flex-direction:column; gap:8px;">
            <button class="btn btn-sm" style="background:var(--ccs-azul); color:#fff; font-size:11px; padding:8px 12px; text-align:left;" onclick="resetTokenStats()">
              <i class="fas fa-redo"></i> Resetear estad\u00edsticas de tokens
            </button>
            <button class="btn btn-sm" style="background:rgba(0,37,88,0.08); color:var(--ccs-azul); font-size:11px; padding:8px 12px; text-align:left;" onclick="navigateTo('agents')">
              <i class="fas fa-robot"></i> Configurar agentes y prompts
            </button>
            <button class="btn btn-sm" style="background:rgba(0,37,88,0.08); color:var(--ccs-azul); font-size:11px; padding:8px 12px; text-align:left;" onclick="navigateTo('tokens')">
              <i class="fas fa-chart-bar"></i> Ver uso de tokens
            </button>
          </div>
        </div>

        <!-- Resumen de Agentes -->
        <div class="card" style="padding:16px;">
          <h4 style="margin:0 0 12px; font-size:13px; color:var(--ccs-azul-oscuro);"><i class="fas fa-users-cog"></i> Agentes Activos</h4>
          ${agents.map(a => `
            <div style="display:flex; align-items:center; gap:10px; padding:6px 0; border-bottom:1px solid var(--border);">
              <i class="fas fa-robot" style="color:var(--ccs-azul); font-size:12px;"></i>
              <div style="flex:1;">
                <div style="font-size:12px; font-weight:600;">${escapeHtml(a.name || a.id)}</div>
                <div style="font-size:10px; color:var(--text-muted);">${escapeHtml(a.model_label || 'Modelo del perfil')}</div>
              </div>
              <span style="font-size:10px; padding:2px 6px; background:rgba(0,213,58,0.1); color:var(--ccs-verde); border-radius:8px;">T:${a.temperature || 0.7}</span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Secci\u00f3n Exportar / Importar -->
      <div style="margin-top:24px; display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:16px;">
        <!-- Exportar -->
        <div class="card" style="padding:20px;">
          <h4 style="margin:0 0 8px; font-size:14px; color:var(--ccs-azul-oscuro);"><i class="fas fa-file-export"></i> Exportar datos</h4>
          <p style="margin:0 0 16px; font-size:12px; color:var(--text-muted);">Descarga un archivo con todas tus empresas, entrevistas, cashflows, simulaciones, agentes y configuraci\u00f3n. El archivo incluye un hash SHA-256 que impide su modificaci\u00f3n.</p>
          <div id="exportInfo" style="margin-bottom:12px; padding:10px; background:rgba(0,37,88,0.04); border-radius:8px; border:1px solid var(--border); font-size:12px;"></div>
          <button class="btn btn-sm" style="background:var(--ccs-azul); color:#fff; font-size:12px; padding:10px 16px;" onclick="exportAllData()" id="btnExportAll">
            <i class="fas fa-download"></i> Descargar archivo de exportaci\u00f3n
          </button>
        </div>

        <!-- Importar -->
        <div class="card" style="padding:20px;">
          <h4 style="margin:0 0 8px; font-size:14px; color:var(--ccs-azul-oscuro);"><i class="fas fa-file-import"></i> Importar datos</h4>
          <p style="margin:0 0 16px; font-size:12px; color:var(--text-muted);">Sube un archivo de exportaci\u00f3n generado en otra m\u00e1quina. Se verificar\u00e1 la integridad del archivo antes de importar. Los datos existentes no se sobreescriben.</p>
          <div id="importDropZone" style="border:2px dashed var(--border); border-radius:12px; padding:24px; text-align:center; cursor:pointer; transition:all 0.2s;" onclick="document.getElementById('importFileInput').click()">
            <div style="font-size:28px; margin-bottom:6px;"><i class="fas fa-cloud-upload-alt" style="color:var(--ccs-azul);"></i></div>
            <div style="font-size:13px; font-weight:500; color:var(--text-primary);">Arrastra el archivo aqu\u00ed o haz click para seleccionar</div>
            <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Solo archivos .json generados por la exportaci\u00f3n</div>
          </div>
          <input type="file" id="importFileInput" accept=".json" style="display:none" onchange="handleImportFileSelect(this)" />
          <div id="importStatus" style="display:none; margin-top:12px; padding:10px; border-radius:8px; font-size:12px;"></div>
          <button class="btn btn-sm" style="background:var(--ccs-verde); color:#fff; font-size:12px; padding:10px 16px; margin-top:12px; display:none;" onclick="executeImportData()" id="btnImportAll">
            <i class="fas fa-upload"></i> Importar datos verificados
          </button>
        </div>
      </div>
    `;

    // Cargar info de exportaci\u00f3n
    loadExportInfo();
  } catch(e) {
    console.error('[SmartCaja] Error loading settings:', e);
    document.getElementById('settingsContent').innerHTML = '<p style="color:var(--text-muted);">Error cargando configuraci\u00f3n: ' + escapeHtml(e.message) + '</p>';
  }
}

async function loadExportInfo() {
  try {
    const r = await fetch(`${API}/api/export/info`);
    const info = await r.json();
    const el = document.getElementById('exportInfo');
    if (el) {
      el.innerHTML = `<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(80px,1fr)); gap:6px;">
        <div><strong>${info.companies || 0}</strong> empresas</div>
        <div><strong>${info.sessions || 0}</strong> sesiones</div>
        <div><strong>${info.scenarios || 0}</strong> escenarios</div>
        <div><strong>${info.prompts || 0}</strong> prompts</div>
        <div><strong>${info.skills || 0}</strong> skills</div>
      </div>`;
    }
  } catch(e) {
    const el = document.getElementById('exportInfo');
    if (el) el.innerHTML = '<span style="color:var(--text-muted);">No se pudo cargar info</span>';
  }
}

var _importFileData = null;

async function exportAllData() {
  const btn = document.getElementById('btnExportAll');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generando...'; }
  try {
    const r = await fetch(`${API}/api/export`);
    if (!r.ok) throw new Error('Error al exportar');
    const disposition = r.headers.get('content-disposition') || '';
    let filename = 'smartcaja_export.json';
    const match = disposition.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];
    const blob = await r.blob();
    downloadBlob(blob, filename);
    notify('success', 'Exportaci\u00f3n descargada exitosamente');
  } catch(e) {
    notify('error', 'Error al exportar: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-download"></i> Descargar archivo de exportaci\u00f3n'; }
  }
}

function handleImportFileSelect(input) {
  if (input.files.length > 0) {
    _processImportFile(input.files[0]);
  }
}

function _processImportFile(file) {
  const statusEl = document.getElementById('importStatus');
  const btnImport = document.getElementById('btnImportAll');
  if (!file.name.endsWith('.json')) {
    statusEl.style.display = 'block';
    statusEl.style.background = '#fef2f2';
    statusEl.style.color = '#dc2626';
    statusEl.innerHTML = '<i class="fas fa-times-circle"></i> El archivo debe ser un .json generado por la exportaci\u00f3n.';
    btnImport.style.display = 'none';
    return;
  }
  statusEl.style.display = 'block';
  statusEl.style.background = 'rgba(0,37,88,0.04)';
  statusEl.style.color = 'var(--text-primary)';
  statusEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verificando archivo...';
  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const content = JSON.parse(e.target.result);
      if (!content.integrity_hash || !content.data) {
        statusEl.style.background = '#fef2f2';
        statusEl.style.color = '#dc2626';
        statusEl.innerHTML = '<i class="fas fa-times-circle"></i> Archivo inv\u00e1lido. No tiene la estructura de exportaci\u00f3n esperada.';
        btnImport.style.display = 'none';
        return;
      }
      if (content.data.export_version !== '1.0') {
        statusEl.style.background = '#fef2f2';
        statusEl.style.color = '#dc2626';
        statusEl.innerHTML = '<i class="fas fa-times-circle"></i> Versi\u00f3n no soportada: ' + escapeHtml(content.data.export_version || 'desconocida');
        btnImport.style.display = 'none';
        return;
      }
      const data = content.data;
      const companyCount = (data.companies || []).length;
      const sessionCount = Object.keys(data.sessions || {}).length;
      const promptCount = Object.keys(data.prompts || {}).length;
      statusEl.style.background = '#f0fdf4';
      statusEl.style.color = '#166534';
      statusEl.innerHTML = '<i class="fas fa-check-circle"></i> <strong>Archivo v\u00e1lido</strong> &mdash; Exportado el ' + escapeHtml(data.exported_at || 'fecha desconocida') + '<br>' +
        '<div style="margin-top:6px;display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:6px;font-size:11px">' +
        '<div><strong>' + companyCount + '</strong> empresas</div>' +
        '<div><strong>' + sessionCount + '</strong> sesiones</div>' +
        '<div><strong>' + promptCount + '</strong> prompts</div>' +
        '</div>' +
        '<div style="margin-top:6px;font-size:10px;color:#166534"><i class="fas fa-lock"></i> Hash SHA-256: ' + escapeHtml(content.integrity_hash.substring(0, 16)) + '...</div>';
      _importFileData = file;
      btnImport.style.display = 'inline-flex';
    } catch(parseErr) {
      statusEl.style.background = '#fef2f2';
      statusEl.style.color = '#dc2626';
      statusEl.innerHTML = '<i class="fas fa-times-circle"></i> Error al leer: ' + escapeHtml(parseErr.message);
      btnImport.style.display = 'none';
    }
  };
  reader.readAsText(file);
}

async function executeImportData() {
  if (!_importFileData) { notify('error', 'No hay archivo seleccionado'); return; }
  if (!confirm('\u00bfEst\u00e1s seguro de importar estos datos?\n\nSe verificar\u00e1 la integridad. Los datos existentes NO se sobreescribir\u00e1n.')) return;
  const btn = document.getElementById('btnImportAll');
  const statusEl = document.getElementById('importStatus');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Importando...';
  const formData = new FormData();
  formData.append('file', _importFileData);
  try {
    const r = await fetch(`${API}/api/import`, { method: 'POST', body: formData });
    if (!r.ok) { const err = await r.json(); throw new Error(err.detail || 'Error desconocido'); }
    const result = await r.json();
    const stats = result.stats || {};
    statusEl.style.background = '#f0fdf4';
    statusEl.style.color = '#166534';
    statusEl.innerHTML = '<i class="fas fa-check-circle"></i> <strong>Importaci\u00f3n exitosa</strong><br>' +
      '<div style="margin-top:6px;font-size:11px">' +
      (stats.companies > 0 ? stats.companies + ' empresas importadas<br>' : '') +
      (stats.sessions > 0 ? stats.sessions + ' sesiones importadas<br>' : '') +
      (stats.prompts > 0 ? stats.prompts + ' prompts importados<br>' : '') +
      (stats.skills > 0 ? stats.skills + ' skills importados<br>' : '') +
      (stats.skipped_existing > 0 ? stats.skipped_existing + ' elementos omitidos (ya exist\u00edan)<br>' : '') +
      '</div>';
    notify('success', 'Importaci\u00f3n completada');
    _importFileData = null;
    btn.style.display = 'none';
    await loadCompanies();
  } catch(e) {
    statusEl.style.background = '#fef2f2';
    statusEl.style.color = '#dc2626';
    statusEl.innerHTML = '<i class="fas fa-times-circle"></i> <strong>Error</strong>: ' + escapeHtml(e.message);
    notify('error', 'Error al importar: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-upload"></i> Importar datos verificados';
  }
}

// ============================================================================
// Utilidades
// ============================================================================
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

function showGlobalLoading(label, sublabel) {
  document.getElementById('globalLoadingLabel').textContent = label || 'Procesando...';
  document.getElementById('globalLoadingSublabel').textContent = sublabel || '';
  document.getElementById('globalLoadingOverlay').classList.add('active');
}
function hideGlobalLoading() { document.getElementById('globalLoadingOverlay').classList.remove('active'); }

function notify(type, message) {
  const area = document.getElementById('notificationArea');
  const el = document.createElement('div');
  el.className = `notification ${type}`;
  el.innerHTML = `<span>${message}</span>`;
  area.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function formatCurrency(value) {
  if (value === null || value === undefined) return '$0';
  return '$' + Math.round(value).toLocaleString('es-CL');
}

function formatCurrencyShort(value) {
  if (value === null || value === undefined) return '$0';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e9) return sign + '$' + (abs / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6) return sign + '$' + (abs / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return sign + '$' + (abs / 1e3).toFixed(0) + 'K';
  return sign + '$' + Math.round(abs).toLocaleString('es-CL');
}

// ============================================================================
// Agentes & Skills (estilo brand-assistant)
// ============================================================================
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadAgents() {
  const grid = document.getElementById('agentsGrid');
  try {
    const [ar, sr, mr] = await Promise.all([
      fetch(`${API}/api/agents`),
      fetch(`${API}/api/skills/available`),
      fetch(`${API}/api/models/available`),
    ]);
    const data = await ar.json();
    const skillsData = sr.ok ? await sr.json() : { skills: [], max_per_agent: 8 };
    const modelsData = mr.ok ? await mr.json() : { models: [] };
    state.availableSkills = skillsData.skills || [];
    state.maxAgentSkills = skillsData.max_per_agent || 8;
    state.installedModels = modelsData.models || [];
    const agents = data.agents || [];

    let html = '';
    html += `<div class="card" style="grid-column:1/-1; padding:16px; margin-bottom:4px;">
      <p style="font-size:12px; color:var(--text-muted); line-height:1.5; margin:0;">
        <strong style="color:var(--ccs-azul-oscuro);">Cómo se configura un agente.</strong>
        El <em>system prompt</em> es la instrucción permanente del agente (rol y reglas).
        La <em>temperatura</em> controla qué tan creativo es: 0 es más predecible, 1 más variado; para finanzas conviene 0.1–0.7.
        Un <em>skill</em> es un bloque de instrucciones extra (máx. ${state.maxAgentSkills} por agente).
        El modelo lo fija el perfil de RAM de este equipo: se listan los instalados solo como referencia.
      </p>
    </div>`;

    for (const agent of agents) {
      const agentId = agent.id;
      const skills = agent.skills || [];
      const skillContents = agent.skill_contents || {};
      const roleLabel = agent.role_label || ({ interviewer: 'Entrevistador', analyst: 'Analista', simulator: 'Simulador', extractor: 'Extractor' }[agent.role] || 'Agente');
      const extraModels = (state.installedModels || []).filter(Boolean);

      html += `<div class="card" style="padding:20px;" id="agent-card-${agentId}">`;
      html += `<div style="display:flex; align-items:flex-start; justify-content:space-between; margin-bottom:16px;">`;
      html += `<div style="display:flex; align-items:center; gap:12px;">`;
      html += `<div style="width:40px; height:40px; border-radius:50%; background:var(--ccs-azul); display:flex; align-items:center; justify-content:center;"><i class="fas fa-robot" style="color:#fff; font-size:16px;"></i></div>`;
      html += `<div><div style="font-weight:700; font-size:14px; color:var(--ccs-azul-oscuro);">${escapeHtml(agent.name || agentId)}</div>`;
      html += `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(agent.description || '')}</div></div>`;
      html += `</div>`;
      html += `<span style="padding:3px 10px; background:rgba(0,213,58,0.1); color:var(--ccs-verde); border-radius:12px; font-size:10px; font-weight:600;">${escapeHtml(roleLabel)}</span>`;
      html += `</div>`;

      html += `<div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">`;
      html += `<div class="form-group" style="flex:1; min-width:180px;"><label style="font-size:11px;">Modelo</label>`;
      html += `<select id="agent-model-${agentId}" disabled style="font-size:12px; opacity:0.85;">`;
      html += `<option selected>Modelo del perfil</option>`;
      extraModels.forEach(m => {
        html += `<option disabled>${escapeHtml(m)} (no disponible en este perfil)</option>`;
      });
      html += `</select>`;
      html += `<div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Bloqueado al modelo del perfil de RAM. Visión: ${escapeHtml(agent.vision || 'no disponible en este perfil')}</div></div>`;
      html += `<div class="form-group" style="width:120px;"><label style="font-size:11px;">Temperatura</label>`;
      html += `<input type="number" id="agent-temp-${agentId}" value="${agent.temperature || 0.7}" min="0" max="2" step="0.1" style="font-size:12px;">`;
      html += `<div style="font-size:10px; color:var(--text-muted); margin-top:4px;">0 = preciso · 1 = creativo</div></div>`;
      html += `</div>`;

      html += `<div style="margin-bottom:16px;">`;
      html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">`;
      html += `<label style="margin:0; font-size:11px; font-weight:600;">System Prompt</label>`;
      html += `<button class="btn btn-sm" style="background:var(--ccs-azul); color:#fff; font-size:11px; padding:4px 12px;" onclick="saveAgentPrompt('${agentId}')">Guardar</button>`;
      html += `</div>`;
      html += `<p class="slider-hint" style="margin-top:0;">Instrucción permanente: define el rol, el tono y lo que el agente no debe hacer.</p>`;
      html += `<textarea id="agent-prompt-${agentId}" style="min-height:180px; font-size:11px; font-family:monospace; line-height:1.5; padding:10px; resize:vertical;">${escapeHtml(agent.system_prompt || '')}</textarea>`;
      html += `</div>`;

      const maxSkills = agent.max_skills || state.maxAgentSkills || 8;
      html += `<div><label style="margin-bottom:8px; display:block; font-size:11px; font-weight:600;">Skills (${skills.length}/${maxSkills})</label>`;
      html += `<p class="slider-hint" style="margin-top:0;">Un skill es un módulo de conocimiento (p. ej. estacionalidad). Máximo ${maxSkills} para no saturar el contexto.</p>`;
      html += `<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px;">`;
      for (const sname of skills) {
        html += `<span style="display:inline-flex; align-items:center; gap:4px;">`;
        html += `<button class="btn btn-sm" style="background:rgba(0,37,88,0.08); color:var(--ccs-azul); border:1px solid rgba(0,37,88,0.2); font-size:10px;" onclick="toggleSkillEditor('${agentId}','${sname}')">&#9998; ${escapeHtml(sname)}</button>`;
        html += `<button class="btn btn-sm" title="Quitar skill" style="font-size:10px; padding:3px 8px;" onclick="removeAgentSkill('${agentId}', ${JSON.stringify(sname)}, ${JSON.stringify(skills)})">&times;</button>`;
        html += `</span>`;
      }
      html += `</div>`;

      const unused = (state.availableSkills || []).filter(s => !skills.includes(s));
      if (skills.length < maxSkills) {
        html += `<div style="display:flex; gap:8px; align-items:flex-end; margin-bottom:12px;">`;
        html += `<div class="form-group" style="flex:1; margin:0;"><label>Añadir skill</label><select id="add-skill-${agentId}">`;
        html += `<option value="">Seleccionar...</option>`;
        unused.forEach(s => { html += `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`; });
        html += `</select></div>`;
        html += `<button class="btn btn-primary btn-sm" onclick="addAgentSkill('${agentId}', ${JSON.stringify(skills)})">Añadir</button>`;
        html += `</div>`;
      } else {
        html += `<p class="slider-hint">Llegaste al máximo. Quita un skill para añadir otro.</p>`;
      }

      for (const skillName of skills) {
        const skillContent = skillContents[skillName] || '';
        html += `<div id="skillEditor_${agentId}_${skillName}" style="display:none; margin-bottom:12px; padding:12px; background:var(--bg-base); border-radius:8px; border:1px solid var(--border);">`;
        html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">`;
        html += `<div style="font-size:11px; font-weight:700; color:var(--ccs-azul);">${escapeHtml(skillName)}.md</div>`;
        html += `<div style="display:flex; gap:6px;">`;
        html += `<button class="btn btn-sm" style="background:var(--ccs-azul); color:#fff; font-size:10px; padding:3px 10px;" onclick="saveSkillContent('${agentId}','${skillName}')">Guardar</button>`;
        html += `<button class="btn btn-sm" style="font-size:10px; padding:3px 10px;" onclick="toggleSkillEditor('${agentId}','${skillName}')">Cerrar</button>`;
        html += `</div></div>`;
        html += `<textarea id="skill_${agentId}_${skillName}" style="min-height:200px; font-size:11px; font-family:monospace; line-height:1.5; padding:8px;" placeholder="Escribe el contenido del skill...">${escapeHtml(skillContent)}</textarea>`;
        html += `</div>`;
      }
      html += `</div></div>`;
    }

    grid.innerHTML = html;
  } catch(e) {
    console.error('[SmartCaja] Error loading agents:', e);
    grid.innerHTML = '<div class="card" style="padding:20px;"><p style="color:var(--text-muted);">Error cargando agentes: ' + escapeHtml(e.message) + '</p></div>';
  }
}

async function addAgentSkill(agentId, currentSkills) {
  const sel = document.getElementById(`add-skill-${agentId}`);
  const name = sel ? sel.value : '';
  if (!name) { notify('error', 'Elige un skill'); return; }
  const next = [...(currentSkills || [])];
  if (!next.includes(name)) next.push(name);
  if (next.length > (state.maxAgentSkills || 8)) {
    notify('error', 'Máximo ' + (state.maxAgentSkills || 8) + ' skills por agente');
    return;
  }
  await saveAgentSkills(agentId, next);
}

async function removeAgentSkill(agentId, skillName, currentSkills) {
  const next = (currentSkills || []).filter(s => s !== skillName);
  await saveAgentSkills(agentId, next);
}

async function saveAgentSkills(agentId, skills) {
  try {
    const resp = await fetch(`${API}/api/agents/${agentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skills })
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      notify('error', err.detail || 'No se pudo actualizar skills');
      return;
    }
    notify('success', 'Skills actualizados');
    loadAgents();
  } catch (e) {
    notify('error', 'Error: ' + e.message);
  }
}

function toggleSkillEditor(agentId, skillName) {
  const el = document.getElementById(`skillEditor_${agentId}_${skillName}`);
  if (!el) return;
  el.style.display = (el.style.display === 'none' || el.style.display === '') ? 'block' : 'none';
}

async function saveSkillContent(agentId, skillName) {
  const el = document.getElementById(`skill_${agentId}_${skillName}`);
  if (!el) return;
  try {
    const resp = await fetch(`${API}/api/agents/${agentId}/skills/${skillName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: el.value })
    });
    if (resp.ok) {
      notify('success', `Skill "${skillName}" guardado correctamente`);
    } else {
      notify('error', 'Error guardando skill');
    }
  } catch(e) {
    notify('error', 'Error: ' + e.message);
  }
}

async function saveAgentPrompt(agentId) {
  const promptEl = document.getElementById(`agent-prompt-${agentId}`);
  const tempEl = document.getElementById(`agent-temp-${agentId}`);
  if (!promptEl) return;

  const payload = { system_prompt: promptEl.value };
  if (tempEl) payload.temperature = parseFloat(tempEl.value) || 0.7;

  try {
    const resp = await fetch(`${API}/api/agents/${agentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    if (data.pull_status && data.pull_status.status === 'queued') {
      notify('info', 'El modelo lo elige el perfil de RAM; no se descarga otro.');
    } else {
      notify('success', `Agente "${agentId}" actualizado correctamente`);
    }
  } catch(e) {
    notify('error', 'Error: ' + e.message);
  }
}

// Legacy function for backward compat
async function saveAgents() {
  // Now each agent saves individually via saveAgentPrompt
  notify('info', 'Usa el bot\u00f3n "Guardar" de cada agente para guardar cambios individuales.');
}

// ============================================================================
// Uso de Tokens y Auditoría (estilo brand-assistant)
// ============================================================================
function _formatNumber(n) {
  if (!n && n !== 0) return '0';
  return Number(n).toLocaleString('es-CL');
}

function _formatLatency(ms) {
  if (!ms) return '-';
  if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
  return ms + 'ms';
}

async function loadTokenStats() {
  try {
    // Cargar tanto token-usage como audit
    const [tokenResp, auditResp] = await Promise.all([
      fetch(`${API}/api/token-usage`),
      fetch(`${API}/api/audit`)
    ]);
    const tokenData = await tokenResp.json();
    const auditData = await auditResp.json();

    const stats = tokenData.stats || { total_tokens: 0, total_requests: 0, by_agent: {} };
    const entries = auditData.entries || [];

    // Calcular ahorro estimado (costo OpenAI GPT-4 vs local)
    const costPerToken = 0.00003; // USD por token GPT-4
    const estimatedSaving = stats.total_tokens * costPerToken;

    // Stats cards
    document.getElementById('tokenStats').innerHTML = `
      <div class="stat-card blue">
        <div class="stat-label">Total Tokens</div>
        <div class="stat-value">${_formatNumber(stats.total_tokens)}</div>
      </div>
      <div class="stat-card green">
        <div class="stat-label">Solicitudes</div>
        <div class="stat-value">${_formatNumber(stats.total_requests)}</div>
      </div>
      <div class="stat-card celeste">
        <div class="stat-label">Promedio/Solicitud</div>
        <div class="stat-value">${stats.total_requests ? _formatNumber(Math.round(stats.total_tokens / stats.total_requests)) : '0'}</div>
      </div>
      <div class="stat-card" style="border-left:3px solid var(--ccs-verde);">
        <div class="stat-label">Ahorro estimado (vs GPT-4)</div>
        <div class="stat-value" style="color:var(--ccs-verde);">$${estimatedSaving.toFixed(2)} USD</div>
      </div>
    `;

    // Chart by agent
    const byAgent = stats.by_agent || {};
    const agentNames = Object.keys(byAgent);
    const agentTokens = agentNames.map(a => byAgent[a]?.tokens || 0);

    const ctx = document.getElementById('chartTokens');
    if (state.charts.tokens) state.charts.tokens.destroy();
    if (agentNames.length > 0) {
      state.charts.tokens = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: agentNames.map(n => n.replace(/_/g, ' ')),
          datasets: [{
            label: 'Tokens usados',
            data: agentTokens,
            backgroundColor: ['#002558', '#00D53A', '#3A89DA', '#3A89DA', '#00D53A', '#8B5CF6'],
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { callback: v => _formatNumber(v) } } }
        }
      });
    }

    // Audit table (estilo brand-assistant)
    let tableHtml = '';
    if (entries.length > 0) {
      tableHtml = `
        <div style="margin-top:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h4 style="margin:0; font-size:14px; color:var(--ccs-azul-oscuro);"><i class="fas fa-list"></i> Registro de Actividad</h4>
            <span style="font-size:11px; color:var(--text-muted);">${entries.length} entradas</span>
          </div>
          <div style="overflow-x:auto; border:1px solid var(--border); border-radius:8px;">
            <table style="width:100%; border-collapse:collapse; font-size:11px;">
              <thead>
                <tr style="background:var(--bg-base); border-bottom:1px solid var(--border);">
                  <th style="padding:8px 10px; text-align:left; font-weight:600;">Hora</th>
                  <th style="padding:8px 10px; text-align:left; font-weight:600;">Agente</th>
                  <th style="padding:8px 10px; text-align:left; font-weight:600;">Tarea</th>
                  <th style="padding:8px 10px; text-align:left; font-weight:600;">Modelo</th>
                  <th style="padding:8px 10px; text-align:right; font-weight:600;">Latencia</th>
                  <th style="padding:8px 10px; text-align:center; font-weight:600;">Estado</th>
                </tr>
              </thead>
              <tbody>
                ${entries.slice(0, 50).map(e => `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:6px 10px; color:var(--text-muted);">${e.timestamp ? new Date(e.timestamp).toLocaleString('es-CL', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '-'}</td>
                    <td style="padding:6px 10px; font-weight:600; color:var(--ccs-azul);">${escapeHtml((e.agent_id || '').replace(/_/g, ' '))}</td>
                    <td style="padding:6px 10px;">${escapeHtml(e.task || '')}</td>
                    <td style="padding:6px 10px; color:var(--text-muted);">${escapeHtml(e.model || '')}</td>
                    <td style="padding:6px 10px; text-align:right;">${_formatLatency(e.latency_ms)}</td>
                    <td style="padding:6px 10px; text-align:center;">${e.success ? '<span style="color:var(--ccs-verde);">\u2713</span>' : '<span style="color:#EF4444;">\u2717</span>'}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;
    } else {
      tableHtml = '<div style="padding:20px; text-align:center; color:var(--text-muted); font-size:13px; margin-top:16px;">No hay actividad registrada a\u00fan. Las llamadas a los agentes aparecer\u00e1n aqu\u00ed.</div>';
    }
    document.getElementById('tokenSessionsList').innerHTML = tableHtml;

  } catch(e) {
    console.error('[SmartCaja] Error loading token stats:', e);
    document.getElementById('tokenStats').innerHTML = `
      <div class="stat-card"><div class="stat-label">Total Tokens</div><div class="stat-value">0</div></div>
      <div class="stat-card"><div class="stat-label">Solicitudes</div><div class="stat-value">0</div></div>
      <div class="stat-card"><div class="stat-label">Promedio</div><div class="stat-value">0</div></div>
      <div class="stat-card"><div class="stat-label">Ahorro</div><div class="stat-value">$0</div></div>
    `;
  }
}

async function resetTokenStats() {
  if (!confirm('\u00bfResetear estad\u00edsticas de tokens y auditor\u00eda?')) return;
  try {
    await fetch(`${API}/api/token-usage`, { method: 'DELETE' });
    notify('success', 'Estad\u00edsticas reseteadas');
    loadTokenStats();
  } catch(e) {
    notify('error', 'Error reseteando estad\u00edsticas');
  }
}
