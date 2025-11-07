import os
import re
import json
import random
import asyncio
from typing import Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from openai import OpenAI

# =========================================================
# 0) 환경설정
# =========================================================
load_dotenv(override=True)

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").strip()
# 0.0.0.0는 접속 주소가 아니므로 로컬 개발시 127.0.0.1로 보정
if "0.0.0.0" in API_BASE:
    API_BASE = API_BASE.replace("0.0.0.0", "127.0.0.1")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-secret-token")
HEADERS = {"X-Admin-Token": ADMIN_TOKEN} if ADMIN_TOKEN else {}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 가 없습니다. .env 또는 환경변수를 확인하세요.")
client = OpenAI(api_key=OPENAI_API_KEY)

print(f"[scg] API_BASE={API_BASE}")

# =========================================================
# 1) 페르소나/프롬프트
# =========================================================
PERSONA_CATALOG: Dict[str, str] = {
    "퇴근길 직장인": "짧고 단정, 이모지 소량",
    "현장 상인": "구체적 묘사, 문장 짧음",
    "대학생": "속어·해시태그 적절",
    "인터넷 지박령": "풍부한 묘사, 약간 과장/비속어 허용, 이모지 다량",
    "기자톤": "사실 서술, 문장 간결",
    "주민대표": "안내·주의 촉구",
}

SYSTEM_PROMPT = (
    "SNS 글 생성기입니다. 씨앗 글의 핵심(무슨 일, 어디 근처)을 유지하되 "
    "새로운 문장으로 작성하세요. 1~2문장, 40~120자."
)

# =========================================================
# 2) 파서 유틸
# =========================================================
def parse_langs(s: str) -> Dict[str, float]:
    """JSON('{"ko":0.9,"en":0.1}') 또는 'ko=0.9,en=0.1' 모두 지원. 잘못된 토큰은 무시."""
    if not s:
        return {"ko": 0.9, "en": 0.1}
    # JSON 먼저 시도
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            total = sum(float(v) for v in obj.values()) or 1.0
            return {str(k): float(v) / total for k, v in obj.items()}
    except Exception:
        pass
    # key=value CSV 파싱 (내구성 업)
    d: Dict[str, float] = {}
    for token in [x.strip() for x in s.split(",") if x.strip()]:
        if "=" not in token:
            print(f"[warn] --langs 토큰 무시: {token!r} (기대형식: key=value)")
            continue
        k, v = token.split("=", 1)  # 1회만 split
        try:
            d[k.strip()] = float(v.strip())
        except Exception:
            print(f"[warn] --langs 값 파싱 실패: {token!r}")
    if not d:
        return {"ko": 0.9, "en": 0.1}
    total = sum(d.values()) or 1.0
    return {k: v / total for k, v in d.items()}

def parse_tags(s: str) -> List[str]:
    """'["#속보","#주의"]' 또는 '#속보,#주의' 또는 공백 구분 모두 지원"""
    if not s:
        return ["#속보", "#주의"]
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return [str(x).strip() for x in obj if str(x).strip()]
    except Exception:
        pass
    s = s.strip()
    s = re.sub(r'^[\[\(\{\'"]+|[\]\)\}\'"]+$', '', s)
    parts = re.split(r'[,\s]+', s)
    return [p.strip().strip('\'"') for p in parts if p.strip()]
def parse_persona_weights(s: Optional[str]) -> Dict[str, float]:
    """
    JSON 또는 '이름:가중치,이름:가중치' 모두 지원. 잘못된 토큰은 무시.
    """
    default = {
        "대학생": 0.2,
        "퇴근길 직장인": 0.1,
        "현장 상인": 0.1,
        "주민대표": 0.15,
        "기자톤": 0.05,
        "인터넷 지박령": 0.4,
    }
    if not s:
        return default
    # JSON 먼저 시도
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            raw = {}
            for k, v in obj.items():
                try:
                    raw[str(k)] = float(v)
                except Exception:
                    print(f"[warn] --personas 값 파싱 실패(JSON): {k!r}:{v!r}")
            if raw:
                total = sum(raw.values()) or 1.0
                return {k: v / total for k, v in raw.items()}
    except Exception:
        pass
    # CSV '이름:값' 파싱
    raw: Dict[str, float] = {}
    for chunk in s.split(","):
        token = chunk.strip()
        if ":" not in token:
            if token:
                print(f"[warn] --personas 토큰 무시: {token!r} (기대형식: name:value)")
            continue
        name, val = token.split(":", 1)  # 1회만 split
        try:
            raw[name.strip()] = float(val.strip())
        except Exception:
            print(f"[warn] --personas 값 파싱 실패: {token!r}")
    if not raw:
        return default
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}


def weighted_choice(weights: Dict[str, float]) -> str:
    r = random.random()
    acc = 0.0
    for k, v in weights.items():
        acc += v
        if r <= acc:
            return k
    return list(weights.keys())[-1]  # rounding 보정

