"use strict";

/* ── PROGRESS TRACKER KEY ── */
const PROGRESS_KEY = "costpilot_progress_v1";

/* ── FORMAT ── */
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const money = (v) => inr.format(Math.round(Number(v) || 0));

/* ── STATE ── */
const state = {
  view: "home",
  type: "travel",
  lastPayload: null,
  lastResult: null,
  selectedPlanId: null,
  chosenPlan: null,
  journeyStage: 0,
  comparePlanIds: [],   // up to 2 plans selected for side-by-side
  compareMode: false,
};

/* ── BOOKING LINKS — context-aware deep links ── */
function getBookingLinks(type, bucketLabel, goal, bucketAmount) {
  const c = state.lastResult?.constraints || {};
  const origin = (c.origin || "Delhi").toLowerCase().replace(/\s+/g, "-");
  const rawTitle = state.lastResult?.title || "";
  // Extract destination from title e.g. "Manali trip from Delhi" → "Manali"
  const destMatch = rawTitle.match(/^([^(]+?)(?:\s+trip|\s+from|\s+purchase)?(?:\s+from\s+\S+)?$/i);
  const dest = (destMatch?.[1] || "").trim().toLowerCase().replace(/\s+/g, "-") || origin;
  const goalEnc = encodeURIComponent(goal || "");
  const citySlug = dest || origin;

  // Price range helpers for filtered searches
  const lo = Math.round((bucketAmount || 0) * 0.8);
  const hi = Math.round((bucketAmount || 0) * 1.2);

  const B = (label, url) => ({ label, url });

  if (type === "travel") {
    const originUp = (c.origin || "Delhi");
    const destUp   = dest.replace(/-/g, " ").replace(/\b\w/g, x => x.toUpperCase());
    if (bucketLabel === "Transit") return [
      B("MakeMyTrip", `https://www.makemytrip.com/flights/${originUp}-to-${destUp}.html`),
      B("Cleartrip", `https://www.cleartrip.com/flights/results?adults=1&childs=0&infants=0&depart_date=&from=${originUp}&to=${destUp}&intl=n&airline=&page=loaded`),
      B("EaseMyTrip", `https://www.easemytrip.com/flights/search?org=${originUp}&dest=${destUp}&dDate=&isNearByAirport=false&tripType=O&adult=1&child=0&infant=0&cls=Economy`),
      B("GoIbibo", `https://www.goibibo.com/flights/search/${originUp}-to-${destUp}-cheap-flights/`),
      B("Ixigo Flights", `https://www.ixigo.com/flight/${originUp}-to-${destUp}/flights-from-${origin}-to-${dest}`),
      B("RedBus", `https://www.redbus.in/bus-tickets/${origin}-to-${dest}`),
      B("AbhiBus", `https://www.abhibus.com/bus_search/${originUp}-to-${destUp}/`),
      B("IRCTC Trains", `https://www.irctc.co.in/nget/train-search`),
    ];
    if (bucketLabel === "Stay") return [
      B("MakeMyTrip", `https://www.makemytrip.com/hotels/${dest}-hotels.html`),
      B("OYO", `https://www.oyorooms.com/search?location=${encodeURIComponent(destUp)}&budget_max=${hi}`),
      B("Booking.com", `https://www.booking.com/search.html?ss=${encodeURIComponent(destUp)}&price=1-${hi}`),
      B("Agoda", `https://www.agoda.com/search?city=${encodeURIComponent(destUp)}&maxPrice=${hi}`),
      B("Treebo", `https://www.treebo.com/search/?location=${encodeURIComponent(destUp)}`),
      B("FabHotels", `https://www.fabhotels.com/search?city=${encodeURIComponent(destUp)}`),
      B("Airbnb", `https://www.airbnb.co.in/s/${encodeURIComponent(destUp)}/homes`),
    ];
    if (bucketLabel === "Food") return [
      B("Zomato", `https://www.zomato.com/${citySlug}/restaurants`),
      B("Swiggy", `https://www.swiggy.com/city/${citySlug}`),
      B("EazyDiner", `https://www.eazydiner.com/${citySlug}`),
    ];
    if (bucketLabel === "Activities") return [
      B("Thrillophilia", `https://www.thrillophilia.com/${citySlug}`),
      B("Klook", `https://www.klook.com/en-IN/search/?query=${encodeURIComponent(destUp)}`),
      B("GetYourGuide", `https://www.getyourguide.com/s/?q=${encodeURIComponent(destUp)}`),
      B("BookMyShow", `https://in.bookmyshow.com/explore/activities/${citySlug}`),
    ];
    if (bucketLabel === "Local transport") return [
      B("Ola", `https://www.olacabs.com/`),
      B("Uber", `https://www.uber.com/in/en/`),
      B("Rapido", `https://rapido.bike/`),
      B("InDrive", `https://indrive.com/en/cities/${citySlug}`),
    ];
  }

  if (type === "gadget") {
    const q = goalEnc;
    if (bucketLabel === "Device") return [
      B("Amazon", `https://www.amazon.in/s?k=${q}&rh=p_36%3A${lo*100}-${hi*100}`),
      B("Flipkart", `https://www.flipkart.com/search?q=${q}&p%5B%5D=facets.price_range.from%3D${lo}&p%5B%5D=facets.price_range.to%3D${hi}`),
      B("Croma", `https://www.croma.com/searchB?q=${q}`),
      B("Reliance Digital", `https://www.reliancedigital.in/search?q=${q}`),
      B("Vijay Sales", `https://www.vijaysales.com/search/${q}`),
      B("Tata Cliq", `https://www.tatacliq.com/search/?searchCategory=all&text=${q}`),
    ];
    if (bucketLabel === "Warranty") return [
      B("Flipkart", `https://www.flipkart.com/search?q=${q}+extended+warranty`),
      B("Amazon", `https://www.amazon.in/s?k=${q}+protection+plan`),
      B("Croma Care", `https://www.croma.com/extended-warranty`),
    ];
    if (bucketLabel === "Accessories") return [
      B("Amazon", `https://www.amazon.in/s?k=${q}+accessories&rh=p_36%3A${lo*100}-${hi*100}`),
      B("Flipkart", `https://www.flipkart.com/search?q=${q}+accessories`),
      B("Boat", `https://www.boat-lifestyle.com/`),
    ];
  }

  if (type === "relocation") {
    const city = (c.origin || "Delhi").toLowerCase();
    const destCity = dest.replace(/-/g, " ").replace(/\b\w/g, x => x.toUpperCase());
    if (bucketLabel === "Deposit") return [
      B("NoBroker", `https://www.nobroker.in/property/residential/for-rent/${dest}/`),
      B("99acres", `https://www.99acres.com/residential-property-for-rent-in-${dest}-ffid`),
      B("MagicBricks", `https://www.magicbricks.com/property-for-rent/residential-real-estate?city=${encodeURIComponent(destCity)}`),
      B("Housing.com", `https://housing.com/rent/flats-in-${dest}`),
      B("CommonFloor", `https://www.commonfloor.com/listing/rent-${dest}`),
    ];
    if (bucketLabel === "Moving") return [
      B("Urban Company", `https://www.urbancompany.com/${city}/packers-and-movers`),
      B("Porter", `https://porter.in/`),
      B("Justdial", `https://www.justdial.com/${citySlug}/Packers-and-Movers`),
      B("Sulekha", `https://www.sulekha.com/packers-and-movers/${citySlug}`),
    ];
    if (bucketLabel === "Furniture") return [
      B("IKEA", `https://www.ikea.com/in/en/`),
      B("Pepperfry", `https://www.pepperfry.com/`),
      B("Urban Ladder", `https://www.urbanladder.com/`),
      B("Amazon Furniture", `https://www.amazon.in/s?k=furniture&rh=p_36%3A${lo*100}-${hi*100}`),
      B("Flipkart Furniture", `https://www.flipkart.com/search?q=furniture&p%5B%5D=facets.price_range.from%3D${lo}&p%5B%5D=facets.price_range.to%3D${hi}`),
    ];
    if (bucketLabel === "Commute") return [
      B("Ola", `https://www.olacabs.com/`),
      B("Uber", `https://www.uber.com/in/en/`),
      B("Rapido", `https://rapido.bike/`),
    ];
    if (bucketLabel === "Setup") return [
      B("Urban Company", `https://www.urbancompany.com/${city}/home-services`),
      B("Amazon", `https://www.amazon.in/s?k=home+setup+essentials&rh=p_36%3A${lo*100}-${hi*100}`),
    ];
  }

  if (type === "event") {
    const city = (c.origin || "Delhi").toLowerCase().replace(/\s+/g, "-");
    if (bucketLabel === "Venue") return [
      B("WedMeGood", `https://www.wedmegood.com/search/wedding-venues-in-${city}`),
      B("WeddingWire", `https://www.weddingwire.in/wedding-venues/${city}`),
      B("Shaadi.com Venues", `https://www.shaadi.com/wedding/venues/${city}`),
      B("BookMyShow", `https://in.bookmyshow.com/events/${city}`),
      B("Venuelook", `https://www.venuelook.com/${city}/venues`),
    ];
    if (bucketLabel === "Catering") return [
      B("Zomato Catering", `https://www.zomato.com/catering/${city}`),
      B("EazyDiner", `https://www.eazydiner.com/${city}/caterers`),
      B("WedMeGood Caterers", `https://www.wedmegood.com/search/wedding-caterers-in-${city}`),
      B("Sulekha Catering", `https://www.sulekha.com/catering-services/${city}`),
    ];
    if (bucketLabel === "Decor") return [
      B("WedMeGood Decor", `https://www.wedmegood.com/search/wedding-decorators-in-${city}`),
      B("Pepperfry", `https://www.pepperfry.com/`),
      B("Amazon Decor", `https://www.amazon.in/s?k=event+decoration&rh=p_36%3A${lo*100}-${hi*100}`),
    ];
    if (bucketLabel === "Photo") return [
      B("WedMeGood Photos", `https://www.wedmegood.com/search/wedding-photographers-in-${city}`),
      B("WeddingWire Photos", `https://www.weddingwire.in/wedding-photographers/${city}`),
      B("Pixelstory", `https://www.pixelstory.in/`),
    ];
    if (bucketLabel === "Logistics") return [
      B("Urban Company", `https://www.urbancompany.com/${city}/`),
      B("Porter", `https://porter.in/`),
    ];
  }

  return [];
}

/* ── TEMPLATES ── */
const TEMPLATES = {
  travel:     { goal: "Plan a Goa trip for 4 days under ₹25,000 with good stays and low travel fatigue", budget: 25000, duration: 4 },
  gadget:     { goal: "Need a coding laptop under ₹60,000 with strong battery and low repair risk", budget: 60000, duration: 1 },
  relocation: { goal: "Move from Lucknow to Bengaluru with minimum setup cost and reliable commute", budget: 150000, duration: 14 },
  event:      { goal: "Plan a wedding for 300 guests within ₹5,00,000 with good food and decor", budget: 500000, duration: 2 },
};
const TYPE_LABELS = {
  travel: "Travel planner", gadget: "Gadget buyer",
  relocation: "Relocation planner", event: "Event planner",
};
const GRAPH_NODES = {
  travel:     ["Transit", "Stay", "Food", "Activities", "Local transport"],
  gadget:     ["Device", "Warranty", "Accessories", "Discounts", "Resale"],
  relocation: ["Deposit", "Moving", "Furniture", "Commute", "Setup"],
  event:      ["Venue", "Catering", "Decor", "Photo", "Logistics"],
};

/* ── DOM ── */
const $ = (id) => document.getElementById(id);
const el = {
  statusDot:    $("status-dot"),   statusLabel:  $("status-label"),
  llmMode:      $("llm-mode"),     llmDetail:    $("llm-detail"),
  progressFill: $("progress-fill"),
  form:         $("goal-form"),    goal:         $("goal"),
  budget:       $("budget"),       budgetOutput: $("budget-output"),
  duration:     $("duration"),     origin:       $("origin"),
  alerts:       $("alerts"),       sustainability: $("sustainability"),
  negotiator:   $("negotiator"),
  submitBtn:    $("submit-button"),submitLabel:  $("submit-label"),
  submitArrow:  $("submit-arrow"), refreshBtn:   $("refresh-button"),
  shareBtn:     $("share-btn"),
  compareToggleBtn: $("compare-toggle-btn"),
  intentChip:   $("intent-chip"),
  traceList:    $("trace-list"),   currentInsight: $("current-insight"),
  agentDot:     $("agent-dot"),
  confidenceScore: $("confidence-score"), decisionStyle: $("decision-style"),
  resultTitle:  $("result-title"), engineMode:   $("engine-mode"),
  metricBudget: $("metric-budget"),metricSaving: $("metric-saving"),
  metricDecision: $("metric-decision"),
  planGrid:     $("plan-grid"),    detailCard:   $("detail-card"),
  graphBoard:   $("graph-board"),  historyList:  $("history-list"),
  chosenPlan:   $("chosen-plan"),
  jStatus:      $("j-status"),
  toastContainer: $("toast-container"),
  whatifBar:    $("whatif-bar"),   whatifSlider: $("whatif-slider"),
  whatifOutput: $("whatif-output"),whatifApply:  $("whatif-apply"),
  savingsDiscovery: $("savings-discovery"), sdHints: $("sd-hints"),
  aiNotes:      $("ai-notes"),
  aiAssumptionsWrap: $("ai-assumptions-wrap"), aiAssumptions: $("ai-assumptions"),
  aiRisksWrap:  $("ai-risks-wrap"), aiRisks: $("ai-risks"),
  compareSide:  $("compare-side"), csBody: $("cs-body"), csClose: $("cs-close"),
  clearHistoryBtn: $("clear-history-btn"),
  createAlertBtn: $("create-alert-btn"),
  draftMsgBtn:  $("draft-msg-btn"),
  shareActBtn:  $("share-act-btn"),
  darkToggle:   $("dark-toggle"),
  modalOverlay: $("modal-overlay"),
  alertModal:   $("alert-modal"),
  draftModal:   $("draft-modal"),
  alertPlanName: $("alert-plan-name"),
  alertThreshold: $("alert-threshold"),
  alertThresholdOutput: $("alert-threshold-output"),
  alertNote:    $("alert-note"),
  saveAlertBtn: $("save-alert-btn"),
  draftMsgText: $("draft-msg-text"),
  copyDraftBtn: $("copy-draft-btn"),
  copyLinkBtn:  $("copy-link-btn"),
  downloadPlanBtn: $("download-plan-btn"),
  exportPdfBtn: $("export-pdf-btn"),
  pdfFrame:     $("pdf-frame"),
  budgetWarning: $("budget-warning"),
  whatsappShareBtn: $("whatsapp-share-btn"),
  htabRecent:   $("htab-recent"),
  htabSaved:    $("htab-saved"),
  savedCount:   $("saved-count"),
  onboardOverlay: $("onboard-overlay"),
  onboardNext:  $("onboard-next"),
  onboardSkip:  $("onboard-skip"),
  onboardDots:  $("onboard-dots"),
  dnaInsight:   $("dna-insight"),
  lifeBudget:   $("life-budget"),
  lifeBudgetOutput: $("life-budget-output"),
  lifeCity:     $("life-city"),
  lifePlanBtn:  $("life-plan-btn"),
  lifeResult:   $("life-result"),
  lifeSummary:  $("life-summary"),
  lifeCategories: $("life-categories"),
};

/* ═══════════════════════════════════════
   TOAST SYSTEM
═══════════════════════════════════════ */
function toast(msg, type = "default", duration = 3200) {
  const icons = {
    success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    default: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  };
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = (icons[type] || icons.default) + `<span>${msg}</span>`;
  el.toastContainer.appendChild(t);
  setTimeout(() => {
    t.classList.add("toast-out");
    t.addEventListener("animationend", () => t.remove(), { once: true });
  }, duration);
}

/* ═══════════════════════════════════════
   VIEW ROUTING
═══════════════════════════════════════ */
const VIEWS = ["home", "plan", "compare", "act", "life", "history"];
function showView(viewId) {
  if (!VIEWS.includes(viewId)) return;
  state.view = viewId;
  VIEWS.forEach((v) => {
    const node = document.getElementById(`view-${v}`);
    if (node) { node.hidden = v !== viewId; node.classList.toggle("active", v === viewId); }
  });
  // Desktop nav tabs
  document.querySelectorAll(".nav-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.view === viewId);
    t.setAttribute("aria-selected", String(t.dataset.view === viewId));
  });
  // Mobile nav
  document.querySelectorAll(".mob-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.view === viewId);
  });
  // Progress
  const pct = { home: 0, plan: 20, compare: 65, act: 92, life: 15, history: 10 };
  el.progressFill.style.width = (pct[viewId] || 0) + "%";
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (viewId === "plan") renderDNAInsight();
}

