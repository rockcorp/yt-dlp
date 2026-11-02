#!/usr/bin/env python3

import os
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test.helper import FakeYDL
from yt_dlp.extractor import get_info_extractor
from yt_dlp.extractor.instagram import InstagramCreatorIE, InstagramIE, InstagramProfileIE
from yt_dlp.utils import ExtractorError


def profile_page(*users):
    scripts = []
    for user in users:
        query = {'__bbox': {'result': {'data': {'xig_user_by_username': user}}}}
        data = {'require': [['ScheduledServerJS', None, None, [{
            '__bbox': {'require': [['RelayPrefetchedStreamCache', None, None, [None, query]]]},
        }]]]}
        scripts.append(f'<script type="application/json" data-sjs>{json.dumps(data)}</script>')
    return ''.join(scripts)


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

    def test_ad_flags_remain_unknown_unless_provided(self):
        self.assertNotIn('is_platform_ad', self.product())
        self.assertIs(self.product(is_ad=True, is_paid_partnership=False)['is_platform_ad'], True)
        self.assertIs(self.product(is_paid_partnership=False)['is_platform_ad'], False)

    def test_metadata_lookup_supports_photos_without_downloading_media(self):
        self.ie.__dict__['_can_impersonate'] = True
        self.ie._lsd_token = 'test-token'
        with mock.patch.object(self.ie, '_download_json', return_value={'data': {
            'xdt_api__v1__media__shortcode__web_info': {'items': [{
                'pk': '482584233761418119', 'taken_at': 1000,
                'like_count': 10, 'is_paid_partnership': False,
            }]},
        }}) as download:
            info = self.ie._extract_post('https://www.instagram.com/p/aye83DjauH/', metadata_only=True)
        self.assertEqual(info['like_count'], 10)
        self.assertEqual(info['formats'], [])
        self.assertEqual(download.call_count, 1)

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


class TestInstagramProfile(unittest.TestCase):
    def setUp(self):
        self.ie = InstagramProfileIE(FakeYDL())
        self.user = {
            'pk': '123', 'username': 'creator', 'full_name': 'A Creator',
            'follower_count': 1234, 'following_count': 56, 'all_media_count': None,
            'biography': 'Creator biography', 'is_verified': False,
            'bio_links': [{'url': 'https://example.com/'}],
        }

    def test_standalone_profile(self):
        self.assertIs(get_info_extractor('InstagramProfile'), InstagramProfileIE)
        page = profile_page({'pk': '123', 'username': 'unrelated'}, self.user, {'pk': '123'})
        with mock.patch.object(self.ie, '_download_webpage', return_value=page) as download:
            info = self.ie._real_extract('instagram:profile:Creator')
        self.assertEqual(info['id'], '123')
        self.assertEqual(info['entries'], [])
        self.assertEqual(info['channel_follower_count'], 1234)
        self.assertEqual(info['channel_following_count'], 56)
        self.assertEqual(info['channel_description'], 'Creator biography')
        self.assertEqual(info['channel_bio_url'], 'https://example.com/')
        self.assertEqual(info['description'], 'Creator biography')
        self.assertNotIn('channel_post_count', info)
        self.assertIs(info['channel_is_verified'], False)
        self.assertEqual(download.call_args.args[0], 'https://www.instagram.com/creator/')

    def test_profile_cache_and_author_identity(self):
        with mock.patch.object(self.ie, '_download_webpage', return_value=profile_page(self.user)) as download:
            self.ie._download_profile('Creator', expected_user_id='123')
            self.ie._download_profile('creator', expected_user_id=123)
            with self.assertRaisesRegex(ExtractorError, 'does not match'):
                self.ie._download_profile('creator', expected_user_id='456')
        self.assertEqual(download.call_count, 1)

    def test_profile_counts(self):
        for value, expected in ((0, 0), ('25', 25), (None, None), (-1, None), (True, None)):
            with self.subTest(value=value):
                ie = InstagramProfileIE(FakeYDL())
                user = {**self.user, 'follower_count': value, 'following_count': value, 'all_media_count': value}
                with mock.patch.object(ie, '_download_webpage', return_value=profile_page(user)):
                    info = ie._download_profile('creator')
                for field in ('channel_follower_count', 'channel_following_count', 'channel_post_count'):
                    self.assertEqual(info.get(field), expected)

    def test_profile_must_match_requested_account(self):
        for page in (
            '<html>Log in to Instagram</html>',
            profile_page({'pk': '456', 'username': 'someone_else'}),
            profile_page({'username': 'creator'}),
        ):
            with self.subTest(page=page), self.assertRaisesRegex(ExtractorError, 'requested profile'):
                self.ie._extract_profile_data(page, 'creator')

    def test_author_enrichment_is_optional(self):
        ie = InstagramIE(FakeYDL())
        post = {'id': 'post', 'channel': 'creator', 'uploader_id': '123'}
        with (
            mock.patch.object(ie, '_extract_post', return_value=post),
            mock.patch.object(ie, '_download_profile') as download,
        ):
            self.assertEqual(ie._real_extract('url'), post)
        download.assert_not_called()

    def test_post_and_carousel_enrichment(self):
        for carousel in (False, True):
            with self.subTest(carousel=carousel):
                ie = InstagramIE(FakeYDL({'extractor_args': {'instagram': {'author_stats': ['true']}}}))
                post = {'id': 'post', 'channel': 'creator', 'uploader_id': '123', 'description': 'Post caption'}
                if carousel:
                    post.update({'_type': 'playlist', 'entries': [{'id': 'child', 'like_count': 10}]})
                with (
                    mock.patch.object(ie, '_extract_post', return_value=post),
                    mock.patch.object(ie, '_download_webpage', return_value=profile_page(self.user)),
                ):
                    info = ie._real_extract('url')
                self.assertEqual(info['channel_follower_count'], 1234)
                self.assertEqual(info['description'], 'Post caption')
                if carousel:
                    self.assertEqual(info['entries'][0]['channel_follower_count'], 1234)
                    self.assertEqual(info['entries'][0]['like_count'], 10)

    def test_failed_profile_lookup_preserves_post(self):
        ie = InstagramIE(FakeYDL({'extractor_args': {'instagram': {'author_stats': ['true']}}}))
        post = {'id': 'post', 'channel': 'creator', 'uploader_id': '123', 'like_count': 10}
        for error in ('HTTP Error 429', 'Instagram profile ID does not match the post author'):
            with (
                self.subTest(error=error),
                mock.patch.object(ie, '_extract_post', return_value=dict(post)),
                mock.patch.object(ie, '_download_profile', side_effect=ExtractorError(error)),
                mock.patch.object(ie, 'report_warning') as warning,
            ):
                self.assertEqual(ie._real_extract('url'), post)
                warning.assert_called_once()


