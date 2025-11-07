# backend/worker.py
from __future__ import annotations
import os, time, json, random, threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Callable

from openai import OpenAI

from .database import SessionLocal
from . import crud, schemas, models  # 기존 CRUD/스키마 사용

# -------------------------------
# 설정/가중치 유틸
# -------------------------------
def _normalize_weights(w: Dict[str, float]) -> List[Tuple[str, float]]:
    keys = list(w.keys())
    vals = []
    for k in keys:
        try:
            v = float(w[k])
        except Exception:
            v = 0.0
        vals.append(max(0.0, v))
    s = sum(vals)
    if s <= 0:
        # 전부 0이면 균등분포
        p = 1.0 / max(len(keys), 1)
        return [(k, p) for k in keys]
    return [(k, v / s) for k, v in zip(keys, vals)]

def sample_by_weights(w: Dict[str, float]) -> str:
    items = _normalize_weights(w)
    keys, probs = zip(*items)
    return random.choices(list(keys), weights=list(probs), k=1)[0]

def parse_langs(s: Optional[str]) -> Dict[str, float]:
    if not s:
        return {"ko": 0.9, "en": 0.1}
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return {str(k): float(v) for k, v in obj.items()}
    except Exception:
        pass
    out: Dict[str, float] = {}
    for chunk in s.split(","):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            out[k.strip()] = float(v.strip())
    return out or {"ko": 0.9, "en": 0.1}

def parse_personas(s: Optional[str]) -> Dict[str, float]:
    default = {
        "대학생": 0.2, "퇴근길 직장인": 0.1, "현장 상인": 0.1,
        "주민대표": 0.15, "기자톤": 0.05, "인터넷 지박령": 0.4,
    }
    if not s:
        return default
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return {str(k): float(v) for k, v in obj.items()}
    except Exception:
        pass
    out: Dict[str, float] = {}
    for chunk in s.split(","):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            out[k.strip()] = float(v.strip())
    return out or default

def parse_tags(s: Optional[str]) -> List[str]:
    if not s:
        return ["#속보", "#주의"]
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return [str(x).strip() for x in obj if str(x).strip()]
    except Exception:
        pass
    # 쉼표/공백 분리
    parts = [p.strip() for p in s.replace(";", ",").split(",")]
    return [p for p in parts if p]

def schedule_intervals(n: int, minutes: int, ppm: Optional[float]) -> List[float]:
    """
    n개 포스트의 대기(초) 배열.
    - ppm 지정: 포아송(지수분포) 평균 60/ppm 간격
    - 미지정: minutes 분 동안 n개를 랜덤 분산
    """
    if ppm and ppm > 0:
        lam = ppm / 60.0
        return [random.expovariate(lam) for _ in range(n)]
    mean = (minutes * 60) / max(n, 1)
    lam = 1.0 / max(mean, 0.001)
    return [random.expovariate(lam) for _ in range(n)]

# -------------------------------
# 워커 설정/카탈로그
# -------------------------------
PERSONA_CATALOG: Dict[str, str] = {
    "퇴근길 직장인": "짧고 단정, 이모지 소량",
    "현장 상인": "구체적 묘사, 문장 짧음",
    "대학생": "속어·해시태그 적절",
    "인터넷 지박령": "풍부한 묘사, 약간 과장/비속어 허용, 이모지 다량",
    "기자톤": "사실 서술, 문장 간결",
    "주민대표": "안내·주의 촉구",
}

SYSTEM_PROMPT = (
    "SNS 글 생성기입니다. 씨앗 글의 핵심(무슨 일, 어느 근처)을 유지하되 "
    "새로운 문장으로 작성하세요. 1~2문장, 40~120자."
)

@dataclass
class WorkerConfig:
    n: int = int(os.getenv("SCG_N", "60"))
    minutes: int = int(os.getenv("SCG_MINUTES", "20"))
    ppm: Optional[float] = float(os.getenv("SCG_PPM")) if os.getenv("SCG_PPM") else None
    langs: Dict[str, float] = None
    personas: Dict[str, float] = None
    tags: List[str] = None

    def __post_init__(self):
        self.langs = parse_langs(os.getenv("SCG_LANGS")) if self.langs is None else self.langs
        self.personas = parse_personas(os.getenv("SCG_PERSONAS")) if self.personas is None else self.personas
        self.tags = parse_tags(os.getenv("SCG_TAGS")) if self.tags is None else self.tags