/* ═══════════════════════════════════════
   JOURNEY STEPPER
═══════════════════════════════════════ */
const JOURNEY_LABELS = ["Goal", "Optimising", "Compare", "Act"];
function setJourneyStage(idx) {
  state.journeyStage = idx;
  el.jStatus.textContent = JOURNEY_LABELS[idx] || JOURNEY_LABELS[0];
  document.querySelectorAll(".journey-step").forEach((s, i) => {
    s.classList.toggle("active", i === idx);
    s.classList.toggle("complete", i < idx);
  });
}

/* ═══════════════════════════════════════
   LOCAL STORAGE HISTORY
═══════════════════════════════════════ */
const STORAGE_KEY = "costpilot_history_v2";
function loadStoredHistory() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
  catch { return []; }
}
function saveHistory(entries) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, 12))); }
  catch {}
}
function pushHistory(entry) {
  const h = loadStoredHistory();
  h.unshift(entry);
  saveHistory(h);
}
function clearHistory() {
  localStorage.removeItem(STORAGE_KEY);
  renderHistoryView([]);
  toast("History cleared", "default");
}

/* ═══════════════════════════════════════
   COPY / SHARE PLAN
═══════════════════════════════════════ */
function buildShareText(result, plan) {
  if (!result || !plan) return "";
  const lines = [
    `CostPilot AI — ${result.title}`,
    `Plan: ${plan.name} (${plan.badge})`,
    `Total: ${money(plan.total_cost)}  |  ${plan.budget_delta_label}`,
    `Fit score: ${plan.fit_score}%`,
    ``,
    `Cost breakdown:`,
    ...plan.cost_breakdown.map((b) => `  ${b.label}: ${money(b.amount)}`),
    ``,
    `Trade-offs:`,
    ...plan.tradeoffs.map((t) => `  • ${t}`),
    ``,
    `Savings opportunities:`,
    ...plan.savings.map((s) => `  ↓ ${s}`),
    ``,
    `Generated by CostPilot AI — costpilot.ai`,
  ];
  return lines.join("\n");
}

async function copyPlan() {
  const plan = state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) { toast("Select a plan first", "error"); return; }
  const text = buildShareText(state.lastResult, plan);
  try {
    await navigator.clipboard.writeText(text);
    toast("Plan copied to clipboard!", "success");
  } catch {
    toast("Copy failed — try again", "error");
  }
}

/* ═══════════════════════════════════════
   SAVINGS DISCOVERY
═══════════════════════════════════════ */
function buildSavingsHints(plans, budget, type) {
  const cheapest = plans.reduce((a, b) => a.total_cost < b.total_cost ? a : b);
  const value    = plans.find((p) => p.id === "value");
  const fastest  = plans.find((p) => p.id === "fastest");
  const hints = [];

  if (cheapest && value) {
    const diff = value.total_cost - cheapest.total_cost;
    if (diff > 0) hints.push({ save: money(diff), label: "Switch cheapest → value", sub: `Pay ${money(diff)} more for a ${value.fit_score - cheapest.fit_score}% fit improvement` });
  }
  if (fastest && value) {
    const diff = fastest.total_cost - value.total_cost;
    if (diff > 0) hints.push({ save: money(diff), label: "Choose value over fastest", sub: `Save ${money(diff)} with only minor time impact` });
  }

  // Budget what-if
  const reduced = Math.round(budget * 0.9);
  hints.push({ save: money(budget - reduced), label: "Reduce budget by 10%", sub: `Plans recalculate from ${money(reduced)} — still covers cheapest route` });

  // Type-specific hints
  const typeHints = {
    travel:     { save: money(Math.round(budget * 0.07)), label: "Shift dates by 2–3 days", sub: "Off-peak flights and hotels typically 10–15% cheaper" },
    gadget:     { save: money(Math.round(budget * 0.12)), label: "Buy refurbished model", sub: "Same specs, 1-year warranty, 15–20% cheaper" },
    relocation: { save: money(Math.round(budget * 0.08)), label: "Negotiate deposit terms", sub: "2-month deposit is often negotiable to 1-month in metro cities" },
    event:      { save: money(Math.round(budget * 0.10)), label: "Book venue off-season", sub: "Weekend pricing 20–30% lower in Jan–Mar window" },
  };
  if (typeHints[type]) hints.push(typeHints[type]);

  // Seasonal hint
  const seasonal = getSeasonalHint(type);
  if (seasonal) hints.push(seasonal);

  return hints.slice(0, 4);
}

function renderSavingsDiscovery(plans, budget, type) {
  const hints = buildSavingsHints(plans, budget, type);
  if (!hints.length) { el.savingsDiscovery.style.display = "none"; return; }
  el.savingsDiscovery.style.display = "block";
  el.sdHints.innerHTML = hints.map((h, i) => `
    <div class="sd-hint" style="animation-delay:${i * 60}ms">
      <div class="sd-hint-save">${h.save}</div>
      <div class="sd-hint-label">${h.label}</div>
      <div class="sd-hint-sub">${h.sub}</div>
    </div>`).join("");
}

/* ═══════════════════════════════════════
   CLAUDE AI NOTES
═══════════════════════════════════════ */
function renderAiNotes(llmNotes) {
  if (!llmNotes || !["claude","gemini"].includes(llmNotes.mode)) { el.aiNotes.style.display = "none"; return; }
  const assumptions = llmNotes.assumptions || [];
  const risks       = llmNotes.risks || [];
  if (!assumptions.length && !risks.length) { el.aiNotes.style.display = "none"; return; }

  el.aiNotes.style.display = "block";
  if (assumptions.length) {
    el.aiAssumptionsWrap.style.display = "block";
    el.aiAssumptions.innerHTML = assumptions.map((a) => `<li>${a}</li>`).join("");
  } else { el.aiAssumptionsWrap.style.display = "none"; }

  if (risks.length) {
    el.aiRisksWrap.style.display = "block";
    el.aiRisks.innerHTML = risks.map((r) => `<li>${r}</li>`).join("");
  } else { el.aiRisksWrap.style.display = "none"; }
}

