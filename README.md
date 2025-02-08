# Zotero Typst Exporter

A command-line tool for exporting Zotero annotations to Typst format.

- Including image annotation
- Including bibtex export

## Installation

```bash
pip install git+https://github.com/ayatough/zotero-typst-exporter.git
```

## Configuration

Create a `.env` file with the following variables:

```env
ZOTERO_API_KEY=your_api_key
ZOTERO_USER_ID=your_user_id
ZOTERO_WEBDAV_URL=your_webdav_url
ZOTERO_WEBDAV_USERNAME=your_webdav_username
ZOTERO_WEBDAV_PASSWORD=your_webdav_password
```

## Usage

Display list of collections:
```bash
zotero-typst-exporter collections
```

Display list of items in the specified collection:
```bash
zotero-typst-exporter items COLLECTION_ID
```

Display list of annotations for the specified item:
```bash
zotero-typst-exporter annotations ITEM_ID
```

Export annotations from a specific item:
```bash
zotero-typst-exporter export-annotations ITEM_ID
```

Export annotations from all items in a collection:
```bash
zotero-typst-exporter export-collection-annotations COLLECTION_ID
```

Export items in a collection as BibTeX:
```bash
zotero-typst-exporter export-bibtex-annotations COLLECTION_ID
```