# -------------------------------
# 임베디드 워커
# -------------------------------
class SCGWorker:
    """
    하나의 FastAPI 프로세스 안에서 돌아가는 백그라운드 스레드 워커.
    - enqueue(seed_id) 로 작업을 넣으면 LLM이 유사 글을 생성해 DB에 바로 저장합니다.
    - DB 접근은 CRUD 함수를 통해 수행(HTTP 자가호출 X).
    """
    def __init__(self, config: WorkerConfig):
        self.config = config
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 가 설정되어 있지 않습니다.")
        self.client = OpenAI(api_key=api_key)

        self._q: "queue.Queue[int]" = __import__("queue").Queue()
        self._th: Optional[threading.Thread] = None
        self._run = threading.Event()

    # 외부에서 호출: 씨앗 글 id 넣기
    def enqueue(self, seed_id: int):
        self._q.put(seed_id)

    # 서버 시작 시 호출
    def start(self):
        if self._th and self._th.is_alive():
            return
        self._run.set()
        self._th = threading.Thread(target=self._loop, name="SCGWorker", daemon=True)
        self._th.start()

    # 서버 종료 시 호출
    def stop(self, timeout: float = 5.0):
        self._run.clear()
        if self._th:
            self._th.join(timeout=timeout)

    # 내부 루프
    def _loop(self):
        while self._run.is_set():
            try:
                seed_id = self._q.get(timeout=1.0)
            except __import__("queue").Empty:
                continue
            try:
                self._run_for_seed(seed_id)
            except Exception as e:
                print(f"[scg] worker error: {e!r}")

    # 한 개 씨앗 글에 대해 N개 생성 실행
    def _run_for_seed(self, seed_post_id: int):
        cfg = self.config
        waits = schedule_intervals(cfg.n, cfg.minutes, cfg.ppm)

        # DB에서 씨앗 글 텍스트 로딩
        with SessionLocal() as db:
            post = db.query(models.UserPost).filter(models.UserPost.id == seed_post_id).first()
            if not post:
                print(f"[scg] seed #{seed_post_id} not found; skip")
                return
            seed_text = post.text

        # 순차 수행(간격 sleep)
        acc = 0.0
        for w in waits:
            if not self._run.is_set():
                break
            time.sleep(w)  # 간격
            acc += w

            lang = sample_by_weights(cfg.langs)
            persona_name = sample_by_weights(cfg.personas)
            if persona_name not in PERSONA_CATALOG:
                PERSONA_CATALOG.setdefault(persona_name, "일반인 말투, 평이함")

            text = self._generate(seed_text, persona_name, lang, cfg.tags)
            # DB 저장
            with SessionLocal() as db:
                crud.create_post(
                    db,
                    schemas.PostCreate(
                        text=text,
                        is_simulated=True,
                        persona=persona_name,
                        seed_post_id=seed_post_id,
                        lang=lang,
                        hashtags=" ".join(cfg.tags) if cfg.tags else None,
                    ),
                )

    # LLM 호출부
    def _generate(self, seed_text: str, persona_name: str, lang: str, tags: List[str]) -> str:
        style = PERSONA_CATALOG.get(persona_name, "일반인 말투, 평이함")
        user_prompt = (
            f"씨앗: {seed_text}\n"
            f"페르소나: {persona_name} ({style})\n"
            f"언어: {lang}\n"
            f"규칙: 단정형 평서문 1~2문장, 40~120자\n"
            f"해시태그는 선택(0~2개)로 자연스럽게.\n"
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_prompt}],
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()
        if tags and random.random() < 0.6:
            k = random.randint(1, min(2, len(tags)))
            pick = " ".join(random.sample(tags, k=k))
            text = f"{text} {pick}"
        return text