/* ═══════════════════════════════════════
   SIDE-BY-SIDE COMPARISON
═══════════════════════════════════════ */
function toggleCompareMode() {
  state.compareMode = !state.compareMode;
  state.comparePlanIds = [];
  el.compareSide.style.display = "none";
  el.compareToggleBtn.style.background = state.compareMode ? "var(--blue-lt)" : "";
  el.compareToggleBtn.style.color      = state.compareMode ? "var(--blue)" : "";
  el.compareToggleBtn.style.borderColor= state.compareMode ? "var(--blue)" : "";
  renderPlanCards(state.lastResult?.plans || []);
  if (state.compareMode) toast("Select 2 plans to compare side by side", "default", 3000);
}

function selectForCompare(planId) {
  if (state.comparePlanIds.includes(planId)) {
    state.comparePlanIds = state.comparePlanIds.filter((id) => id !== planId);
  } else if (state.comparePlanIds.length < 2) {
    state.comparePlanIds.push(planId);
  } else {
    state.comparePlanIds = [state.comparePlanIds[1], planId];
  }
  renderPlanCards(state.lastResult?.plans || []);
  if (state.comparePlanIds.length === 2) showSideBySide();
  else el.compareSide.style.display = "none";
}

function showSideBySide() {
  const plans = state.lastResult?.plans || [];
  const [a, b] = state.comparePlanIds.map((id) => plans.find((p) => p.id === id));
  if (!a || !b) return;
  el.compareSide.style.display = "block";

  function col(plan, other) {
    const bucketRows = plan.cost_breakdown.map((bucket, i) => {
      const otherAmount = other.cost_breakdown[i]?.amount || 0;
      const diff = bucket.amount - otherAmount;
      const diffLabel = diff === 0 ? "" : `<span class="cs-diff ${diff > 0 ? "worse" : ""}">${diff > 0 ? "+" : ""}${money(diff)}</span>`;
      return `<div class="cs-bucket-row"><span>${bucket.label}</span><strong>${money(bucket.amount)}${diffLabel}</strong></div>`;
    }).join("");
    return `
      <div class="cs-col">
        <div class="cs-plan-name">${plan.name}</div>
        <div class="cs-price">${money(plan.total_cost)}</div>
        <div class="cs-section">
          <div class="cs-sec-label">Cost breakdown</div>
          ${bucketRows}
        </div>
        <div class="cs-section">
          <div class="cs-sec-label">Fit score</div>
          <strong>${plan.fit_score}%</strong>
        </div>
        <div class="cs-section">
          <div class="cs-sec-label">Explanation</div>
          <div style="font-size:.8rem;color:var(--muted);line-height:1.45">${plan.explanation}</div>
        </div>
      </div>`;
  }

  el.csBody.innerHTML = col(a, b) + col(b, a);
}

/* ═══════════════════════════════════════
   WHAT-IF SLIDER
═══════════════════════════════════════ */
function initWhatif(budget) {
  el.whatifSlider.value = budget;
  el.whatifOutput.textContent = money(budget);
  el.whatifBar.style.display = "block";

  el.whatifSlider.oninput = () => {
    el.whatifOutput.textContent = money(el.whatifSlider.value);
  };
  el.whatifApply.onclick = () => {
    if (!state.lastPayload) return;
    const newPayload = { ...state.lastPayload, budget: Number(el.whatifSlider.value) };
    el.budget.value = newPayload.budget;
    updateBudget();
    generatePlan(newPayload);
    toast(`Re-running with ${money(newPayload.budget)} budget…`, "default");
  };
}

/* ═══════════════════════════════════════
   GRAPH
═══════════════════════════════════════ */
function renderGraph(nodes = []) {
  el.graphBoard.innerHTML =
    `<span class="graph-node root">Goal</span>` +
    nodes.map((n, i) => `<span class="graph-node" style="animation-delay:${(i+1)*55}ms">${n}</span>`).join("");
}

/* ═══════════════════════════════════════
   TYPE SWITCH
═══════════════════════════════════════ */
function setType(type) {
  state.type = type;
  const t = TEMPLATES[type];
  el.goal.value = t.goal;
  el.budget.value = t.budget;
  el.duration.value = t.duration;
  updateBudget();
  el.intentChip.textContent = TYPE_LABELS[type];
  renderGraph(GRAPH_NODES[type]);
  document.querySelectorAll(".persona-btn").forEach((b) => {
    const on = b.dataset.type === type;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
}

/* ═══════════════════════════════════════
   BUDGET
═══════════════════════════════════════ */
function updateBudget() {
  el.budgetOutput.textContent = money(el.budget.value);
}

/* ═══════════════════════════════════════
   BUSY
═══════════════════════════════════════ */
function setBusy(busy) {
  el.submitBtn.disabled = busy;
  el.submitBtn.classList.toggle("busy", busy);
  el.submitLabel.textContent = busy ? "Optimising routes…" : "Generate optimised plans";
  el.refreshBtn.disabled  = busy || !state.lastPayload;
  el.shareBtn.disabled    = busy || !state.lastResult;
  el.compareToggleBtn.disabled = busy || !state.lastResult;
  el.agentDot.classList.toggle("active", busy);
  if (busy) setJourneyStage(1);
}

/* ═══════════════════════════════════════
   TRACE
═══════════════════════════════════════ */
function renderTrace(steps = []) {
  const fallback = [
    { label: "Goal parser ready",          status: "done" },
    { label: "Research agent idle",        status: "idle" },
    { label: "Cost model idle",            status: "idle" },
    { label: "Optimizer idle",             status: "idle" },
    { label: "Explanation agent idle",     status: "idle" },
  ];
  const items = steps.length ? steps : fallback;
  el.traceList.innerHTML = items.map(({ label, status = "idle" }) =>
    `<li class="trace-item ${status}"><span class="trace-dot"></span><span>${label}</span></li>`
  ).join("");
}

let _traceTimer = null;
function animateTrace() {
  clearTimeout(_traceTimer);
  const steps = [
    { label: "Parsing natural language goal…",  status: "running" },
    { label: "Research agent gathering data…",  status: "idle" },
    { label: "Cost model building buckets…",    status: "idle" },
    { label: "Optimizer scoring routes…",       status: "idle" },
    { label: "Explanation agent writing…",      status: "idle" },
  ];
  let i = 0;
  function tick() {
    if (i >= steps.length) return;
    if (i > 0) steps[i - 1].status = "done";
    steps[i].status = "running";
    renderTrace([...steps]);
    i++;
    _traceTimer = setTimeout(tick, 900);
  }
  tick();
}

/* ═══════════════════════════════════════
   PAYLOAD
═══════════════════════════════════════ */
function getPayload() {
  const priority = document.querySelector('input[name="priority"]:checked')?.value || "balanced";
  return {
    goal:     el.goal.value.trim(),
    type:     state.type,
    budget:   Number(el.budget.value),
    duration: Number(el.duration.value || 1),
    origin:   el.origin.value,
    priority,
    options: {
      alerts:         el.alerts.checked,
      sustainability: el.sustainability.checked,
      negotiator:     el.negotiator.checked,
    },
  };
}

/* ═══════════════════════════════════════
   API
═══════════════════════════════════════ */
async function api(path, opts = {}) {
  if (window.location.protocol === "file:") {
    if (path === "/api/health") return { ok: true, llm_configured: false, model: "local", routes: [] };
    if (path === "/api/plan")   return localPlan(JSON.parse(opts.body || "{}"));
  }
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  return res.json();
}

/* ═══════════════════════════════════════
   LOCAL PLAN (FALLBACK)
═══════════════════════════════════════ */
const TYPE_CFG = {
  travel:     { buckets: ["Transit","Stay","Food","Activities","Local transport"],       weights:[.34,.27,.16,.15,.08] },
  gadget:     { buckets: ["Device","Warranty","Accessories","Discounts","Resale buffer"],weights:[.78,.08,.06,.04,.04] },
  relocation: { buckets: ["Deposit","Moving","Furniture","Commute","Setup"],             weights:[.46,.16,.18,.09,.11] },
  event:      { buckets: ["Venue","Catering","Decor","Photo","Logistics"],               weights:[.24,.42,.14,.09,.11] },
};
const VARIANTS = [
  { id:"cheapest", name:"Cheapest",   badge:"Lowest cash out", m:.82,  fit:79, sp:68, exp:"Uses flexible timing, modest choices, and the least expensive viable combinations across all cost buckets." },
  { id:"fastest",  name:"Fastest",    badge:"Time saver",      m:1.13, fit:82, sp:94, exp:"Spends selectively to reduce waiting, coordination effort, and avoidable delays throughout the plan." },
  { id:"value",    name:"Best value", badge:"Recommended",     m:.96,  fit:90, sp:84, exp:"Balances the full solution by avoiding cheap components that create downstream cost and friction." },
  { id:"premium",  name:"Premium",    badge:"Comfort first",   m:1.27, fit:85, sp:88, exp:"Prioritises reliability, comfort, warranty, support, and lower execution risk throughout the plan." },
];
// Extract a meaningful destination/subject from the goal text
function extractTitle(goal, type, origin) {
  if (!goal) return TYPE_LABELS[type] || "Plan";

  if (type === "gadget") {
    const brand = goal.match(/\b(iPhone\s*\d+\w*(?:\s+\w+)?|MacBook\s+\w+(?:\s+\w+)?|Samsung\s+\w+\d+\w*|OnePlus\s+\d+\w*|Pixel\s+\d+\w*|iPad\s+\w*|Dell\s+\w+|HP\s+\w+|Sony\s+\w+)/i);
    if (brand) return `${brand[1].trim()} purchase`;
    const cat = goal.match(/\b(laptop|phone|tablet|camera|smartwatch|headphone|speaker|TV|monitor|keyboard)\b/i);
    if (cat) return `${cat[1].charAt(0).toUpperCase()+cat[1].slice(1)} purchase`;
    return "Gadget purchase";
  }

  if (type === "relocation") {
    const dest = goal.match(/\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b/);
    if (dest?.[1] && dest[1].toLowerCase() !== origin.toLowerCase()) return `Relocation to ${dest[1]}`;
    return `Relocation from ${origin}`;
  }

  if (type === "event") {
    const ev = goal.match(/\b(wedding|birthday|anniversary|conference|concert|festival|farewell|reunion)\b/i);
    if (ev) {
      const loc = goal.match(/\bin\s+([A-Z][a-zA-Z]+)\b/);
      return `${ev[1].charAt(0).toUpperCase()+ev[1].slice(1)}${loc ? ` in ${loc[1]}` : ""}`;
    }
    return "Event plan";
  }

  // travel
  const patterns = [
    /\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b/,
    /\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b/,
    /\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+trip\b/i,
    /\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+tour\b/i,
    /\bvisit\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b/i,
  ];
  for (const re of patterns) {
    const m = goal.match(re);
    if (m?.[1] && m[1].toLowerCase() !== origin.toLowerCase()) return `${m[1]} trip from ${origin}`;
  }
  return `Trip from ${origin}`;
}

function localPlan(p) {
  const cfg    = TYPE_CFG[p.type] || TYPE_CFG.travel;
  const budget = Number(p.budget || 25000);
  // Duration factor: only apply for travel, but cap so cheapest always stays under budget
  // User's budget is their total for the trip — we respect it as a hard cap baseline
  const rawDf  = p.type === "travel" ? Math.max(.72, Number(p.duration||4)/4) : 1;
  // Normalise: cheapest variant (m=0.82) must stay <= budget, so cap df at 1/0.82 = 1.22
  const df     = Math.min(rawDf, 1 / 0.84);
  const priorityAdj = { cheapest: p.priority==="cheap"?-0.06:0, fastest: p.priority==="fast"?-0.04:0, value: p.priority==="quality"?0.02:0, premium: p.priority==="quality"?0.04:0 };
  const plans  = VARIANTS.map((v) => {
    const adj   = v.m + (priorityAdj[v.id] || 0);
    const total = Math.round(budget * adj * df);
    const delta = budget - total;
    return {
      id:v.id, name:v.name, badge:v.badge,
      total_cost:total, budget_delta:delta,
      budget_delta_label:`${money(Math.abs(delta))} ${delta>=0?"under":"over"} budget`,
      fit_score:v.fit,
      time_label: p.type==="travel"
        ? `${Math.max(1,Math.round(Number(p.duration||4)*(100/v.sp)))} day impact`
        : `${Math.round(100/v.sp*8)} effort score`,
      explanation:v.exp,
      cost_breakdown: cfg.buckets.map((label,i)=>({label,amount:Math.round(total*cfg.weights[i])})),
      tradeoffs:["Lower cost increases flexibility and coordination requirements.","Higher fit score means fewer weak links in the plan.","Best route depends on cash, time, or reliability priority."],
      savings:[`Target ${money(Math.max(500,budget*.06))} by shifting one high-cost bucket.`,"Enable alerts to wait for a better booking window.","Bundle vendor decisions before negotiating."],
    };
  });
  const cheap = plans.reduce((a,b)=>a.total_cost<b.total_cost?a:b);
  const value = plans.find((x)=>x.id==="value");
  const title = extractTitle(p.goal, p.type, p.origin||"Delhi");
  // Pick best recommendation based on priority
  const recommended = p.priority === "cheap" ? plans.find(x=>x.id==="cheapest")
    : p.priority === "fast"    ? plans.find(x=>x.id==="fastest")
    : p.priority === "quality" ? plans.find(x=>x.id==="premium")
    : value;
  const bestSaving = Math.max(0, budget - cheap.total_cost);
  const headline = bestSaving > 0
    ? `${recommended?.name||"Best value"} recommended — save up to ${money(bestSaving)} vs premium.`
    : `${recommended?.name||"Best value"} is the strongest fit for your ₹${(budget/1000).toFixed(0)}K budget.`;
  return {
    title,
    engine_label:"Local optimizer",
    constraints:{budget, priority:p.priority||"balanced", type:p.type, goal:p.goal, duration:p.duration, origin:p.origin},
    summary:{headline, best_saving:bestSaving, decision:recommended?.name||"Best value"},
    trace:[
      {label:"Goal parsed into constraints",       status:"done"},
      {label:"Cost buckets estimated",             status:"done"},
      {label:"Routes scored by fit and speed",     status:"done"},
      {label:"Trade-offs prepared for each route", status:"done"},
      {label:"Explanation generated",              status:"done"},
    ],
    plans, knowledge_graph:{nodes:cfg.buckets}, llm_notes:{mode:"mock"},
    history:[{title, budget, engine:"Local optimizer", created_at:Date.now()/1000, type:p.type, goal:p.goal}],
  };
}

/* ═══════════════════════════════════════
   RENDER PLAN CARDS (shared)
═══════════════════════════════════════ */
function renderPlanCards(plans) {
  const budget = state.lastResult?.constraints?.budget || 0;
  el.planGrid.innerHTML = plans.map((plan, idx) => {
    const over     = plan.total_cost > budget;
    const isActive = plan.id === state.selectedPlanId;
    const isCmp    = state.comparePlanIds.includes(plan.id);
    const cmpBtnLabel = isCmp ? "✓ Selected" : "+ Compare";
    return `
      <button class="plan-card ${isActive?"active":""} ${isCmp?"compare-selected":""}"
        type="button" data-plan-id="${plan.id}"
        style="animation-delay:${idx*55}ms" aria-pressed="${isActive}">
        <span class="plan-badge">${plan.badge}</span>
        <span class="plan-name">${plan.name}</span>
        <span class="plan-price">${money(plan.total_cost)}</span>
        <span class="plan-delta ${over?"over":""}">${plan.budget_delta_label}</span>
        <span class="plan-bar"><span class="plan-bar-fill" style="width:${plan.fit_score}%"></span></span>
        <span class="plan-foot">${plan.time_label} · ${plan.fit_score}% fit</span>
        ${state.compareMode?`<div class="compare-btn-row"><button class="compare-add-btn ${isCmp?"selected":""}" type="button" data-cmp-id="${plan.id}">${cmpBtnLabel}</button></div>`:""}
      </button>`;
  }).join("");

  // Card click → select plan
  el.planGrid.querySelectorAll(".plan-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".compare-add-btn")) return;
      if (state.compareMode) return;
      selectPlan(card.dataset.planId);
    });
  });
  // Compare add button
  el.planGrid.querySelectorAll(".compare-add-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      selectForCompare(btn.dataset.cmpId);
    });
  });
}

