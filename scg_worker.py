import os, asyncio, random, httpx, json, re
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
from openai import OpenAI

HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=5.0)  # ✅ 전역 재사용


# ----------------------------
# 0) 환경설정
# ----------------------------
load_dotenv(override=True)

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
if "0.0.0.0" in API_BASE:
    API_BASE = API_BASE.replace("0.0.0.0", "127.0.0.1")
print(f"[scg] API_BASE={API_BASE}")

# 상단 공통
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-secret-token")
HEADERS = {"X-Admin-Token": ADMIN_TOKEN} if ADMIN_TOKEN else {}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY 가 없습니다. .env 또는 환경변수를 확인하세요.")
client = OpenAI(api_key=OPENAI_API_KEY)

# ----------------------------
# 1) 페르소나 카탈로그 & 시스템 프롬프트
#    (가중치는 CLI에서 지정)
# ----------------------------
PERSONA_CATALOG: Dict[str, str] = {
    "퇴근길 직장인": "짧고 단정, 이모지 소량",
    "현장 상인": "구체적 묘사, 문장 짧음",
    "대학생": "속어·해시태그 적절",
    "인터넷 지박령": "풍부한 묘사, 약간 과장/비속어 허용, 이모지 다량",
    "기자톤": "사실 서술, 문장 간결",
    "주민대표": "안내·주의 촉구",
}

SYSTEM_PROMPT = (
    "SNS 글 생성기입니다. 씨앗 글의 핵심(무슨 일, 어디 근처)을 유지하되"
    " 새로운 문장으로 작성하세요. 1~2문장, 40~120자."
    #" 좌표/개인정보 금지. 피해 규모나 책임 주체에 대한 단정 금지."
)

# ----------------------------
# 2) 유틸 파서
# ----------------------------
def parse_langs(s: str) -> Dict[str, float]:
    if not s:
        return {"ko": 0.9, "en": 0.1}
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    d: Dict[str, float] = {}
    for p in [x for x in s.split(",") if x.strip()]:
        k, v = p.split("=")
        d[k.strip()] = float(v.strip())
    total = sum(d.values()) or 1.0
    return {k: v / total for k, v in d.items()}

def parse_tags(s: str) -> List[str]:
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
    예) '대학생:0.45,택시기사:0.15,직장인:0.25,인근상인:0.15'
      또는 '{"대학생":0.45,"퇴근길 직장인":0.25,"주민대표":0.3}'
    카탈로그에 없는 키가 오면 '일반인' 스타일로 처리.
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
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            raw = {str(k): float(v) for k, v in obj.items()}
        else:
            raw = {}
    except Exception:
        raw = {}
        for chunk in s.split(","):
            if ":" in chunk:
                k, v = chunk.split(":")
                raw[k.strip()] = float(v.strip())
    total = sum(raw.values()) or 1.0
    return {k: v / total for k, v in raw.items()}

def weighted_choice(weights: Dict[str, float]) -> str:
    r = random.random()
    acc = 0.0
    for k, v in weights.items():
        acc += v
        if r <= acc:
            return k
    return list(weights.keys())[-1]

# ----------------------------
# 3) 백엔드 통신
# ----------------------------

async def fetch_seed(post_id: int) -> str:
    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as http:  # ✅
        r = await http.get(f"{API_BASE}/api/posts/{post_id}", headers=HEADERS)
        r.raise_for_status()
        return r.json()["text"]

async def fetch_latest_real_seed() -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as http:  # ✅
        r = await http.get(f"{API_BASE}/api/posts/latest_real", headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        return data["id"], data["text"]

async def post_simulated(text: str, persona_name: str, seed_id: int,
                         lang: str | None, tags: list[str]) -> None:
    payload = {
        "text": text,
        "is_simulated": True,
        "persona": persona_name,
        "seed_post_id": seed_id,
        "lang": lang,
        "hashtags": " ".join(tags) if tags else None,
    }
    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as http:  # ✅
        r = await http.post(f"{API_BASE}/api/user_posts", json=payload, headers=HEADERS)
        r.raise_for_status()
# ----------------------------
# 4) 텍스트 생성
# ----------------------------
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
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_prompt}],
        temperature=0.7,
    )
    text = resp.choices[0].message.content.strip()
    if tags and random.random() < 0.6:
        pick = " ".join(random.sample(tags, k=min(len(tags), random.randint(1, 2))))
        text = f"{text} {pick}"
    return text

# ----------------------------
# 5) 스케줄링 (ppm 지원)
# ----------------------------
def schedule_intervals(n: int, minutes: int, ppm: Optional[float]) -> List[float]:
    """
    반환: 길이 n 의 '대기초' 배열
    - ppm 지정 시: 포아송(지수간격) 기반으로 평균 60/ppm 초 간격
    - 미지정 시: 평균 (minutes*60)/n 에 지수분산 섞기
    """
    if ppm and ppm > 0:
        lam = ppm / 60.0  # 초당 λ
        return [random.expovariate(lam) for _ in range(n)]
    mean = (minutes * 60) / max(n, 1)
    lam = 1.0 / max(mean, 0.001)
    return [random.expovariate(lam) for _ in range(n)]

# ----------------------------
# 6) 메인
# ----------------------------
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

    print("[scg] API_BASE =", API_BASE)
    print("[langs]", language_mix)
    print("[tags ]", hashtags)
    print("[personas]", persona_weights)


    async def run():
        
        # 시드 결정
        if args.seed.lower() == "latest":
            seed_post_id, seed_text = await fetch_latest_real_seed()
        else:
            seed_post_id = int(args.seed)
            seed_text = await fetch_seed(seed_post_id)

        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as http:
            r = await http.get(f"{API_BASE}/api/posts/{seed_post_id}")
            r.raise_for_status()
            return r.json()["text"]            # ← await 금지

        waits = schedule_intervals(args.n, args.minutes, args.ppm)

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

            # 페르소나 가중 샘플링 → 카탈로그에서 스타일 가져오기
            persona_name = weighted_choice(persona_weights)
            if persona_name not in PERSONA_CATALOG:
                PERSONA_CATALOG.setdefault(persona_name, "일반인 말투, 평이함")

            text = await generate_text_from_seed(seed_text, persona_name, lang, hashtags)
            await post_simulated(text, persona_name, seed_post_id, lang, hashtags)

        await asyncio.gather(*[one(w) for w in waits])

    asyncio.run(run())
