"""
Read daily briefs from Google Drive JSON files using per-user OAuth 2.0 tokens.

Each user authenticates with Google Drive and stores a refresh token.
This module uses that token to access their briefs.

Folder structure expected:
  <parent_folder>/briefs/<YYYY-MM-DD>/
    manifest.json          — metadata (brief_date, brief_type, generated_at)
    today.json             — array of items
    meetings.json          — array of items (yesterday-meetings section)
    action-items.json      — array of items
    fyi.json               — array of items
    manager-update.json    — single item dict (wrapped in array by reader)
    accounts/              — per-account JSON files
    updates/               — per-account update JSON files

Performance notes:
  - Drive credentials are cached per refresh_token with a 45-minute TTL
    so token refresh (the single most expensive call) only happens once
    per session, not on every page load.
  - Folder IDs (briefs/, date subfolders) are cached with a 5-minute TTL.
  - File downloads within a date folder use ThreadPoolExecutor for
    parallel I/O — the Drive API is the bottleneck, not CPU.
"""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List, Tuple

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

logger = logging.getLogger(__name__)

BRIEFS_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

logger.info(f'gdrive_briefs: GDRIVE_AVAILABLE={GDRIVE_AVAILABLE}, BRIEFS_FOLDER_ID={BRIEFS_FOLDER_ID}, HAS_OAUTH_CREDS={bool(GOOGLE_CLIENT_ID)}')

# Map filename -> section slug used by the viewer template
_FILE_TO_SECTION = {
    'today.json': 'today',
    'meetings.json': 'yesterday-meetings',
    'action-items.json': 'action-items',
    'fyi.json': 'fyi',
    'manager-update.json': 'manager-update',
}

# ── Credential and folder caching ────────────────────────────────────────

_cache_lock = threading.Lock()

# {refresh_token: (drive_service, expiry_monotonic)}
_drive_cache: Dict[str, Tuple] = {}
_DRIVE_TTL = 45 * 60  # 45 minutes (Google access tokens last 60 min)

# {cache_key: (folder_id, expiry_monotonic)}
_folder_cache: Dict[str, Tuple] = {}
_FOLDER_TTL = 5 * 60  # 5 minutes

# {cache_key: (file_listing, expiry_monotonic)}
_listing_cache: Dict[str, Tuple] = {}
_LISTING_TTL = 2 * 60  # 2 minutes


def _get_drive_service(refresh_token: str):
    """Get or create a cached Google Drive service for this refresh token."""
    if not GDRIVE_AVAILABLE or not refresh_token:
        return None
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.error('_get_drive_service: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set')
        return None

    now = time.monotonic()
    cache_key = refresh_token[-16:]  # last 16 chars as key (avoid storing full token)

    with _cache_lock:
        cached = _drive_cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    try:
        t0 = time.monotonic()
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        request = Request()
        credentials.refresh(request)
        drive = build('drive', 'v3', credentials=credentials)
        elapsed = time.monotonic() - t0
        logger.info(f'_get_drive_service: token refresh + build took {elapsed:.1f}s')

        with _cache_lock:
            _drive_cache[cache_key] = (drive, now + _DRIVE_TTL)
        return drive
    except Exception as e:
        logger.error(f'_get_drive_service: Failed to build Drive service: {e}', exc_info=True)
        return None


def _find_folder_cached(drive, parent_id: str, name: str) -> Optional[str]:
    """Find a subfolder by name, with caching."""
    now = time.monotonic()
    cache_key = f'{parent_id}/{name}'

    with _cache_lock:
        cached = _folder_cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    query = f"parents='{parent_id}' and name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, spaces='drive', pageSize=1, fields='files(id)').execute()
    files = results.get('files', [])
    if not files:
        logger.warning(f'No folder "{name}" found in parent {parent_id}')
        return None
    folder_id = files[0]['id']

    with _cache_lock:
        _folder_cache[cache_key] = (folder_id, now + _FOLDER_TTL)
    return folder_id


