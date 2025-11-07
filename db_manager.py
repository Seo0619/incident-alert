# db_manager.py
import os, sys, argparse
from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

# engine / DATABASE_URL 은 database.py 에서, Base 는 models.py 에서 가져옵니다.
from backend.database import engine, DATABASE_URL
from backend import models

Base = models.Base  # ✅ Base는 models 쪽에 있음

def init_db() -> None:
    """모든 테이블 생성 (존재하면 그대로 둠)"""
    Base.metadata.create_all(bind=engine)
    print("[db] create_all 완료")

def drop_db() -> None:
    """DB 초기화: SQLite면 파일 삭제, 그 외는 drop_all"""
    url = make_url(DATABASE_URL)
    if url.drivername.startswith("sqlite"):
        db_path = url.database
        if db_path and db_path != ":memory:":
            # 상대경로를 절대경로로 보정
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.getcwd(), db_path)
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"[db] SQLite 파일 삭제: {db_path}")
            else:
                print(f"[db] 이미 없음: {db_path}")
        else:
            print("[db] 메모리 SQLite는 삭제 스킵")
    else:
        Base.metadata.drop_all(bind=engine)
        print("[db] drop_all 완료")

def seed_one(text: str, is_simulated: bool = False) -> None:
    """샘플 글 한 건 삽입"""
    with Session(engine) as db:
        db.add(models.UserPost(text=text, processed=False, is_simulated=is_simulated))
        db.commit()
    print(f"[db] seed 추가: {text[:40]}... (is_simulated={is_simulated})")

def main():
    p = argparse.ArgumentParser(description="DB 초기화/생성/시드 관리")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="테이블 생성만 (create_all)")

    rp = sub.add_parser("reset", help="모두 초기화 후 재생성")
    rp.add_argument("-y", "--yes", action="store_true", help="확인 없이 진행")

    sp = sub.add_parser("seed", help="샘플 글 한 건 삽입")
    sp.add_argument("--text", required=True, help="시드 글 내용")
    sp.add_argument("--sim", action="store_true", help="is_simulated=True 로 기록")

    args = p.parse_args()

    if args.cmd == "init":
        init_db()
        return

    if args.cmd == "reset":
        if not args.yes:
            yn = input("⚠ DB를 초기화합니다. 계속할까요? [y/N] ").strip().lower()
            if yn != "y":
                print("중단합니다."); sys.exit(1)
        drop_db()
        init_db()
        return

    if args.cmd == "seed":
        seed_one(args.text, is_simulated=args.sim)
        return

if __name__ == "__main__":
    main()
