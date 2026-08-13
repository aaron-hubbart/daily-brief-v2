"""
Read daily briefs from Google Drive JSON files.

The daily-brief skill writes manifest.json files to:
  /briefs/{brief_date}/manifest.json

This module reads those files and parses them for display.
"""
import json
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


BRIEFS_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')


def _get_drive_service():
    """Get Google Drive service using Application Default Credentials."""
    if not GDRIVE_AVAILABLE or not BRIEFS_FOLDER_ID:
        return None
    
    try:
        credentials, _ = auth_default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
        return build('drive', 'v3', credentials=credentials)
    except Exception:
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
        return None
    
    try:
        drive = _get_drive_service()
        if not drive:
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
            return None
        
        manifest_id = files[0]['id']
        
        # Download and parse the manifest
        request = drive.files().get_media(fileId=manifest_id)
        content = request.execute()
        
        return json.loads(content)
    
    except Exception:
        return None


def list_available_briefs() -> List[str]:
    """List all available brief dates from Google Drive in descending order."""
    if not BRIEFS_FOLDER_ID:
        return []
    
    try:
        drive = _get_drive_service()
        if not drive:
            return []
        
        # List all folders in briefs folder
        query = f"parents='{BRIEFS_FOLDER_ID}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive.files().list(
            q=query,
            spaces='drive',
            pageSize=100,
            fields='files(name)',
            orderBy='name desc',
        ).execute()
        
        # Extract valid date-like names (YYYY-MM-DD)
        dates = []
        for f in results.get('files', []):
            name = f['name']
            if len(name) == 10 and name[4] == '-' and name[7] == '-':
                try:
                    from datetime import datetime
                    datetime.strptime(name, '%Y-%m-%d')
                    dates.append(name)
                except ValueError:
                    pass
        
        return sorted(dates, reverse=True)
    
    except Exception:
        return []
