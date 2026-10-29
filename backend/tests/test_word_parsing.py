from pathlib import Path

import pytest
from docx import Document

from app.word_loader import paragraph_style_name, parse_docx_file


@pytest.fixture
def sample_docx(tmp_path) -> Path:
    document = Document()
    document.add_heading("1 概述", level=1)
    document.add_paragraph("本工程依据 GB 50311-2016 第 3.1.1 条。")
    document.add_heading("1.1 设计依据", level=2)
    document.add_paragraph("正文", style="List Bullet")
    plain = document.add_paragraph("缺失样式的段落")
    plain._p.get_or_add_pPr().get_or_add_pStyle().val = "NoSuchStyle"
    table = document.add_table(rows=3, cols=3)
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            cell.text = f"r{row_index}c{cell_index}"
    table.cell(0, 0).merge(table.cell(0, 2))
    table.cell(1, 1).merge(table.cell(2, 1))
    path = tmp_path / "sample.docx"
    document.save(path)
    return path


def test_cached_style_name_matches_python_docx(sample_docx):
    document = Document(sample_docx)
    names = [paragraph_style_name(p) for p in document.paragraphs]
    assert names == [p.style.name for p in document.paragraphs]
    assert "Heading 1" in names and "List Bullet" in names
    # Unknown style ids fall back to the default paragraph style.
    assert names[4] == "Normal"


def test_merged_cells_are_kept_once_and_deterministically(sample_docx):
    runs = [
        [chunk.text for chunk in parse_docx_file(str(sample_docx)) if chunk.source_type == "word_docx_table"]
        for _ in range(20)
    ]
    assert all(run == runs[0] for run in runs)
    # Merging moves the cells' paragraphs into one cell: every text appears exactly once.
    assert sorted(runs[0]) == sorted(f"r{r}c{c}" for r in range(3) for c in range(3))
