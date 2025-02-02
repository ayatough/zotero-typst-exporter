import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional
from zipfile import ZipFile

import fitz
import requests
import typer
from dotenv import load_dotenv
from pyzotero import zotero
from rich import print
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="CLI tool for exporting Zotero annotations to Typst",
    no_args_is_help=True,  # Show help when no arguments are provided
    context_settings={"help_option_names": ["-h", "--help"]},  # Enable -h for help
)


@dataclass
class Property:
    API_KEY: str = None
    USER_ID: str = None
    WEBDAV_URL: str = None
    WEBDAV_USERNAME: str = None
    WEBDAV_PASSWORD: str = None
    CACHE_DIR: Path = Path("~/.cache/zotero-cli").expanduser()
    zot: None | zotero.Zotero = None


prop = Property()


@app.callback()
def app_callback(
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        "-e",
        help="Path to the .env file to use",
        exists=False,
    ),
):
    """Initialize configuration"""
    load_dotenv(override=True)
    prop.API_KEY = os.getenv("ZOTERO_API_KEY")
    prop.USER_ID = os.getenv("ZOTERO_USER_ID")
    prop.WEBDAV_URL = os.getenv("ZOTERO_WEBDAV_URL")
    prop.WEBDAV_USERNAME = os.getenv("ZOTERO_WEBDAV_USERNAME")
    prop.WEBDAV_PASSWORD = os.getenv("ZOTERO_WEBDAV_PASSWORD")

    # キャッシュディレクトリの作成
    prop.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    library_id = prop.USER_ID
    library_type = "user"
    prop.zot = zotero.Zotero(library_id, library_type, prop.API_KEY)


def get_cached_pdf(attachment_id: str) -> fitz.Document:
    """
    PDFをキャッシュから取得、なければダウンロードして保存
    """
    cache_path = prop.CACHE_DIR / f"{attachment_id}.pdf"

    if not cache_path.exists():
        # WebDAVからZIPをダウンロード
        zip_url = f"{prop.WEBDAV_URL}/zotero/{attachment_id}.zip"
        response = requests.get(
            zip_url, auth=(prop.WEBDAV_USERNAME, prop.WEBDAV_PASSWORD)
        )
        response.raise_for_status()

        # ZIPからPDFを抽出
        with ZipFile(BytesIO(response.content)) as zipped:
            pdf_name = next(name for name in zipped.namelist() if name.endswith(".pdf"))
            pdf_data = zipped.read(pdf_name)

            # キャッシュとして保存
            cache_path.write_bytes(pdf_data)

    # PDFを返す
    return fitz.open(cache_path)


def parse_date(date_str: str) -> tuple[str, str]:
    """
    様々な形式の日付文字列から年と月を抽出する

    Args:
        date_str: 日付文字列

    Returns:
        tuple[str, str]: (年, 月)のタプル。取得できない場合は空文字列
    """
    if not date_str:
        return "", ""

    # ISOフォーマット (2025-01-19T23:25:38Z) の処理
    if "T" in date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return str(dt.year), str(dt.month).zfill(2)
        except ValueError:
            pass

    # YYYY-MM-DD, YYYY/MM/DD, YYYY-MM の処理
    patterns = [
        r"(\d{4})[/-](\d{2})(?:[/-]\d{2})?",  # 2024-06-19 or 2024/06/19 or 2024-06
    ]

    for pattern in patterns:
        if match := re.search(pattern, date_str):
            return match.group(1), match.group(2)

    # 日本語形式 (10月 23, 2023) の処理
    if match := re.search(r"(\d{1,2})月\s+\d{1,2},\s+(\d{4})", date_str):
        return match.group(2), str(int(match.group(1))).zfill(2)

    return "", ""


