"""
Overview

- Gathers a set of repositories into one enclosing directory for local inspection.
- Each repository is cloned shallowly, then any `.git` directories inside that cloned repo are removed.
- Each `.git` removal is validated to stay within that cloned repo before deletion.
- See `README.md` for more detail.

Usage

Run:
`uv run --env-file="/path/to/.env" ./main.py --enclosing-dir "/path/to/enclosing_dir/"`

Or clone and sanitize a single repository directly:
`uv run ./main.py --enclosing-dir "/path/to/enclosing_dir/" --github-repo-url "https://github.com/org/repo.git"`

Use `uv run ./main.py --help` for the CLI reference.
"""

import argparse
import logging
import os
from pathlib import Path

from lib.repo_operations import clone_repo
from lib.repo_operations import confirm_overwrite
from lib.repo_operations import current_timestamp
from lib.repo_operations import derive_state_file_path
from lib.repo_operations import derive_repo_dir_name
from lib.repo_operations import determine_repo_action
from lib.repo_operations import ensure_enclosing_dir
from lib.repo_operations import fetch_local_head_metadata
from lib.repo_operations import fetch_remote_main_info
from lib.repo_operations import load_repo_state
from lib.repo_operations import load_repo_urls
from lib.repo_operations import remove_existing_repo_dir
from lib.repo_operations import remove_git_dirs
from lib.repo_operations import save_repo_state
from lib.repo_operations import validate_git_available
from lib.sensitive_cleanup import SanitizationStats
from lib.sensitive_cleanup import sanitize_repo_contents

