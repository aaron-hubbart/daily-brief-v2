"""
Read daily briefs from Google Drive JSON files.

The daily-brief skill writes manifest.json files to:
  /briefs/{brief_date}/manifest.json

This module reads those files and parses them for display.
"""
import json
import logging
import os
from typing import Optional, Dict, List

try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google.auth import default as auth_default
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

logger = logging.getLogger(__name__)

BRIEFS_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')

logger.info(f'gdrive_briefs: GDRIVE_AVAILABLE={GDRIVE_AVAILABLE}, BRIEFS_FOLDER_ID={BRIEFS_FOLDER_ID}')


def _get_drive_service():
    """Get Google Drive service using Application Default Credentials."""
    if not GDRIVE_AVAILABLE or not BRIEFS_FOLDER_ID:
        logger.warning(f'_get_drive_service: GDRIVE_AVAILABLE={GDRIVE_AVAILABLE}, BRIEFS_FOLDER_ID={bool(BRIEFS_FOLDER_ID)}')
        return None
    
    try:
        credentials, _ = auth_default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
        logger.info('_get_drive_service: Successfully obtained credentials')
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        logger.error(f'_get_drive_service: Failed to get Google Drive service: {e}', exc_info=True)
        return None


def read_brief_manifest(brief_date: str) -> Optional[Dict]:
    """
    Read and parse manifest.json from /briefs/{brief_date}/ in Google Drive.
    
    Args:
        brief_date: Date string like "2026-08-13"
        
    Returns:
        Parsed JSON dict, or None if not found
    """
    if not BRIEFS_FOLDER_ID:
        logger.warning(f'read_brief_manifest: BRIEFS_FOLDER_ID not set')
        return None
    
    try:
        drive = _get_drive_service()
        if not drive:
            logger.error(f'read_brief_manifest: Could not get Drive service')
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


def list_available_briefs() -> List[str]:
    """List all available brief dates from Google Drive in descending order."""
    if not BRIEFS_FOLDER_ID:
        logger.warning('list_available_briefs: BRIEFS_FOLDER_ID not set')
        return []
    
    try:
        drive = _get_drive_service()
        if not drive:
            logger.error('list_available_briefs: Could not get Drive service')
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
                    logger.debug(f'list_available_briefs: Found valid date folder: {name}')
                except ValueError:
                    logger.debug(f'list_available_briefs: Skipped invalid date folder: {name}')
        
        logger.info(f'list_available_briefs: Returning {len(dates)} valid dates')
        return sorted(dates, reverse=True)
    
    except Exception as e:
        logger.error(f'list_available_briefs: Error listing briefs: {e}', exc_info=True)
        return []