def _list_date_folder(drive, date_folder_id: str):
    """List all files and subfolders in a date folder, with caching.
    Returns (file_map, subfolder_map)."""
    now = time.monotonic()
    cache_key = f'listing:{date_folder_id}'

    with _cache_lock:
        cached = _listing_cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    query = f"parents='{date_folder_id}' and trashed=false"
    results = drive.files().list(
        q=query, spaces='drive', pageSize=50,
        fields='files(id,name,mimeType)',
    ).execute()
    all_files = results.get('files', [])

    file_map = {}
    subfolder_map = {}
    for f in all_files:
        if f['mimeType'] == 'application/vnd.google-apps.folder':
            subfolder_map[f['name']] = f['id']
        else:
            file_map[f['name']] = f['id']

    result = (file_map, subfolder_map)
    with _cache_lock:
        _listing_cache[cache_key] = (result, now + _LISTING_TTL)
    return result


def _download_json(drive, file_id: str):
    """Download and parse a JSON file from Drive."""
    content = drive.files().get_media(fileId=file_id).execute()
    return json.loads(content)


def _read_subfolder_files_parallel(drive, subfolder_id: str) -> List[Dict]:
    """Read all JSON files from a subfolder in parallel."""
    query = f"parents='{subfolder_id}' and trashed=false"
    results = drive.files().list(
        q=query, spaces='drive', pageSize=50,
        fields='files(id,name)',
    ).execute()

    json_files = [f for f in results.get('files', []) if f['name'].endswith('.json')]
    if not json_files:
        return []

    items = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_download_json, drive, f['id']): f['name']
            for f in json_files
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                data = future.result()
                if isinstance(data, list):
                    items.extend(data)
                elif isinstance(data, dict):
                    items.append(data)
            except Exception as e:
                logger.warning(f'Failed to read {name} from subfolder: {e}')
    return items


def _resolve_date_folder(refresh_token: str, brief_date: str, folder_id: Optional[str] = None):
    """Authenticate, find the date folder, and return (drive, date_folder_id).
    Uses caching for credentials and folder lookups. Returns (None, None) on failure."""
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder or not refresh_token:
        return None, None

    drive = _get_drive_service(refresh_token)
    if not drive:
        return None, None

    briefs_folder_id = _find_folder_cached(drive, parent_folder, 'briefs')
    if not briefs_folder_id:
        return None, None

    date_folder_id = _find_folder_cached(drive, briefs_folder_id, brief_date)
    if not date_folder_id:
        return None, None

    return drive, date_folder_id


def read_brief_metadata(brief_date: str, refresh_token: str, folder_id: Optional[str] = None) -> Optional[Dict]:
    """Read just the manifest and folder listing (no section file downloads).
    Fast enough for the initial page skeleton. Returns dict with brief_date,
    brief_type, generated_at, and available_sections (list of slugs)."""
    try:
        drive, date_folder_id = _resolve_date_folder(refresh_token, brief_date, folder_id)
        if not drive:
            return None

        file_map, subfolder_map = _list_date_folder(drive, date_folder_id)

        meta = {'brief_date': brief_date, 'brief_type': 'default'}
        if 'manifest.json' in file_map:
            try:
                manifest = _download_json(drive, file_map['manifest.json'])
                meta['brief_date'] = manifest.get('brief_date', brief_date)
                meta['brief_type'] = manifest.get('brief_type', 'default')
                meta['generated_at'] = manifest.get('generated_at')
            except Exception as e:
                logger.warning(f'Failed to read manifest.json: {e}')

        available = []
        for filename, slug in _FILE_TO_SECTION.items():
            if filename in file_map:
                available.append(slug)
        if 'accounts' in subfolder_map:
            available.append('account-recap')
        if 'updates' in subfolder_map:
            available.append('customer-updates')
        meta['available_sections'] = available
        return meta

    except Exception as e:
        logger.error(f'read_brief_metadata: Error: {e}', exc_info=True)
        return None


def read_section(brief_date: str, section_slug: str, refresh_token: str,
                 folder_id: Optional[str] = None) -> Optional[List[Dict]]:
    """Read a single section's data from Drive. Uses cached credentials and
    folder IDs so this is typically just one file download."""
    try:
        drive, date_folder_id = _resolve_date_folder(refresh_token, brief_date, folder_id)
        if not drive:
            return None

        file_map, subfolder_map = _list_date_folder(drive, date_folder_id)

        # Section files
        _SLUG_TO_FILE = {v: k for k, v in _FILE_TO_SECTION.items()}
        if section_slug in _SLUG_TO_FILE:
            filename = _SLUG_TO_FILE[section_slug]
            if filename not in file_map:
                return []
            data = _download_json(drive, file_map[filename])
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
            return []

        # Subfolder sections
        if section_slug == 'account-recap' and 'accounts' in subfolder_map:
            return _read_subfolder_files_parallel(drive, subfolder_map['accounts'])
        if section_slug == 'customer-updates' and 'updates' in subfolder_map:
            return _read_subfolder_files_parallel(drive, subfolder_map['updates'])

        return []

    except Exception as e:
        logger.error(f'read_section: Error reading {section_slug} for {brief_date}: {e}', exc_info=True)
        return None


