"""HTTP bridge for the Rockcorp Instagram creator snapshot extractor."""

import hmac
import os
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import YoutubeDL
from .utils import DownloadError


class CreatorRequest(BaseModel):
    handle: str = Field(min_length=1, max_length=30, pattern=r'^[A-Za-z0-9_][A-Za-z0-9_.]*$')
    include_posts: bool = True


def extract_snapshot(handle, include_posts=True):
    with YoutubeDL({
        'quiet': True,
        'skip_download': True,
        'socket_timeout': 12,
        'retries': 0,
        'extractor_retries': 0,
    }) as ydl:
        command = 'creator' if include_posts else 'profile'
        result = ydl.extract_info(f'instagram:{command}:{handle}', download=False)
    result.setdefault('instagram_posts', [])
    result['observed_at_ms'] = int(time.time() * 1000)
    return result


def create_app(token):
    if not token:
        raise ValueError('YTDLP_API_TOKEN is required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    capacity = threading.BoundedSemaphore(2)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.post('/instagram/creator')
    def creator(request: CreatorRequest, authorization: str | None = Header(default=None)):
        expected = f'Bearer {token}'.encode()
        if not hmac.compare_digest((authorization or '').encode(), expected):
            raise HTTPException(status_code=401, detail='Unauthorized')
        if not capacity.acquire(timeout=240):
            raise HTTPException(status_code=503, detail='Instagram worker is busy')
        try:
            return extract_snapshot(request.handle, request.include_posts)
        except DownloadError as error:
            raise HTTPException(status_code=502, detail='Instagram creator snapshot unavailable') from error
        finally:
            capacity.release()

    return app


def app_factory():
    return create_app(os.environ.get('YTDLP_API_TOKEN'))
