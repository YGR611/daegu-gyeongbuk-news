# 대구경북 뉴스 대시보드 — 설치 가이드

파이썬 스크립트가 네이버 뉴스 API로 대구경북 관련 기사를 모아서 중복·저관련성 기사를 걸러내고 중요도순으로 정리합니다. 깃허브 액션이 매시 정각(한국시간)마다 자동으로 이 스크립트를 실행하고, 깃허브 페이지가 그 결과를 웹 대시보드로 보여줍니다. 컴퓨터를 꺼두어도 계속 갱신되고, 휴대폰에서도 접속할 수 있습니다.

제가 이 작업환경 안에서는 보안 정책상 사용자님 대신 깃허브에 직접 코드를 올리는 것이 막혀 있어서, 아래 순서를 사용자님이 직접 진행해 주셔야 합니다. 예상 소요시간은 10분 정도입니다.

## 1단계. 깃허브 저장소 만들기

1. github.com 에 로그인합니다.
2. 우측 상단 `+` 버튼 → `New repository` 클릭
3. Repository name에 `daegu-gyeongbuk-news` 등 원하는 이름 입력
4. Public(공개)으로 설정 (무료 깃허브 페이지는 공개 저장소에서만 가능합니다. 코드는 공개되지만 API 키는 아래 3단계에서 별도 안전 저장소에 넣기 때문에 노출되지 않습니다)
5. `Create repository` 클릭

## 2단계. 파일 업로드하기

압축 해제하면 아래와 같은 구조입니다.

```
news-dashboard/
├── fetch_news.py
├── README.md
├── .github/
│   └── workflows/
│       └── update.yml
└── docs/
    └── index.html
```

이 구조 그대로, 폴더 구조가 안 깨지도록 올려야 합니다. 두 가지 방법 중 편하신 걸로 하시면 됩니다.

**방법 A (터미널 사용, 추천)**

```bash
cd 압축해제한폴더/news-dashboard
git init
git add .
git commit -m "초기 설정"
git branch -M main
git remote add origin https://github.com/사용자님아이디/daegu-gyeongbuk-news.git
git push -u origin main
```

**방법 B (웹에서 업로드)**

저장소 페이지에서 `Add file` → `Upload files` 클릭 후, `news-dashboard` 폴더 안의 `fetch_news.py`, `README.md`, `.github` 폴더, `docs` 폴더를 통째로 끌어다 놓습니다 (크롬 기준 폴더째로 드래그하면 하위 구조가 유지됩니다). 다 올라갔으면 `Commit changes` 클릭.

## 3단계. 네이버 API 키를 Secrets에 등록하기

1. 저장소 페이지 → 상단 `Settings` 탭
2. 왼쪽 메뉴에서 `Secrets and variables` → `Actions` 클릭
3. `New repository secret` 클릭해서 아래 두 개를 각각 등록합니다.
   - 이름: `NAVER_CLIENT_ID` / 값: 네이버 API Client ID
   - 이름: `NAVER_CLIENT_SECRET` / 값: 네이버 API Client Secret
4. (선택) 유튜브 화제 영상도 넣고 싶으시면 `YOUTUBE_API_KEY` 라는 이름으로 유튜브 데이터 API 키도 하나 더 등록합니다. 등록 안 하시면 그 섹션은 자동으로 숨겨집니다.

> 참고: 지난번에 주셨던 "API 허브" 키를 먼저 넣어보시고, 첫 자동 실행이 실패하면 (아래 4단계에서 로그로 확인 가능) "개발자센터"에서 발급받은 키로 교체해 주시면 됩니다. 네이버 뉴스 검색 API는 개발자센터(developers.naver.com)에서 "애플리케이션 등록" 시 "검색" API를 사용 설정한 Client ID/Secret이어야 정상 동작합니다.

## 4단계. 깃허브 페이지(웹사이트) 켜기

1. `Settings` → 왼쪽 메뉴 `Pages` 클릭
2. `Build and deployment` → `Source`를 `Deploy from a branch`로 설정
3. `Branch`를 `main`, 폴더를 `/docs`로 선택 → `Save`
4. 1~2분 후 페이지 상단에 `https://사용자님아이디.github.io/daegu-gyeongbuk-news/` 형태의 주소가 표시됩니다. 이게 대시보드 주소입니다. 즐겨찾기 해두시면 됩니다.

## 5단계. 첫 데이터 만들기 (수동 실행)

기본적으로는 매시 정각에 자동 실행되지만, 바로 확인해보고 싶으시면 수동으로 한 번 돌릴 수 있습니다.

1. 저장소 페이지 → 상단 `Actions` 탭
2. 왼쪽에서 `Update Daegu-Gyeongbuk News Dashboard` 클릭
3. 오른쪽 `Run workflow` 버튼 → 다시 `Run workflow` 클릭
4. 30초~1분 정도 후 초록색 체크 표시가 뜨면 성공입니다. 빨간 X가 뜨면 클릭해서 로그를 열어보시면 실패 이유(주로 네이버 API 키 문제)가 나옵니다.
5. 성공했으면 4단계에서 확인한 대시보드 주소로 들어가면 실제 뉴스가 보입니다.

## 나중에 바꾸고 싶은 것들

- **갱신 주기**: `.github/workflows/update.yml` 파일의 `cron: "0 * * * *"` 부분을 수정하면 됩니다. 예를 들어 30분마다는 `"*/30 * * * *"` 입니다.
- **필터링/중요도 기준**: `fetch_news.py`의 `EXCLUDE_KEYWORDS`(제외 키워드), `CATEGORY_RULES`(카테고리·가중치), `cluster_articles`의 `threshold`(중복 판단 민감도) 값을 조정하면 됩니다. 실제로 며칠 써보시면서 이상하게 분류되는 기사가 있으면 그 패턴에 맞게 키워드를 추가해 나가시는 걸 추천드립니다.
- **검색 지역 범위**: `NEWS_QUERIES`, `REGION_KEYWORDS`에 포항·안동·구미 등 특정 시군 키워드를 더 추가하면 해당 지역 기사가 더 많이 잡힙니다.

## 참고 — 깃허브 토큰 관련

채팅으로 전달해 주신 깃허브 개인용 액세스 토큰은 이 작업환경의 보안 정책 때문에 실제로 사용되지 못했습니다(외부로 전송 자체가 차단됨). 어디에도 사용되지 않았지만, 채팅 기록에 남아있는 게 꺼림칙하시면 깃허브 `Settings` → `Developer settings` → `Personal access tokens`에서 해당 토큰을 삭제(Delete)하고 필요시 새로 발급받으셔도 됩니다.
