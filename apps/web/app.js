const DEFAULT_LIMIT = 20;

const state = {
  q: "",
  sourceId: "",
  symbol: "",
  sector: "",
  topic: "",
  limit: DEFAULT_LIMIT,
  offset: 0,
  pagination: {
    total: 0,
    current_page: 1,
    total_pages: 0,
    has_next: false,
    has_prev: false,
    next_offset: null,
    prev_offset: null,
  },
};

const els = {
  searchForm: document.getElementById("search-form"),
  searchInput: document.getElementById("search-input"),
  sourceSelect: document.getElementById("source-select"),
  sortSelect: document.getElementById("sort-select"),
  limitSelect: document.getElementById("limit-select"),
  newsGrid: document.getElementById("news-grid"),
  emptyState: document.getElementById("empty-state"),
  meta: document.getElementById("meta"),
  prevBtn: document.getElementById("prev-btn"),
  nextBtn: document.getElementById("next-btn"),
  pageLabel: document.getElementById("page-label"),
  cardTemplate: document.getElementById("card-template"),
  trendingSymbols: document.getElementById("trending-symbols"),
  trendingTopics: document.getElementById("trending-topics"),
  trendingSectors: document.getElementById("trending-sectors"),
  activeFilters: document.getElementById("active-filters"),
  clearFilterButtons: Array.from(document.querySelectorAll("[data-clear-filter]")),
};

function readStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  state.q = params.get("q") || "";
  state.sourceId = params.get("source_id") || "";
  state.symbol = params.get("symbol") || "";
  state.sector = params.get("sector") || "";
  state.topic = params.get("topic") || "";
  state.limit = Number(params.get("limit")) || DEFAULT_LIMIT;
  state.offset = Number(params.get("offset")) || 0;
}

