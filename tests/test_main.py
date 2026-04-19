import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from lib.sensitive_cleanup import SanitizationStats


class MainTests(unittest.TestCase):
    def test_resolve_repo_urls_prefers_cli_repo_url(self) -> None:
        """
        Checks the CLI repository URL overrides environment-based repo loading.
        """
        with mock.patch.object(main, 'load_repo_urls') as mock_load_repo_urls:
            repo_urls = main.resolve_repo_urls(' https://github.com/org/repo_a.git ')

        self.assertEqual(repo_urls, ['https://github.com/org/repo_a.git'])
        mock_load_repo_urls.assert_not_called()

    def test_resolve_repo_urls_rejects_blank_cli_repo_url(self) -> None:
        """
        Checks a blank CLI repository URL raises a ValueError.
        """
        with self.assertRaisesRegex(ValueError, 'cannot be blank'):
            main.resolve_repo_urls('   ')

    def test_load_repo_urls_parses_valid_json(self) -> None:
        """
        Checks valid repository JSON is parsed into a cleaned list of URLs.
        """
        with mock.patch.dict(
            os.environ,
            {'REPOS_TO_CLONE_JSON': '["git@github.com:org/repo_a.git", " https://github.com/org/repo_b.git "]'},
            clear=False,
        ):
            repo_urls = main.load_repo_urls()

        self.assertEqual(
            repo_urls,
            ['git@github.com:org/repo_a.git', 'https://github.com/org/repo_b.git'],
        )

    def test_load_repo_urls_rejects_non_list_json(self) -> None:
        """
        Checks non-list JSON input raises a ValueError.
        """
        with mock.patch.dict(os.environ, {'REPOS_TO_CLONE_JSON': '{"repo": "value"}'}, clear=False):
            with self.assertRaisesRegex(ValueError, 'must decode to a list'):
                main.load_repo_urls()

    def test_main_runs_sanitizer_after_git_cleanup(self) -> None:
        """
        Checks main sanitizes each repo after cloning and .git removal.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[str] = []
            repo_url = 'git@github.com:Brown-University-Library/repo_a.git'
            expected_repo_dir = (Path(temp_dir) / 'repo_a').resolve()
            expected_state_file = Path(temp_dir).resolve().parent / 'gather_repos_state.json'

            def fake_clone_repo(clone_url: str, destination_dir: Path) -> None:
                self.assertEqual(clone_url, repo_url)
                destination_dir.mkdir(parents=True)
                events.append('clone')

            def fake_remove_git_dirs(repo_dir: Path) -> list[Path]:
                self.assertEqual(repo_dir.resolve(), expected_repo_dir)
                events.append('remove_git_dirs')
                return []

            def fake_sanitize_repo_contents(repo_dir: Path) -> SanitizationStats:
                self.assertEqual(repo_dir.resolve(), expected_repo_dir)
                events.append('sanitize_repo_contents')
                return SanitizationStats(files_scanned=1, files_changed=1, replacement_count=2)

            def fake_save_repo_state(state_file: Path, state: dict[str, object]) -> None:
                self.assertEqual(state_file, expected_state_file)
                self.assertIn(repo_url, state['repos'])

            with mock.patch.object(main, 'parse_args', return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=None)):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls', return_value=[repo_url]):
                        with mock.patch.object(
                            main,
                            'fetch_remote_main_info',
                            return_value={'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
                        ):
                            with mock.patch.object(
                                main,
                                'fetch_local_head_metadata',
                                return_value={'commit': 'abc123', 'timestamp': '2026-04-19T12:00:00-04:00'},
                            ):
                                with mock.patch.object(main, 'load_repo_state', return_value={'version': 1, 'repos': {}}):
                                    with mock.patch.object(
                                        main,
                                        'current_timestamp',
                                        side_effect=[
                                            '2026-04-19T12:00:00-04:00',
                                            '2026-04-19T12:00:00-04:00',
                                        ],
                                    ):
                                        with mock.patch.object(main, 'save_repo_state', side_effect=fake_save_repo_state):
                                            with mock.patch.object(main, 'confirm_overwrite', return_value=True):
                                                with mock.patch.object(main, 'clone_repo', side_effect=fake_clone_repo):
                                                    with mock.patch.object(
                                                        main,
                                                        'remove_git_dirs',
                                                        side_effect=fake_remove_git_dirs,
                                                    ):
                                                        with mock.patch.object(
                                                            main,
                                                            'sanitize_repo_contents',
                                                            side_effect=fake_sanitize_repo_contents,
                                                        ):
                                                            main.main()

        self.assertEqual(events, ['clone', 'remove_git_dirs', 'sanitize_repo_contents'])

    def test_main_uses_single_cli_repo_url_without_loading_env_repo_urls(self) -> None:
        """
        Checks main clones and sanitizes the CLI-supplied repo without loading environment repo URLs.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[str] = []
            repo_url = 'https://github.com/Brown-University-Library/repo_a.git'
            expected_repo_dir = (Path(temp_dir) / 'repo_a').resolve()

            def fake_clone_repo(clone_url: str, destination_dir: Path) -> None:
                self.assertEqual(clone_url, repo_url)
                destination_dir.mkdir(parents=True)
                events.append('clone')

            def fake_remove_git_dirs(repo_dir: Path) -> list[Path]:
                self.assertEqual(repo_dir.resolve(), expected_repo_dir)
                events.append('remove_git_dirs')
                return []

            def fake_sanitize_repo_contents(repo_dir: Path) -> SanitizationStats:
                self.assertEqual(repo_dir.resolve(), expected_repo_dir)
                events.append('sanitize_repo_contents')
                return SanitizationStats(files_scanned=1, files_changed=0, replacement_count=0)

            with mock.patch.object(
                main,
                'parse_args',
                return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=repo_url),
            ):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls') as mock_load_repo_urls:
                        with mock.patch.object(
                            main,
                            'fetch_remote_main_info',
                            return_value={'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
                        ):
                            with mock.patch.object(
                                main,
                                'fetch_local_head_metadata',
                                return_value={'commit': 'abc123', 'timestamp': '2026-04-19T12:00:00-04:00'},
                            ):
                                with mock.patch.object(main, 'load_repo_state', return_value={'version': 1, 'repos': {}}):
                                    with mock.patch.object(
                                        main,
                                        'current_timestamp',
                                        side_effect=[
                                            '2026-04-19T12:00:00-04:00',
                                            '2026-04-19T12:00:00-04:00',
                                        ],
                                    ):
                                        with mock.patch.object(main, 'save_repo_state'):
                                            with mock.patch.object(main, 'confirm_overwrite', return_value=True):
                                                with mock.patch.object(main, 'clone_repo', side_effect=fake_clone_repo):
                                                    with mock.patch.object(
                                                        main,
                                                        'remove_git_dirs',
                                                        side_effect=fake_remove_git_dirs,
                                                    ):
                                                        with mock.patch.object(
                                                            main,
                                                            'sanitize_repo_contents',
                                                            side_effect=fake_sanitize_repo_contents,
                                                        ):
                                                            main.main()

        self.assertEqual(events, ['clone', 'remove_git_dirs', 'sanitize_repo_contents'])
        mock_load_repo_urls.assert_not_called()

    def test_main_skips_repo_when_remote_main_is_unchanged(self) -> None:
        """
        Checks main skips work when the saved main commit matches and the destination exists.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_url = 'git@github.com:Brown-University-Library/repo_a.git'
            repo_dir = Path(temp_dir) / 'repo_a'
            repo_dir.mkdir()

            state = {
                'version': 1,
                'repos': {
                    repo_url: {
                        'repo_dir_name': 'repo_a',
                        'remote_head_branch': 'main',
                        'remote_head_commit': 'abc123',
                        'remote_head_commit_timestamp': '2026-04-19T11:00:00-04:00',
                        'last_checked_at': '2026-04-19T11:00:00-04:00',
                        'last_updated_at': '2026-04-19T11:00:00-04:00',
                    }
                },
            }

            with mock.patch.object(main, 'parse_args', return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=None)):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls', return_value=[repo_url]):
                        with mock.patch.object(main, 'load_repo_state', return_value=state):
                            with mock.patch.object(
                                main,
                                'fetch_remote_main_info',
                                return_value={'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
                            ):
                                with mock.patch.object(main, 'current_timestamp', return_value='2026-04-19T12:00:00-04:00'):
                                    with mock.patch.object(main, 'confirm_overwrite', return_value=True) as mock_confirm:
                                        with mock.patch.object(main, 'clone_repo') as mock_clone_repo:
                                            with mock.patch.object(main, 'remove_git_dirs') as mock_remove_git_dirs:
                                                with mock.patch.object(
                                                    main,
                                                    'sanitize_repo_contents',
                                                ) as mock_sanitize_repo_contents:
                                                    with mock.patch.object(main, 'save_repo_state') as mock_save_repo_state:
                                                        main.main()

        mock_confirm.assert_called_once_with([])
        mock_clone_repo.assert_not_called()
        mock_remove_git_dirs.assert_not_called()
        mock_sanitize_repo_contents.assert_not_called()
        saved_state = mock_save_repo_state.call_args.args[1]
        saved_repo_state = saved_state['repos'][repo_url]
        self.assertEqual(saved_repo_state['last_checked_at'], '2026-04-19T12:00:00-04:00')
        self.assertEqual(saved_repo_state['last_updated_at'], '2026-04-19T11:00:00-04:00')

    def test_main_updates_repo_when_destination_is_missing(self) -> None:
        """
        Checks main updates a repo when state exists but the destination directory is missing.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[str] = []
            repo_url = 'git@github.com:Brown-University-Library/repo_a.git'
            state = {
                'version': 1,
                'repos': {
                    repo_url: {
                        'repo_dir_name': 'repo_a',
                        'remote_head_branch': 'main',
                        'remote_head_commit': 'abc123',
                        'remote_head_commit_timestamp': '2026-04-19T11:00:00-04:00',
                        'last_checked_at': '2026-04-19T11:00:00-04:00',
                        'last_updated_at': '2026-04-19T11:00:00-04:00',
                    }
                },
            }

            def fake_clone_repo(clone_url: str, destination_dir: Path) -> None:
                self.assertEqual(clone_url, repo_url)
                destination_dir.mkdir(parents=True)
                events.append('clone')

            with mock.patch.object(main, 'parse_args', return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=None)):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls', return_value=[repo_url]):
                        with mock.patch.object(main, 'load_repo_state', return_value=state):
                            with mock.patch.object(
                                main,
                                'fetch_remote_main_info',
                                return_value={'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
                            ):
                                with mock.patch.object(
                                    main,
                                    'fetch_local_head_metadata',
                                    return_value={'commit': 'abc123', 'timestamp': '2026-04-19T12:00:00-04:00'},
                                ):
                                    with mock.patch.object(
                                        main,
                                        'current_timestamp',
                                        side_effect=[
                                            '2026-04-19T12:00:00-04:00',
                                            '2026-04-19T12:00:00-04:00',
                                        ],
                                    ):
                                        with mock.patch.object(main, 'save_repo_state'):
                                            with mock.patch.object(main, 'confirm_overwrite', return_value=True) as mock_confirm:
                                                with mock.patch.object(main, 'clone_repo', side_effect=fake_clone_repo):
                                                    with mock.patch.object(main, 'remove_git_dirs', return_value=[]):
                                                        with mock.patch.object(
                                                            main,
                                                            'sanitize_repo_contents',
                                                            return_value=SanitizationStats(),
                                                        ):
                                                            main.main()

        self.assertEqual(events, ['clone'])
        mock_confirm.assert_called_once_with([])

    def test_main_only_confirms_existing_dirs_for_changed_repos(self) -> None:
        """
        Checks overwrite confirmation only targets repos that need update.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_a_url = 'git@github.com:Brown-University-Library/repo_a.git'
            repo_b_url = 'git@github.com:Brown-University-Library/repo_b.git'
            repo_a_dir = (Path(temp_dir) / 'repo_a').resolve()
            repo_b_dir = (Path(temp_dir) / 'repo_b').resolve()
            repo_a_dir.mkdir()
            repo_b_dir.mkdir()
            state = {
                'version': 1,
                'repos': {
                    repo_a_url: {
                        'repo_dir_name': 'repo_a',
                        'remote_head_branch': 'main',
                        'remote_head_commit': 'old-a',
                        'remote_head_commit_timestamp': '2026-04-19T11:00:00-04:00',
                        'last_checked_at': '2026-04-19T11:00:00-04:00',
                        'last_updated_at': '2026-04-19T11:00:00-04:00',
                    },
                    repo_b_url: {
                        'repo_dir_name': 'repo_b',
                        'remote_head_branch': 'main',
                        'remote_head_commit': 'same-b',
                        'remote_head_commit_timestamp': '2026-04-19T11:00:00-04:00',
                        'last_checked_at': '2026-04-19T11:00:00-04:00',
                        'last_updated_at': '2026-04-19T11:00:00-04:00',
                    },
                },
            }

            def fake_fetch_remote_main_info(repo_url: str) -> dict[str, str]:
                info: dict[str, str]
                if repo_url == repo_a_url:
                    info = {'branch': 'main', 'commit': 'new-a', 'head_branch': 'main'}
                else:
                    info = {'branch': 'main', 'commit': 'same-b', 'head_branch': 'main'}
                return info

            with mock.patch.object(main, 'parse_args', return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=None)):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls', return_value=[repo_a_url, repo_b_url]):
                        with mock.patch.object(main, 'load_repo_state', return_value=state):
                            with mock.patch.object(main, 'fetch_remote_main_info', side_effect=fake_fetch_remote_main_info):
                                with mock.patch.object(
                                    main,
                                    'fetch_local_head_metadata',
                                    return_value={'commit': 'new-a', 'timestamp': '2026-04-19T12:00:00-04:00'},
                                ):
                                    with mock.patch.object(
                                        main,
                                        'current_timestamp',
                                        side_effect=[
                                            '2026-04-19T12:00:00-04:00',
                                            '2026-04-19T12:00:01-04:00',
                                            '2026-04-19T12:00:02-04:00',
                                        ],
                                    ):
                                        with mock.patch.object(main, 'save_repo_state'):
                                            with mock.patch.object(main, 'confirm_overwrite', return_value=True) as mock_confirm:
                                                with mock.patch.object(main, 'clone_repo') as mock_clone_repo:
                                                    with mock.patch.object(main, 'remove_git_dirs', return_value=[]):
                                                        with mock.patch.object(
                                                            main,
                                                            'sanitize_repo_contents',
                                                            return_value=SanitizationStats(),
                                                        ):
                                                            main.main()

        mock_confirm.assert_called_once_with([repo_a_dir])
        mock_clone_repo.assert_called_once_with(repo_a_url, repo_a_dir)

    def test_save_repo_state_writes_expected_json(self) -> None:
        """
        Checks main saves updated repo state after a successful update.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_url = 'git@github.com:Brown-University-Library/repo_a.git'
            repo_dir = Path(temp_dir) / 'repo_a'

            def fake_clone_repo(clone_url: str, destination_dir: Path) -> None:
                self.assertEqual(clone_url, repo_url)
                destination_dir.mkdir(parents=True)

            with mock.patch.object(main, 'parse_args', return_value=mock.Mock(enclosing_dir=temp_dir, github_repo_url=None)):
                with mock.patch.object(main, 'validate_git_available'):
                    with mock.patch.object(main, 'load_repo_urls', return_value=[repo_url]):
                        with mock.patch.object(
                            main,
                            'fetch_remote_main_info',
                            return_value={'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
                        ):
                            with mock.patch.object(
                                main,
                                'fetch_local_head_metadata',
                                return_value={'commit': 'abc123', 'timestamp': '2026-04-19T12:00:00-04:00'},
                            ):
                                with mock.patch.object(main, 'load_repo_state', return_value={'version': 1, 'repos': {}}):
                                    with mock.patch.object(
                                        main,
                                        'current_timestamp',
                                        side_effect=[
                                            '2026-04-19T12:00:00-04:00',
                                            '2026-04-19T12:00:00-04:00',
                                        ],
                                    ):
                                        with mock.patch.object(main, 'confirm_overwrite', return_value=True):
                                            with mock.patch.object(main, 'clone_repo', side_effect=fake_clone_repo):
                                                with mock.patch.object(main, 'remove_git_dirs', return_value=[]):
                                                    with mock.patch.object(
                                                        main,
                                                        'sanitize_repo_contents',
                                                        return_value=SanitizationStats(),
                                                    ):
                                                        main.main()

            state_file = Path(temp_dir).resolve().parent / 'gather_repos_state.json'
            saved_state = json.loads(state_file.read_text(encoding='utf-8'))

        self.assertEqual(saved_state['version'], 1)
        self.assertEqual(saved_state['repos'][repo_url]['remote_head_commit'], 'abc123')
        self.assertEqual(saved_state['repos'][repo_url]['repo_dir_name'], repo_dir.name)


if __name__ == '__main__':
    unittest.main()