/* ═══════════════════════════════════════
   RENDER PLANS
═══════════════════════════════════════ */
function renderPlans(result) {
  state.lastResult = result;
  const plans = result.plans || [];
  state.selectedPlanId = plans.find((p)=>p.id==="value")?.id || plans[0]?.id || null;
  state.comparePlanIds = [];
  state.compareMode    = false;

  el.resultTitle.textContent    = result.title || "Optimised plans";
  el.engineMode.textContent     = result.engine_label || "--";
  el.metricBudget.textContent   = money(result.constraints?.budget || el.budget.value);
  el.metricSaving.textContent   = money(result.summary?.best_saving || 0);
  el.metricDecision.textContent = result.summary?.decision || "--";
  el.currentInsight.textContent = result.summary?.headline || "Plans generated.";
  el.confidenceScore.textContent= plans.length ? `${Math.max(...plans.map((p)=>p.fit_score))}%` : "--";
  el.decisionStyle.textContent  = result.constraints?.priority || "Balanced";

  setJourneyStage(2);
  renderGraph(result.knowledge_graph?.nodes || GRAPH_NODES[state.type]);
  renderPlanCards(plans);

  // Enable action buttons
  el.shareBtn.disabled         = false;
  el.compareToggleBtn.disabled = false;
  el.compareSide.style.display = "none";

  // What-if slider
  initWhatif(result.constraints?.budget || Number(el.budget.value));

  // Feature 6: budget warning
  renderBudgetWarning(plans, result.constraints?.budget || 0);

  // Feature 7: timing badge on title
  const timingBadge = getTimingBadge(result.constraints?.type || state.type);
  const timingColors = { green: "var(--green)", yellow: "#d97706", red: "var(--rose)" };
  const timingDot = `<span style="display:inline-flex;align-items:center;gap:5px;font-size:.72rem;font-weight:600;color:${timingColors[timingBadge.signal]};background:${timingColors[timingBadge.signal]}18;padding:2px 9px;border-radius:20px;margin-left:10px;vertical-align:middle">${timingBadge.signal === "green" ? "✓" : timingBadge.signal === "red" ? "⚠" : "~"} ${timingBadge.label}</span>`;
  el.resultTitle.innerHTML = (result.title || "Optimised plans") + timingDot;

  // Feature 4: alternate destinations (inject after plan grid via mutation)
  const altHtml = renderAltSuggestions(result.constraints?.type || state.type, result.title || "", result.constraints?.budget || 0);
  const existingAlt = document.getElementById("alt-suggestions-block");
  if (existingAlt) existingAlt.remove();
  if (altHtml) {
    const block = document.createElement("div");
    block.id = "alt-suggestions-block";
    block.innerHTML = altHtml;
    el.planGrid.parentNode.insertBefore(block, el.planGrid.nextSibling);
  }

  // Savings discovery
  renderSavingsDiscovery(plans, result.constraints?.budget || 0, result.constraints?.type || state.type);

  // Claude AI notes
  renderAiNotes(result.llm_notes);

  // History (merge with stored)
  const serverHistory = result.history || [];
  if (serverHistory.length) {
    const entry = serverHistory[0];
    entry.type  = result.constraints?.type || state.type;
    entry.goal  = result.constraints?.goal || "";
    pushHistory(entry);
  }
  renderHistoryView(loadStoredHistory());

  selectPlan(state.selectedPlanId);
}

/* ═══════════════════════════════════════
   SELECT PLAN
═══════════════════════════════════════ */
function selectPlan(planId) {
  const plans = state.lastResult?.plans || [];
  const plan  = plans.find((p)=>p.id===planId) || plans[0];
  if (!plan) return;
  state.selectedPlanId = plan.id;

  el.planGrid.querySelectorAll(".plan-card").forEach((c) => {
    const on = c.dataset.planId===plan.id && !state.compareMode;
    c.classList.toggle("active", on);
    c.setAttribute("aria-pressed", String(on));
  });

  const budget = state.lastResult?.constraints?.budget || 0;
  const over   = plan.total_cost > budget;

  el.detailCard.innerHTML = `
    <div class="detail-body">
      <div class="detail-top">
        <div>
          <div class="detail-name">${plan.name}</div>
          <div class="detail-desc">${plan.explanation}</div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div class="detail-price">${money(plan.total_cost)}</div>
          <div class="detail-delta" style="color:${over?"var(--rose)":"var(--green)"}">${plan.budget_delta_label}</div>
        </div>
      </div>
      <div class="detail-cols">
        <div class="detail-section">
          <div class="detail-sec-label" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            Cost breakdown
            <span style="font-size:.68rem;font-weight:500;color:var(--muted);background:var(--border);padding:2px 7px;border-radius:20px;white-space:nowrap">Estimated · compare live prices →</span>
          </div>
          <div class="bucket-list">
            ${plan.cost_breakdown.map((b,i)=>{
              const pct = plan.total_cost > 0 ? Math.round(b.amount / plan.total_cost * 100) : 0;
              const planType = state.lastResult?.constraints?.type || state.type;
              const goal = state.lastResult?.constraints?.goal || "";
              const links = getBookingLinks(planType, b.label, goal, b.amount);
              const linksHtml = links.length
                ? `<div class="book-links">${links.map(l=>`<a class="book-link" href="${l.url}" target="_blank" rel="noopener noreferrer">${l.label}</a>`).join("")}</div>`
                : "";
              return `<div class="bucket-row" style="animation-delay:${i*45}ms">
                <div class="bucket-row-top"><span>${b.label}</span><strong>${money(b.amount)}</strong></div>
                <div class="bucket-bar-track"><div class="bucket-bar-fill" style="width:${pct}%"></div></div>
                ${linksHtml}
              </div>`;
            }).join("")}
          </div>
        </div>
        <div style="display:grid;gap:14px;align-content:start">
          <div class="detail-section">
            <div class="detail-sec-label">Trade-offs</div>
            <div class="tradeoff-list">
              ${plan.tradeoffs.map((t)=>`<div class="tradeoff-item">${t}</div>`).join("")}
            </div>
          </div>
          <div class="detail-section">
            <div class="detail-sec-label">Savings opportunities</div>
            <div class="savings-list">
              ${plan.savings.map((s)=>`<div class="savings-item">${s}</div>`).join("")}
            </div>
          </div>
        </div>
      </div>
      <div class="detail-actions">
        <button class="btn-primary" type="button" id="choose-plan-btn">Choose ${plan.name}</button>
        <button class="btn-ghost" type="button" id="copy-detail-btn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
          Copy plan
        </button>
        <button class="btn-ghost" type="button" data-view="act">See next steps →</button>
      </div>
    </div>`;

  $("choose-plan-btn")?.addEventListener("click", () => choosePlan(plan));
  $("copy-detail-btn")?.addEventListener("click", copyPlan);
  el.detailCard.querySelector('[data-view="act"]')?.addEventListener("click", () => showView("act"));
  setJourneyStage(3);
}

