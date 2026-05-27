from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from base64 import b64decode
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except Exception:  # pragma: no cover - selenium is optional at import time.
    webdriver = None
    ChromeOptions = None
    By = None
    EC = None
    WebDriverWait = None
    TimeoutException = WebDriverException = Exception


KST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


@dataclass(frozen=True)
class Movie:
    cinema: str
    cinemaLabel: str
    title: str
    posterUrl: str | None
    reservationRate: float | None
    reservationRateText: str
    releaseDate: str | None
    rank: int | None
    detailUrl: str | None
    sourceUrl: str
    sourceId: str | None = None


@dataclass(frozen=True)
class SourceStatus:
    cinema: str
    cinemaLabel: str
    sourceUrl: str
    status: str
    count: int
    message: str


class CrawlerError(RuntimeError):
    """Raised when one source cannot be crawled."""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    return re.sub(r"\s+", " ", text).strip()


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )
    return session


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def percent_text(value: float | None) -> str:
    if value is None:
        return "-"
    formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def parse_date(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    candidates = [
        r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})",
        r"(\d{4})(\d{2})(\d{2})",
    ]
    for pattern in candidates:
        match = re.search(pattern, text)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def normalize_url(url: str | None, base: str) -> str | None:
    if not url:
        return None
    value = html.unescape(url.strip())
    if value.startswith("//"):
        value = f"https:{value}"
    if value.startswith("http://"):
        value = "https://" + value[len("http://") :]
    return urljoin(base, value)


def sort_movies(movies: list[Movie]) -> list[Movie]:
    return sorted(
        movies,
        key=lambda item: (
            item.cinemaLabel,
            item.rank if item.rank is not None else 9999,
            -(item.reservationRate or 0),
            item.title,
        ),
    )


