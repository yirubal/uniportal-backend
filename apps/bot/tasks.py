"""Inbox extraction; claiming and retries are owned by run_worker."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .processor import extract_document


def process_inbox_item(inbox_item):
    if not inbox_item.file:
        raise ValueError('Inbox item has no file; manual review required.')
    # Works with local storage and R2 without assuming a filesystem path.
    with TemporaryDirectory(prefix='uniportal-extract-') as directory:
        path = Path(directory) / ('document' + Path(inbox_item.file.name).suffix)
        try:
            inbox_item.file.open('rb')
            with path.open('wb') as target:
                for chunk in inbox_item.file.chunks():
                    target.write(chunk)
        finally:
            inbox_item.file.close()
        result = extract_document(str(path))
    if result.outcome in {'skipped', 'empty'} or not result.text.strip():
        raise ValueError(result.note or 'No text extracted; manual review required.')
    return {'extracted_text': result.text, 'processing_error': result.note,
            'extraction_outcome': result.outcome}


def recover_stuck_inbox_items():
    from .worker import recover_stale_claims
    return recover_stale_claims('inbox')


def recover_failed_inbox_items():
    # Kept for old callers; permanent failures require an explicit admin retry.
    return 0
