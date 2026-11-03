#!/usr/bin/env python3

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test.helper import FakeYDL
from yt_dlp.extractor import get_info_extractor
from yt_dlp.extractor.tiktok import TikTokCreatorIE, TikTokProfileIE, TikTokUserIE
from yt_dlp.utils import ExtractorError


def profile_detail(count=20):
    return {'statusCode': 0, 'userInfo': {
        'user': {'id': '123', 'uniqueId': 'creator', 'secUid': 'secondary-id',
                 'nickname': 'A Creator', 'signature': 'Creator biography',
                 'verified': False, 'bioLink': {'link': 'https://example.com/'}},
        'stats': {'followerCount': 1000, 'followingCount': 10, 'heartCount': 20000, 'videoCount': count},
        'statsV2': {'followerCount': '1234', 'followingCount': '0', 'heartCount': '23456', 'videoCount': str(count)},
    }}


def post_item(post_id, *, photo=False, pinned=False):
    item = {
        'id': str(post_id), 'createTime': 1000 + post_id, 'desc': 'A post #testing',
        'author': {'id': '123', 'uniqueId': 'creator'}, 'isPinnedItem': pinned, 'isAd': False,
        'stats': {'playCount': 1000, 'diggCount': 10},
        'statsV2': {'playCount': '1234', 'diggCount': '12', 'commentCount': '0',
                    'shareCount': '3', 'collectCount': '4', 'repostCount': '1'},
    }
    if photo:
        item['imagePost'] = {'images': [
            {'imageURL': {'urlList': ['https://example.com/first.jpg']}},
            {'imageURL': {'urlList': ['https://example.com/second.jpg']}},
        ]}
    return item


class TestTikTokProfileMetadata(unittest.TestCase):
    def setUp(self):
        self.ie = TikTokProfileIE(FakeYDL())

    def test_metadata_command_registration(self):
        self.assertIs(get_info_extractor('TikTokProfile'), TikTokProfileIE)
        self.assertIs(get_info_extractor('TikTokCreator'), TikTokCreatorIE)
        self.assertTrue(TikTokProfileIE.suitable('tiktok:profile:creator'))
        self.assertTrue(TikTokCreatorIE.suitable('tiktok:creator:creator'))
        self.assertFalse(TikTokProfileIE.suitable('tiktok:profile:../creator'))

    def test_profile_uses_precise_stats_and_retains_zero_and_false(self):
        detail = profile_detail()
        with (mock.patch.object(self.ie, '_download_webpage', return_value='page') as download,
              mock.patch.object(self.ie, '_get_universal_data', return_value={'webapp.user-detail': detail}),
              mock.patch.object(self.ie, '_download_json') as api):
            result = self.ie._real_extract('tiktok:profile:Creator')
        self.assertEqual(result['id'], '123')
        self.assertEqual(result['channel_id'], 'secondary-id')
        self.assertEqual(result['title'], 'A Creator')
        self.assertEqual(result['channel_follower_count'], 1234)
        self.assertEqual(result['channel_following_count'], 0)
        self.assertEqual(result['channel_like_count'], 23456)
        self.assertEqual(result['channel_post_count'], 20)
        self.assertEqual(result['description'], 'Creator biography')
        self.assertEqual(result['channel_bio_url'], 'https://example.com/')
        self.assertIs(result['channel_is_verified'], False)
        self.assertEqual(result['entries'], [])
        self.assertEqual(download.call_count, 1)
        api.assert_not_called()

    def test_counter_fallback_is_per_field(self):
        detail = profile_detail()
        detail['userInfo']['statsV2'] = {'followerCount': '-1', 'heart': '5'}
        result = self.ie._parse_profile_metadata(detail)
        self.assertEqual(result['channel_follower_count'], 1000)
        self.assertEqual(result['channel_following_count'], 10)
        self.assertEqual(result['channel_like_count'], 5)
        self.assertEqual(result['channel_post_count'], 20)

    def test_unknown_profile_counts_are_not_zero(self):
        for value in (None, -1, '-1', True, False, 'hidden'):
            with self.subTest(value=value):
                detail = profile_detail()
                detail['userInfo']['stats'] = detail['userInfo']['statsV2'] = {'followerCount': value}
                self.assertNotIn('channel_follower_count', self.ie._parse_profile_metadata(detail))
        self.assertEqual(self.ie._parse_profile_metadata({}), {})

    def test_unrelated_missing_or_refused_profiles_fail(self):
        for detail in ({}, {'statusCode': 10204},
                       {'userInfo': {'user': {'id': '456', 'uniqueId': 'someone_else'}}}):
            with (self.subTest(detail=detail),
                  mock.patch.object(self.ie, '_download_webpage', return_value='page'),
                  mock.patch.object(self.ie, '_get_universal_data', return_value={'webapp.user-detail': detail}),
                  self.assertRaises(ExtractorError)):
                self.ie._real_extract('tiktok:profile:creator')

    def test_normal_profile_url_also_includes_author_metadata(self):
        ie = TikTokUserIE(FakeYDL())
        with (mock.patch.object(ie, '_download_webpage', return_value='page'),
              mock.patch.object(ie, '_get_universal_data', return_value={'webapp.user-detail': profile_detail()}),
              mock.patch.object(ie, '_entries', return_value=iter([]))):
            result = ie._real_extract('https://www.tiktok.com/@creator')
        self.assertEqual(result['channel_follower_count'], 1234)
        self.assertEqual(result['id'], 'secondary-id')

    def test_secondary_id_only_profile_keeps_existing_behavior(self):
        ie = TikTokUserIE(FakeYDL())
        secondary_id = 'MS4wLjABAAAA' + 'a' * 64
        with (mock.patch.object(ie, '_entries', return_value=iter([])),
              mock.patch.object(ie, '_download_webpage') as download):
            result = ie._real_extract(f'tiktokuser:{secondary_id}')
        self.assertEqual(result['id'], secondary_id)
        self.assertNotIn('channel_follower_count', result)
        download.assert_not_called()