def crawl_lotte(session: requests.Session, timeout: int) -> list[Movie]:
    source_url = "https://www.lottecinema.co.kr/NLCHS/Movie/List?flag=1"
    api_url = "https://www.lottecinema.co.kr/LCWS/Movie/MovieData.aspx"
    payload = {
        "MethodName": "GetMoviesToBe",
        "channelType": "HO",
        "osType": "Chrome",
        "osVersion": USER_AGENT,
        "multiLanguageID": "KR",
        "division": 1,
        "moviePlayYN": "Y",
        "orderType": "1",
        "blockSize": 1000,
        "pageNo": 1,
        "memberOnNo": "",
        "imgdivcd": 2,
    }
    response = session.post(
        api_url,
        data={"paramList": json.dumps(payload, ensure_ascii=False)},
        headers={"Referer": source_url},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("IsOK") != "true":
        raise CrawlerError(clean_text(data.get("ResultMessage")) or "롯데시네마 API 응답 오류")

    movies: list[Movie] = []
    for index, item in enumerate(data.get("Movies", {}).get("Items", []), start=1):
        title = clean_text(item.get("MovieNameKR") or item.get("MovieNameUS"))
        code = clean_text(item.get("RepresentationMovieCode"))
        if not title or code == "AD":
            continue
        poster = normalize_url(item.get("PosterURL"), source_url)
        rate = parse_float(item.get("BookingRate") or item.get("ViewRate"))
        detail_url = (
            f"https://www.lottecinema.co.kr/NLCHS/Movie/MovieDetailView?movie={code}"
            if code
            else source_url
        )
        movies.append(
            Movie(
                cinema="lotte",
                cinemaLabel="롯데시네마",
                title=title,
                posterUrl=poster,
                reservationRate=rate,
                reservationRateText=percent_text(rate),
                releaseDate=parse_date(item.get("ReleaseDate")),
                rank=index,
                detailUrl=detail_url,
                sourceUrl=source_url,
                sourceId=code or None,
            )
        )
    return movies


def crawl_megabox(session: requests.Session, timeout: int) -> list[Movie]:
    source_url = "https://www.megabox.co.kr/movie"
    api_url = "https://www.megabox.co.kr/on/oh/oha/Movie/selectMovieList.do"
    payload = {
        "currentPage": "1",
        "recordCountPerPage": "100",
        "pageType": "ticketing",
        "ibxMovieNmSearch": "",
        "onairYn": "N",
        "specialType": "",
        "specialYn": "N",
    }
    response = session.post(
        api_url,
        json=payload,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": source_url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("statCd") not in (0, "0", None):
        raise CrawlerError(clean_text(data.get("msg")) or "메가박스 API 응답 오류")

    image_base = data.get("imgSvrUrl") or "https://img.megabox.co.kr"
    movies: list[Movie] = []
    for item in data.get("movieList", []):
        title = clean_text(item.get("movieNm"))
        if not title:
            continue
        movie_no = clean_text(item.get("rpstMovieNo") or item.get("movieNo"))
        rank = int(item.get("rowNum") or item.get("boxoRank") or len(movies) + 1)
        rate = parse_float(item.get("boxoBokdRt"))
        detail_url = f"https://www.megabox.co.kr/movie-detail?rpstMovieNo={movie_no}" if movie_no else source_url
        movies.append(
            Movie(
                cinema="megabox",
                cinemaLabel="메가박스",
                title=title,
                posterUrl=normalize_url(item.get("imgPathNm"), image_base),
                reservationRate=rate,
                reservationRateText=percent_text(rate),
                releaseDate=parse_date(item.get("rfilmDe") or item.get("rfilmDeReal")),
                rank=rank,
                detailUrl=detail_url,
                sourceUrl=source_url,
                sourceId=movie_no or None,
            )
        )
    return movies


def extract_cgv_card(img: Any, source_url: str) -> Movie | None:
    src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy-src")
    alt = clean_text(img.get("alt"))
    if not src or "/Movie/Thumbnail/Poster/" not in src or "/PosterIcon/" in src:
        return None
    title = re.sub(r"\s*(영화\s*)?포스터\s*$", "", alt).strip()
    if not title:
        title = alt
    if not title or len(title) < 2:
        return None

    card = img.find_parent(["li", "article"])
    if card is None:
        card = img.find_parent("div")
    text = clean_text(card.get_text(" ")) if card else ""
    if "상세보기" not in text and "예매하기" not in text and "개봉" not in text:
        return None

    rate = None
    if "예매율" in text:
        rate_match = re.search(r"예매율\s*([0-9]+(?:\.[0-9]+)?)\s*%", text)
        if rate_match:
            rate = parse_float(rate_match.group(1))

    release_date = None
    release_match = re.search(r"(\d{4}[.-]\d{1,2}[.-]\d{1,2})\s*(?:개봉)?", text)
    if release_match:
        release_date = parse_date(release_match.group(1))

    detail_url = None
    link = img.find_parent("a")
    if link and link.get("href"):
        detail_url = normalize_url(link.get("href"), source_url)

    return Movie(
        cinema="cgv",
        cinemaLabel="CGV",
        title=title,
        posterUrl=normalize_url(src, source_url),
        reservationRate=rate,
        reservationRateText=percent_text(rate),
        releaseDate=release_date,
        rank=None,
        detailUrl=detail_url or source_url,
        sourceUrl=source_url,
        sourceId=None,
    )


def iter_cgv_movie_items(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("movNm") and (node.get("imgPath") or node.get("img320Fnm")):
            found.append(node)
        for value in node.values():
            found.extend(iter_cgv_movie_items(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(iter_cgv_movie_items(value))
    return found


def get_cgv_chart_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tabs = (
        payload.get("data", {})
        .get("dspScrdispMovctTab", {})
        .get("dspScrdispMovctDtlList", [])
    )
    if isinstance(tabs, list):
        for tab in tabs:
            if clean_text(tab.get("tabExpoNm")) == "무비차트":
                items = tab.get("movctSearchResDtoList")
                return items if isinstance(items, list) else []
        if tabs and isinstance(tabs[0], dict):
            items = tabs[0].get("movctSearchResDtoList")
            return items if isinstance(items, list) else []
    return iter_cgv_movie_items(payload)


def parse_cgv_api_payload(payload: dict[str, Any], source_url: str) -> list[Movie]:
    movies: list[Movie] = []
    seen: set[str] = set()

    for item in get_cgv_chart_items(payload):
        title = clean_text(item.get("movNm"))
        movie_no = clean_text(item.get("movNo"))
        key = movie_no or title
        if not title or key in seen:
            continue
        seen.add(key)

        image_path = clean_text(item.get("imgPath"))
        image_file = clean_text(item.get("img320Fnm") or item.get("img592Fnm") or item.get("img126Fnm"))
        poster = normalize_url(f"{image_path}{image_file}", "https://cdn.cgv.co.kr") if image_file else None
        rate = parse_float(item.get("atktRate"))
        rank = int(item.get("curnAtktRnk") or len(movies) + 1)

        movies.append(
            Movie(
                cinema="cgv",
                cinemaLabel="CGV",
                title=title,
                posterUrl=poster,
                reservationRate=rate,
                reservationRateText=percent_text(rate),
                releaseDate=parse_date(item.get("realOpenYmd") or item.get("rlsYmd")),
                rank=rank,
                detailUrl=source_url,
                sourceUrl=source_url,
                sourceId=movie_no or None,
            )
        )

    return sort_movies(movies)


def extract_cgv_api_movies_from_driver(driver: Any, source_url: str) -> list[Movie]:
    movies: list[Movie] = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return movies

    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
        except Exception:
            continue
        if message.get("method") != "Network.responseReceived":
            continue
        params = message.get("params", {})
        response_url = params.get("response", {}).get("url", "")
        if "searchScrDspCpotDtl" not in response_url:
            continue
        try:
            body_info = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": params["requestId"]})
            body_text = body_info.get("body", "")
            if body_info.get("base64Encoded"):
                body_text = b64decode(body_text).decode("utf-8")
            movies = parse_cgv_api_payload(json.loads(body_text), source_url)
        except Exception as exc:
            logging.debug("CGV response body parse failed: %s", exc)
            continue
        if movies:
            return movies

    return movies


def parse_cgv_html(html_text: str, source_url: str) -> list[Movie]:
    blocked_markers = ("비정상적으로 CGV에 접속", "RAY_ID", "Cloudflare")
    if any(marker in html_text for marker in blocked_markers):
        raise CrawlerError("CGV가 자동 요청을 차단했습니다. Selenium 렌더링으로 재시도합니다.")

    soup = BeautifulSoup(html_text, "html.parser")
    movies: list[Movie] = []
    seen_titles: set[str] = set()
    for img in soup.select("img"):
        movie = extract_cgv_card(img, source_url)
        if movie is None or movie.title in seen_titles:
            continue
        seen_titles.add(movie.title)
        movies.append(movie)

    ranked: list[Movie] = []
    for index, movie in enumerate(movies, start=1):
        ranked.append(Movie(**{**asdict(movie), "rank": index}))
    return ranked


def crawl_cgv_with_requests(session: requests.Session, timeout: int) -> list[Movie]:
    source_url = "https://cgv.co.kr/cnm/cgvChart/movieChart?tabParam=106"
    response = session.get(
        source_url,
        headers={"Accept": "text/html,application/xhtml+xml", "Referer": "https://cgv.co.kr/"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_cgv_html(response.text, source_url)


def crawl_cgv_with_selenium(timeout: int) -> list[Movie]:
    if webdriver is None or ChromeOptions is None:
        raise CrawlerError("Selenium이 설치되어 있지 않습니다.")

    source_url = "https://cgv.co.kr/cnm/cgvChart/movieChart?tabParam=106"
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,1600")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except Exception:
            pass
        driver.set_page_load_timeout(timeout)
        driver.get(source_url)
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
            )
        except TimeoutException:
            pass
        time.sleep(4)
        movies = extract_cgv_api_movies_from_driver(driver, source_url)
        if movies:
            return movies
        return parse_cgv_html(driver.page_source, source_url)
    except WebDriverException as exc:
        raise CrawlerError(f"CGV Selenium 실행 실패: {exc}") from exc
    finally:
        if driver is not None:
            driver.quit()


def crawl_cgv(session: requests.Session, timeout: int, use_selenium: bool = True) -> list[Movie]:
    request_error: Exception | None = None
    try:
        movies = crawl_cgv_with_requests(session, timeout)
        if movies:
            return movies
    except Exception as exc:
        request_error = exc
        logging.info("CGV requests crawler failed: %s", exc)

    if use_selenium:
        movies = crawl_cgv_with_selenium(timeout)
        if movies:
            return movies

    message = f"CGV 공개 페이지 파싱 실패: {request_error}" if request_error else "CGV 영화 데이터를 찾지 못했습니다."
    raise CrawlerError(message)


def crawl_all(timeout: int, use_selenium: bool = True) -> tuple[list[Movie], list[SourceStatus]]:
    session = make_session()
    crawlers = [
        ("cgv", "CGV", "https://cgv.co.kr/cnm/cgvChart/movieChart?tabParam=106", lambda: crawl_cgv(session, timeout, use_selenium)),
        ("lotte", "롯데시네마", "https://www.lottecinema.co.kr/NLCHS/Movie/List?flag=1", lambda: crawl_lotte(session, timeout)),
        ("megabox", "메가박스", "https://www.megabox.co.kr/movie", lambda: crawl_megabox(session, timeout)),
    ]
    all_movies: list[Movie] = []
    statuses: list[SourceStatus] = []

    for cinema, label, source_url, crawler in crawlers:
        try:
            movies = crawler()
            all_movies.extend(movies)
            statuses.append(
                SourceStatus(cinema, label, source_url, "ok", len(movies), f"{len(movies)}개 영화 수집")
            )
            logging.info("%s: %s movies", label, len(movies))
        except Exception as exc:
            statuses.append(SourceStatus(cinema, label, source_url, "error", 0, clean_text(exc)))
            logging.warning("%s crawler failed: %s", label, exc)

    return sort_movies(all_movies), statuses


def build_payload(movies: list[Movie], statuses: list[SourceStatus]) -> dict[str, Any]:
    now = datetime.now(KST)
    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "timezone": "Asia/Seoul",
        "totalCount": len(movies),
        "sources": [asdict(status) for status in statuses],
        "movies": [asdict(movie) for movie in movies],
    }


def write_json(path: Path, payload: dict[str, Any], pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="현재 상영작 데이터를 수집해 정적 JSON으로 저장합니다.")
    parser.add_argument("--output", default="docs/data/movies.json", help="저장할 JSON 파일 경로")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("CRAWLER_TIMEOUT", "20")))
    parser.add_argument("--pretty", action="store_true", help="JSON을 읽기 좋게 저장")
    parser.add_argument("--no-selenium", action="store_true", help="CGV Selenium fallback 비활성화")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(message)s")
    movies, statuses = crawl_all(timeout=args.timeout, use_selenium=not args.no_selenium)

    if not movies:
        logging.error("수집된 영화가 없습니다. 모든 소스가 실패했습니다.")
        return 1

    payload = build_payload(movies, statuses)
    output = Path(args.output)
    write_json(output, payload, pretty=args.pretty)
    logging.info("Wrote %s movies to %s", len(movies), output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
