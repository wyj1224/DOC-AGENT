import argparse

from app.services.excel_ingest import ingest_excel_to_postgres


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Excel knowledge base into PostgreSQL.")
    parser.add_argument("xlsx_path")
    parser.add_argument("--sheet", default="强条")
    parser.add_argument("--replace", action="store_true", help="Delete existing Excel knowledge rows before inserting.")
    args = parser.parse_args()

    result = ingest_excel_to_postgres(args.xlsx_path, sheet=args.sheet, replace=args.replace)
    print(f"[OK] inserted {result['mandatory_clause_count']} mandatory clauses")
    print(f"[OK] inserted {result['standard_validity_count']} standard validity records")


if __name__ == "__main__":
    main()
