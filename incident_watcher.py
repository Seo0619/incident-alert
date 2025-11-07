# incident_watcher.py
import os, time, json, httpx
from openai import OpenAI

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-secret-token")

client = OpenAI(api_key=OPENAI_API_KEY)

UNPROCESSED_URL = f"{API_BASE}/api/unprocessed?include_simulated=false&limit=20"

SYSTEM_PROMPT = (
    "You are a classifier for human-caused incidents in short social posts. "
    "Return JSON ONLY with keys: is_incident('Yes'|'No'), confidence(0-100 int), "
    "incident_type(string|null), country(string|null), city_or_area(string|null), summary(string|null). "
    "If not clearly a real, reported event, answer No. Do NOT include coordinates."
)

def classify(text: str) -> dict:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"POST:\n{text}\nRespond with JSON only."},
        ],
    )
    raw = resp.choices[0].message.content
    try:
        data = json.loads(raw)
    except Exception:
        data = {"is_incident":"No","confidence":0,"incident_type":None,"country":None,"city_or_area":None,"summary":None}
    # 보정
    data["is_incident"] = "Yes" if str(data.get("is_incident","No")).strip().lower()=="yes" else "No"
    try:
        data["confidence"] = max(0, min(100, int(data.get("confidence", 0))))
    except Exception:
        data["confidence"] = 0
    for k in ("incident_type","country","city_or_area","summary"):
        v = data.get(k)
        data[k] = (None if v in ("", "null", None) else str(v)[:300])
    return data

def save_incident(post_id: int, result: dict):
    payload = {
        "post_id": post_id,
        "incident_type": result["incident_type"],
        "confidence": result["confidence"],
        "country": result["country"],
        "city_or_area": result["city_or_area"],
        "summary": result["summary"],
    }
    headers = {"Content-Type":"application/json", "X-Admin-Token": ADMIN_TOKEN}
    with httpx.Client(timeout=10) as http:
        r = http.post(f"{API_BASE}/api/incidents", headers=headers, json=payload)
        r.raise_for_status()

def mark_processed(post_id: int):
    with httpx.Client(timeout=8) as http:
        r = http.post(f"{API_BASE}/api/mark_processed/{post_id}")
        r.raise_for_status()

def loop(threshold=70, interval_sec=5):
    print("[watcher] start. threshold=", threshold)
    while True:
        try:
            with httpx.Client(timeout=10) as http:
                rows = http.get(UNPROCESSED_URL).json()
        except Exception as e:
            print("[watcher] fetch error:", e)
            time.sleep(interval_sec); continue

        if not rows:
            time.sleep(interval_sec); continue

        for row in rows:
            post_id, text = row["id"], row["text"]
            try:
                res = classify(text)
                print(f"[watcher] #{post_id} -> {res}")
                if res["is_incident"] == "Yes" and res["confidence"] >= threshold:
                    save_incident(post_id, res)
            except Exception as e:
                print(f"[watcher] classify/save error on {post_id}:", e)
            finally:
                try:
                    mark_processed(post_id)
                except Exception as e2:
                    print(f"[watcher] mark_processed error on {post_id}:", e2)
        time.sleep(interval_sec)

if __name__ == "__main__":
    loop(threshold=70, interval_sec=5)
