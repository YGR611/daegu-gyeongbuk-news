#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대구경북 뉴스 대시보드 데이터 생성 스크립트

네이버 뉴스 검색 API로 대구경북 관련 기사를 모은 뒤,
1) 관련 없는/저품질 기사 제외 (부고, 인사동정, 광고성 등)
2) 같은 사건을 다룬 중복 기사 묶기
3) 여러 매체가 다룰수록, 최신일수록, 하드뉴스 카테고리일수록 중요도를 높게 계산
4) docs/data.json 으로 저장 (대시보드 HTML이 이 파일을 읽음)

(선택) 유튜브 데이터 API 키가 있으면 대구경북 관련 화제 영상도 함께 수집.
"""

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# 검색 쿼리 (대구경북 관련성을 이 단계에서 1차로 확보)
NEWS_QUERIES = [
    "대구",
    "경북",
    "대구시",
    "경상북도",
    "대구경북",
]

# 지역 관련성 재확인용 키워드 (제목+요약에 하나라도 있어야 통과)
# 짧은 시·군 이름 중 일반 단어와 겹치는 것들은 "시/군"을 붙여서 오탐을 막습니다.
# (예: "영주" 단독으로 두면 "직영주유소"처럼 전혀 상관없는 단어 안에 우연히
#  포함돼서 오작동합니다. "상주"=상주하다, "고령"=고령화, "영양"=영양소,
#  "구미"=구미가 당기다 등도 같은 이유로 접미사를 붙였습니다.)
REGION_KEYWORDS = [
    "대구", "경북", "경상북도", "대구시", "포항", "안동", "구미시", "경산", "김천",
    "영주시", "영천", "상주시", "문경", "경주시", "칠곡", "성주군", "고령군", "청도",
    "군위", "의성", "청송군", "영양군", "영덕", "울진", "봉화군", "예천", "울릉",
]

# 지역 관련성이 있어도 뉴스로서 가치가 낮아 제외할 카테고리 (부고/인사/인물소개/공지성)
EXCLUDE_KEYWORDS = [
    "부고", "부음", "인사동정", "동정]", "[인사]", "승진 인사", "정기인사",
    "인사말씀", "축사", "화보", "포토뉴스", "날씨]", "오늘의 날씨",
    "[새의자]", "[인물]", "[프로필]", "[동정]", "[모시는 자리]", "이임", "취임",
    # 단순 일기예보성 기사 (지역 뉴스로서 가치가 낮음)
    "낮 최고", "아침 최저", "체감온도", "체감 온도", "미세먼지 농도", "자외선지수",
    "예상 강수량",
    # 공공기관 입찰·공고성 게시물 (뉴스가 아님)
    "[입찰", "입찰공고", "입찰 정보", "낙찰자",
    # 여러 지역 소식을 짧게 묶어 다루는 코너 (지역 하나를 다루는 기사가 아님)
    "[간추린 단신]", "[전국 단신]", "[지역 단신]",
    # 게임·e스포츠 뉴스는 지자체가 대회를 후원했다는 이유만으로 섞여 들어오는
    # 경우가 많아 전부 제외
    "e스포츠", "이스포츠", "게임대회", "PC방", "LCK ", "LoL ",
    # 사설·칼럼·기고 등 의견성 글 (사실 보도가 아니라 개인 의견이라 제외)
    "[사설]", "[칼럼]", "[기고]", "[시론]", "[특별기고]", "[데스크시각]", "[여의도포럼]",
    "[영남시론]", "[대구논단]", "[치유의 인문학]",
    # 사진 한 장 + 짧은 설명뿐인 '포토에세이'성 기사에 자주 나오는 상투적 표현
    "즐기고 있다", "만끽하고 있다", "펼쳐지고 있다", "연출하고 있다", "수놓고 있다",
    # 기업 홍보·매장 오픈·프랜차이즈성 보도자료 (사실 보도라기보다 광고성 기사)
    "참여 매장은", "신규 오픈", "그랜드 오픈", "지사 개소",
    # TV 프로그램 맛집 소개 재탕 기사 (뉴스로서 가치가 낮은 클릭베이트성 기사)
    "맛집 위치는", "6시 내고향", "생방송 투데이", "생생정보",
    # 소규모 기부·기탁·나눔 미담성 기사 (지역 뉴스로서 가치가 낮은 홍보성 훈훈한 소식)
    "기탁식", "성금 기탁", "물품 기탁", "나눔에 나섰다", "나눔을 이어갔다",
    "폭염에 지친", "나눔", "[영웅시대]",
    # 백화점·매장 팝업 행사 등 유통업체 프로모션 (기업 홍보기사)
    "팝업 행사", "프로모션으로",
]

# 연합뉴스·뉴시스 등 통신사가 배포하는 '사진 캡션'성 기사 탐지용.
# 본문 없이 사진 설명 한 줄 + 촬영일자 + 기자 이메일로 끝나는 경우가 많아서
# (예: "...공판에 출석하고 있다.(공동취재) 2026.08.12. since1999@newsis.com")
# 정규식으로 걸러냅니다. 제목에 지역 키워드가 있어도 이 패턴이면 제외합니다.
PHOTO_CAPTION_PATTERN = re.compile(r"\d{4}\.\d{1,2}\.\d{1,2}\.\s*[\w.\-]+@[\w.\-]+")

# 확실한 대구경북 지역 언론사(신문·방송) 도메인만 모았습니다. 이 목록에 있는
# 곳에서 나온 기사는 기존처럼 "제목 또는 요약문 어디든" 지역 키워드가 있으면
# 관련 기사로 인정합니다.
#
# 이 목록에 없는 나머지 모든 도메인(전국 방송·통신사, 다른 지역 신문, 업종별
# 전문지, 처음 보는 사이트 등)은 "제목에 지역 키워드가 직접 있을 때만" 인정합니다.
# 처음에는 "다른 지역 언론사만 따로 모아서 그곳만 엄격하게 본다"는 방식이었는데,
# 계속 새로운 도메인(패션 전문지, 인물 소개 사이트 등)에서 같은 문제가 나와서
# 기본값 자체를 엄격하게 바꾸고, "확실히 믿을 수 있는 지역 언론사"만 예외로
# 두는 방식으로 바꿨습니다.
DAEGU_GYEONGBUK_LOCAL_DOMAINS = {
    "imaeil.com",         # 매일신문
    "yeongnam.com",       # 영남일보
    "idaegu.co.kr",       # 대구신문
    "dgn.kr",             # 대구경북일보
    "dailydgnews.com",    # 데일리대구경북뉴스
    "dg1news.com",        # 대구뉴스
    "daegunews.net",      # 대구뉴스
    "kyongbuk.co.kr",     # 경북일보
    "kbmaeil.com",        # 경북매일
    "kbsm.net",           # 경북신문
    "kbin.co.kr",         # 경북in뉴스
    "newgbnews.com",      # 일간경북신문
    "gbprimenews.com",    # 프라임경북뉴스
    "tk.newdaily.co.kr",  # 뉴데일리대구경북
    "dgmbc.com",          # 대구MBC
    "tbc.co.kr",          # TBC(대구방송)
}

CATEGORY_RULES = [
    ("사건사고", ["사고", "화재", "붕괴", "추락", "폭발", "충돌", "전복", "실종", "익사",
                "교통사고", "산불", "침수", "붕괴사고"], 1.3),
    ("범죄사법", ["구속", "검찰", "기소", "징역", "재판", "수사", "체포", "마약", "사기",
                "경찰", "고소", "고발", "압수수색"], 1.25),
    ("정치행정", ["시장", "도지사", "시의회", "도의회", "국회의원", "예산", "조례",
                "공약", "선거", "국정감사", "시청", "도청"], 1.1),
    ("경제", ["기업", "일자리", "실업률", "부동산", "분양", "수출", "투자", "공장",
             "산업단지", "창업", "물가"], 1.1),
    ("사회복지", ["교육", "복지", "의료", "병원", "학교", "환경", "폭염", "한파",
                "태풍", "호우", "지진", "재난"], 1.15),
    ("문화생활", ["축제", "공연", "전시", "관광", "맛집", "행사", "박람회"], 0.85),
    ("스포츠", ["프로야구", "축구", "야구", "경기", "선수", "우승", "구단"], 0.9),
]

# KBS 대구 "단신 작성" 스킬의 "리포트/단신 판단" 기준에 나오는 "전형적 단신
# 대상" 6가지 유형입니다. 진짜 뉴스가 맞고 관련성도 있어서 제외하지는 않지만,
# 데이터·복수 입장·원인배경처럼 깊이 다룰 거리가 없는 정형화된 정기·행정
# 발표성 소식이라 특종성이 낮습니다. 그래서 완전히 빼지 않고 중요도만
# 한 단계 낮춰서(가중치 0.7배) 화면 하단으로 내려가게 합니다.
ROUTINE_ANNOUNCEMENT_KEYWORDS = [
    # 1) 단일 기관 사업 선정·공모 통과
    "공모 사업에 최종 선정", "공모전에서 최종 선정", "공모 사업 선정",
    "공모 사업에 선정", "공모전 선정", "사업에 최종 선정", "사업에 선정됐",
    # 2) 청소년 공모전·행사 개최
    "청소년 공모전", "학생 공모전", "백일장", "그리기대회", "그리기 대회",
    "글짓기대회", "글짓기 대회",
    # 3) 계절성·정기 반복 경보·통계 발표
    "조류경보", "조류 경보", "녹조", "폭염특보", "폭염 특보", "한파특보",
    "한파 특보", "황사경보", "황사 경보", "오존주의보", "오존 주의보",
    "적조주의보", "적조 주의보",
    # 4) 단일 기관 주도 펀드·기금 결성
    "펀드를 출범", "펀드 출범", "펀드 결성", "기금을 조성", "기금 조성",
    # 5) 조례 심사·행정 절차 진행
    "조례안", "상임위 심사", "본회의를 통과", "조례 개정안", "조례 수정안",
    # 6) 시설 휴장·재개장 안내
    "임시휴장", "임시휴관", "정기휴관", "휴장합니다", "재개장합니다",
]

ROUTINE_ANNOUNCEMENT_WEIGHT = 0.7  # 완전 제외는 아니고 중요도만 낮추는 배율


def is_routine_announcement(article) -> bool:
    text = article["title"] + " " + article["desc"]
    return any(k in text for k in ROUTINE_ANNOUNCEMENT_KEYWORDS)

# 참고: 예전에는 set(list("이가을를은는...")) 형태로 만들어서 실제로는
# 한 글자짜리 문자 집합이 되어버렸고(글자 단위로 쪼개짐), tokenize()가 애초에
# 길이 1 이하 토큰을 걸러내기 때문에 사실상 아무 효과가 없었습니다. 아래처럼
# 실제 불용어 "단어" 목록으로 고쳐서, 뉴스 문장에 자주 나오지만 사건 특정에는
# 도움이 안 되는 접속사·상투적 보도 표현을 토큰에서 제외합니다.
STOPWORDS = {
    "위해", "위한", "대해", "대한", "관해", "관한", "통해", "따라", "따른",
    "이번", "오늘", "지난", "현재", "한편", "이날", "당시",
    "밝혔다", "말했다", "전했다", "있다", "없다", "된다", "한다", "됐다", "했다",
    "이라고", "라고", "라며", "이라며",
}

# 제목이 "~해야", "~걸어야", "~나서야", "~잡아야" 처럼 "-아야/-어야"(~해야
# 한다는 뜻을 줄인 표현) 로 끝나면 사실 보도가 아니라 주장·의견을 담은
# 사설/칼럼성 제목인 경우가 많습니다. (예: "대구시는 '기업은행 본점' 유치에
# 사활 걸어야" - [사설] 태그가 없어도 사설과 같은 형식) 따옴표·괄호 등 꼬리에
# 붙는 문장부호는 떼고 마지막 글자를 확인합니다.
OPINION_TITLE_PATTERN = re.compile(r"(아야|어야)$")


def looks_like_opinion_title(title: str) -> bool:
    cleaned = title.strip().rstrip("\"'”’)]」』】.!?· ")
    return bool(OPINION_TITLE_PATTERN.search(cleaned))

# 도메인 -> 한글 매체명. 여기 없는 도메인은 그냥 도메인이 표시됩니다.
# 새로운 매체를 추가하고 싶으면 이 딕셔너리에 한 줄만 추가하면 됩니다.
PRESS_NAME_MAP = {
    # 대구경북 지역 매체
    "imaeil.com": "매일신문",
    "yeongnam.com": "영남일보",
    "idaegu.co.kr": "대구신문",
    "dgn.kr": "대구경북일보",
    "dailydgnews.com": "데일리대구경북뉴스",
    "dg1news.com": "대구뉴스",
    "daegunews.net": "대구뉴스",
    "kyongbuk.co.kr": "경북일보",
    "kbmaeil.com": "경북매일",
    "kbsm.net": "경북신문",
    "kbin.co.kr": "경북in뉴스",
    "newgbnews.com": "일간경북신문",
    "gbprimenews.com": "프라임경북뉴스",
    "tk.newdaily.co.kr": "뉴데일리대구경북",
    "dgmbc.com": "대구MBC",
    "tbc.co.kr": "TBC",
    # 통신사·방송사
    "yna.co.kr": "연합뉴스",
    "yonhapnewstv.co.kr": "연합뉴스TV",
    "news1.kr": "뉴스1",
    "newsis.com": "뉴시스",
    "ytn.co.kr": "YTN",
    "sbs.co.kr": "SBS",
    "news.sbs.co.kr": "SBS",
    "imbc.com": "MBC",
    "imnews.imbc.com": "MBC",
    "mbc.co.kr": "MBC",
    "kbs.co.kr": "KBS",
    "news.kbs.co.kr": "KBS",
    "jtbc.co.kr": "JTBC",
    # 전국 종합일간지·경제지
    "chosun.com": "조선일보",
    "donga.com": "동아일보",
    "joongang.co.kr": "중앙일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "seoul.co.kr": "서울신문",
    "segye.com": "세계일보",
    "kmib.co.kr": "국민일보",
    "munhwa.com": "문화일보",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "mt.co.kr": "머니투데이",
    "edaily.co.kr": "이데일리",
    "fnnews.com": "파이낸셜뉴스",
    "sedaily.com": "서울경제",
    "asiae.co.kr": "아시아경제",
    "dt.co.kr": "디지털타임스",
    "etnews.com": "전자신문",
    "nocutnews.co.kr": "노컷뉴스",
    "pressian.com": "프레시안",
    "news.naver.com": "네이버뉴스",
    "n.news.naver.com": "네이버뉴스",
}


def press_display_name(domain: str) -> str:
    """도메인을 한글 매체명으로 변환. 매핑에 없으면 도메인을 그대로 반환."""
    domain = domain.lower()
    if domain in PRESS_NAME_MAP:
        return PRESS_NAME_MAP[domain]
    # www. 등 앞의 서브도메인을 하나씩 떼어가며 재시도
    parts = domain.split(".")
    while len(parts) > 2:
        parts = parts[1:]
        candidate = ".".join(parts)
        if candidate in PRESS_NAME_MAP:
            return PRESS_NAME_MAP[candidate]
    return domain


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def call_naver(endpoint: str, query: str, display: int = 100, sort: str = "date", start: int = 1):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없습니다.")
    url = (
        f"https://openapi.naver.com/v1/search/{endpoint}.json?"
        f"query={urllib.parse.quote(query)}&display={display}&sort={sort}&start={start}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            "User-Agent": "daegu-gyeongbuk-news-dashboard",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


FETCH_WINDOW_HOURS = 24  # 이 시간 이내에 나온 기사만 수집합니다.
NAVER_MAX_START = 901    # 네이버 검색 API 제약: start + display - 1 <= 1000 (display=100 기준 마지막 페이지)


def fetch_all_news():
    seen_links = set()
    articles = []
    cutoff = datetime.now(KST) - timedelta(hours=FETCH_WINDOW_HOURS)

    for q in NEWS_QUERIES:
        start = 1
        query_count = 0
        oldest_seen = None  # 이 검색어에서 지금까지 확인한 것 중 가장 오래된 기사 시각

        while start <= NAVER_MAX_START:
            try:
                data = call_naver("news", q, display=100, sort="date", start=start)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="ignore")
                print(f"[WARN] '{q}' 검색 실패(start={start}): HTTP {e.code} {body}", file=sys.stderr)
                break
            except Exception as e:
                print(f"[WARN] '{q}' 검색 실패(start={start}): {e}", file=sys.stderr)
                break

            items = data.get("items", [])
            if not items:
                break

            reached_cutoff = False
            for item in items:
                link = item.get("originallink") or item.get("link")
                title = strip_html(item.get("title", ""))
                desc = strip_html(item.get("description", ""))
                pub_raw = item.get("pubDate", "")
                try:
                    pub_dt = datetime.strptime(pub_raw, "%a, %d %b %Y %H:%M:%S %z").astimezone(KST)
                except Exception:
                    pub_dt = datetime.now(KST)

                oldest_seen = pub_dt

                # 결과는 최신순(sort=date)이라, 24시간보다 오래된 기사가
                # 나오면 그 뒤로는 더 볼 필요 없이 이 검색어는 종료합니다.
                if pub_dt < cutoff:
                    reached_cutoff = True
                    break

                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                query_count += 1

                press = urllib.parse.urlparse(link).netloc.replace("www.", "")
                articles.append({
                    "title": title,
                    "desc": desc,
                    "link": link,
                    "press": press,
                    "pub_dt": pub_dt,
                })

            time.sleep(0.15)  # API 예의상 살짝 딜레이

            if reached_cutoff:
                break
            if len(items) < 100:
                break
            start += 100
        else:
            # while 조건(start <= NAVER_MAX_START)이 거짓이 되어 자연 종료된 경우만
            # 여기로 옵니다 = 네이버 API가 검색어당 최대로 허용하는 1000건을 전부
            # 확인했는데도 아직 24시간 전까지 도달하지 못한 경우입니다. 이 검색어가
            # 그만큼 검색량이 많다는 뜻이라, 1000건보다 더 오래된(그러나 여전히
            # 24시간 이내인) 기사는 이번 수집에서 놓쳤을 수 있습니다. 네이버 API
            # 자체가 검색어당 조회 가능한 결과를 1000건으로 제한하고 있어서, 이
            # 경우는 코드로 더 파고들 수 없는 한계이지만 최소한 로그로 남깁니다.
            if oldest_seen is not None:
                gap_hours = (datetime.now(KST) - oldest_seen).total_seconds() / 3600
                print(
                    f"[INFO] '{q}' 검색: 네이버 API 1000건 상한에 도달했지만 아직 "
                    f"{FETCH_WINDOW_HOURS}시간 전까지는 못 갔습니다 (지금까지 확인한 가장 "
                    f"오래된 기사가 {gap_hours:.1f}시간 전 — 이보다 오래됐지만 여전히 "
                    f"{FETCH_WINDOW_HOURS}시간 이내인 기사는 이번 수집에서 놓쳤을 수 있습니다).",
                    file=sys.stderr,
                )

        print(f"[INFO] '{q}' 검색: {query_count}건 수집", file=sys.stderr)

    return articles


def is_relevant(article) -> bool:
    title = article["title"]
    text = title + " " + article["desc"]

    if any(k in text for k in EXCLUDE_KEYWORDS):
        return False

    if PHOTO_CAPTION_PATTERN.search(text):
        return False

    if looks_like_opinion_title(title):
        return False

    # 제목에 지역 키워드가 직접 있으면 어느 매체든 인정.
    if any(k in title for k in REGION_KEYWORDS):
        return True

    # 제목에는 없고 요약문에만 있는 경우: 확실한 대구경북 지역 언론사에서
    # 나온 기사만 인정합니다. (본문 어딘가에 대구/경북이 스쳐 지나가듯
    # 언급된 기사를 걸러내기 위함 - 예: 인물 약력에 "대구 OO고 졸업",
    # 여러 지점을 나열하는 프랜차이즈 기사, 전국 뉴스 속 지역 비교 등)
    if article.get("press") in DAEGU_GYEONGBUK_LOCAL_DOMAINS:
        return any(k in text for k in REGION_KEYWORDS)

    return False


def classify(article):
    text = article["title"] + " " + article["desc"]
    best = ("일반", 1.0)
    for name, keywords, weight in CATEGORY_RULES:
        if any(k in text for k in keywords):
            best = (name, weight)
            break
    return best


# 조사(은,는,이,가,을,를,의,에,와,과,도,만,로 등)가 명사 뒤에 그대로 붙어 있으면
# 완전히 같은 단어인데도 다른 토큰으로 인식돼서 중복 판단을 놓치는 경우가 많습니다
# (예: "생활개선회" vs "생활개선회와", "새마을지도자대학" vs "새마을지도자대학을",
#  "김천대는" vs "김천대에서"). 완벽한 형태소 분석기는 아니지만, 흔한 조사를
# 어미에서 떼어내는 간단한 규칙만으로도 이런 경우 상당수가 해결됩니다.
# (중복 묶기에만 쓰이는 함수라, 관련성 판단(is_relevant)에는 영향을 주지 않습니다.)
JOSA_SUFFIXES = sorted([
    "에서는", "으로는", "이라는", "에게서", "부터는", "까지는",
    "에서", "으로", "부터", "까지", "에게", "한테", "에는", "와는", "과는",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로",
], key=len, reverse=True)


def strip_josa(word: str) -> str:
    for suf in JOSA_SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            return word[: -len(suf)]
    return word


def tokenize(title: str):
    words = re.findall(r"[가-힣A-Za-z0-9]+", title)
    return set(strip_josa(w) for w in words if len(w) > 1 and w not in STOPWORDS)


def bigrams(text: str):
    """제목+요약에서 '연속된 두 단어' 묶음을 뽑아낸다.
    ("응급실 뺑뺑이", "대구형 응급의료" 처럼 두 단어가 붙어야 의미가 통하는
    사건 고유의 표현은, 단어 하나하나로 쪼개면 다른 기사에도 흔해서
    "드물게 등장하는 단어" 신호에 안 걸리는 경우가 많다. 두 단어를 붙여서
    보면 훨씬 더 그 사건에 특정적인 신호가 된다.)"""
    words = re.findall(r"[가-힣A-Za-z0-9]+", text)
    stems = [strip_josa(w) for w in words if len(w) > 1 and w not in STOPWORDS]
    return set(zip(stems, stems[1:]))


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


QUOTE_PATTERN = re.compile(r"['\"‘’“”]([^'\"‘’“”]{4,30})['\"‘’“”]")


def extract_quoted_phrases(text: str):
    """제목+요약 속 따옴표로 묶인 문구를 뽑아낸다.
    ('대구형 응급의료 안전망' 처럼 정책·사업명·슬로건을 그대로 인용하는 경우가 많은데,
    제목에는 없고 요약문에만 인용구가 있는 경우도 많아서 (예: 행사 슬로건) 제목뿐
    아니라 요약문까지 함께 봐야 놓치지 않는다. 이 문구를 공유하면 표현이 달라도
    사실상 같은 사건으로 볼 수 있다.)"""
    return set(m.strip() for m in QUOTE_PATTERN.findall(text) if len(m.strip()) >= 4)


def cluster_articles(articles, window_hours=30, title_threshold=0.4,
                      combined_threshold=0.3, min_distinctive_shared=2):
    """같은 사건을 다룬 기사를 묶는다 (union-find).

    아래 다섯 신호 중 하나라도 만족하면 같은 사건으로 묶습니다. 제목만 비교하면
    매체마다 표현이 달라서(예: "3층 규제 풀린다" vs "고도지구 폐지 추진") 놓치는
    경우가 많아, 요약까지 함께 보고 + 이 사건에서만 등장하는 단어를 공유하는지,
    같은 정책·사업명을 따옴표로 인용하는지도 같이 확인합니다.

    1) 제목 단어 유사도가 높다
    2) 제목+요약을 합친 단어 유사도가 어느 정도 높다 (표현은 달라도 같은 사실을 담은 경우)
    3) 여러 기사 중 드물게만 등장하는(=이 사건에서만 나오는) 단어를 2개 이상 공유한다
    4) 제목이나 요약에 따옴표로 인용된 정책·사업명·슬로건이 서로 같다
    5) "응급실 뺑뺑이"처럼 붙어야 뜻이 통하는 두 단어 묶음(bigram) 중
       드물게만 등장하는 것을 하나라도 공유한다 (헤드라인 앵글이 매체마다
       완전히 달라도, 같은 정책 보도자료를 인용 보도한 기사들은 이런
       고유 표현을 그대로 옮겨 쓰는 경우가 많다)
    """
    n = len(articles)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    title_tokens = [tokenize(a["title"]) for a in articles]
    combined_tokens = [tokenize(a["title"]) | tokenize(a["desc"]) for a in articles]
    quoted_phrases = [extract_quoted_phrases(a["title"] + " " + a["desc"]) for a in articles]
    combined_bigrams = [bigrams(a["title"] + " " + a["desc"]) for a in articles]

    doc_freq = {}
    for toks in combined_tokens:
        for t in toks:
            doc_freq[t] = doc_freq.get(t, 0) + 1

    bigram_doc_freq = {}
    for bg in combined_bigrams:
        for b in bg:
            bigram_doc_freq[b] = bigram_doc_freq.get(b, 0) + 1

    for i in range(n):
        for j in range(i + 1, n):
            dt = abs((articles[i]["pub_dt"] - articles[j]["pub_dt"]).total_seconds()) / 3600
            if dt > window_hours:
                continue

            if quoted_phrases[i] & quoted_phrases[j]:
                union(i, j)
                continue

            if jaccard(title_tokens[i], title_tokens[j]) >= title_threshold:
                union(i, j)
                continue

            if jaccard(combined_tokens[i], combined_tokens[j]) >= combined_threshold:
                union(i, j)
                continue

            shared = combined_tokens[i] & combined_tokens[j]
            distinctive_shared = [t for t in shared if doc_freq.get(t, 0) <= 3]
            if len(distinctive_shared) >= min_distinctive_shared:
                union(i, j)
                continue

            shared_bigrams = combined_bigrams[i] & combined_bigrams[j]
            if any(bigram_doc_freq.get(b, 0) <= 3 for b in shared_bigrams):
                union(i, j)

    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)
    return list(groups.values())


def build_dataset():
    raw = fetch_all_news()
    relevant = [a for a in raw if is_relevant(a)]

    if not relevant:
        return {"generated_at": datetime.now(KST).isoformat(), "articles": [], "stats": {}}

    groups = cluster_articles(relevant)
    now = datetime.now(KST)

    results = []
    for idx_list in groups:
        members = [relevant[i] for i in idx_list]
        members.sort(key=lambda a: a["pub_dt"])
        rep = members[-1]  # 가장 최근 기사를 대표로
        cat_name, cat_weight = classify(rep)
        press_list = sorted(set(m["press"] for m in members))
        press_name_list = sorted(set(press_display_name(p) for p in press_list))

        routine = is_routine_announcement(rep)
        if routine:
            cat_weight *= ROUTINE_ANNOUNCEMENT_WEIGHT

        age_hours = max((now - rep["pub_dt"]).total_seconds() / 3600, 0)
        recency_score = max(0.0, 1 - age_hours / 48)  # 48시간 지나면 0에 수렴
        coverage_score = 1 + 0.8 * (len(press_list) - 1)
        importance = round((coverage_score + recency_score) * cat_weight, 3)

        results.append({
            "title": rep["title"],
            "desc": rep["desc"],
            "link": rep["link"],
            "press": rep["press"],
            "press_name": press_display_name(rep["press"]),
            "press_count": len(press_list),
            "press_list": press_list,
            "press_name_list": press_name_list,
            "is_routine": routine,
            "pub_date": rep["pub_dt"].isoformat(),
            "category": cat_name,
            "importance": importance,
        })

    results.sort(key=lambda r: r["importance"], reverse=True)

    stats = {
        "total_articles_raw": len(raw),
        "total_relevant": len(relevant),
        "total_clusters": len(results),
        "excluded": len(raw) - len(relevant),
    }

    youtube = fetch_youtube_trending() if YOUTUBE_API_KEY else []

    return {
        "generated_at": now.isoformat(),
        "articles": results,
        "youtube": youtube,
        "stats": stats,
    }


def fetch_youtube_trending():
    """대구경북 관련 최근 화제 유튜브 영상 (선택 기능)."""
    try:
        published_after = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        search_url = (
            "https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
            f"&q={urllib.parse.quote('대구 경북')}&order=viewCount&maxResults=10"
            f"&publishedAfter={published_after}&regionCode=KR&relevanceLanguage=ko"
            f"&key={YOUTUBE_API_KEY}"
        )
        with urllib.request.urlopen(search_url, timeout=15) as resp:
            search_data = json.loads(resp.read().decode("utf-8"))

        video_ids = [it["id"]["videoId"] for it in search_data.get("items", []) if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []

        stats_url = (
            "https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics"
            f"&id={','.join(video_ids)}&key={YOUTUBE_API_KEY}"
        )
        with urllib.request.urlopen(stats_url, timeout=15) as resp:
            stats_data = json.loads(resp.read().decode("utf-8"))

        videos = []
        for it in stats_data.get("items", []):
            snippet = it.get("snippet", {})
            stats = it.get("statistics", {})
            videos.append({
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "video_id": it.get("id"),
                "url": f"https://www.youtube.com/watch?v={it.get('id')}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "published_at": snippet.get("publishedAt", ""),
            })
        videos.sort(key=lambda v: v["view_count"], reverse=True)
        return videos
    except Exception as e:
        print(f"[WARN] 유튜브 수집 실패: {e}", file=sys.stderr)
        return []


def main():
    dataset = build_dataset()
    out_path = os.path.join(os.path.dirname(__file__), "docs", "data.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {out_path} (기사 {len(dataset.get('articles', []))}건)")


if __name__ == "__main__":
    main()
