from app.db.database import init_db


def main() -> None:
    init_db()
    print("[OK] PostgreSQL tables created")


if __name__ == "__main__":
    main()

