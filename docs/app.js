const DATA_URL = "./data/movies.json";

const state = {
  movies: [],
  sources: [],
  cinema: "all",
  query: "",
  sort: "rank",
};

const labels = {
  cgv: "CGV",
  lotte: "롯데시네마",
  megabox: "메가박스",
};

const grid = document.querySelector("#movieGrid");
const template = document.querySelector("#movieCardTemplate");
const emptyState = document.querySelector("#emptyState");
const updatedAt = document.querySelector("#updatedAt");
const visibleCount = document.querySelector("#visibleCount");
const sourceAlerts = document.querySelector("#sourceAlerts");
const searchInput = document.querySelector("#searchInput");
const sortSelect = document.querySelector("#sortSelect");

function parseDate(value) {
  if (!value) return 0;
  const date = new Date(`${value}T00:00:00+09:00`);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function formatGeneratedAt(value) {
  if (!value) return "정보 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(date);
}

function bySort(a, b) {
  if (state.sort === "rate") {
    return (b.reservationRate ?? -1) - (a.reservationRate ?? -1) || byRank(a, b);
  }
  if (state.sort === "release") {
    return parseDate(b.releaseDate) - parseDate(a.releaseDate) || byRank(a, b);
  }
  if (state.sort === "title") {
    return a.title.localeCompare(b.title, "ko") || byRank(a, b);
  }
  return byRank(a, b);
}

function byRank(a, b) {
  return (
    a.cinemaLabel.localeCompare(b.cinemaLabel, "ko") ||
    (a.rank ?? 9999) - (b.rank ?? 9999) ||
    a.title.localeCompare(b.title, "ko")
  );
}

function getFilteredMovies() {
  const query = state.query.trim().toLocaleLowerCase("ko-KR");
  return state.movies
    .filter((movie) => state.cinema === "all" || movie.cinema === state.cinema)
    .filter((movie) => !query || movie.title.toLocaleLowerCase("ko-KR").includes(query))
    .sort(bySort);
}

function countByCinema(cinema) {
  return state.movies.filter((movie) => movie.cinema === cinema).length;
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value;
}

function renderSummary() {
  setText("#totalCount", state.movies.length.toLocaleString("ko-KR"));
  setText("#cgvCount", countByCinema("cgv").toLocaleString("ko-KR"));
  setText("#lotteCount", countByCinema("lotte").toLocaleString("ko-KR"));
  setText("#megaboxCount", countByCinema("megabox").toLocaleString("ko-KR"));
}

function renderAlerts() {
  const failed = state.sources.filter((source) => source.status !== "ok");
  sourceAlerts.replaceChildren();
  failed.forEach((source) => {
    const item = document.createElement("div");
    item.className = "source-alert";
    item.textContent = `${source.cinemaLabel}: ${source.message}`;
    sourceAlerts.append(item);
  });
}

function renderCards() {
  const movies = getFilteredMovies();
  grid.replaceChildren();
  visibleCount.textContent = movies.length.toLocaleString("ko-KR");
  emptyState.hidden = movies.length > 0;

  movies.forEach((movie) => {
    const fragment = template.content.cloneNode(true);
    const card = fragment.querySelector(".movie-card");
    const link = fragment.querySelector(".poster-link");
    const img = fragment.querySelector(".poster");
    const badge = fragment.querySelector(".cinema-badge");

    card.dataset.cinema = movie.cinema;
    link.href = movie.detailUrl || movie.sourceUrl || "#";
    img.alt = `${movie.title} 포스터`;
    if (movie.posterUrl) {
      img.src = movie.posterUrl;
    } else {
      img.classList.add("is-hidden");
    }
    img.addEventListener("error", () => img.classList.add("is-hidden"), { once: true });

    badge.textContent = labels[movie.cinema] || movie.cinemaLabel || movie.cinema;
    badge.classList.add(movie.cinema);
    fragment.querySelector(".rank").textContent = movie.rank ? `#${movie.rank}` : "";
    fragment.querySelector(".movie-title").textContent = movie.title;
    fragment.querySelector(".rate").textContent = movie.reservationRateText || "-";
    fragment.querySelector(".release").textContent = movie.releaseDate || "-";
    grid.append(fragment);
  });
}

function render() {
  renderSummary();
  renderAlerts();
  renderCards();
}

async function loadMovies() {
  const response = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`데이터를 불러오지 못했습니다. (${response.status})`);
  const data = await response.json();
  state.movies = Array.isArray(data.movies) ? data.movies : [];
  state.sources = Array.isArray(data.sources) ? data.sources : [];
  updatedAt.textContent = formatGeneratedAt(data.generatedAt);
  render();
}

document.querySelectorAll(".filter-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter-button").forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    state.cinema = button.dataset.cinema || "all";
    renderCards();
  });
});

searchInput.addEventListener("input", (event) => {
  state.query = event.target.value;
  renderCards();
});

sortSelect.addEventListener("change", (event) => {
  state.sort = event.target.value;
  renderCards();
});

loadMovies().catch((error) => {
  updatedAt.textContent = "데이터 오류";
  sourceAlerts.innerHTML = "";
  const item = document.createElement("div");
  item.className = "source-alert";
  item.textContent = error.message;
  sourceAlerts.append(item);
  emptyState.hidden = false;
});
