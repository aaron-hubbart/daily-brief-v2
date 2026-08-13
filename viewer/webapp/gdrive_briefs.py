"""
Read daily briefs from Google Drive JSON files using per-user OAuth 2.0 tokens.

Each user authenticates with Google Drive and stores a refresh token.
This module uses that token to access their briefs.
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


def _get_drive_service(refresh_token: str):
    """Get Google Drive service using user's refresh token."""
    if not GDRIVE_AVAILABLE or not refresh_token:
        return None
    
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        logger.error('_get_drive_service: GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set')
        return None
    
    try:
        # Build credentials from refresh token
        credentials = Credentials(
            token=None,  # Will be fetched using refresh_token
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
        )
        
        # Refresh the token to get a valid access token
        request = Request()
        credentials.refresh(request)
        
        logger.info('_get_drive_service: Successfully authenticated with user refresh token')
        return build('drive', 'v3', credentials=credentials)
    
    except Exception as e:
        logger.error(f'_get_drive_service: Failed to build Drive service: {e}', exc_info=True)
        return None


def read_brief_manifest(brief_date: str, refresh_token: str) -> Optional[Dict]:
    """
    Read and parse manifest.json from /briefs/{brief_date}/ in Google Drive.
    
    Args:
        brief_date: Date string like "2026-08-13"
        refresh_token: User's Google refresh token
        
    Returns:
        Parsed JSON dict, or None if not found
    """
    if not BRIEFS_FOLDER_ID or not refresh_token:
        return None
    
    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            logger.error(f'read_brief_manifest: Could not authenticate with Google Drive')
            return None
        
        # Find the date folder
        query = f"parents='{BRIEFS_FOLDER_ID}' and name='{brief_date}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive.files().list(
            q=query,
            spaces='drive',
            pageSize=1,
            fields='files(id)',
        ).execute()
        
        files = results.get('files', [])
        if not files:
            logger.warning(f'read_brief_manifest: No folder found for date {brief_date}')
            return None
        
        date_folder_id = files[0]['id']
        
        # Find manifest.json in that folder
        query = f"parents='{date_folder_id}' and name='manifest.json' and trashed=false"
        results = drive.files().list(
            q=query,
            spaces='drive',
            pageSize=1,
            fields='files(id)',
        ).execute()
        
        files = results.get('files', [])
        if not files:
            logger.warning(f'read_brief_manifest: No manifest.json found in {brief_date} folder')
            return None
        
        manifest_id = files[0]['id']
        
        # Download and parse the manifest
        request = drive.files().get_media(fileId=manifest_id)
        content = request.execute()
        
        logger.info(f'read_brief_manifest: Successfully read manifest for {brief_date}')
        return json.loads(content)
    
    except Exception as e:
        logger.error(f'read_brief_manifest: Error reading brief {brief_date}: {e}', exc_info=True)
        return None


def list_available_briefs(refresh_token: str) -> List[str]:
    """List all available brief dates from Google Drive in descending order."""
    if not BRIEFS_FOLDER_ID or not refresh_token:
        return []
    
    try:
        drive = _get_drive_service(refresh_token)
        if not drive:
            logger.error('list_available_briefs: Could not authenticate with Google Drive')
            return []
        
        logger.info(f'list_available_briefs: Querying folder {BRIEFS_FOLDER_ID}')
        
        # List all folders in briefs folder
        query = f"parents='{BRIEFS_FOLDER_ID}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive.files().list(
            q=query,
            spaces='drive',
            pageSize=100,
            fields='files(name)',
            orderBy='name desc',
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