def read_brief_manifest(brief_date: str, refresh_token: str, folder_id: Optional[str] = None) -> Optional[Dict]:
    """Read a complete brief from Google Drive by assembling all section files
    in parallel. Uses cached credentials and folder lookups.

    Returns a dict with:
      - brief_date, brief_type, generated_at (from manifest.json)
      - sections: {slug: [items]} for each section
    """
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder or not refresh_token:
        return None

    try:
        drive, date_folder_id = _resolve_date_folder(refresh_token, brief_date, folder_id)
        if not drive:
            return None

        file_map, subfolder_map = _list_date_folder(drive, date_folder_id)

        # Read manifest
        brief_data = {'brief_date': brief_date, 'brief_type': 'default', 'sections': {}}
        if 'manifest.json' in file_map:
            try:
                manifest = _download_json(drive, file_map['manifest.json'])
                brief_data['brief_date'] = manifest.get('brief_date', brief_date)
                brief_data['brief_type'] = manifest.get('brief_type', 'default')
                brief_data['generated_at'] = manifest.get('generated_at')
            except Exception as e:
                logger.warning(f'Failed to read manifest.json: {e}')

        # Download all section files in parallel
        download_tasks = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for filename, section_slug in _FILE_TO_SECTION.items():
                if filename in file_map:
                    download_tasks[pool.submit(_download_json, drive, file_map[filename])] = (filename, section_slug)

            # Also submit subfolder reads
            if 'accounts' in subfolder_map:
                download_tasks[pool.submit(_read_subfolder_files_parallel, drive, subfolder_map['accounts'])] = ('accounts/', 'account-recap')
            if 'updates' in subfolder_map:
                download_tasks[pool.submit(_read_subfolder_files_parallel, drive, subfolder_map['updates'])] = ('updates/', 'customer-updates')

            for future in as_completed(download_tasks):
                filename, section_slug = download_tasks[future]
                try:
                    data = future.result()
                    if isinstance(data, list):
                        brief_data['sections'][section_slug] = data
                    elif isinstance(data, dict):
                        brief_data['sections'][section_slug] = [data]
                    logger.info(f'read_brief_manifest: {filename} -> {section_slug}: {len(brief_data["sections"].get(section_slug, []))} items')
                except Exception as e:
                    logger.warning(f'Failed to read {filename}: {e}')

        total_items = sum(len(v) for v in brief_data['sections'].values())
        logger.info(f'read_brief_manifest: Assembled brief for {brief_date} with {len(brief_data["sections"])} sections, {total_items} total items')
        return brief_data

    except Exception as e:
        logger.error(f'read_brief_manifest: Error reading brief {brief_date}: {e}', exc_info=True)
        return None


def list_available_briefs(refresh_token: str, folder_id: Optional[str] = None) -> List[str]:
    """List all available brief dates from Google Drive in descending order."""
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder or not refresh_token:
        return []

    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            logger.error('list_available_briefs: Could not authenticate with Google Drive')
            return []

        briefs_folder_id = _find_folder_cached(drive, parent_folder, 'briefs')
        if not briefs_folder_id:
            return []

        query = f"parents='{briefs_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive.files().list(
            q=query, spaces='drive', pageSize=100,
            fields='files(name)', orderBy='name desc',
        ).execute()

        files = results.get('files', [])
        dates = []
        for f in files:
            name = f['name']
            if len(name) == 10 and name[4] == '-' and name[7] == '-':
                try:
                    from datetime import datetime
                    datetime.strptime(name, '%Y-%m-%d')
                    dates.append(name)
                except ValueError:
                    pass

        logger.info(f'list_available_briefs: Returning {len(dates)} valid dates')
        return sorted(dates, reverse=True)

    except Exception as e:
        logger.error(f'list_available_briefs: Error listing briefs: {e}', exc_info=True)
        return []