class TestTikTokCreatorMetadata(unittest.TestCase):
    def setUp(self):
        self.ie = TikTokCreatorIE(FakeYDL())
        self.detail = profile_detail()
        self.profile = self.ie._parse_profile_metadata(self.detail)

    def test_mixed_snapshot_is_chronological_and_excludes_explicit_pins(self):
        items = [post_item(index, photo=index % 2 == 0, pinned=index >= 113) for index in range(100, 115)]
        with (mock.patch.object(self.ie, '_download_profile_data', return_value=(self.detail, self.profile)),
              mock.patch.object(self.ie, '_download_json', return_value={
                  'statusCode': 0, 'itemList': items, 'hasMorePrevious': True,
              }) as download,
              mock.patch.object(self.ie, '_extract_web_formats', side_effect=AssertionError('No media requests')),
              mock.patch.object(self.ie, 'extract_subtitles', side_effect=AssertionError('No subtitle requests'))):
            result = self.ie._real_extract('tiktok:creator:creator')
        posts = result['tiktok_posts']
        self.assertEqual([post['id'] for post in posts], [str(index) for index in range(112, 102, -1)])
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['channel_follower_count'], 1234)
        self.assertEqual({post['media_type'] for post in posts}, {'image', 'video'})
        self.assertEqual(download.call_count, 1)
        for post in posts:
            self.assertNotIn('formats', post)
            self.assertNotIn('download_count', post)
            self.assertEqual(post['view_count'], 1234)
            self.assertEqual(post['comment_count'], 0)
            self.assertEqual(post['share_count'], 3)
            self.assertEqual(post['repost_count'], 1)
            if post['media_type'] == 'image':
                self.assertEqual(post['image_count'], 2)
                self.assertIn('/photo/', post['webpage_url'])

    def test_missing_and_hidden_metrics_remain_unknown(self):
        for value in (None, -1, '-1', True, False, 'hidden'):
            with self.subTest(value=value):
                item = post_item(100)
                item['stats'] = item['statsV2'] = dict.fromkeys(
                    ('playCount', 'diggCount', 'commentCount', 'shareCount', 'collectCount', 'downloadCount'), value)
                info = self.ie._post_metadata(item, self.profile)
                for field in ('view_count', 'like_count', 'comment_count', 'share_count', 'save_count', 'download_count'):
                    self.assertNotIn(field, info)

    def test_real_zero_and_available_download_count_are_preserved(self):
        item = post_item(100)
        item['statsV2'] = {'playCount': '0', 'downloadCount': '7'}
        info = self.ie._post_metadata(item, self.profile)
        self.assertEqual(info['view_count'], 0)
        self.assertEqual(info['like_count'], 10)
        self.assertEqual(info['download_count'], 7)
        self.assertIs(info['is_platform_ad'], False)

    def test_mismatched_author_and_missing_timestamps_are_rejected(self):
        for change in ({'author': {'id': '456', 'uniqueId': 'creator'}},
                       {'author': {'id': '123', 'uniqueId': 'other'}}, {'createTime': 0}, {'id': 'invalid'}):
            with self.subTest(change=change), self.assertRaises(ExtractorError):
                self.ie._post_metadata({**post_item(100), **change}, self.profile)

    def test_incomplete_photo_metadata_is_not_a_video(self):
        item = post_item(100)
        item['imagePost'] = {'images': []}
        with self.assertRaisesRegex(ExtractorError, 'photo post images'):
            self.ie._post_metadata(item, self.profile)

    def test_pagination_deduplicates_and_preserves_publish_times(self):
        first = [post_item(index) for index in range(110, 116)]
        second = [post_item(110), *[post_item(index) for index in range(100, 106)]]
        with mock.patch.object(self.ie, '_download_json', side_effect=[
            {'itemList': first, 'hasMorePrevious': True},
            {'itemList': second, 'hasMorePrevious': False},
        ]) as download:
            posts = self.ie._recent_posts(self.profile)
        self.assertEqual([post['id'] for post in posts], ['115', '114', '113', '112', '111', '110', '105', '104', '103', '102'])
        self.assertEqual(download.call_count, 2)
        self.assertEqual(download.call_args.kwargs['query']['cursor'], 1110 * 1000)

    def test_repeated_pages_and_missing_pagination_are_errors(self):
        page = {'itemList': [post_item(100)], 'hasMorePrevious': True}
        with mock.patch.object(self.ie, '_download_json', return_value=page) as download:
            with self.assertRaisesRegex(ExtractorError, 'repeated'):
                self.ie._recent_posts(self.profile)
            self.assertEqual(download.call_count, 2)
        with mock.patch.object(self.ie, '_download_json', return_value={'itemList': [post_item(100)]}):
            with self.assertRaisesRegex(ExtractorError, 'pagination status'):
                self.ie._recent_posts(self.profile)

    def test_malformed_and_empty_responses_do_not_clear_a_known_nonempty_profile(self):
        for response in ({}, [], {'statusCode': 10204, 'itemList': []},
                         {'itemList': [], 'hasMorePrevious': False}):
            with (self.subTest(response=response),
                  mock.patch.object(self.ie, '_download_json', return_value=response),
                  self.assertRaises(ExtractorError)):
                self.ie._recent_posts(self.profile)

    def test_private_profile_is_not_reported_as_empty(self):
        self.detail['userInfo']['user']['privateAccount'] = True
        with (mock.patch.object(self.ie, '_download_profile_data', return_value=(self.detail, self.profile)),
              mock.patch.object(self.ie, '_download_json') as download,
              self.assertRaises(ExtractorError)):
            self.ie._real_extract('tiktok:creator:creator')
        download.assert_not_called()

    def test_zero_post_profile_does_not_make_feed_requests(self):
        profile = {**self.profile, 'channel_post_count': 0}
        with mock.patch.object(self.ie, '_download_json') as download:
            self.assertEqual(self.ie._recent_posts(profile), [])
        download.assert_not_called()

    def test_empty_pagination_is_bounded(self):
        with mock.patch.object(self.ie, '_download_json', return_value={
            'itemList': [], 'hasMorePrevious': True,
        }) as download:
            with self.assertRaisesRegex(ExtractorError, 'pagination limit'):
                self.ie._recent_posts(self.profile)
            self.assertEqual(download.call_count, 5)


if __name__ == '__main__':
    unittest.main()
