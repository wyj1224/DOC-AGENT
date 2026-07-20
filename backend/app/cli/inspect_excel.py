import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect workbook sheets and sample rows.")
    parser.add_argument("xlsx_path")
    parser.add_argument("--max-rows", type=int, default=8)
    parser.add_argument("--export-dir", default="", help="Optional directory to save extracted regions as CSV files.")
    args = parser.parse_args()

    from app.excel_loader import inspect_excel

    inspect_excel(args.xlsx_path, max_rows=args.max_rows, export_dir=args.export_dir or None)


if __name__ == "__main__":
    main()