@app.command()
def collections():
    """Display list of collections"""
    assert prop.zot is not None

    # テーブルの作成
    table = Table(title="Zotero Collections")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Items", justify="right", style="magenta")
    table.add_column("Parent", style="blue")

    try:
        collections = prop.zot.collections()
        collection_names = {c["data"]["key"]: c["data"]["name"] for c in collections}

        for collection in collections:
            coll_id = collection["data"]["key"]
            name = collection["data"]["name"]
            num_items = len(prop.zot.collection_items_top(coll_id))
            parent_id = collection["data"].get("parentCollection")
            parent_name = collection_names.get(parent_id, "-") if parent_id else "-"

            table.add_row(coll_id, name, str(num_items), parent_name)

        console = Console()
        console.print(table)

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}", err=True)
        raise typer.Exit(1)


@app.command()
def items(collection_id: str = typer.Argument(..., help="Collection ID")):
    """Display list of items in the specified collection"""
    assert prop.zot is not None

    table = Table(title=f"Items in Collection: {collection_id}")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Authors", style="yellow")
    table.add_column("Year", style="blue")
    table.add_column("Type", style="magenta")

    try:
        items = prop.zot.collection_items_top(collection_id)

        for item in items:
            data = item["data"]
            # 著者名の取得
            authors = []
            for creator in data.get("creators", []):
                if "firstName" in creator and "lastName" in creator:
                    authors.append(f"{creator['lastName']}, {creator['firstName']}")
                elif "name" in creator:
                    authors.append(creator["name"])

            # 日付の処理
            year, month = parse_date(data.get("date", ""))
            date_str = f"{year}-{month}" if year and month else year or ""

            table.add_row(
                data["key"],
                data.get("title", ""),
                "; ".join(authors),
                date_str,
                data.get("itemType", ""),
            )

        console = Console()
        console.print(table)

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}", err=True)
        raise typer.Exit(1)


@app.command()
def annotations(item_id: str = typer.Argument(..., help="Item ID")):
    """Display list of annotations for the specified item"""
    assert prop.zot is not None

    table = Table(title=f"Annotations for Item: {item_id}")
    table.add_column("Type", style="cyan")
    table.add_column("Text", style="green", max_width=60)
    table.add_column("Comment", style="yellow", max_width=40)
    table.add_column("Tags", style="red")  # タグ列を追加
    table.add_column("Page", style="blue")

    try:
        attachments = prop.zot.children(item_id)
        pdf_items = [
            att
            for att in attachments
            if att["data"]["itemType"] == "attachment"
            and att["data"].get("contentType") == "application/pdf"
        ]

        if not pdf_items:
            typer.echo("PDFアタッチメントが見つかりませんでした。")
            raise typer.Exit(1)

        for pdf_item in pdf_items:
            annotations = prop.zot.children(pdf_item["key"])

            for anno in annotations:
                data = anno["data"]
                if data["itemType"] != "annotation":
                    continue

                anno_type = data["annotationType"]
                color = data.get("annotationColor", "")
                text = data.get("annotationText", "")
                comment = data.get("annotationComment", "")

                # タグの取得
                tags = ", ".join(t["tag"] for t in data.get("tags", []))

                # アノテーションタイプに応じたテキスト装飾
                formatted_text = ""
                if anno_type == "highlight":
                    formatted_text = f"[on {color}]{text}[/]"
                elif anno_type in ["underline", "image", "note"]:
                    formatted_text = f"[u {color}]{text or '<' + anno_type + '>'}[/]"

                # ページ情報の取得
                position = eval(data.get("annotationPosition", "{}"))
                page = position.get("pageIndex", 0) + 1 if position else ""

                table.add_row(
                    anno_type,
                    formatted_text,
                    comment,
                    tags,  # タグ列を追加
                    str(page),
                )

        console = Console()
        console.print(table)

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}", err=True)
        raise typer.Exit(1)


def convert_pdf_rect(page, rect):
    return (
        rect[0],
        page.rect.height - rect[3],
        rect[2],
        page.rect.height - rect[1],
    )


