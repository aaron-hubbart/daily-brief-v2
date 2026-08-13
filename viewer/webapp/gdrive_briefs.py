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
"""
import json
import logging
import os
from typing import Optional, Dict, List

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

# Map filename → section slug used by the viewer template
_FILE_TO_SECTION = {
    'today.json': 'today',
    'meetings.json': 'yesterday-meetings',
    'action-items.json': 'action-items',
    'fyi.json': 'fyi',
    'manager-update.json': 'manager-update',
}


def _get_drive_service(refresh_token: str):
    """Get Google Drive service using user's refresh token."""
    if not GDRIVE_AVAILABLE or not refresh_token:
        return None

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.error('_get_drive_service: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set')
        return None

    try:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        request = Request()
        credentials.refresh(request)
        logger.info('_get_drive_service: Successfully authenticated with user refresh token')
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        logger.error(f'_get_drive_service: Failed to build Drive service: {e}', exc_info=True)
        return None


def _find_briefs_folder(drive, parent_folder: str) -> Optional[str]:
    """Find the /briefs/ subfolder inside the parent folder."""
    query = f"parents='{parent_folder}' and name='briefs' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, spaces='drive', pageSize=1, fields='files(id)').execute()
    files = results.get('files', [])
    if not files:
        logger.warning(f'No briefs folder found in parent folder {parent_folder}')
        return None
    return files[0]['id']


def _find_date_folder(drive, briefs_folder_id: str, brief_date: str) -> Optional[str]:
    """Find the date subfolder inside /briefs/."""
    query = f"parents='{briefs_folder_id}' and name='{brief_date}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=query, spaces='drive', pageSize=1, fields='files(id)').execute()
    files = results.get('files', [])
    if not files:
        logger.warning(f'No folder found for date {brief_date}')
        return None
    return files[0]['id']


def _download_json(drive, file_id: str):
    """Download and parse a JSON file from Drive."""
    content = drive.files().get_media(fileId=file_id).execute()
    return json.loads(content)


def _read_subfolder_files(drive, subfolder_id: str) -> List[Dict]:
    """Read all JSON files from a subfolder (accounts/ or updates/) and return as a flat list."""
    query = f"parents='{subfolder_id}' and trashed=false"
    results = drive.files().list(
        q=query, spaces='drive', pageSize=50,
        fields='files(id,name)',
    ).execute()

    items = []
    for f in results.get('files', []):
        if f['name'].endswith('.json'):
            try:
                data = _download_json(drive, f['id'])
                # Each account/update file can be a single dict or an array
                if isinstance(data, list):
                    items.extend(data)
                elif isinstance(data, dict):
                    items.append(data)
            except Exception as e:
                logger.warning(f'Failed to read {f["name"]} from subfolder: {e}')
    return items


def read_brief_manifest(brief_date: str, refresh_token: str, folder_id: Optional[str] = None) -> Optional[Dict]:
    """
    Read a complete brief from Google Drive by assembling all section files.

    Returns a dict with:
      - brief_date, brief_type, generated_at (from manifest.json)
      - sections: {slug: [items]} for each section
    """
    parent_folder = folder_id or BRIEFS_FOLDER_ID
    if not parent_folder or not refresh_token:
        return None

    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            logger.error('read_brief_manifest: Could not authenticate with Google Drive')
            return None

        briefs_folder_id = _find_briefs_folder(drive, parent_folder)
        if not briefs_folder_id:
            return None

        date_folder_id = _find_date_folder(drive, briefs_folder_id, brief_date)
        if not date_folder_id:
            return None

        # List all files and subfolders in the date folder
        query = f"parents='{date_folder_id}' and trashed=false"
        results = drive.files().list(
            q=query, spaces='drive', pageSize=50,
            fields='files(id,name,mimeType)',
        ).execute()
        all_files = results.get('files', [])

        # Build a lookup: filename -> file info
        file_map = {}
        subfolder_map = {}
        for f in all_files:
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                subfolder_map[f['name']] = f['id']
            else:
                file_map[f['name']] = f['id']

        # Read manifest.json for metadata
        brief_data = {'brief_date': brief_date, 'brief_type': 'default', 'sections': {}}
        if 'manifest.json' in file_map:
            try:
                manifest = _download_json(drive, file_map['manifest.json'])
                brief_data['brief_date'] = manifest.get('brief_date', brief_date)
                brief_data['brief_type'] = manifest.get('brief_type', 'default')
                brief_data['generated_at'] = manifest.get('generated_at')
            except Exception as e:
                logger.warning(f'Failed to read manifest.json: {e}')

        # Read each section file
        for filename, section_slug in _FILE_TO_SECTION.items():
            if filename in file_map:
                try:
                    data = _download_json(drive, file_map[filename])
                    if isinstance(data, list):
                        brief_data['sections'][section_slug] = data
                    elif isinstance(data, dict):
                        # Single item (e.g. manager-update.json) — wrap in array
                        brief_data['sections'][section_slug] = [data]
                    logger.info(f'read_brief_manifest: {filename} -> {section_slug}: {len(brief_data["sections"][section_slug])} items')
                except Exception as e:
                    logger.warning(f'Failed to read {filename}: {e}')

        # Read accounts/ subfolder -> account-recap section
        if 'accounts' in subfolder_map:
            try:
                items = _read_subfolder_files(drive, subfolder_map['accounts'])
                if items:
                    brief_data['sections']['account-recap'] = items
                    logger.info(f'read_brief_manifest: accounts/ -> account-recap: {len(items)} items')
            except Exception as e:
                logger.warning(f'Failed to read accounts/ subfolder: {e}')

        # Read updates/ subfolder -> customer-updates section
        if 'updates' in subfolder_map:
            try:
                items = _read_subfolder_files(drive, subfolder_map['updates'])
                if items:
                    brief_data['sections']['customer-updates'] = items
                    logger.info(f'read_brief_manifest: updates/ -> customer-updates: {len(items)} items')
            except Exception as e:
                logger.warning(f'Failed to read updates/ subfolder: {e}')

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

        logger.info(f'list_available_briefs: Querying parent folder {parent_folder}')

        briefs_folder_id = _find_briefs_folder(drive, parent_folder)
        if not briefs_folder_id:
            return []

        logger.info(f'list_available_briefs: Found briefs folder {briefs_folder_id}')

        # List all folders in /briefs/
        query = f"parents='{briefs_folder_id}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive.files().list(
            q=query, spaces='drive', pageSize=100,
            fields='files(name)', orderBy='name desc',
        ).execute()

        files = results.get('files', [])
        logger.info(f'list_available_briefs: Found {len(files)} folders in briefs folder')

        # Extract valid date-like names (YYYY-MM-DD)
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