function syncUrl() {
  const params = new URLSearchParams();
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.sourceId) params.set("source_id", state.sourceId);
  if (state.symbol) params.set("symbol", state.symbol);
  if (state.sector) params.set("sector", state.sector);
  if (state.topic) params.set("topic", state.topic);
  if (state.limit !== DEFAULT_LIMIT) params.set("limit", String(state.limit));
  if (state.offset > 0) params.set("offset", String(state.offset));
  const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ""}`;
  window.history.replaceState({}, "", next);
}

function applyStateToControls() {
  els.searchInput.value = state.q;
  els.sourceSelect.value = state.sourceId;
  els.limitSelect.value = String(state.limit);

  if (state.symbol) {
    els.sortSelect.value = "symbol";
  } else if (state.topic) {
    els.sortSelect.value = "topic";
  } else {
    els.sortSelect.value = "all";
  }
}

function buildArticleUrl() {
  const params = new URLSearchParams();
  params.set("limit", String(state.limit));
  params.set("offset", String(state.offset));
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.sourceId) params.set("source_id", state.sourceId);
  if (state.symbol) params.set("symbol", state.symbol);
  if (state.sector) params.set("sector", state.sector);
  if (state.topic) params.set("topic", state.topic);
  return `/v1/articles?${params.toString()}`;
}

async function fetchSources() {
  const resp = await fetch("/v1/sources?status=active");
  const sources = await resp.json();

  for (const source of sources) {
    const opt = document.createElement("option");
    opt.value = String(source.id);
    opt.textContent = source.name;
    els.sourceSelect.appendChild(opt);
  }
}

async function fetchTrending() {
  const resp = await fetch("/v1/tags/trending?limit=8");
  if (!resp.ok) return;
  const payload = await resp.json();
  renderTrendingGroup(els.trendingSymbols, payload.symbols || [], "symbol");
  renderTrendingGroup(els.trendingTopics, payload.topics || [], "topic");
  renderTrendingGroup(els.trendingSectors, payload.sectors || [], "sector");
}

function renderTrendingGroup(root, items, filterType) {
  root.innerHTML = "";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trend-chip";
    button.dataset.filterType = filterType;
    button.dataset.filterValue = item.key;
    button.innerHTML = `<span>${item.label}</span><strong>${item.article_count}</strong>`;
    root.appendChild(button);
  });
}

function formatDate(value) {
  if (!value) return "Unknown time";
  const dt = new Date(value.replace(" ", "T") + "Z");
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function summarize(text) {
  const clean = (text || "").replace(/<[^>]*>/g, "").trim();
  if (!clean) return "No summary available.";
  return clean.length > 220 ? `${clean.slice(0, 217)}...` : clean;
}

function renderTagGroup(root, items, filterType, maxItems) {
  root.innerHTML = "";
  items.slice(0, maxItems).forEach((tag) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `article-chip ${filterType}`;
    button.dataset.filterType = filterType;
    button.dataset.filterValue = tag.key;
    button.textContent = tag.label;
    root.appendChild(button);
  });
}

function renderCards(items) {
  els.newsGrid.innerHTML = "";
  els.emptyState.classList.toggle("hidden", items.length > 0);

  items.forEach((article, idx) => {
    const fragment = els.cardTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".card");
    card.style.animationDelay = `${Math.min(idx * 40, 320)}ms`;

    fragment.querySelector(".source-tag").textContent = article.source_name;
    fragment.querySelector(".published-at").textContent = formatDate(article.published_at || article.fetched_at);
    fragment.querySelector(".title").textContent = article.title;
    fragment.querySelector(".summary").textContent = summarize(article.summary);

    renderTagGroup(fragment.querySelector('[data-group="symbols"]'), article.symbols || [], "symbol", 2);
    renderTagGroup(fragment.querySelector('[data-group="sectors"]'), article.sectors || [], "sector", 1);
    renderTagGroup(fragment.querySelector('[data-group="topics"]'), article.topics || [], "topic", 2);

    const link = fragment.querySelector(".read-link");
    link.href = article.original_url;

    els.newsGrid.appendChild(fragment);
  });
}

function renderMeta(pagination) {
  const showingFrom = pagination.total === 0 ? 0 : pagination.offset + 1;
  const showingTo = pagination.offset + pagination.returned;
  let suffix = "";
  if (state.symbol) suffix = ` for symbol ${state.symbol.toUpperCase()}`;
  if (state.topic) suffix = ` for topic ${state.topic.replace(/-/g, " ")}`;
  if (state.sector) suffix = ` in ${state.sector.replace(/-/g, " ")} sector`;
  els.meta.textContent = `Showing ${showingFrom}-${showingTo} of ${pagination.total} articles${suffix}`;

  els.pageLabel.textContent = pagination.total_pages
    ? `Page ${pagination.current_page} of ${pagination.total_pages}`
    : "Page 0";

  els.prevBtn.disabled = !pagination.has_prev;
  els.nextBtn.disabled = !pagination.has_next;
}

function renderActiveFilters() {
  const filters = [];
  if (state.symbol) filters.push({ type: "symbol", label: `Symbol: ${state.symbol.toUpperCase()}` });
  if (state.topic) filters.push({ type: "topic", label: `Topic: ${state.topic.replace(/-/g, " ")}` });
  if (state.sector) filters.push({ type: "sector", label: `Sector: ${state.sector.replace(/-/g, " ")}` });
  if (state.sourceId) {
    const sourceLabel = els.sourceSelect.selectedOptions[0]?.textContent || state.sourceId;
    filters.push({ type: "source", label: `Source: ${sourceLabel}` });
  }
  if (state.q.trim()) filters.push({ type: "q", label: `Search: ${state.q.trim()}` });

  els.activeFilters.innerHTML = "";
  els.activeFilters.classList.toggle("hidden", filters.length === 0);

  filters.forEach((filter) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "active-filter-pill";
    pill.dataset.clearFilter = filter.type;
    pill.textContent = `${filter.label} ×`;
    els.activeFilters.appendChild(pill);
  });
}

async function fetchArticles() {
  syncUrl();
  const resp = await fetch(buildArticleUrl());
  if (!resp.ok) {
    els.meta.textContent = "Failed to load feed.";
    return;
  }

  const payload = await resp.json();
  state.pagination = payload.pagination;
  renderCards(payload.items || []);
  renderMeta(payload.pagination || state.pagination);
  renderActiveFilters();
}

function resetOffset() {
  state.offset = 0;
}

function clearLens(target) {
  if (target === "symbol") state.symbol = "";
  if (target === "topic") state.topic = "";
  if (target === "sector") state.sector = "";
  if (target === "source") state.sourceId = "";
  if (target === "q") state.q = "";
  if (!state.symbol && !state.topic) {
    els.sortSelect.value = "all";
  }
}

function applyTagFilter(filterType, filterValue) {
  if (filterType === "symbol") {
    state.symbol = filterValue;
    state.topic = "";
    els.sortSelect.value = "symbol";
  } else if (filterType === "topic") {
    state.topic = filterValue;
    state.symbol = "";
    els.sortSelect.value = "topic";
  } else if (filterType === "sector") {
    state.sector = filterValue;
  }
  resetOffset();
  fetchArticles();
}

els.searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  state.q = els.searchInput.value;
  resetOffset();
  await fetchArticles();
});

els.sourceSelect.addEventListener("change", async () => {
  state.sourceId = els.sourceSelect.value;
  resetOffset();
  await fetchArticles();
});

els.sortSelect.addEventListener("change", async () => {
  if (els.sortSelect.value === "all") {
    state.symbol = "";
    state.topic = "";
  } else if (els.sortSelect.value === "symbol" && !state.symbol) {
    state.topic = "";
  } else if (els.sortSelect.value === "topic" && !state.topic) {
    state.symbol = "";
  }
  resetOffset();
  await fetchArticles();
});

els.limitSelect.addEventListener("change", async () => {
  state.limit = Number(els.limitSelect.value) || DEFAULT_LIMIT;
  resetOffset();
  await fetchArticles();
});

els.prevBtn.addEventListener("click", async () => {
  if (!state.pagination.has_prev) return;
  state.offset = state.pagination.prev_offset;
  await fetchArticles();
});

els.nextBtn.addEventListener("click", async () => {
  if (!state.pagination.has_next) return;
  state.offset = state.pagination.next_offset;
  await fetchArticles();
});

document.addEventListener("click", async (event) => {
  const filterEl = event.target.closest("[data-filter-type]");
  if (filterEl) {
    applyTagFilter(filterEl.dataset.filterType, filterEl.dataset.filterValue);
    return;
  }

  const clearEl = event.target.closest("[data-clear-filter]");
  if (clearEl) {
    clearLens(clearEl.dataset.clearFilter);
    applyStateToControls();
    resetOffset();
    await fetchArticles();
  }
});

window.addEventListener("popstate", async () => {
  readStateFromUrl();
  applyStateToControls();
  await fetchArticles();
});

(async function init() {
  readStateFromUrl();
  await fetchSources();
  applyStateToControls();
  await fetchTrending();
  await fetchArticles();
})();
