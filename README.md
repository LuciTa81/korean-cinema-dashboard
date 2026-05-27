# 한국 영화관 통합 상영작

CGV, 롯데시네마, 메가박스의 현재 상영작을 수집해 `docs/data/movies.json`으로 저장하고, GitHub Pages에서 정적 웹사이트로 보여주는 프로젝트입니다.

## 구성

- `src/scrape.py`: Python 크롤러. 롯데시네마와 메가박스는 공식 웹페이지 내부 JSON 호출을 사용하고, CGV는 공개 차트 페이지를 BeautifulSoup으로 파싱한 뒤 필요하면 Selenium 렌더링으로 재시도합니다.
- `docs/`: GitHub Pages가 배포할 정적 사이트입니다.
- `.github/workflows/update-and-deploy.yml`: 매일 00:00 KST에 크롤링, JSON 갱신 커밋, Pages 배포를 실행합니다.

## 로컬 실행

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m src.scrape --output docs/data/movies.json --pretty
```

정적 파일만 있으므로 `docs/index.html`을 브라우저로 열어도 되고, 로컬 서버로 확인하려면 아래처럼 실행합니다.

```bash
python -m http.server 8000 -d docs
```

## GitHub 리포지토리에 올리고 배포하기

1. GitHub에서 새 리포지토리를 만듭니다.
2. 로컬 프로젝트를 리포지토리에 연결하고 푸시합니다.

```bash
git init
git add .
git commit -m "Initial movie dashboard"
git branch -M main
git remote add origin https://github.com/USER/REPO.git
git push -u origin main
```

3. GitHub 리포지토리에서 `Settings` → `Actions` → `General`로 이동합니다.
4. `Workflow permissions`를 `Read and write permissions`로 설정하고 저장합니다. 크롤링 결과 JSON을 자동 커밋하려면 필요합니다.
5. `Settings` → `Pages`로 이동합니다.
6. `Build and deployment`의 `Source`를 `GitHub Actions`로 선택합니다.
7. `Actions` 탭에서 `Update movies and deploy Pages` 워크플로우를 선택한 뒤 `Run workflow`를 눌러 첫 배포를 실행합니다.
8. 실행이 끝나면 `Settings` → `Pages` 또는 워크플로우 결과의 `github-pages` URL에서 사이트 주소를 확인합니다.

## 자동화 일정

GitHub Actions cron은 UTC 기준이라 워크플로우는 `0 15 * * *`로 설정되어 있습니다. 이는 한국 시간 기준 매일 00:00입니다.

## 운영 메모

- 한 영화관 사이트가 일시적으로 차단되거나 구조가 바뀌면 해당 소스만 `error` 상태로 저장하고, 나머지 영화관 데이터는 계속 표시합니다.
- 모든 영화관 수집이 실패하면 워크플로우가 실패해 기존 GitHub Pages 배포본을 유지합니다.
- CGV는 자동 요청을 차단할 수 있어 Selenium fallback을 포함했습니다. GitHub Actions에서 Chrome/Selenium 실행이 막히면 README의 로컬 실행으로 먼저 파서 상태를 확인하세요.