def process_item_annotations(item_id: str, output_dir: Path) -> tuple[str, dict]:
    """文献のアノテーション情報を処理する共通関数"""
    assert prop.zot is not None

    item = prop.zot.item(item_id)
    item_data = item["data"]

    # BibTeXの引用キーを取得
    citation_key = get_citation_key(prop.USER_ID, item_data)
    typer.echo(citation_key)

    # 著者情報の取得
    authors = []
    for creator in item_data.get("creators", []):
        if "firstName" in creator and "lastName" in creator:
            authors.append(f"{creator['lastName']}, {creator['firstName']}")
        elif "name" in creator:
            authors.append(creator["name"])

    # 年と月の取得
    year, month = parse_date(item_data.get("date", ""))

    paper_info = {
        "title": item_data.get("title", ""),
        "authors": authors,
        "year": year,
        "month": month,  # 月の情報を追加
        "annotations": [],
    }

    # アノテーションの抽出
    attachments = prop.zot.children(item_id)
    pdf_items = [
        att
        for att in attachments
        if att["data"]["itemType"] == "attachment"
        and att["data"].get("contentType") == "application/pdf"
    ]

    for pdf_item in pdf_items:
        doc = get_cached_pdf(pdf_item["key"])
        annotations = prop.zot.children(pdf_item["key"])

        for anno in annotations:
            data = anno["data"]
            if data["itemType"] != "annotation":
                continue

            anno_type = data["annotationType"]
            annotation_info = {
                "type": anno_type,
                "text": data.get("annotationText", ""),
                "comment": data.get("annotationComment", ""),
                "tags": [t["tag"] for t in data.get("tags", [])],
                "page": eval(data.get("annotationPosition", "{}")).get("pageIndex", 0)
                + 1,
            }

            # 画像アノテーションの処理
            if anno_type == "image":
                position = eval(data.get("annotationPosition", "{}"))
                if position:
                    page = doc[position["pageIndex"]]
                    rect = convert_pdf_rect(page, position["rects"][0])

                    hash_input = f"{item_id}_{position['pageIndex']}_{rect[0]}_{rect[1]}_{rect[2]}_{rect[3]}"
                    file_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
                    image_filename = f"annotation_{file_hash}.png"
                    image_path = output_dir / image_filename

                    pix = page.get_pixmap(
                        matrix=fitz.Matrix(4, 4), clip=rect, alpha=False
                    )
                    pix.save(image_path)

                    annotation_info["image"] = str(image_path)

            paper_info["annotations"].append(annotation_info)

    return citation_key, paper_info


def get_citation_key(library_id: str, item_data: dict) -> str:
    """
    文献のBibTeX引用キーを取得する関数
    """
    assert prop.zot is not None
    try:
        # BibTeX形式でアイテムを取得
        bibtex = prop.zot.item(item_data["key"], format="bibtex")
        # entriesから最初のエントリのcitation keyを取得
        if bibtex.entries:
            return bibtex.entries[0]["ID"]
    except Exception as e:
        typer.echo(f"Warning: BibTeX keyの取得に失敗: {str(e)}")

    # 取得に失敗した場合はZoteroのキーを使用
    return item_data["key"]


def escape_typst_string(s: str) -> str:
    """
    文字列をTypst形式で安全にエスケープする
    """
    if not s:
        return ""

    # バックスラッシュを最初にエスケープ
    s = s.replace("\\", "\\\\")

    # ダブルクォートをエスケープ
    s = s.replace('"', '\\"')

    return s


