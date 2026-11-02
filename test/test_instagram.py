#!/usr/bin/env python3

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test.helper import FakeYDL
from yt_dlp.extractor.instagram import InstagramIE


class TestInstagramMetadata(unittest.TestCase):
    def setUp(self):
        self.ie = InstagramIE(FakeYDL())

    def product(self, **fields):
        return self.ie._extract_product({
            'pk': '482584233761418119',
            'user': {'username': 'creator', 'pk': '123'},
            **fields,
        }, get_comments=False)

    def test_reel_play_count_fallback(self):
        for fields, expected in (
            ({'play_count': 1234}, 1234),
            ({'view_count': None, 'play_count': '1234'}, 1234),
            ({'view_count': 50, 'play_count': 1234}, 50),
            ({'view_count': 0, 'play_count': 1234}, 0),
            ({'view_count': -1, 'play_count': 1234}, 1234),
            ({'view_count': 'unavailable', 'play_count': 1234}, 1234),
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.product(**fields).get('view_count'), expected)

    def test_unknown_and_hidden_counts(self):
        for value in (None, -1, '-1', 'unavailable', True, False):
            with self.subTest(value=value):
                info = self.product(**dict.fromkeys((
                    'view_count', 'play_count', 'like_count', 'comment_count',
                    'media_repost_count', 'save_count',
                ), value))
                for field in ('view_count', 'like_count', 'comment_count', 'repost_count', 'save_count'):
                    self.assertNotIn(field, info)

    def test_zero_counts_are_available(self):
        info = self.product(play_count=0, like_count=0, comment_count=0, media_repost_count=0, save_count=0)
        for field in ('view_count', 'like_count', 'comment_count', 'repost_count', 'save_count'):
            self.assertEqual(info.get(field), 0)

    def test_legacy_graphql_nodes(self):
        for fields, expected in (
            ({'video_play_count': '1234'}, 1234),
            ({'video_view_count': 0, 'video_play_count': 1234}, 0),
            ({'video_view_count': -1, 'video_play_count': 1234}, 1234),
            ({'video_play_count': -1}, None),
        ):
            with self.subTest(fields=fields):
                info = next(self.ie._extract_nodes([{
                    '__typename': 'GraphVideo', 'shortcode': 'aye83DjauH', **fields,
                }]))
                self.assertEqual(info.get('view_count'), expected)

    def test_account_metadata(self):
        info = self.product(user={
            'username': 'creator', 'pk': '123', 'follower_count': '100', 'is_verified': False,
        })
        self.assertEqual(info.get('channel_follower_count'), 100)
        self.assertIs(info.get('channel_is_verified'), False)
        self.assertEqual(info.get('channel_url'), 'https://www.instagram.com/creator/')
        self.assertEqual(info.get('uploader_url'), info['channel_url'])
        self.assertNotIn('channel_follower_count', self.product())
        self.assertNotIn('channel_follower_count', self.product(user={'follower_count': -1}))
        self.assertNotIn('channel_url', self.product(user={}))

    def test_carousel_keeps_post_counts(self):
        info = self.product(like_count=10, comment_count=2, carousel_media=[
            {'pk': '482584233761418119'}, {'pk': '482584233761418120'},
        ])
        self.assertEqual(info['_type'], 'playlist')
        for entry in info['entries']:
            self.assertEqual(entry['like_count'], 10)
            self.assertEqual(entry['comment_count'], 2)
            self.assertNotIn('view_count', entry)

    def test_authenticated_response_extracts_play_count(self):
        self.ie.__dict__['_can_impersonate'] = True
        with (
            mock.patch.object(self.ie, '_get_cookies', return_value={'sessionid': object()}),
            mock.patch.object(self.ie, '_download_json', return_value={'items': [{
                'pk': '482584233761418119', 'play_count': 1234, 'like_count': 10,
            }]}) as download,
        ):
            info = self.ie._real_extract('https://www.instagram.com/p/aye83DjauH/')
        self.assertEqual(info.get('view_count'), 1234)
        self.assertEqual(info.get('like_count'), 10)
        self.assertEqual(download.call_count, 1)
        self.assertIn('/media/482584233761418119/info/', download.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
