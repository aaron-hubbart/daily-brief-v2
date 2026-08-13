"""
Read daily briefs from Google Drive instead of database.

This is for read-only access when DATABASE_URL is not configured.
Reads manifest.json files from the /briefs/{date}/ folder structure
that the daily-brief skill creates.
"""
import json
import os
from datetime import datetime


def read_brief_from_gdrive(brief_date_str: str) -> dict:
    """
    Read a brief's manifest.json from Google Drive.
    
    For now, returns a placeholder since we'd need the Google Drive API
    credentials to actually read files. In production, this would:
    
    1. Use google-auth + google-api-python-client
    2. Read from GOOGLE_DRIVE_BRIEFS_FOLDER_ID/{brief_date_str}/manifest.json
    3. Parse and return the JSON
    
    Args:
        brief_date_str: Date string like "2026-08-13"
        
    Returns:
        Brief data dict with structure matching what the skill writes
    """
    gdrive_folder_id = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')
    
    if not gdrive_folder_id:
        return {
            'error': 'GOOGLE_DRIVE_BRIEFS_FOLDER_ID not configured',
            'message': 'Configure Google Drive folder ID to read briefs',
            'date': brief_date_str,
        }
    
    # TODO: Implement actual Google Drive reading via google-api-python-client
    # For now, return placeholder that indicates the system is in Google Drive mode
    return {
        'status': 'gdrive_mode',
        'date': brief_date_str,
        'message': 'Google Drive reader not yet implemented. Update to use google-auth + google-api-python-client.',
        'folder_id': gdrive_folder_id,
    }


def list_briefs_from_gdrive() -> list:
    """
    List available brief dates from Google Drive folder.
    
    Would use google-api-python-client to list folders in the briefs folder.
    """
    gdrive_folder_id = os.environ.get('GOOGLE_DRIVE_BRIEFS_FOLDER_ID')
    
    if not gdrive_folder_id:
        return []
    
    # TODO: Implement actual Google Drive listing
    return []