class TestInstagramCreator(unittest.TestCase):
    def setUp(self):
        self.ie = InstagramCreatorIE(FakeYDL({'extractor_args': {'instagramcreator': {'tab': ['reels']}}}))
        self.user = {
            'pk': '123', 'username': 'creator', 'follower_count': 100,
            '_pagination_doc_id': '12345',
        }

    def node(self, code, pinned=False, owner='123'):
        return {
            'code': code, 'user': {'pk': owner}, 'play_count': 0,
            'like_count': 5, 'comment_count': 0,
            'clips_tab_pinned_user_ids': ['123'] if pinned else [],
        }

    def connection(self, nodes, more=False, cursor=None):
        return {'edges': [{'node': node} for node in nodes],
                'page_info': {'has_next_page': more, 'end_cursor': cursor}}

    def test_pagination_excludes_pins_and_duplicates(self):
        user = {**self.user, 'polaris_clips_connection': self.connection([
            self.node('pinned', pinned=True), self.node('first'), self.node('first'),
        ], more=True, cursor='next')}
        post_extractor = mock.Mock(_lsd_token='test-token')
        post_extractor._download_json.return_value = {'data': {'xig_user_by_username': {
            'pk': '123', 'polaris_clips_connection': self.connection([self.node('second')]),
        }}}
        posts = list(self.ie._recent_nodes('creator', user, post_extractor))
        self.assertEqual([post['code'] for post in posts], ['first', 'second'])
        self.assertIn(b'after', post_extractor._download_json.call_args.kwargs['data'])

    def test_missing_owner_is_rejected(self):
        user = {**self.user, 'polaris_clips_connection': self.connection([{'code': 'unknown'}])}
        with self.assertRaisesRegex(ExtractorError, 'identify the post author'):
            list(self.ie._recent_nodes('creator', user, mock.Mock()))

    def test_collaborations_require_explicit_coauthor_membership(self):
        user = {**self.user, 'polaris_clips_connection': self.connection([self.node('collab', owner='456')])}
        for coauthors in ([], ['123']):
            with (
                self.subTest(coauthors=coauthors),
                mock.patch.object(self.ie, '_download_profile_user', return_value=user),
                mock.patch('yt_dlp.extractor.instagram.InstagramIE') as post_class,
            ):
                post_class.return_value._extract_post.return_value = {
                    'id': 'collab', 'uploader_id': '456', 'timestamp': 1000,
                    'coauthor_uploader_ids': coauthors,
                }
                if coauthors:
                    self.assertEqual(len(self.ie._real_extract('instagram:creator:creator')['instagram_posts']), 1)
                else:
                    with self.assertRaisesRegex(ExtractorError, 'does not list'):
                        self.ie._real_extract('instagram:creator:creator')

    def test_incomplete_or_repeated_cursor_is_not_an_empty_profile(self):
        for connection in (None, self.connection([], more=True)):
            with self.subTest(connection=connection), self.assertRaises(ExtractorError):
                list(self.ie._recent_nodes('creator', {**self.user, 'polaris_clips_connection': connection}, mock.Mock()))
        user = {**self.user, 'polaris_clips_connection': self.connection([], more=True, cursor='repeat')}
        post_extractor = mock.Mock(_lsd_token='test-token')
        post_extractor._download_json.return_value = {'data': {'xig_user_by_username': {
            'pk': '123', 'polaris_clips_connection': user['polaris_clips_connection'],
        }}}
        with self.assertRaisesRegex(ExtractorError, 'pagination is unavailable'):
            list(self.ie._recent_nodes('creator', user, post_extractor))

    def test_creator_snapshot_keeps_ten_posts_and_real_zero_views(self):
        user = {**self.user, 'polaris_clips_connection': self.connection([self.node(f'post{i}') for i in range(12)])}

        def post(url, metadata_only=False):
            code = url.rstrip('/').split('/')[-1]
            self.assertTrue(metadata_only)
            return {'id': code, 'uploader_id': '123', 'timestamp': 1000 + int(code[4:]), 'description': 'Caption'}

        with (
            mock.patch.object(self.ie, '_download_profile_user', return_value=user),
            mock.patch('yt_dlp.extractor.instagram.InstagramIE') as post_class,
        ):
            post_class.return_value._extract_post.side_effect = post
            info = self.ie._real_extract('instagram:creator:creator')
        self.assertEqual(info['channel_follower_count'], 100)
        self.assertEqual(info['entries'], [])
        self.assertEqual(len(info['instagram_posts']), 10)
        self.assertEqual(info['instagram_posts'][0]['id'], 'post9')
        self.assertTrue(all(post['view_count'] == 0 for post in info['instagram_posts']))
        self.assertEqual(post_class.return_value._extract_post.call_count, 10)


