# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Parser for Notion HTML exports.

Reads a Notion "Export" zip (format: HTML, include subpages ON, create
folders for subpages ON) and produces a manifest describing the page
tree, databases, and assets it contains — without touching the database.

Notion export layout rules this parser understands:
- A page is a file named ``<Title> <32-hex-uuid>.html``.
- Its children (subpages and assets) live in a sibling folder named
  ``<Title>``, ``<Title> <32-hex-uuid>`` or — when several sibling pages
  share a title — ``<Title> <first4>-<last4>`` of the page uuid.
- A database is a file named ``<Title> <32-hex-uuid>.csv`` (optionally
  with a ``_all`` variant carrying every property column). Each row is
  itself a page inside the matching sibling folder.
- Newer exports (Notion "data sources", 2025+) name each database CSV
  ``<DB Title> <db-uuid>_<Source Title> <source-uuid>.csv`` and nest the
  row pages under ``<DB Title>/<Source Title>/`` — folders without uuids.
- The outer download zip may nest the real export as ``*-Part-N.zip``.
- Zip entry names may be encoded as cp437 when the UTF-8 flag is unset.
"""

import csv
import io
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass, field

# Notion database properties (long text/rollups) can exceed Python's default
# 128 KB CSV field limit, which would otherwise raise _csv.Error mid-parse.
csv.field_size_limit(10 * 1024 * 1024)

# `<Title> <uuid>.<ext>` — the standard Notion export filename
FILENAME_RE = re.compile(r"^(?P<title>.*?) (?P<uuid>[0-9a-f]{32})(?P<all>_all)?\.(?P<ext>html|csv|md)$")
# `<DB Title> <db-uuid>_<Source Title> <source-uuid>.csv` — data-source CSV
DATA_SOURCE_CSV_RE = re.compile(
    r"^(?P<dbtitle>.*?) (?P<dbuuid>[0-9a-f]{32})"
    r"_(?P<dstitle>.*?) (?P<dsuuid>[0-9a-f]{32})(?P<all>_all)?\.csv$"
)
# Disambiguated child folder: `<Title> <first4>-<last4>`
SHORT_SUFFIX_RE = re.compile(r"^(?P<title>.*?) (?P<pre>[0-9a-f]{4})-(?P<suf>[0-9a-f]{4})$")
# Page icon exported in the document head
PAGE_ICON_RE = re.compile(r'<meta name="data-notion-page-icon" content="([^"]*)"')
HTML_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)

NESTED_PART_RE = re.compile(r".*-Part-\d+\.zip$")

ASSET_EXTENSIONS_IGNORED = {"html", "csv", "md", "zip"}

# Uncompressed-size ceiling per zip entry. The upload endpoint only caps the
# *compressed* archive, so without this a deflate bomb (trivially 1000:1) inside
# the size budget could expand to hundreds of GB and OOM the worker. No single
# Notion export file (page HTML, CSV, asset, or nested part) should exceed this.
MAX_ENTRY_BYTES = 256 * 1024 * 1024  # 256MB


def _read_bounded(fileobj, max_bytes, label):
    """Read a decompressing file object, raising if it exceeds ``max_bytes``.

    Reads in chunks so a bomb is stopped after ~max_bytes rather than fully
    decompressed into memory.
    """
    chunks = []
    total = 0
    while True:
        try:
            chunk = fileobj.read(1 << 20)  # 1MB
        except (zlib.error, EOFError, OSError) as exc:
            raise NotionExportError(f"corrupt_entry: '{label}' could not be decompressed ({exc}).")
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise NotionExportError(
                f"entry_too_large: '{label}' decompresses beyond the "
                f"{max_bytes // (1024 * 1024)}MB per-file limit; the export may be corrupt or malicious."
            )
        chunks.append(chunk)
    return b"".join(chunks)


class NotionExportError(Exception):
    """Raised when the uploaded file is not a usable Notion HTML export."""


@dataclass
class NotionPage:
    uuid: str
    title: str
    path: str  # entry path inside the export zip
    parent_uuid: str | None = None
    database_uuid: str | None = None  # set when this page is a database row
    icon: str | None = None
    children: list = field(default_factory=list)  # page uuids, in name order
    assets: list = field(default_factory=list)  # entry paths


@dataclass
class NotionDatabase:
    uuid: str
    title: str
    csv_path: str
    csv_all_path: str | None = None
    parent_uuid: str | None = None  # page embedding this database
    # set for data-source CSVs: the database the source belongs to
    source_db_uuid: str | None = None
    source_db_title: str | None = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)  # page uuids


class NotionExportParser:
    """Walks a Notion HTML export zip and builds an import manifest."""

    def __init__(self, fileobj):
        self._source = fileobj
        self.pages: dict = {}
        self.databases: dict = {}
        # folder path -> owning page/database uuid
        self._folder_owner: dict = {}
        # entry path -> zip entry (kept for later content reads)
        self._entries: dict = {}
        self._zips: list = []

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def parse(self):
        self._collect_entries()
        if not any(name.lower().endswith(".html") for name in self._entries):
            if any(name.lower().endswith(".md") for name in self._entries):
                raise NotionExportError(
                    "markdown_export: this looks like a 'Markdown & CSV' export. "
                    "Re-export from Notion using the HTML format."
                )
            raise NotionExportError("empty_export: no Notion pages found in the uploaded zip.")

        self._register_pages_and_databases()
        self._claim_folders()
        self._link_hierarchy()
        self._read_page_headers()
        self._read_database_csvs()
        return self.manifest()

    def manifest(self):
        root_pages = [
            uuid
            for uuid, page in self.pages.items()
            if page.parent_uuid is None and page.database_uuid is None
        ]
        return {
            "version": 1,
            "source": "notion",
            "root_pages": root_pages,
            "pages": {
                uuid: {
                    "title": p.title,
                    "path": p.path,
                    "parent": p.parent_uuid,
                    "database": p.database_uuid,
                    "icon": p.icon,
                    "children": p.children,
                    "assets": p.assets,
                }
                for uuid, p in self.pages.items()
            },
            "databases": {
                uuid: {
                    "title": d.title,
                    "csv_path": d.csv_path,
                    "csv_all_path": d.csv_all_path,
                    "parent": d.parent_uuid,
                    "columns": d.columns,
                    "rows": d.rows,
                }
                for uuid, d in self.databases.items()
            },
            "stats": {
                "pages": len([p for p in self.pages.values() if p.database_uuid is None]),
                "database_rows": len([p for p in self.pages.values() if p.database_uuid is not None]),
                "databases": len(self.databases),
                "assets": sum(len(p.assets) for p in self.pages.values()),
            },
        }

    def read_entry(self, path, max_bytes=MAX_ENTRY_BYTES):
        """Return the raw bytes of an entry, bounding decompression size."""
        zf, info = self._entries[path]
        with zf.open(info) as fileobj:
            return _read_bounded(fileobj, max_bytes, posixpath.basename(path))

    def close(self):
        for zf in self._zips:
            zf.close()

    # ------------------------------------------------------------------
    # zip walking
    # ------------------------------------------------------------------
    def _collect_entries(self):
        try:
            outer = zipfile.ZipFile(self._source)
        except zipfile.BadZipFile:
            raise NotionExportError("invalid_zip: the uploaded file is not a zip archive.")
        self._zips.append(outer)

        # Notion nests the real export as `...-Part-N.zip` inside the download
        infos = [i for i in outer.infolist() if not i.is_dir()]
        part_infos = [i for i in infos if NESTED_PART_RE.match(i.filename)]
        if part_infos and len(part_infos) == len(infos):
            for part in part_infos:
                try:
                    with outer.open(part) as fileobj:
                        raw = _read_bounded(fileobj, MAX_ENTRY_BYTES, part.filename)
                    inner = zipfile.ZipFile(io.BytesIO(raw))
                except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as exc:
                    raise NotionExportError(
                        f"invalid_zip: a nested export part could not be opened ({exc})."
                    )
                self._zips.append(inner)
                self._index_zip(inner)
        else:
            self._index_zip(outer)

    def _index_zip(self, zf):
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = self._decode_name(info)
            self._entries[name] = (zf, info)

    @staticmethod
    def _decode_name(info):
        # zipfile decodes names as cp437 unless the UTF-8 flag bit is set
        if info.flag_bits & 0x800:
            return info.filename
        try:
            return info.filename.encode("cp437").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return info.filename

    # ------------------------------------------------------------------
    # structure discovery
    # ------------------------------------------------------------------
    def _register_pages_and_databases(self):
        for path in self._entries:
            directory, filename = posixpath.split(path)
            ds_match = DATA_SOURCE_CSV_RE.match(filename)
            if ds_match:
                database = self.databases.setdefault(
                    ds_match["dsuuid"],
                    NotionDatabase(
                        uuid=ds_match["dsuuid"],
                        title=ds_match["dstitle"],
                        csv_path=path,
                        source_db_uuid=ds_match["dbuuid"],
                        source_db_title=ds_match["dbtitle"],
                    ),
                )
                if ds_match["all"]:
                    database.csv_all_path = path
                else:
                    database.csv_path = path
                continue
            match = FILENAME_RE.match(filename)
            if not match:
                continue
            uuid, title, ext = match["uuid"], match["title"], match["ext"]
            if ext == "html":
                self.pages[uuid] = NotionPage(uuid=uuid, title=title, path=path)
            elif ext == "csv":
                database = self.databases.setdefault(
                    uuid, NotionDatabase(uuid=uuid, title=title, csv_path=path)
                )
                if match["all"]:
                    database.csv_all_path = path
                else:
                    database.csv_path = path

    def _claim_folders(self):
        """Map each child folder to the page/database that owns it."""
        directories = set()
        for path in self._entries:
            directory = posixpath.dirname(path)
            while directory:
                directories.add(directory)
                directory = posixpath.dirname(directory)

        owners = list(self.pages.values()) + list(self.databases.values())
        claimed_folders = set()
        satisfied_owners = set()

        def claim(folder, owner_uuid):
            if owner_uuid in satisfied_owners:
                return False
            if folder in directories and folder not in claimed_folders:
                self._folder_owner[folder] = owner_uuid
                claimed_folders.add(folder)
                satisfied_owners.add(owner_uuid)
                return True
            return False

        def base_dir(owner):
            return posixpath.dirname(owner.csv_path if isinstance(owner, NotionDatabase) else owner.path)

        # Most-specific names first so duplicated titles resolve correctly;
        # each owner claims at most one folder. Data-source databases keep
        # their rows one level deeper (`<db title>/<source title>`, either
        # segment optionally carrying its uuid), so those candidates are
        # tried alongside the classic single-folder ones at each tier.
        def candidates(owner, rank):
            base = base_dir(owner)
            paths = []
            if isinstance(owner, NotionDatabase) and owner.source_db_uuid:
                db_full = f"{owner.source_db_title} {owner.source_db_uuid}"
                db_short = f"{owner.source_db_title} {owner.source_db_uuid[:4]}-{owner.source_db_uuid[-4:]}"
                ds_full = f"{owner.title} {owner.uuid}"
                if rank == 0:
                    paths += [
                        posixpath.join(base, db_full, ds_full),
                        posixpath.join(base, db_full, owner.title),
                        posixpath.join(base, owner.source_db_title, ds_full),
                    ]
                elif rank == 1:
                    paths.append(posixpath.join(base, db_short, owner.title))
                else:
                    paths.append(posixpath.join(base, owner.source_db_title, owner.title))
            if rank == 0:
                paths.append(posixpath.join(base, f"{owner.title} {owner.uuid}"))
            elif rank == 1:
                paths.append(posixpath.join(base, f"{owner.title} {owner.uuid[:4]}-{owner.uuid[-4:]}"))
            else:
                paths.append(posixpath.join(base, owner.title))
            return paths

        for rank in (0, 1, 2):
            for owner in owners:
                for folder in candidates(owner, rank):
                    claim(folder, owner.uuid)

    def _link_hierarchy(self):
        for path, page in ((p.path, p) for p in self.pages.values()):
            owner_uuid = self._folder_owner.get(posixpath.dirname(path))
            if owner_uuid is None:
                continue
            if owner_uuid in self.databases:
                page.database_uuid = owner_uuid
                self.databases[owner_uuid].rows.append(page.uuid)
            else:
                page.parent_uuid = owner_uuid
                self.pages[owner_uuid].children.append(page.uuid)

        for database in self.databases.values():
            # a data source's database exported as its own page is the parent;
            # a full-page database (html and csv share the uuid) parents to its
            # own page; otherwise fall back to the page owning the CSV's folder
            if database.source_db_uuid and database.source_db_uuid in self.pages:
                database.parent_uuid = database.source_db_uuid
            elif database.uuid in self.pages:
                database.parent_uuid = database.uuid
            else:
                database.parent_uuid = self._folder_owner.get(posixpath.dirname(database.csv_path))

        # Everything else in a page's folder is an asset of that page
        for path in self._entries:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext in ASSET_EXTENSIONS_IGNORED:
                continue
            directory = posixpath.dirname(path)
            owner_uuid = self._folder_owner.get(directory)
            # asset folders sit one level inside the owner's folder too
            if owner_uuid is None:
                owner_uuid = self._folder_owner.get(posixpath.dirname(directory))
            if owner_uuid in self.databases:
                owner_uuid = self._resolve_database_asset_owner(path, self.databases[owner_uuid])
            if owner_uuid in self.pages:
                self.pages[owner_uuid].assets.append(path)

        for page in self.pages.values():
            page.children.sort(key=lambda uuid: self.pages[uuid].title.lower())

    def _resolve_database_asset_owner(self, path, database):
        """An asset sitting directly in a database folder (e.g. a row icon
        named after the row) belongs to the matching row page; fall back to
        the page embedding the database."""
        stem = posixpath.basename(path).rsplit(".", 1)[0].strip().lower()
        for row_uuid in database.rows:
            if self.pages[row_uuid].title.strip().lower() == stem:
                return row_uuid
        return database.parent_uuid

    # ------------------------------------------------------------------
    # light content reads (headers only — full parsing happens at import)
    # ------------------------------------------------------------------
    def _read_page_headers(self):
        for page in self.pages.values():
            try:
                zf, info = self._entries[page.path]
            except KeyError:
                continue
            # stream only the first 4KB — never decompress the whole page just
            # to read its <title> and icon meta (guards the synchronous path)
            with zf.open(info) as fileobj:
                head = fileobj.read(4096).decode("utf-8", errors="replace")
            icon_match = PAGE_ICON_RE.search(head)
            if icon_match:
                page.icon = icon_match.group(1)
            title_match = HTML_TITLE_RE.search(head)
            if title_match and title_match.group(1).strip():
                page.title = _unescape_html(title_match.group(1).strip())

    def _read_database_csvs(self):
        for database in self.databases.values():
            path = database.csv_all_path or database.csv_path
            try:
                raw = self.read_entry(path).decode("utf-8-sig", errors="replace")
            except KeyError:
                continue
            reader = csv.reader(io.StringIO(raw))
            header = next(reader, None)
            if header:
                database.columns = [column.strip() for column in header if column.strip()]


def _unescape_html(text):
    import html

    return html.unescape(text)