def write_typst_annotations(papers: dict, output_path: Path):
    """アノテーション情報をTypst形式で書き出す共通関数"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("#let papers = (\n")
        for paper_key, paper in papers.items():
            f.write(f"  {paper_key}: (\n")
            f.write(f'    title: "{escape_typst_string(paper["title"])}",\n')
            authors_str = ", ".join(
                f'"{escape_typst_string(author)}"' for author in paper["authors"]
            )
            f.write(f"    authors: ({authors_str}),\n")
            f.write(f'    year: "{paper["year"]}",\n')
            if paper["month"]:  # 月の情報がある場合のみ出力
                f.write(f'    month: "{paper["month"]}",\n')

            f.write("    annotations: (\n")
            for anno in paper["annotations"]:
                f.write("      (\n")
                for key, value in anno.items():
                    if key == "tags":
                        tags_str = ", ".join(f'"{tag}"' for tag in value)
                        if len(value) == 1:
                            tags_str += ","
                        f.write(f"        {key}: ({tags_str}),\n")
                    elif isinstance(value, (int, float)):
                        f.write(f"        {key}: {value},\n")
                    else:
                        f.write(f'        {key}: "{escape_typst_string(value)}",\n')
                f.write("      ),\n")
            f.write("    ),\n")
            f.write("  ),\n")
        f.write(")\n")


@app.command()
def export_annotations(
    item_id: str = typer.Argument(..., help="文献ID"),
    output_dir: Path = typer.Option(
        Path("assets"), "--output-dir", "-o", help="Output directory for annotations"
    ),
):
    """Export annotations from a specific item"""
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        citation_key, paper_info = process_item_annotations(item_id, output_dir)
        papers = {citation_key: paper_info}

        typst_output = output_dir / "annotations.typ"
        write_typst_annotations(papers, typst_output)

        typer.echo(f"アノテーションを {typst_output} にエクスポートしました。")

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}", err=True)
        raise typer.Exit(1)


@app.command()
def export_collection_annotations(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    output_dir: Path = typer.Option(
        Path("assets"), "--output-dir", "-o", help="Output directory for annotations"
    ),
):
    """Export annotations from all items in a collection"""
    assert prop.zot is not None

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # コレクションのトップレベルアイテムを取得
        items = prop.zot.collection_items_top(collection_id)
        papers = {}

        with typer.progressbar(items, label="文献のアノテーションを処理中") as progress:
            for item in progress:
                paper_key = item["key"]
                citation_key, paper_info = process_item_annotations(
                    paper_key, output_dir
                )

                if paper_info["annotations"]:  # アノテーションがある文献のみ追加
                    papers[citation_key] = paper_info

        # Typst変数としてエクスポート
        typst_output = output_dir / "collection_annotations.typ"
        write_typst_annotations(papers, typst_output)

        typer.echo(f"\nアノテーションを {typst_output} にエクスポートしました。")
        typer.echo(f"処理された文献数: {len(items)}")
        typer.echo(f"アノテーションを含む文献数: {len(papers)}")

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}", err=True)
        raise typer.Exit(1)


@app.command()
def export_bibtex(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    output_file: Path = typer.Option(
        Path("references.bib"), "--output", "-o", help="Path to output BibTeX file"
    ),
):
    """Export items in a collection as BibTeX"""
    assert prop.zot is not None

    try:
        # コレクションのトップレベルアイテムを取得
        items = prop.zot.collection_items_top(collection_id)

        successful_exports = 0
        all_entries = []

        with typer.progressbar(items, label="BibTeXをエクスポート中") as progress:
            for item in progress:
                try:
                    # bibtexparserオブジェクトを取得
                    bib_data = prop.zot.item(item["key"], format="bibtex")
                    # entriesプロパティから引用情報を取得
                    entries = bib_data.entries
                    if entries:
                        all_entries.extend(entries)
                        successful_exports += 1
                except Exception as e:
                    title = item["data"].get("title", "Unknown Title")
                    typer.echo(
                        f"\nWarning: アイテム「{title}」の処理中にエラー: {str(e)}"
                    )
                    continue

        if all_entries:
            # bibtexparserオブジェクトを作成して書き出し
            from bibtexparser.bwriter import BibTexWriter
            from bibtexparser.bibdatabase import BibDatabase

            db = BibDatabase()
            db.entries = all_entries

            writer = BibTexWriter()
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(writer.write(db))

            typer.echo(f"\nBibTeXを {output_file} にエクスポートしました。")
            typer.echo(f"処理されたアイテム数: {len(items)}")
            typer.echo(f"成功したエクスポート数: {successful_exports}")
        else:
            typer.echo("エクスポートできたアイテムがありませんでした。")
            raise typer.Exit(1)

    except Exception as e:
        typer.echo(f"エラーが発生しました: {str(e)}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
