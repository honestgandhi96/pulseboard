const state = {
  q: "",
  sourceId: "",
  limit: 20,
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
  limitSelect: document.getElementById("limit-select"),
  newsGrid: document.getElementById("news-grid"),
  emptyState: document.getElementById("empty-state"),
  meta: document.getElementById("meta"),
  prevBtn: document.getElementById("prev-btn"),
  nextBtn: document.getElementById("next-btn"),
  pageLabel: document.getElementById("page-label"),
  cardTemplate: document.getElementById("card-template"),
};

function buildArticleUrl() {
  const params = new URLSearchParams();
  params.set("limit", String(state.limit));
  params.set("offset", String(state.offset));
  if (state.q.trim()) {
    params.set("q", state.q.trim());
  }
  if (state.sourceId) {
    params.set("source_id", state.sourceId);
  }
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

    const link = fragment.querySelector(".read-link");
    link.href = article.original_url;

    els.newsGrid.appendChild(fragment);
  });
}

function renderMeta(pagination) {
  const showingFrom = pagination.total === 0 ? 0 : pagination.offset + 1;
  const showingTo = pagination.offset + pagination.returned;
  els.meta.textContent = `Showing ${showingFrom}-${showingTo} of ${pagination.total} articles`;

  els.pageLabel.textContent = pagination.total_pages
    ? `Page ${pagination.current_page} of ${pagination.total_pages}`
    : "Page 0";

  els.prevBtn.disabled = !pagination.has_prev;
  els.nextBtn.disabled = !pagination.has_next;
}

async function fetchArticles() {
  const resp = await fetch(buildArticleUrl());
  if (!resp.ok) {
    els.meta.textContent = "Failed to load feed.";
    return;
  }

  const payload = await resp.json();
  state.pagination = payload.pagination;
  renderCards(payload.items || []);
  renderMeta(payload.pagination || state.pagination);
}

function resetOffset() {
  state.offset = 0;
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

els.limitSelect.addEventListener("change", async () => {
  state.limit = Number(els.limitSelect.value) || 20;
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

(async function init() {
  await fetchSources();
  await fetchArticles();
})();
