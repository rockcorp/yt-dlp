import unittest
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from yt_dlp.rockcorp_api import create_app
except ImportError as error:
    raise unittest.SkipTest('Install rockcorp-api and httpx to test the HTTP bridge') from error

from yt_dlp.utils import DownloadError


class TestRockcorpApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app('test-token'))
        self.headers = {'Authorization': 'Bearer test-token'}

    def test_requires_token(self):
        with mock.patch('yt_dlp.rockcorp_api.extract_snapshot') as extract:
            response = self.client.post('/instagram/creator', json={'handle': 'creator'})
        self.assertEqual(response.status_code, 401)
        extract.assert_not_called()

    def test_rejects_urls_and_path_injection(self):
        with mock.patch('yt_dlp.rockcorp_api.extract_snapshot') as extract:
            for handle in ('../creator', 'https://example.com/', 'creator?x=1'):
                response = self.client.post('/instagram/creator', json={'handle': handle}, headers=self.headers)
                self.assertEqual(response.status_code, 422)
        extract.assert_not_called()

    def test_passes_creator_and_profile_modes(self):
        with mock.patch('yt_dlp.rockcorp_api.extract_snapshot', return_value={'instagram_posts': []}) as extract:
            for include_posts in (True, False):
                response = self.client.post('/instagram/creator', headers=self.headers,
                                            json={'handle': 'creator', 'include_posts': include_posts})
                self.assertEqual(response.status_code, 200)
                extract.assert_called_with('creator', include_posts, 'feed')

    def test_reels_mode_is_explicit_and_invalid_modes_are_rejected(self):
        with mock.patch('yt_dlp.rockcorp_api.extract_snapshot', return_value={}) as extract:
            response = self.client.post('/instagram/creator', headers=self.headers,
                                        json={'handle': 'creator', 'post_tab': 'reels'})
            self.assertEqual(response.status_code, 200)
            extract.assert_called_once_with('creator', True, 'reels')
            invalid = self.client.post('/instagram/creator', headers=self.headers,
                                       json={'handle': 'creator', 'post_tab': '../feed'})
            self.assertEqual(invalid.status_code, 422)

    def test_failures_release_worker_capacity(self):
        with mock.patch('yt_dlp.rockcorp_api.extract_snapshot', side_effect=[DownloadError('Unavailable'), {}]):
            first = self.client.post('/instagram/creator', json={'handle': 'creator'}, headers=self.headers)
            second = self.client.post('/instagram/creator', json={'handle': 'creator'}, headers=self.headers)
        self.assertEqual(first.status_code, 502)
        self.assertEqual(second.status_code, 200)

    def test_missing_configuration_fails_at_startup(self):
        with self.assertRaisesRegex(ValueError, 'YTDLP_API_TOKEN'):
            create_app('')