class TestInstagramMixedFeed(unittest.TestCase):
    def node(self, code, product_type='feed'):
        return {'code': code, 'product_type': product_type, 'user': {'username': 'creator'}}

    def test_feed_default_keeps_photos_carousels_and_reels_in_chronological_order(self):
        ie = InstagramCreatorIE(FakeYDL())
        kinds = ('feed', 'carousel_container', 'clips')
        nodes = [self.node(f'post{i}', kinds[i % 3]) for i in range(13)]
        user = {'pk': '123', 'username': 'creator', 'follower_count': 100,
                'polaris_ordered_timeline_connection': {'edges': [{'node': node} for node in nodes],
                                                       'page_info': {'has_next_page': False}}}
        clips = [{'code': node['code'], 'user': {'pk': '123'}, 'play_count': 0,
                  'clips_tab_pinned_user_ids': ['123']} for node in nodes[3:] if node['product_type'] == 'clips']
        reels_user = {**user, 'polaris_clips_connection': {
            'edges': [{'node': node} for node in clips], 'page_info': {'has_next_page': False}}}

        def profile(username, tab=''):
            return reels_user if tab == 'reels' else user

        def post(url, metadata_only=False):
            code = url.rstrip('/').split('/')[-1]
            index = int(code[4:])
            return {'id': code, 'uploader_id': '123', 'channel': 'creator',
                    'timestamp': index if index < 3 else 2000 - index,
                    'product_type': kinds[index % 3], 'like_count': index,
                    'media_type': {'feed': 1, 'carousel_container': 8, 'clips': 2}[kinds[index % 3]]}

        with (mock.patch.object(ie, '_download_profile_user', side_effect=profile),
              mock.patch('yt_dlp.extractor.instagram.InstagramIE') as post_class):
            post_class.return_value._extract_post.side_effect = post
            result = ie._real_extract('instagram:creator:creator')
        posts = result['instagram_posts']
        self.assertEqual(result['instagram_post_tab'], 'feed')
        self.assertEqual([post['id'] for post in posts], [f'post{i}' for i in range(3, 13)])
        self.assertEqual({post['product_type'] for post in posts}, set(kinds))
        self.assertEqual(post_class.return_value._extract_post.call_count, 13)
        for post in posts:
            if post['product_type'] == 'clips':
                self.assertEqual(post['view_count'], 0)
            else:
                self.assertNotIn('view_count', post)

    def test_feed_pagination_uses_the_feed_connection_and_scoped_owner_handle(self):
        ie = InstagramCreatorIE(FakeYDL())
        user = {'pk': '123', 'username': 'creator', '_pagination_doc_id': 'feed-query',
                'polaris_ordered_timeline_connection': {'edges': [{'node': self.node('photo')}],
                                                       'page_info': {'has_next_page': True, 'end_cursor': 'next'}}}
        post_extractor = mock.Mock(_lsd_token='test-token')
        post_extractor._download_json.return_value = {'data': {'xig_user_by_username': {
            'pk': '123', 'polaris_ordered_timeline_connection': {
                'edges': [{'node': self.node('carousel', 'carousel_container')}],
                'page_info': {'has_next_page': False},
            },
        }}}
        nodes = list(ie._recent_nodes('creator', user, post_extractor, tab='feed'))
        self.assertEqual([node['code'] for node in nodes], ['photo', 'carousel'])
        self.assertEqual(post_extractor._download_json.call_args.kwargs['headers']['Referer'],
                         'https://www.instagram.com/creator/')
        self.assertIn(b'PolarisSEOIsCrawler', post_extractor._download_json.call_args.kwargs['data'])


if __name__ == '__main__':
    unittest.main()