/* ═══════════════════════════════════════
   CHOOSE PLAN
═══════════════════════════════════════ */
function choosePlan(plan) {
  state.chosenPlan = plan;
  updateDNA(state.type, state.lastResult?.constraints?.priority || "balanced", plan.total_cost);
  const budget = state.lastResult?.constraints?.budget || 0;
  const over   = plan.total_cost > budget;
  el.chosenPlan.innerHTML = `
    <div class="chosen-summary">
      <div class="chosen-label">Chosen plan</div>
      <div class="chosen-name">${state.lastResult?.title||""} — ${plan.name}</div>
      <div class="chosen-price">${money(plan.total_cost)}</div>
      <div style="font-size:.8rem;font-weight:600;color:${over?"var(--rose)":"var(--green)"};margin-top:2px">${plan.budget_delta_label}</div>
      <div style="font-size:.82rem;color:var(--muted);margin-top:4px">${plan.explanation}</div>
    </div>`;
  renderProgressTracker(plan, state.lastResult?.title, state.lastResult?.constraints?.budget);
  setJourneyStage(3);
  showView("act");
  toast(`${plan.name} plan selected!`, "success");
}

/* ═══════════════════════════════════════
   PORTFOLIO VIEW
═══════════════════════════════════════ */
const PORTFOLIO_COLORS = { travel: "var(--green)", gadget: "var(--blue)", relocation: "var(--gold)", event: "var(--rose)" };
function renderPortfolio() {
  const section = $("portfolio-section");
  if (!section) return;
  const history = loadStoredHistory();
  if (history.length < 2) { section.style.display = "none"; return; }

  section.style.display = "";
  const total = history.reduce((sum, h) => sum + (Number(h.budget) || 0), 0);
  const totalEl = $("portfolio-total");
  if (totalEl) totalEl.textContent = money(total) + " total";

  // Group by type
  const groups = {};
  history.forEach((h) => {
    const t = h.type || "travel";
    groups[t] = (groups[t] || 0) + (Number(h.budget) || 0);
  });

  const barsEl = $("portfolio-bars");
  if (!barsEl) return;
  barsEl.innerHTML = Object.entries(groups).map(([type, amt]) => {
    const pct = total > 0 ? Math.round(amt / total * 100) : 0;
    const color = PORTFOLIO_COLORS[type] || "var(--green)";
    const label = { travel: "Travel", gadget: "Gadgets", relocation: "Relocation", event: "Events" }[type] || type;
    return `
      <div class="portfolio-bar-row">
        <div class="portfolio-bar-label"><span>${label}</span><span>${money(amt)} · ${pct}%</span></div>
        <div class="portfolio-bar-track"><div class="portfolio-bar-fill" style="width:${pct}%;background:${color}"></div></div>
      </div>`;
  }).join("");
}

/* ═══════════════════════════════════════
   HISTORY VIEW
═══════════════════════════════════════ */
function renderHistoryView(history = [], isSavedTab = false) {
  updateSavedCount();
  if (!history.length) {
    el.historyList.innerHTML = `
      <div class="history-empty">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <p>${isSavedTab ? "No bookmarked plans yet." : "No saved runs yet."} <button class="link-btn" data-view="plan" type="button">Generate your first plan →</button></p>
      </div>`;
    el.historyList.querySelector("[data-view]")?.addEventListener("click", () => showView("plan"));
    return;
  }
  el.historyList.innerHTML = history.map((h, i) => {
    const savedState = isSaved(h.id || h.title);
    const daysSince = Math.round((Date.now() / 1000 - (h.created_at || h.saved_at || 0)) / 86400);
    return `
    <div class="history-item ${savedState ? "is-saved" : ""}" style="animation-delay:${i*45}ms" data-history-id="${h.id || ""}">
      <div class="history-item-title">${h.title}${daysSince > 3 ? '<span class="stale-badge">Re-check prices</span>' : ''}</div>
      <div class="history-item-meta">${money(h.budget)} · ${new Date((h.created_at||h.saved_at||0)*1000).toLocaleDateString("en-IN",{day:"numeric",month:"short"})}</div>
      <div class="history-item-tag">${h.engine || "Local optimizer"}</div>
      <div class="history-item-actions">
        <button class="btn-ghost btn-sm bookmark-btn ${savedState?"saved":""}" data-bookmark-id="${h.id || h.title}" type="button">
          ${savedState ? "Saved" : "Save"}
        </button>
        ${h.goal ? `<button class="btn-outline btn-sm replay-btn" data-goal='${JSON.stringify({goal:h.goal,type:h.type||"travel",budget:h.budget})}' type="button">Re-run →</button>` : ""}
      </div>
    </div>`;
  }).join("");

  // Bookmark toggles
  el.historyList.querySelectorAll(".bookmark-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.bookmarkId;
      const entry = history.find((h) => (h.id || h.title) === id) || {};
      const nowSaved = toggleSavePlan({ ...entry, id });
      btn.textContent = nowSaved ? "Saved" : "Save";
      btn.classList.toggle("saved", nowSaved);
      btn.closest(".history-item").classList.toggle("is-saved", nowSaved);
      if (isSavedTab && !nowSaved) renderHistoryView(loadSaved(), true);
    });
  });

  // Replay buttons
  el.historyList.querySelectorAll(".replay-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      try {
        const data = JSON.parse(btn.dataset.goal);
        setType(data.type || "travel");
        if (data.goal)   el.goal.value   = data.goal;
        if (data.budget) { el.budget.value = data.budget; updateBudget(); }
        showView("plan");
        toast("Goal loaded — click Generate to re-run", "default", 3500);
      } catch {}
    });
  });

  renderPortfolio();
}

/* ═══════════════════════════════════════
   HEALTH CHECK
═══════════════════════════════════════ */
async function loadHealth() {
  try {
    const h = await api("/api/health");
    const live     = Boolean(h.llm_configured);
    const provider = h.provider === "gemini" ? "Gemini AI" : "Claude AI";
    el.statusDot.classList.toggle("live", live);
    el.statusLabel.textContent = live ? provider : "Local optimizer";
    el.llmMode.textContent     = live ? provider : "Mock planner";
    el.llmDetail.textContent   = live
      ? `${h.model} connected`
      : "Add ANTHROPIC_API_KEY or GEMINI_API_KEY to .env";
  } catch {
    el.statusDot.classList.remove("live");
    el.statusLabel.textContent = "Offline";
    el.llmMode.textContent = "Disconnected";
  }
}

/* ═══════════════════════════════════════
   GENERATE PLAN
═══════════════════════════════════════ */
async function generatePlan(p) {
  setBusy(true);
  animateTrace();
  el.planGrid.innerHTML = Array(4).fill(`<div class="plan-skeleton"></div>`).join("");
  el.detailCard.innerHTML = `<div class="detail-empty"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/></svg><p>Generating optimised plans…</p></div>`;
  el.savingsDiscovery.style.display = "none";
  el.aiNotes.style.display = "none";
  el.compareSide.style.display = "none";
  el.whatifBar.style.display = "none";
  showView("compare");

  try {
    const result = await api("/api/plan", { method: "POST", body: JSON.stringify(p) });
    state.lastPayload = p;
    renderTrace(result.trace || []);
    renderPlans(result);
    el.agentDot.classList.remove("active");
    toast("Plans generated!", "success");
  } catch (err) {
    el.currentInsight.textContent = err.message;
    renderTrace([{ label: "Plan request failed", status: "error" }]);
    el.planGrid.innerHTML = "";
    el.agentDot.classList.remove("active");
    showView("plan");
    toast(err.message, "error");
  } finally {
    setBusy(false);
  }
}

/* ═══════════════════════════════════════
   DARK MODE
═══════════════════════════════════════ */
function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  try { localStorage.setItem("costpilot_theme", dark ? "dark" : "light"); } catch {}
}
function toggleDarkMode() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  applyTheme(!isDark);
}
// Restore on load
(function () {
  const saved = (() => { try { return localStorage.getItem("costpilot_theme"); } catch { return null; } })();
  if (saved) applyTheme(saved === "dark");
  else if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) applyTheme(true);
})();
el.darkToggle?.addEventListener("click", toggleDarkMode);

/* ═══════════════════════════════════════
   PERSONAL COST DNA
═══════════════════════════════════════ */
const DNA_KEY = "costpilot_dna_v1";
function loadDNA() {
  try { return JSON.parse(localStorage.getItem(DNA_KEY) || "null"); } catch { return null; }
}
function saveDNA(dna) {
  try { localStorage.setItem(DNA_KEY, JSON.stringify(dna)); } catch {}
}
function updateDNA(type, priority, budget) {
  const dna = loadDNA() || { types: {}, priorities: {}, budgets: [], count: 0 };
  dna.types[type] = (dna.types[type] || 0) + 1;
  dna.priorities[priority] = (dna.priorities[priority] || 0) + 1;
  dna.budgets = [...dna.budgets, budget].slice(-10);
  dna.count = (dna.count || 0) + 1;
  saveDNA(dna);
}
function renderDNAInsight() {
  const dna = loadDNA();
  if (!dna || dna.count < 2) { el.dnaInsight.style.display = "none"; return; }

  const topType = Object.entries(dna.types).sort((a,b)=>b[1]-a[1])[0]?.[0] || "travel";
  const topPri  = Object.entries(dna.priorities).sort((a,b)=>b[1]-a[1])[0]?.[0] || "balanced";
  const avgBudget = Math.round(dna.budgets.reduce((a,b)=>a+b,0) / dna.budgets.length);
  const typeLabel = { travel:"Travel", gadget:"Gadget", relocation:"Relocation", event:"Event" };
  const priLabel  = { balanced:"Balanced", cheap:"Budget", fast:"Speed", quality:"Quality" };

  el.dnaInsight.innerHTML = `
    <span class="dna-label">YOUR COST DNA</span>
    <span class="dna-pill">${typeLabel[topType] || topType}</span>
    <span class="dna-pill">${priLabel[topPri] || topPri}</span>
    <span class="dna-pill">~${money(avgBudget)}</span>
    <span style="margin-left:auto;font-size:.72rem;color:var(--muted)">${dna.count} plans</span>
  `;
  el.dnaInsight.style.display = "flex";
}

/* ═══════════════════════════════════════
   SHAREABLE URL
═══════════════════════════════════════ */
function getShareableURL() {
  if (!state.lastResult || !state.lastPayload) return null;
  try {
    const data = { payload: state.lastPayload, result: state.lastResult, v: 2 };
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(data))));
    return `${window.location.origin}${window.location.pathname}#plan=${encoded}`;
  } catch { return null; }
}
function loadFromURL() {
  const hash = window.location.hash;
  if (!hash.startsWith("#plan=")) return;
  try {
    const data = JSON.parse(decodeURIComponent(escape(atob(hash.slice(6)))));
    window.history.replaceState(null, "", window.location.pathname);
    if (data.v === 2 && data.result) {
      // v2: full result embedded — load directly, no API call needed
      state.lastPayload = data.payload;
      state.type = data.payload?.type || "travel";
      setType(state.type);
      renderPlans(data.result);
      showView("compare");
      toast("Shared plan loaded — view only", "success");
      return;
    }
    // v1 fallback: pre-fill form only
    const payload = data.payload || data;
    setType(payload.type || "travel");
    if (payload.goal) el.goal.value = payload.goal;
    if (payload.budget) { el.budget.value = payload.budget; updateBudget(); }
    if (payload.duration) el.duration.value = payload.duration;
    if (payload.origin) el.origin.value = payload.origin;
    showView("plan");
    toast("Plan loaded from shared link!", "success");
  } catch {}
}
async function copyShareLink() {
  const url = getShareableURL();
  if (!url) { toast("Generate a plan first", "error"); return; }
  try {
    await navigator.clipboard.writeText(url);
    toast("Shareable link copied!", "success");
  } catch { toast("Copy failed", "error"); }
}

