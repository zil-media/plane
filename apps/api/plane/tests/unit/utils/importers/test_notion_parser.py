# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Unit tests for the Notion HTML export parser.

The parser is dependency-free by design (stdlib only), so it is loaded
directly from its file instead of through the ``plane`` package — that
keeps these tests runnable without Django/Celery installed.
"""

import importlib.util
import io
import pathlib
import types
import zipfile

import pytest

_PARSER_PATH = (
    pathlib.Path(__file__).resolve().parents[4] / "utils" / "importers" / "notion" / "parser.py"
)
_spec = importlib.util.spec_from_file_location("notion_parser_under_test", _PARSER_PATH)
parser_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parser_module)

NotionExportParser = parser_module.NotionExportParser
NotionExportError = parser_module.NotionExportError

ROOT_UUID = "a" * 32
CHILD_UUID = "b" * 32
DB_UUID = "c" * 32
ROW1_UUID = "d" * 32
ROW2_UUID = "e" * 32
ROW3_UUID = "f" * 32


def page_html(title, icon=None):
    icon_meta = f'<meta name="data-notion-page-icon" content="{icon}"/>' if icon else ""
    return (
        f"<html><head><title>{title}</title>{icon_meta}</head>"
        f'<body><article><div class="page-body"><p>{title} body</p></div></article></body></html>'
    ).encode("utf-8")


def build_zip(files, nested=True):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    if not nested:
        inner.seek(0)
        return inner
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("ExportBlock-1234-Part-1.zip", inner.getvalue())
    outer.seek(0)
    return outer


@pytest.fixture
def export_files():
    """A miniature Notion export: root page, child page, database with
    duplicate row titles (disambiguated folders) and assets."""
    base = "Private & Shared"
    root = f"{base}/Root {ROOT_UUID}.html"
    root_dir = f"{base}/Root"
    return {
        root: page_html("Root", icon="📝"),
        f"{root_dir}/Child {CHILD_UUID}.html": page_html("Child"),
        f"{root_dir}/Child/photo.png": b"png-bytes",
        # database: csv + rows folder named after the csv title
        f"{root_dir}/Tracker {DB_UUID}.csv": "﻿Name,Tags\nAlpha,\nDupe,\nDupe,\n".encode("utf-8"),
        f"{root_dir}/Tracker/Alpha {ROW1_UUID}.html": page_html("Alpha"),
        f"{root_dir}/Tracker/Dupe {ROW2_UUID}.html": page_html("Dupe"),
        f"{root_dir}/Tracker/Dupe {ROW3_UUID}.html": page_html("Dupe"),
        # duplicate-title asset folders: plain + short-suffix disambiguation
        f"{root_dir}/Tracker/Dupe/logo.png": b"png-1",
        f"{root_dir}/Tracker/Dupe {ROW3_UUID[:4]}-{ROW3_UUID[-4:]}/logo.png": b"png-2",
        # asset named after a row, sitting directly in the rows folder
        f"{root_dir}/Tracker/Alpha.jpg": b"jpg-bytes",
    }


def parse(files, nested=True):
    parser = NotionExportParser(build_zip(files, nested=nested))
    manifest = parser.parse()
    return parser, manifest


class TestNotionExportParser:
    def test_parses_nested_part_zip(self, export_files):
        _, manifest = parse(export_files, nested=True)
        assert manifest["stats"]["pages"] == 2  # Root + Child

    def test_parses_flat_zip(self, export_files):
        _, manifest = parse(export_files, nested=False)
        assert manifest["stats"]["pages"] == 2

    def test_page_hierarchy(self, export_files):
        _, manifest = parse(export_files)
        assert manifest["root_pages"] == [ROOT_UUID]
        assert manifest["pages"][CHILD_UUID]["parent"] == ROOT_UUID
        assert CHILD_UUID in manifest["pages"][ROOT_UUID]["children"]

    def test_page_icon_and_title_from_html_head(self, export_files):
        _, manifest = parse(export_files)
        assert manifest["pages"][ROOT_UUID]["icon"] == "📝"
        assert manifest["pages"][ROOT_UUID]["title"] == "Root"

    def test_database_detection(self, export_files):
        _, manifest = parse(export_files)
        database = manifest["databases"][DB_UUID]
        assert database["parent"] == ROOT_UUID
        assert database["columns"] == ["Name", "Tags"]
        assert sorted(database["rows"]) == sorted([ROW1_UUID, ROW2_UUID, ROW3_UUID])
        # rows are not part of the regular page tree
        for row_uuid in database["rows"]:
            assert manifest["pages"][row_uuid]["database"] == DB_UUID
            assert manifest["pages"][row_uuid]["parent"] is None

    def test_duplicate_titles_each_claim_one_folder(self, export_files):
        _, manifest = parse(export_files)
        # ROW3 owns the short-suffix folder, ROW2 the plain folder — one asset each
        assert len(manifest["pages"][ROW2_UUID]["assets"]) == 1
        assert len(manifest["pages"][ROW3_UUID]["assets"]) == 1
        assert manifest["pages"][ROW2_UUID]["assets"] != manifest["pages"][ROW3_UUID]["assets"]

    def test_row_asset_in_database_folder_matched_by_title(self, export_files):
        _, manifest = parse(export_files)
        assert any(asset.endswith("Alpha.jpg") for asset in manifest["pages"][ROW1_UUID]["assets"])

    def test_child_page_asset(self, export_files):
        _, manifest = parse(export_files)
        assert any(asset.endswith("photo.png") for asset in manifest["pages"][CHILD_UUID]["assets"])

    def test_read_entry_roundtrip(self, export_files):
        parser, manifest = parse(export_files)
        content = parser.read_entry(manifest["pages"][ROOT_UUID]["path"])
        assert b"Root body" in content

    def test_read_entry_bounds_decompression(self, export_files):
        # guards against decompression bombs: a tight per-entry cap raises
        # instead of decompressing the whole entry into memory
        parser, manifest = parse(export_files)
        path = manifest["pages"][ROOT_UUID]["path"]
        assert parser.read_entry(path)  # full read still works
        with pytest.raises(NotionExportError, match="entry_too_large"):
            parser.read_entry(path, max_bytes=4)

    def test_corrupt_nested_part_rejected(self):
        # a *-Part-N.zip entry that is not a valid zip is a clean 400, not a 500
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("Export-1234-Part-1.zip", b"not a real zip")
        outer.seek(0)
        parser = NotionExportParser(outer)
        with pytest.raises(NotionExportError, match="invalid_zip"):
            parser.parse()

    def test_markdown_export_rejected(self):
        files = {f"Private & Shared/Root {ROOT_UUID}.md": b"# Root"}
        with pytest.raises(NotionExportError, match="markdown_export"):
            parse(files)

    def test_garbage_rejected(self):
        parser = NotionExportParser(io.BytesIO(b"not a zip at all"))
        with pytest.raises(NotionExportError, match="invalid_zip"):
            parser.parse()

    def test_empty_export_rejected(self):
        files = {"readme.txt": b"nothing here"}
        with pytest.raises(NotionExportError, match="empty_export"):
            parse(files)

    def test_data_source_export_format(self):
        """New-format (2025 'data sources') export: `<DB> <dbuuid>.html`,
        `<DB> <dbuuid>_<Source> <dsuuid>.csv`, rows under `<DB>/<Source>/`."""
        db_page = "1a" * 16
        ds1, ds2 = "2b" * 16, "3c" * 16
        row1, row2, row3 = "4d" * 16, "5e" * 16, "6f" * 16
        base = "Privado y Compartido"
        files = {
            f"{base}/Proyectos {db_page}.html": page_html("Proyectos"),
            f"{base}/Proyectos {db_page}_Proyectos {ds1}.csv": "﻿Cliente,Estado\nAlpha,Hecho\nBeta,\n".encode("utf-8"),
            f"{base}/Proyectos {db_page}_Nueva fuente {ds2}.csv": "﻿Nombre\nGamma\n".encode("utf-8"),
            f"{base}/Proyectos/Proyectos/Alpha {row1}.html": page_html("Alpha"),
            f"{base}/Proyectos/Proyectos/Beta {row2}.html": page_html("Beta"),
            f"{base}/Proyectos/Nueva fuente/Gamma {row3}.html": page_html("Gamma"),
            f"{base}/Proyectos/Proyectos/Alpha/doc.pdf": b"pdf-bytes",
        }
        _, manifest = parse(files)

        assert manifest["root_pages"] == [db_page]
        assert manifest["stats"] == {"pages": 1, "database_rows": 3, "databases": 2, "assets": 1}

        source1 = manifest["databases"][ds1]
        assert source1["title"] == "Proyectos"
        assert source1["parent"] == db_page
        assert source1["columns"] == ["Cliente", "Estado"]
        assert sorted(source1["rows"]) == sorted([row1, row2])

        source2 = manifest["databases"][ds2]
        assert source2["title"] == "Nueva fuente"
        assert source2["parent"] == db_page
        assert source2["rows"] == [row3]

        for row_uuid, ds_uuid in ((row1, ds1), (row2, ds1), (row3, ds2)):
            assert manifest["pages"][row_uuid]["database"] == ds_uuid
            assert manifest["pages"][row_uuid]["parent"] is None
        assert any(asset.endswith("doc.pdf") for asset in manifest["pages"][row1]["assets"])

    def test_full_page_database_with_bare_rows_folder(self):
        """Full-page database export: html and csv share the uuid and the
        rows folder carries no uuid suffix — rows parent to the db's page."""
        db_uuid = "7a" * 16
        row_uuid = "8b" * 16
        base = "Private & Shared"
        files = {
            f"{base}/Clientes {db_uuid}.html": page_html("Clientes"),
            f"{base}/Clientes {db_uuid}.csv": "﻿Name,Lead\nAdvantia,\n".encode("utf-8"),
            f"{base}/Clientes/Advantia {row_uuid}.html": page_html("Advantia"),
        }
        _, manifest = parse(files)
        assert manifest["root_pages"] == [db_uuid]
        database = manifest["databases"][db_uuid]
        assert database["parent"] == db_uuid
        assert database["rows"] == [row_uuid]
        assert manifest["pages"][row_uuid]["database"] == db_uuid

    def test_cp437_filename_decoding(self):
        # legacy zips without the utf-8 flag decode entry names as cp437
        raw = "Café.html".encode("utf-8").decode("cp437")
        info = types.SimpleNamespace(flag_bits=0, filename=raw)
        assert NotionExportParser._decode_name(info) == "Café.html"

    def test_utf8_flagged_names_untouched(self):
        info = types.SimpleNamespace(flag_bits=0x800, filename="Café.html")
        assert NotionExportParser._decode_name(info) == "Café.html"
