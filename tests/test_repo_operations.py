import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib.repo_operations import confirm_overwrite
from lib.repo_operations import derive_repo_dir_name
from lib.repo_operations import derive_state_file_path
from lib.repo_operations import fetch_remote_main_info
from lib.repo_operations import remove_git_dirs
from lib.repo_operations import validate_git_dir_is_within_repo


class RepoOperationsTests(unittest.TestCase):
    def test_derive_repo_dir_name_handles_ssh_url(self) -> None:
        """
        Checks an SSH repository URL is converted into the expected directory name.
        """
        repo_dir_name = derive_repo_dir_name('git@github.com:Brown-University-Library/repo_a.git')
        self.assertEqual(repo_dir_name, 'repo_a')

    def test_derive_state_file_path_uses_parent_of_enclosing_dir(self) -> None:
        """
        Checks the state file is placed alongside the enclosing directory.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            enclosing_dir = Path(temp_dir) / 'bundle'
            expected_state_file = Path(temp_dir) / 'gather_repos_state.json'

            state_file = derive_state_file_path(enclosing_dir)

        self.assertEqual(state_file, expected_state_file)

    def test_confirm_overwrite_accepts_explicit_yes(self) -> None:
        """
        Checks explicit yes confirmation returns True.
        """
        with mock.patch('sys.stdin.isatty', return_value=True):
            with mock.patch('builtins.print'):
                with mock.patch('builtins.input', return_value='yes'):
                    confirmed = confirm_overwrite([Path('/tmp/repo_a')])

        self.assertTrue(confirmed)

    def test_confirm_overwrite_rejects_non_yes_response(self) -> None:
        """
        Checks non-yes confirmation returns False.
        """
        with mock.patch('sys.stdin.isatty', return_value=True):
            with mock.patch('builtins.print'):
                with mock.patch('builtins.input', return_value='no'):
                    confirmed = confirm_overwrite([Path('/tmp/repo_a')])

        self.assertFalse(confirmed)

    def test_fetch_remote_main_info_parses_ls_remote_output(self) -> None:
        """
        Checks remote main metadata is parsed from git ls-remote output.
        """
        repo_url = 'git@github.com:Brown-University-Library/repo_a.git'

        with mock.patch('lib.repo_operations.subprocess.run') as mock_run:
            mock_run.side_effect = [
                mock.Mock(stdout='abc123\trefs/heads/main\n'),
                mock.Mock(stdout='ref: refs/heads/main\tHEAD\nabc123\tHEAD\n'),
            ]

            remote_main_info = fetch_remote_main_info(repo_url)

        self.assertEqual(
            remote_main_info,
            {'branch': 'main', 'commit': 'abc123', 'head_branch': 'main'},
        )

    def test_remove_git_dir_deletes_top_level_git_directory(self) -> None:
        """
        Checks all .git directories inside the repo are removed when present.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / 'repo_a'
            top_level_git_dir = repo_dir / '.git'
            nested_git_dir = repo_dir / 'vendor' / 'child_repo' / '.git'
            top_level_git_dir.mkdir(parents=True)
            nested_git_dir.mkdir(parents=True)
            (top_level_git_dir / 'config').write_text('data', encoding='utf-8')
            (nested_git_dir / 'config').write_text('data', encoding='utf-8')

            removed_git_dirs = remove_git_dirs(repo_dir)

            self.assertEqual(
                removed_git_dirs,
                [top_level_git_dir.resolve(), nested_git_dir.resolve()],
            )
            self.assertFalse(top_level_git_dir.exists())
            self.assertFalse(nested_git_dir.exists())

    def test_validate_git_dir_is_within_repo_rejects_outside_path(self) -> None:
        """
        Checks .git removal is rejected when the target path is outside the repo root.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_dir = temp_root / 'repo_a'
            outside_git_dir = temp_root / 'outside' / '.git'
            repo_dir.mkdir()
            outside_git_dir.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, 'outside repository root'):
                validate_git_dir_is_within_repo(repo_dir, outside_git_dir)


if __name__ == '__main__':
    unittest.main()