/* ═══════════════════════════════════════
   PLAN DOWNLOAD
═══════════════════════════════════════ */
function downloadPlan() {
  const plan = state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) { toast("Select a plan first", "error"); return; }
  const data = {
    exported_at:  new Date().toISOString(),
    app:          "CostPilot AI",
    title:        state.lastResult.title,
    constraints:  state.lastResult.constraints,
    plan: {
      name:              plan.name,
      total_cost:        plan.total_cost,
      budget_delta:      plan.budget_delta_label,
      fit_score:         plan.fit_score,
      explanation:       plan.explanation,
      cost_breakdown:    plan.cost_breakdown,
      tradeoffs:         plan.tradeoffs,
      savings:           plan.savings,
    },
    summary: state.lastResult.summary,
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement("a"), {
    href: url,
    download: `costpilot-${(plan.name || "plan").toLowerCase().replace(/\s+/g,"-")}.json`,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("Plan downloaded as JSON!", "success");
}

/* ═══════════════════════════════════════
   SEASONAL COST PREDICTION
═══════════════════════════════════════ */
const MONTH_NAMES = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
const SEASONAL = {
  travel: {
    jan:"Winter peak — Goa/Rajasthan 20% above base. Try Kerala or Himachal for better value.",
    feb:"Valentine demand spike. Weekday travel 15–20% cheaper than weekends.",
    mar:"Holi week: flights/hotels surge 30%. Book 2 days before or after.",
    apr:"Summer begins — hill station prices rising fast. Book in next 2 weeks.",
    may:"Peak summer pricing. Monsoon destinations (Meghalaya, Coorg) 40% cheaper.",
    jun:"Monsoon opens — Goa hotels drop 50%. Best value window of the year.",
    jul:"Monsoon deep: cheapest travel month. 40–60% off beach hotels.",
    aug:"Independence Day weekend demand spike. Avoid 14–17 Aug for savings.",
    sep:"Monsoon ending — best value before festive season starts.",
    oct:"Navratri/Dussehra pushes prices up. Book 3+ weeks ahead.",
    nov:"Post-Diwali window. Prices normalising before winter peak.",
    dec:"Christmas & New Year peak. Prices 50%+ above base. Book early or go off-beat.",
  },
  gadget: {
    jan:"Republic Day sales — Amazon/Flipkart offer up to 20% off.",
    feb:"Post-sale lull. Prices steady. Wait for Holi sale in March.",
    mar:"Holi sale: 10–15% off flagship devices. Good buy window.",
    apr:"End of fiscal year — EMI offers and buyback deals on premium gadgets.",
    may:"Pre-summer lull. Negotiate extended warranty as add-on.",
    jun:"Flipkart Big Summer sale — up to 25% off on electronics.",
    jul:"Amazon Prime Day — historically the best month to buy gadgets.",
    aug:"Independence Day sales — major electronics discounts.",
    sep:"New model season — buy current-gen at 10–15% off before launch.",
    oct:"Festive season: Navratri/Diwali sales — peak discount window of the year.",
    nov:"Post-Diwali: prices normalise. Good for remaining festive stock.",
    dec:"Year-end clearance — older models discounted before new launches.",
  },
  relocation: {
    jan:"Low demand post-holiday. Landlords negotiate 2-month to 1-month deposits.",
    feb:"Mild demand. Good time to lock in 11-month lease with rent freeze.",
    mar:"Pre-summer rush begins. Lock in price before April peak.",
    apr:"Peak relocation season. Movers 30% costlier. Book 3 weeks ahead.",
    may:"High demand. Negotiate free parking or maintenance as offset.",
    jun:"Demand easing. Good window to negotiate long-term discounts.",
    jul:"Moderate demand. Best month to negotiate 2-month rent-free period.",
    aug:"Mid-year moves common. Standard pricing — compare 3+ movers.",
    sep:"Low demand. Landlords may offer first month at 50% for long leases.",
    oct:"Festive season slows moves. Venue discounts but movers busy.",
    nov:"Steady demand. Normal pricing — good time to plan a Jan move.",
    dec:"Low demand. Year-end — landlords may offer first month free.",
  },
  event: {
    jan:"Off-season for events — venues 30% cheaper. Best month for weddings.",
    feb:"Valentine weekend demand spike for intimate venues — book early.",
    mar:"Pre-summer window. Good venue availability at base price.",
    apr:"Summer weddings peak. AC costs rise — budget extra for venue cooling.",
    may:"Peak outdoor season. Book catering 3 months ahead.",
    jun:"Monsoon: outdoor events risky. Indoor venues discounted 20–30%.",
    jul:"Low demand: venues 40% cheaper. Rainy season indoor weddings.",
    aug:"Still low demand. Best value for large indoor events.",
    sep:"Pre-festive rush — venues and caterers booking up. Plan now.",
    oct:"Navratri/Diwali peak — venues fully booked. Plan 6 months ahead.",
    nov:"Post-Diwali window. Good value before winter wedding season.",
    dec:"Winter weddings peak. New Year events. Premium pricing.",
  },
};
function getSeasonalHint(type) {
  const month = MONTH_NAMES[new Date().getMonth()];
  const sub = SEASONAL[type]?.[month];
  if (!sub) return null;
  return { save: "Timing", label: "Seasonal market insight", sub };
}

/* ═══════════════════════════════════════
   FEATURE 7: TIMING BADGE
   Green = good time, Yellow = neutral, Red = peak/avoid
═══════════════════════════════════════ */
const TIMING_SIGNAL = {
  travel: {
    jan:"red", feb:"yellow", mar:"yellow", apr:"yellow",
    may:"yellow", jun:"green", jul:"green", aug:"yellow",
    sep:"green", oct:"red", nov:"yellow", dec:"red",
  },
  gadget: {
    jan:"green", feb:"yellow", mar:"green", apr:"yellow",
    may:"yellow", jun:"green", jul:"green", aug:"green",
    sep:"yellow", oct:"green", nov:"yellow", dec:"yellow",
  },
  relocation: {
    jan:"green", feb:"green", mar:"yellow", apr:"red",
    may:"red", jun:"yellow", jul:"green", aug:"yellow",
    sep:"yellow", oct:"yellow", nov:"yellow", dec:"green",
  },
  event: {
    jan:"green", feb:"yellow", mar:"green", apr:"yellow",
    may:"yellow", jun:"green", jul:"green", aug:"green",
    sep:"yellow", oct:"red", nov:"yellow", dec:"red",
  },
};
const TIMING_LABELS = {
  green:  "Good time to plan",
  yellow: "Average timing",
  red:    "Peak season — prices high",
};
function getTimingBadge(type) {
  const month = MONTH_NAMES[new Date().getMonth()];
  const signal = TIMING_SIGNAL[type]?.[month] || "yellow";
  return { signal, label: TIMING_LABELS[signal] };
}

/* ═══════════════════════════════════════
   FEATURE 6: BUDGET WARNING BANNER
═══════════════════════════════════════ */
function renderBudgetWarning(plans, budget) {
  if (!el.budgetWarning) return;
  const cheap = plans.find(p => p.id === "cheapest");
  if (!cheap) { el.budgetWarning.style.display = "none"; return; }
  const over = cheap.total_cost - budget;
  if (over <= 0) { el.budgetWarning.style.display = "none"; return; }
  el.budgetWarning.style.display = "block";
  el.budgetWarning.innerHTML = `
    <div class="budget-warning-banner">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
      <span><strong>Budget too low</strong> — cheapest option is ${money(over)} over your budget. Raise budget or simplify your goal.</span>
      <button class="btn-ghost btn-sm" type="button" onclick="el.whatifBar.style.display='block';el.whatifSlider.focus()">Adjust budget →</button>
    </div>`;
}

/* ═══════════════════════════════════════
   FEATURE 4: ALTERNATE DESTINATION SUGGESTER
═══════════════════════════════════════ */
const ALT_DESTINATIONS = {
  travel: {
    "manali":      [{ dest:"Kasol",       saving:.40, desc:"quieter, same Himachal vibe" },
                    { dest:"Chopta",      saving:.50, desc:"less crowded, great trekking" }],
    "goa":         [{ dest:"Pondicherry", saving:.35, desc:"French Quarter, beaches, calmer" },
                    { dest:"Gokarna",     saving:.45, desc:"peaceful beaches, similar vibe" }],
    "ladakh":      [{ dest:"Spiti Valley",saving:.30, desc:"equally scenic, less touristy" },
                    { dest:"Zanskar",     saving:.35, desc:"raw Himalayan beauty" }],
    "mumbai":      [{ dest:"Pune",        saving:.40, desc:"similar culture, 3hr away" }],
    "shimla":      [{ dest:"Dalhousie",   saving:.30, desc:"quieter hill station, colonial charm" }],
    "ooty":        [{ dest:"Kodaikanal",  saving:.25, desc:"similar hills, less crowded" }],
    "andaman":     [{ dest:"Lakshadweep", saving:.20, desc:"pristine beaches, fewer tourists" }],
    "rajasthan":   [{ dest:"Gujarat",     saving:.30, desc:"rich heritage, quieter" }],
    "kerala":      [{ dest:"Coorg",       saving:.35, desc:"coffee hills, similar greenery" }],
    "europe":      [{ dest:"Georgia",     saving:.55, desc:"visa-free, similar charm, far cheaper" },
                    { dest:"Vietnam",     saving:.60, desc:"world-class sights, fraction of cost" }],
    "thailand":    [{ dest:"Vietnam",     saving:.30, desc:"equally vibrant, slightly cheaper" }],
    "singapore":   [{ dest:"Malaysia",    saving:.40, desc:"similar food and culture, cheaper" }],
    "dubai":       [{ dest:"Oman",        saving:.35, desc:"similar Gulf experience, more authentic" }],
    "bali":        [{ dest:"Vietnam",     saving:.25, desc:"beaches + history, cheaper overall" }],
  },
};
function renderAltSuggestions(type, title, budget) {
  if (type !== "travel") return "";
  const dest = title.split(" ")[0]?.toLowerCase();
  const alts = ALT_DESTINATIONS.travel[dest];
  if (!alts?.length) return "";
  const items = alts.map(a => {
    const saved = Math.round(budget * a.saving);
    return `<div class="alt-dest-item">
      <span class="alt-dest-name">${a.dest}</span>
      <span class="alt-dest-desc">${a.desc}</span>
      <span class="alt-dest-save">~${money(saved)} cheaper</span>
    </div>`;
  }).join("");
  return `<div class="alt-suggestions card">
    <div class="alt-suggestions-header">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <strong>Budget-friendly alternatives</strong>
      <span>Similar experience, lower cost</span>
    </div>
    <div class="alt-dest-list">${items}</div>
  </div>`;
}

/* ═══════════════════════════════════════
   FEATURE 5: WHATSAPP SHARE
═══════════════════════════════════════ */
function shareWhatsApp() {
  const plan   = state.chosenPlan || state.lastResult?.plans?.find(p => p.id === state.selectedPlanId);
  const result = state.lastResult;
  if (!plan || !result) { toast("Generate and select a plan first", "error"); return; }
  const lines = [
    `*CostPilot AI Plan*`,
    `*${result.title}*`,
    ``,
    `Plan: ${plan.name} (${plan.badge})`,
    `Total: ${money(plan.total_cost)} | ${plan.budget_delta_label}`,
    `Fit score: ${plan.fit_score}%`,
    ``,
    `*Cost breakdown:*`,
    ...plan.cost_breakdown.map(b => `• ${b.label}: ${money(b.amount)}`),
    ``,
    `Generated by CostPilot AI`,
  ];
  const text = encodeURIComponent(lines.join("\n"));
  window.open(`https://wa.me/?text=${text}`, "_blank", "noopener");
  toast("Opening WhatsApp…", "success");
}

/* ═══════════════════════════════════════
   EMAIL THE PLAN
═══════════════════════════════════════ */
function emailPlan() {
  const plan   = state.chosenPlan || state.lastResult?.plans?.find(p => p.id === state.selectedPlanId);
  const result = state.lastResult;
  if (!plan || !result) { toast("Generate and select a plan first", "error"); return; }

  const subject = encodeURIComponent(`CostPilot AI — ${result.title}`);
  const breakdown = plan.cost_breakdown.map(b => `  • ${b.label}: ${money(b.amount)}`).join("\n");
  const body = encodeURIComponent(
`Hi,

Here's my CostPilot AI plan for: ${result.title}

Plan: ${plan.name} (${plan.badge})
Total cost: ${money(plan.total_cost)} · ${plan.budget_delta_label}
Fit score: ${plan.fit_score}%

Cost breakdown:
${breakdown}

${plan.explanation || ""}

Generated by CostPilot AI
`);
  window.location.href = `mailto:?subject=${subject}&body=${body}`;
  toast("Opening your email app…", "success");
}
document.getElementById("email-plan-btn")?.addEventListener("click", emailPlan);

/* ═══════════════════════════════════════
   ONBOARDING WALKTHROUGH
═══════════════════════════════════════ */
const ONBOARD_KEY = "costpilot_onboarded_v1";
const ONBOARD_STEPS = [
  {
    title: "Set your goal",
    desc: "Type what you want in plain English — a trip, a gadget, a move, or an event. CostPilot figures out the rest.",
    target: "[data-view='plan']",
    icon: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>`,
  },
  {
    title: "Compare plans",
    desc: "Get 4 ranked options from cheapest to premium. Click any plan to see the full cost breakdown and booking links.",
    target: "[data-view='compare']",
    icon: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
  },
  {
    title: "Execute your plan",
    desc: "Share to WhatsApp, email it to yourself, set a price alert, or export for later. One tap to act.",
    target: "[data-view='act']",
    icon: `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  },
];

let onboardStep = 0;

function startOnboarding() {
  try { if (localStorage.getItem(ONBOARD_KEY)) return; } catch {}
  onboardStep = 0;
  showOnboardStep();
}

function showOnboardStep() {
  const overlay = document.getElementById("onboard-overlay");
  const step    = ONBOARD_STEPS[onboardStep];
  if (!step || !overlay) return;

  // Fill content first (while overlay may still be hidden)
  document.getElementById("onboard-step-pills").innerHTML = ONBOARD_STEPS.map((_, i) =>
    `<span class="onboard-pill${i === onboardStep ? " active" : ""}"></span>`
  ).join("");
  document.getElementById("onboard-icon-wrap").innerHTML = step.icon;
  document.getElementById("onboard-title").textContent   = step.title;
  document.getElementById("onboard-desc").textContent    = step.desc;
  document.getElementById("onboard-next").textContent    = onboardStep < ONBOARD_STEPS.length - 1 ? "Next →" : "Let's go!";

  overlay.classList.add("visible");
  document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("onboard-highlight"));
  const target = step.target ? document.querySelector(step.target) : null;
  if (target) target.classList.add("onboard-highlight");
}