# =========================================================
# 3) 백엔드와 통신
# =========================================================
async def fetch_seed_text_by_id(post_id: int) -> str:
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.get(f"{API_BASE}/api/posts/{post_id}", headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        return data["text"]

async def fetch_latest_real_seed() -> Tuple[int, str]:
    """
    백엔드에 최신 '실제'(is_simulated=False) 글을 물어봅니다.
    없으면 422가 떨어지도록 백엔드를 구성했다면, 그에 맞춰 친절 메시지 후 종료.
    """
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.get(f"{API_BASE}/api/posts/latest_real", headers=HEADERS)
        if r.status_code == 422:
            print("[scg] 최신 실제 글이 없습니다. /report 에서 실제 글을 하나 등록하시거나 --seed <id> 를 사용해 주세요. (latest_real 조회 실패)")
            raise SystemExit(1)
        r.raise_for_status()
        data = r.json()
        return data["id"], data["text"]

async def post_simulated(text: str, persona_name: str, seed_id: int,
                         lang: Optional[str], tags: List[str]) -> None:
    payload = {
        "text": text,
        "is_simulated": True,
        "persona": persona_name,
        "seed_post_id": seed_id,
        "lang": lang,
        "hashtags": " ".join(tags) if tags else None,
    }
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        r = await http.post(f"{API_BASE}/api/user_posts", json=payload, headers=HEADERS)
        r.raise_for_status()

# =========================================================
# 4) 텍스트 생성 (OpenAI 호출은 스레드로 오프로드)
# =========================================================
async def generate_text_from_seed(seed_text: str, persona_name: str,
                                  lang: Optional[str], tags: List[str]) -> str:
    style = PERSONA_CATALOG.get(persona_name, "일반인 말투, 평이함")
    user_prompt = (
        f"씨앗: {seed_text}\n"
        f"페르소나: {persona_name} ({style})\n"
        f"언어: {lang or 'ko'}\n"
        f"규칙: 단정형 평서문 1~2문장, 40~120자\n"
        f"해시태그는 선택(0~2개)로 자연스럽게.\n"
    )

    def _call_openai():
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_prompt}],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()

    text = await asyncio.to_thread(_call_openai)

    if tags and random.random() < 0.6:
        pick = " ".join(random.sample(tags, k=min(len(tags), random.randint(1, 2))))
        text = f"{text} {pick}"
    return text

# =========================================================
# 5) 스케줄링 (ppm 지원)
# =========================================================
def schedule_intervals(n: int, minutes: int, ppm: Optional[float]) -> List[float]:
    """
    반환: 길이 n 의 '대기초' 배열
    - ppm 지정 시: 포아송(지수간격) 기반 -> 평균 간격 60/ppm 초
    - 미지정 시: 평균 (minutes*60)/n 초를 기준으로 지수분산 샘플
    """
    if ppm and ppm > 0:
        lam = ppm / 60.0  # 초당 λ
        return [random.expovariate(lam) for _ in range(n)]
    mean = (minutes * 60) / max(n, 1)
    lam = 1.0 / max(mean, 0.001)
    return [random.expovariate(lam) for _ in range(n)]

# =========================================================
# 6) 메인
# =========================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=str, required=True, help="정수 ID 또는 'latest'")
    parser.add_argument("--n", type=int, default=50, help="생성할 총 글 수")
    parser.add_argument("--minutes", type=int, default=20, help="분산 시간(분). --ppm 없을 때 사용")
    parser.add_argument("--ppm", type=float, default=None, help="분당 게시 수(평균). 지정 시 minutes/n 대신 사용")
    parser.add_argument("--langs", type=str, default='{"ko":0.9,"en":0.1}')
    parser.add_argument("--tags", type=str, default='["#속보","#주의"]')
    parser.add_argument("--personas", type=str, default=None,
                        help="예: '대학생:0.45,퇴근길 직장인:0.25,주민대표:0.3' 또는 JSON")

    args = parser.parse_args()

    language_mix = parse_langs(args.langs)
    hashtags = parse_tags(args.tags)
    persona_weights = parse_persona_weights(args.personas)

    print("[scg] 시작")
    print("[langs]", language_mix)
    print("[tags ]", hashtags)
    print("[personas]", persona_weights)

    async def run():
        # ① 시드 결정
        if args.seed.lower() == "latest":
            seed_post_id, seed_text = await fetch_latest_real_seed()
        else:
            seed_post_id = int(args.seed)  # 여기서 int 변환 (검증)
            seed_text = await fetch_seed_text_by_id(seed_post_id)

        # ② 스케줄 생성
        waits = schedule_intervals(args.n, args.minutes, args.ppm)

        # ③ 작업 루프
        async def one(wait_s: float):
            await asyncio.sleep(wait_s)

            # 언어 샘플링
            r = random.random(); acc = 0.0; lang = None
            for k, v in language_mix.items():
                acc += v
                if r <= acc:
                    lang = k; break
            if not lang:
                lang = list(language_mix.keys())[-1]

            # 페르소나 샘플링
            persona_name = weighted_choice(persona_weights)
            if persona_name not in PERSONA_CATALOG:
                PERSONA_CATALOG.setdefault(persona_name, "일반인 말투, 평이함")

            # 생성 & 등록
            text = await generate_text_from_seed(seed_text, persona_name, lang, hashtags)
            await post_simulated(text, persona_name, seed_post_id, lang, hashtags)

        await asyncio.gather(*[one(w) for w in waits])

    asyncio.run(run())