logging.basicConfig(
    level=logging.DEBUG if os.getenv('LOG_LEVEL') == 'DEBUG' else logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments for the repo gathering script.

    Called by: main()
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=(
            'Gather repositories into an enclosing directory. Use either all-repos mode with '
            'REPOS_TO_CLONE_JSON from the environment, or single-repo mode with --github-repo-url.'
        ),
        epilog=(
            'All-repos mode:\n'
            '  uv run --env-file="/path/to/.env" ./main.py --enclosing-dir "/path/to/enclosing_dir/"\n\n'
            'Single-repo mode:\n'
            '  uv run ./main.py --enclosing-dir "/path/to/enclosing_dir/" '
            '--github-repo-url "git@github.com:Brown-University-Library/the_repo.git"'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--enclosing-dir',
        required=True,
        help='Directory that will contain the gathered repository directories.',
    )
    parser.add_argument(
        '--github-repo-url',
        help='Optional single repository URL for single-repo mode. If omitted, the script uses REPOS_TO_CLONE_JSON.',
    )
    args: argparse.Namespace = parser.parse_args()
    return args


def resolve_repo_urls(github_repo_url: str | None) -> list[str]:
    """
    Resolves the repository URL list from CLI input or environment configuration.

    Called by: main()
    """
    repo_urls: list[str]
    if github_repo_url:
        cleaned_repo_url: str = github_repo_url.strip()
        if not cleaned_repo_url:
            raise ValueError('--github-repo-url cannot be blank.')
        repo_urls = [cleaned_repo_url]
    else:
        repo_urls = load_repo_urls()
    return repo_urls


def main() -> None:
    """
    Orchestrates repository cloning, replacement confirmation, and .git removal.

    Called by: __main__
    """
    args: argparse.Namespace = parse_args()
    enclosing_dir: Path = Path(args.enclosing_dir).expanduser().resolve()
    github_repo_url: str | None = args.github_repo_url

    try:
        validate_git_available()
        repo_urls: list[str] = resolve_repo_urls(github_repo_url)
        ensure_enclosing_dir(enclosing_dir)
        state_file: Path = derive_state_file_path()
        state: dict[str, object] = load_repo_state(state_file)
        state_repos: dict[str, object] = state['repos'] if isinstance(state.get('repos'), dict) else {}
        pending_updates: list[dict[str, object]] = []
        skipped_count: int = 0

        log.info('Starting repository gather into %s', enclosing_dir)
        if github_repo_url:
            log.info('Using repository URL from --github-repo-url')
        else:
            log.info('Parsed %s repositories from REPOS_TO_CLONE_JSON', len(repo_urls))

        for repo_url in repo_urls:
            repo_dir_name: str = derive_repo_dir_name(repo_url)
            destination_dir: Path = enclosing_dir / repo_dir_name
            remote_main_info: dict[str, str] = fetch_remote_main_info(repo_url)
            head_branch: str = remote_main_info.get('head_branch', '')
            if head_branch and head_branch != 'main':
                log.warning(
                    'Remote HEAD for %s points to %s, but update checks will continue against main',
                    repo_url,
                    head_branch,
                )

            repo_state: dict[str, object] = {}
            saved_repo_state: object = state_repos.get(repo_url)
            if isinstance(saved_repo_state, dict):
                repo_state = saved_repo_state

            action: str = determine_repo_action(repo_state, destination_dir, remote_main_info['commit'])
            if action == 'skip':
                skipped_count += 1
                updated_repo_state: dict[str, object] = dict(repo_state)
                updated_repo_state['repo_dir_name'] = repo_dir_name
                updated_repo_state['remote_head_branch'] = 'main'
                updated_repo_state['remote_head_commit'] = remote_main_info['commit']
                updated_repo_state['last_checked_at'] = current_timestamp()
                state_repos[repo_url] = updated_repo_state
                log.info('Skipping %s; remote main unchanged at %s', repo_dir_name, remote_main_info['commit'])
                continue

            update_reason: str = 'no prior state found'
            if repo_state and not destination_dir.exists():
                update_reason = 'destination directory is missing'
            elif repo_state and repo_state.get('remote_head_commit') != remote_main_info['commit']:
                update_reason = (
                    f'remote main changed from {repo_state.get("remote_head_commit")} to {remote_main_info["commit"]}'
                )

            pending_updates.append(
                {
                    'repo_url': repo_url,
                    'repo_dir_name': repo_dir_name,
                    'destination_dir': destination_dir,
                    'remote_main_info': remote_main_info,
                    'reason': update_reason,
                }
            )
            log.info('Updating %s; %s', repo_dir_name, update_reason)

        existing_destinations: list[Path] = []
        pending_update: dict[str, object]
        for pending_update in pending_updates:
            destination_dir = pending_update['destination_dir']
            if isinstance(destination_dir, Path) and destination_dir.exists():
                existing_destinations.append(destination_dir)

        log.info(
            'Checked remote main branch for %s repos; %s need update and %s will be skipped',
            len(repo_urls),
            len(pending_updates),
            skipped_count,
        )

        overwrite_confirmed: bool = confirm_overwrite(existing_destinations)
        if not overwrite_confirmed:
            log.info('User declined deletion of existing destination paths. Exiting without changes.')
            raise SystemExit(1)

        if existing_destinations:
            log.info('User confirmed deletion of existing destination paths.')
        for existing_destination in existing_destinations:
            log.info('Removing existing destination path: %s', existing_destination)
            remove_existing_repo_dir(existing_destination)

        for pending_update in pending_updates:
            repo_url = pending_update['repo_url']
            repo_dir_name = pending_update['repo_dir_name']
            destination_dir = pending_update['destination_dir']
            if not isinstance(repo_url, str) or not isinstance(repo_dir_name, str) or not isinstance(destination_dir, Path):
                raise ValueError('Unexpected pending-update structure.')

            log.info('Cloning %s into %s', repo_url, destination_dir)
            clone_repo(repo_url, destination_dir)
            log.info('Finished cloning %s', repo_url)
            local_head_metadata: dict[str, str] = fetch_local_head_metadata(destination_dir)
            removed_git_dirs: list[Path] = remove_git_dirs(destination_dir)
            git_dir_count: int = len(removed_git_dirs)
            git_dir_label: str = 'directory' if git_dir_count == 1 else 'directories'
            log.info(
                'Removed %s .git %s from %s',
                git_dir_count,
                git_dir_label,
                destination_dir,
            )
            sanitization_stats: SanitizationStats = sanitize_repo_contents(destination_dir)
            log.info(
                'Sanitized %s files in %s and applied %s replacements',
                sanitization_stats.files_changed,
                destination_dir,
                sanitization_stats.replacement_count,
            )
            state_repos[repo_url] = {
                'repo_dir_name': repo_dir_name,
                'remote_head_branch': 'main',
                'remote_head_commit': local_head_metadata['commit'],
                'remote_head_commit_timestamp': local_head_metadata['timestamp'],
                'last_checked_at': current_timestamp(),
                'last_updated_at': current_timestamp(),
            }
            state['repos'] = state_repos
            save_repo_state(state_file, state)

        state['repos'] = state_repos
        save_repo_state(state_file, state)
        log.info(
            'Completed repository gather for %s repositories; updated %s and skipped %s',
            len(repo_urls),
            len(pending_updates),
            skipped_count,
        )
    except KeyboardInterrupt:
        log.error('Interrupted by user.')
        raise SystemExit(1) from None
    except Exception as exc:
        error_message: str = str(exc)
        log.error('Repository gather failed: %s', error_message)
        raise SystemExit(1) from exc


if __name__ == '__main__':
    main()