function finishOnboarding() {
  const overlay = document.getElementById("onboard-overlay");
  if (overlay) overlay.classList.remove("visible");
  try { localStorage.setItem(ONBOARD_KEY, "1"); } catch {}
}

document.getElementById("onboard-next")?.addEventListener("click", () => {
  onboardStep++;
  if (onboardStep >= ONBOARD_STEPS.length) finishOnboarding();
  else showOnboardStep();
});
document.getElementById("onboard-skip")?.addEventListener("click", finishOnboarding);

// Start after a short delay on first visit
setTimeout(startOnboarding, 1200);

/* ═══════════════════════════════════════
   LIFE EVENT PLANNER
═══════════════════════════════════════ */
const LIFE_ALLOCS = [
  { type:"travel",    label:"Travel",     pct:.20, icon:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21 4 21 4s-2 0-3.5 1.5L14 9 5.8 7.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 3.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>`, desc:"2–3 trips per year including one long-haul or international trip" },
  { type:"gadget",    label:"Gadgets",    pct:.12, icon:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`, desc:"Laptop refresh, phone upgrade, peripherals, and warranty" },
  { type:"event",     label:"Events",     pct:.15, icon:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>`, desc:"Celebrations, weddings attended, gifts, and dining out" },
  { type:"relocation",label:"Housing",    pct:.53, icon:`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>`, desc:"Rent, deposit, utilities, internet, and setup costs" },
];
function renderLifePlan() {
  const budget = Number(el.lifeBudget.value);
  const city   = el.lifeCity.value;
  const savings = Math.round(budget * 0.12);
  const spendable = budget - savings;
  const emergency = Math.round(budget * 0.08);

  el.lifeResult.style.display = "block";
  el.lifeSummary.innerHTML = `
    <div class="life-stat"><div class="life-stat-label">Annual budget</div><div class="life-stat-value">${money(budget)}</div></div>
    <div class="life-stat"><div class="life-stat-label">Suggested savings</div><div class="life-stat-value" style="color:var(--green)">${money(savings)}</div></div>
    <div class="life-stat"><div class="life-stat-label">Emergency fund</div><div class="life-stat-value" style="color:var(--gold)">${money(emergency)}</div></div>
  `;

  const spendBudget = spendable - emergency;
  el.lifeCategories.innerHTML = LIFE_ALLOCS.map((cat) => {
    const amount = Math.round(spendBudget * cat.pct);
    const pctOfTotal = Math.round(cat.pct * 85); // visual scale
    return `
      <div class="life-cat">
        <div class="life-cat-icon ${cat.type}">${cat.icon}</div>
        <div>
          <div class="life-cat-name">${cat.label}</div>
          <div class="life-cat-desc">${cat.desc}</div>
          <div class="life-cat-bar-track" style="margin-top:10px"><div class="life-cat-bar-fill ${cat.type}" style="width:${pctOfTotal}%"></div></div>
        </div>
        <div>
          <div class="life-cat-amount">${money(amount)}</div>
          <div class="life-cat-pct">${Math.round(cat.pct*100)}% of spend</div>
        </div>
      </div>`;
  }).join("");

  toast(`Budget allocated across ${LIFE_ALLOCS.length} life categories`, "success");
}

/* ═══════════════════════════════════════
   FORM AUTOSAVE
═══════════════════════════════════════ */
const FORM_SAVE_KEY = "costpilot_form_v1";
function saveForm() {
  try {
    localStorage.setItem(FORM_SAVE_KEY, JSON.stringify({
      type:     state.type,
      goal:     el.goal.value,
      budget:   el.budget.value,
      duration: el.duration.value,
      origin:   el.origin.value,
    }));
  } catch {}
}
function restoreForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(FORM_SAVE_KEY) || "null");
    if (!saved) return;
    setType(saved.type || "travel");
    if (saved.goal)     el.goal.value     = saved.goal;
    if (saved.budget)   { el.budget.value = saved.budget; updateBudget(); }
    if (saved.duration) el.duration.value = saved.duration;
    if (saved.origin)   el.origin.value   = saved.origin;
  } catch {}
}

/* ═══════════════════════════════════════
   SAVED / BOOKMARKED PLANS
═══════════════════════════════════════ */
const SAVED_KEY = "costpilot_saved_v1";
function loadSaved() { try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"); } catch { return []; } }
function writeSaved(arr) { try { localStorage.setItem(SAVED_KEY, JSON.stringify(arr.slice(0, 20))); } catch {} }

function toggleSavePlan(entry) {
  const arr = loadSaved();
  const idx = arr.findIndex((x) => x.id === entry.id);
  if (idx >= 0) {
    arr.splice(idx, 1);
    writeSaved(arr);
    toast("Bookmark removed", "default");
  } else {
    arr.unshift({ ...entry, saved_at: Date.now() / 1000 });
    writeSaved(arr);
    toast("Plan bookmarked!", "success");
  }
  updateSavedCount();
  return idx < 0; // true = now saved
}

function isSaved(id) { return loadSaved().some((x) => x.id === id); }

function updateSavedCount() {
  const n = loadSaved().length;
  el.savedCount.textContent = n;
  el.savedCount.style.display = n ? "inline" : "none";
}

let _historyTab = "recent";
function switchHistoryTab(tab) {
  _historyTab = tab;
  el.htabRecent.classList.toggle("active", tab === "recent");
  el.htabSaved.classList.toggle("active", tab === "saved");
  if (tab === "recent") renderHistoryView(loadStoredHistory());
  else renderHistoryView(loadSaved(), true);
}

/* ═══════════════════════════════════════
   PROGRESS TRACKER
═══════════════════════════════════════ */
function loadProgress() {
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || "{}"); } catch { return {}; }
}
function saveProgress(title, amount) {
  const p = loadProgress();
  p[title] = amount;
  try { localStorage.setItem(PROGRESS_KEY, JSON.stringify(p)); } catch {}
}
function renderProgressTracker(plan, title, budget) {
  const card = $("progress-tracker-card");
  if (!card || !plan) { if (card) card.style.display = "none"; return; }
  card.style.display = "";

  const max = plan.total_cost || budget || 100000;
  const slider = $("progress-slider");
  const fill   = $("progress-track-fill");
  const savedLabel = $("progress-saved-label");
  const goalLabel  = $("progress-goal-label");
  const desc  = $("progress-desc");

  if (desc) desc.textContent = `How much have you saved toward "${title || "your goal"}"?`;

  const progData = loadProgress();
  const saved = progData[title] || 0;

  if (slider) { slider.max = max; slider.value = saved; }
  if (goalLabel) goalLabel.textContent = `of ${money(max)}`;

  function updateBar(val) {
    const pct = max > 0 ? Math.min(100, Math.round(val / max * 100)) : 0;
    if (fill) fill.style.width = pct + "%";
    if (savedLabel) savedLabel.textContent = money(val) + " saved";
  }
  updateBar(saved);

  if (slider) {
    slider.oninput = () => updateBar(Number(slider.value));
  }
  const saveBtn = $("progress-save-btn");
  if (saveBtn) {
    saveBtn.onclick = () => {
      const val = Number(slider?.value || 0);
      saveProgress(title, val);
      toast("Savings updated!", "success");
    };
  }
}

/* ═══════════════════════════════════════
   PDF EXPORT
═══════════════════════════════════════ */
function exportPDF() {
  const plan = state.chosenPlan || state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) { toast("Select a plan first", "error"); return; }
  const result = state.lastResult;
  const budget = result?.constraints?.budget || 0;
  const over   = plan.total_cost > budget;

  el.pdfFrame.innerHTML = `
    <div class="pdf-title">${result?.title || "CostPilot Plan"}</div>
    <div class="pdf-sub">Generated by CostPilot AI · ${new Date().toLocaleDateString("en-IN",{day:"numeric",month:"long",year:"numeric"})}</div>
    <span class="pdf-badge">${plan.badge} — ${plan.name}</span>

    <div class="pdf-section">
      <div class="pdf-section-label">Goal</div>
      <div style="font-size:.88rem;color:#333">${result?.constraints?.goal || ""}</div>
    </div>

    <div class="pdf-section">
      <div class="pdf-section-label">Cost summary</div>
      <div class="pdf-row"><span>Total cost</span><strong>${money(plan.total_cost)}</strong></div>
      <div class="pdf-row"><span>Budget</span><span>${money(budget)}</span></div>
      <div class="pdf-row"><span>Budget status</span><span style="color:${over?"#e11d48":"#0a7a55"}">${plan.budget_delta_label}</span></div>
      <div class="pdf-row"><span>Fit score</span><span>${plan.fit_score}%</span></div>
    </div>

    <div class="pdf-section">
      <div class="pdf-section-label">Cost breakdown</div>
      ${plan.cost_breakdown.map((b) => `<div class="pdf-row"><span>${b.label}</span><span>${money(b.amount)}</span></div>`).join("")}
    </div>

    <div class="pdf-section">
      <div class="pdf-section-label">Trade-offs</div>
      <ul class="pdf-tradeoffs">${plan.tradeoffs.map((t) => `<li>${t}</li>`).join("")}</ul>
    </div>

    <div class="pdf-section">
      <div class="pdf-section-label">Savings opportunities</div>
      <ul class="pdf-tradeoffs">${plan.savings.map((s) => `<li>${s}</li>`).join("")}</ul>
    </div>
  `;

  window.print();
  toast("Print dialog opened — save as PDF", "default", 4000);
}


/* ═══════════════════════════════════════
   MODAL SYSTEM
═══════════════════════════════════════ */
function openModal(modalEl) {
  document.querySelectorAll(".modal").forEach((m) => m.classList.remove("active"));
  modalEl.classList.add("active");
  el.modalOverlay.classList.add("open");
  el.modalOverlay.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  modalEl.querySelector("input:not([readonly]),textarea")?.focus();
}
function closeModal() {
  el.modalOverlay.classList.remove("open");
  el.modalOverlay.setAttribute("aria-hidden", "true");
  document.querySelectorAll(".modal").forEach((m) => m.classList.remove("active"));
  document.body.style.overflow = "";
}
el.modalOverlay?.addEventListener("click", (e) => {
  if (e.target === el.modalOverlay) closeModal();
});
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-close-modal]")) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && el.modalOverlay?.classList.contains("open")) { closeModal(); e.preventDefault(); }
});

/* ═══════════════════════════════════════
   PRICE ALERT MODAL
═══════════════════════════════════════ */
const ALERTS_KEY = "costpilot_alerts_v1";
function loadAlerts() { try { return JSON.parse(localStorage.getItem(ALERTS_KEY) || "[]"); } catch { return []; } }
function saveAlerts(alerts) { try { localStorage.setItem(ALERTS_KEY, JSON.stringify(alerts.slice(0, 20))); } catch {} }

function openAlertModal() {
  const plan = state.chosenPlan || state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) { toast("Choose a plan first from the Compare view", "error"); return; }
  el.alertPlanName.value = `${state.lastResult?.title || "Plan"} — ${plan.name}`;
  const threshold = Math.round(plan.total_cost * 0.9);
  el.alertThreshold.min = Math.round(plan.total_cost * 0.5);
  el.alertThreshold.max = Math.round(plan.total_cost * 1.1);
  el.alertThreshold.value = threshold;
  el.alertThresholdOutput.textContent = money(threshold);
  el.alertNote.value = "";
  openModal(el.alertModal);
}

el.alertThreshold?.addEventListener("input", () => {
  el.alertThresholdOutput.textContent = money(el.alertThreshold.value);
});

el.saveAlertBtn?.addEventListener("click", () => {
  const plan = state.chosenPlan || state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) return;
  const alert = {
    id:        Date.now(),
    plan_name: el.alertPlanName.value,
    threshold: Number(el.alertThreshold.value),
    note:      el.alertNote.value.trim(),
    created_at: Date.now() / 1000,
  };
  const alerts = loadAlerts();
  alerts.unshift(alert);
  saveAlerts(alerts);
  closeModal();
  toast(`Alert saved — notify me if under ${money(alert.threshold)}`, "success", 4000);
});

/* ═══════════════════════════════════════
   DRAFT MESSAGE MODAL (AI NEGOTIATOR)
═══════════════════════════════════════ */
const NEGOTIATOR_TEMPLATES = {
  travel: (plan, type) => `Subject: Pricing inquiry — ${plan.name} travel package

Hi,

I've been comparing travel options for my upcoming trip and have found packages in a similar range to ${money(plan.total_cost)} covering transit, accommodation, and local transport.

Key breakdown I'm working with:
${plan.cost_breakdown.slice(0, 3).map((b) => `• ${b.label}: ${money(b.amount)}`).join("\n")}

I'm ready to confirm quickly if you can match or come close to this budget. Could you share your best available rate?

Looking forward to your response.`,

  gadget: (plan) => `Subject: Purchase inquiry — price match request

Hi,

I'm looking to purchase a device and have researched market prices. Based on current listings, I'm targeting around ${money(plan.total_cost)} inclusive of warranty and accessories.

My budget allocation:
${plan.cost_breakdown.slice(0, 3).map((b) => `• ${b.label}: ${money(b.amount)}`).join("\n")}

If you can match or improve on this, I'm prepared to complete the purchase immediately. Please let me know your best offer.

Thanks`,

  relocation: (plan) => `Subject: Relocation services inquiry

Hi,

I'm planning a move and have received several quotes. My target is ${money(plan.total_cost)} covering moving, setup, and the first month's deposit.

Key items I need priced:
${plan.cost_breakdown.slice(0, 3).map((b) => `• ${b.label}: ${money(b.amount)}`).join("\n")}

I'd like to finalise within the next few days. Could you provide a competitive quote that covers these items?

Best regards`,

  event: (plan) => `Subject: Event planning inquiry — budget ${money(plan.total_cost)}

Hi,

I'm organising an event and am comparing vendors. My total budget is ${money(plan.total_cost)}, allocated roughly as:
${plan.cost_breakdown.slice(0, 3).map((b) => `• ${b.label}: ${money(b.amount)}`).join("\n")}

I've received competing quotes in this range. If you can work within this budget with good quality, I'd love to discuss further. What packages can you offer?

Thank you`,
};

function openDraftModal() {
  const plan = state.chosenPlan || state.lastResult?.plans?.find((p) => p.id === state.selectedPlanId);
  if (!plan) { toast("Choose a plan first from the Compare view", "error"); return; }
  const templateFn = NEGOTIATOR_TEMPLATES[state.type] || NEGOTIATOR_TEMPLATES.travel;
  el.draftMsgText.value = templateFn(plan, state.type);
  openModal(el.draftModal);
}

el.copyDraftBtn?.addEventListener("click", () => {
  navigator.clipboard.writeText(el.draftMsgText.value)
    .then(() => { toast("Negotiation message copied!", "success"); closeModal(); })
    .catch(() => toast("Copy failed", "error"));
});

/* ═══════════════════════════════════════
   ACT VIEW ACTIONS
═══════════════════════════════════════ */
el.createAlertBtn?.addEventListener("click", openAlertModal);
el.draftMsgBtn?.addEventListener("click", openDraftModal);
el.shareActBtn?.addEventListener("click", copyPlan);
el.copyLinkBtn?.addEventListener("click", copyShareLink);
el.downloadPlanBtn?.addEventListener("click", downloadPlan);
el.exportPdfBtn?.addEventListener("click", exportPDF);
el.htabRecent?.addEventListener("click", () => switchHistoryTab("recent"));
el.htabSaved?.addEventListener("click",  () => switchHistoryTab("saved"));
el.whatsappShareBtn?.addEventListener("click", shareWhatsApp);

/* ═══════════════════════════════════════
   EVENT DELEGATION
═══════════════════════════════════════ */
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-view]");
  if (!btn) return;
  const view = btn.dataset.view;
  const type = btn.dataset.type;
  if (type) { setType(type); }
  showView(view);
});

/* ═══════════════════════════════════════
   WIRING
═══════════════════════════════════════ */
document.querySelectorAll(".persona-btn").forEach((b) => b.addEventListener("click", () => setType(b.dataset.type)));
el.budget.addEventListener("input", () => { updateBudget(); saveForm(); });
el.goal.addEventListener("input", saveForm);
el.duration.addEventListener("input", saveForm);
el.origin.addEventListener("change", saveForm);
el.form.addEventListener("submit", (e) => { e.preventDefault(); generatePlan(getPayload()); });
el.refreshBtn.addEventListener("click", () => { if (state.lastPayload) generatePlan(state.lastPayload); });
el.shareBtn.addEventListener("click", copyPlan);
el.compareToggleBtn.addEventListener("click", toggleCompareMode);
el.csClose.addEventListener("click", () => {
  el.compareSide.style.display = "none";
  state.comparePlanIds = [];
  renderPlanCards(state.lastResult?.plans || []);
});
el.clearHistoryBtn?.addEventListener("click", () => {
  if (confirm("Clear all saved history?")) clearHistory();
});

// Life Event Planner
el.lifeBudget?.addEventListener("input", () => {
  el.lifeBudgetOutput.textContent = money(el.lifeBudget.value);
});
el.lifePlanBtn?.addEventListener("click", renderLifePlan);

/* ═══════════════════════════════════════
   KEYBOARD SHORTCUTS
═══════════════════════════════════════ */
document.addEventListener("keydown", (e) => {
  // Skip if typing in an input/textarea
  if (e.target.closest("input,textarea,select")) return;
  // Skip if modal is open
  if (el.modalOverlay?.classList.contains("open")) return;

  switch (e.key) {
    case "/":
      e.preventDefault();
      showView("plan");
      el.goal?.focus();
      break;
    case "h":
      if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); showView("home"); }
      break;
    case "c":
      if (!e.metaKey && !e.ctrlKey && state.lastResult) { e.preventDefault(); showView("compare"); }
      break;
    case "a":
      if (!e.metaKey && !e.ctrlKey && state.chosenPlan) { e.preventDefault(); showView("act"); }
      break;
    case "d":
      if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); toggleDarkMode(); }
      break;
    case "1": case "2": case "3": case "4": {
      const idx = Number(e.key) - 1;
      const plans = state.lastResult?.plans;
      if (plans?.[idx] && state.view === "compare") {
        e.preventDefault();
        selectPlan(plans[idx].id);
        toast(`Selected: ${plans[idx].name}`, "default", 1800);
      }
      break;
    }
  }
});

/* ═══════════════════════════════════════
   INIT
═══════════════════════════════════════ */
setJourneyStage(0);
restoreForm();
loadHealth();
renderHistoryView(loadStoredHistory());
updateSavedCount();
loadFromURL();
if (!window.location.hash) {
  showView("home");
  setTimeout(showOnboarding, 600);
}
