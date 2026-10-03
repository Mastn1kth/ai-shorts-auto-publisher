"""YouTube Data API v3 publisher using OAuth and resumable uploads."""

import os
from typing import Dict, Optional

from .base import PublisherError


class YouTubePublisher:
    name = "youtube"

    def __init__(self, client_secret_file: Optional[str] = None, token_file: Optional[str] = None):
        self.client_secret_file = client_secret_file or os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
        self.token_file = token_file or os.getenv("YOUTUBE_TOKEN_FILE", "youtube-token.json")

    def _service(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise PublisherError(
                "YouTube publishing needs google-api-python-client, "
                "google-auth-oauthlib and google-auth-httplib2. Install requirements.txt."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        credentials = None
        if os.path.exists(self.token_file):
            credentials = Credentials.from_authorized_user_file(self.token_file, scopes)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not os.path.exists(self.client_secret_file):
                raise PublisherError(
                    f"YouTube OAuth client file not found: {self.client_secret_file}. "
                    "Create OAuth Desktop credentials in Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_file, scopes)
            credentials = flow.run_local_server(port=0)
        with open(self.token_file, "w", encoding="utf-8") as token:
            token.write(credentials.to_json())
        return build("youtube", "v3", credentials=credentials)

    def publish(self, video_path: str, metadata: Dict, privacy_status: str = "private", dry_run: bool = False) -> Dict:
        if dry_run:
            return {"platform": self.name, "status": "dry_run", "video_path": video_path}
        if privacy_status not in {"private", "unlisted", "public"}:
            raise PublisherError("YouTube visibility must be private, unlisted, or public")
        if not os.path.isfile(video_path):
            raise PublisherError(f"Video file not found: {video_path}")
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise PublisherError("YouTube publishing dependencies are not installed") from exc

        body = {
            "snippet": {
                "title": metadata["title"],
                "description": metadata.get("description", ""),
                "tags": metadata.get("tags", []),
                "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "22"),
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }
        try:
            service = self._service()
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True),
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = response["id"]
            return {
                "platform": self.name,
                "status": "uploaded",
                "external_id": video_id,
                "url": f"https://www.youtube.com/shorts/{video_id}",
            }
        except Exception as exc:
            raise PublisherError(f"YouTube upload failed: {exc}") from exc
