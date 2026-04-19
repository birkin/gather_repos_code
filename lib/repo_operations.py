"""
Helpers for repository gathering and cleanup operations.
"""

from datetime import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE_FILE_NAME: str = 'gather_repos_state.json'
STATE_FILE_VERSION: int = 1


def load_repo_urls() -> list[str]:
    """
    Loads and validates repository URLs from the REPOS_TO_CLONE_JSON environment variable.

    Called by: main.main()
    """
    raw_repo_json: str | None = os.getenv('REPOS_TO_CLONE_JSON')
    if raw_repo_json is None:
        raise ValueError('REPOS_TO_CLONE_JSON is not set.')

    try:
        parsed_repo_urls: object = json.loads(raw_repo_json)
    except json.JSONDecodeError as exc:
        raise ValueError('REPOS_TO_CLONE_JSON is not valid JSON.') from exc

    if not isinstance(parsed_repo_urls, list):
        raise ValueError('REPOS_TO_CLONE_JSON must decode to a list of repository URLs.')

    repo_urls: list[str] = []
    for repo_url in parsed_repo_urls:
        if not isinstance(repo_url, str):
            raise ValueError('Each repository entry in REPOS_TO_CLONE_JSON must be a string.')
        cleaned_repo_url: str = repo_url.strip()
        if not cleaned_repo_url:
            raise ValueError('Repository URLs in REPOS_TO_CLONE_JSON cannot be blank.')
        repo_urls.append(cleaned_repo_url)

    if not repo_urls:
        raise ValueError('REPOS_TO_CLONE_JSON must contain at least one repository URL.')

    return repo_urls


def derive_repo_dir_name(repo_url: str) -> str:
    """
    Derives the local repository directory name from a repository URL.

    Called by: lib.repo_operations.collect_existing_destinations()
    """
    normalized_repo_url: str = repo_url.rstrip('/')
    repo_basename: str = normalized_repo_url.rsplit('/', maxsplit=1)[-1]
    repo_basename = repo_basename.rsplit(':', maxsplit=1)[-1]
    if repo_basename.endswith('.git'):
        repo_basename = repo_basename[:-4]
    if not repo_basename:
        raise ValueError(f'Could not derive a repository directory name from {repo_url!r}.')
    return repo_basename


def derive_state_file_path() -> Path:
    """
    Derives the persistent state-file path relative to main.py.

    Called by: main.main()
    """
    main_file_dir: Path = Path(__file__).resolve().parent.parent
    state_file_path: Path = main_file_dir.parent / STATE_FILE_NAME
    return state_file_path


def ensure_enclosing_dir(enclosing_dir: Path) -> None:
    """
    Ensures the enclosing directory exists.

    Called by: main.main()
    """
    enclosing_dir.mkdir(parents=True, exist_ok=True)


def load_repo_state(state_file: Path) -> dict[str, object]:
    """
    Loads repository update state from disk when present.

    Called by: main.main()
    """
    state: dict[str, object]
    if not state_file.exists():
        state = {'version': STATE_FILE_VERSION, 'repos': {}}
        return state

    raw_state_text: str = state_file.read_text(encoding='utf-8')
    parsed_state: object = json.loads(raw_state_text)
    if not isinstance(parsed_state, dict):
        raise ValueError('Repository state file must decode to an object.')

    version: object = parsed_state.get('version')
    if version != STATE_FILE_VERSION:
        raise ValueError(f'Unsupported repository state-file version: {version!r}')

    repos: object = parsed_state.get('repos')
    if not isinstance(repos, dict):
        raise ValueError('Repository state file must contain a "repos" object.')

    state = {'version': STATE_FILE_VERSION, 'repos': repos}
    return state


def save_repo_state(state_file: Path, state: dict[str, object]) -> None:
    """
    Saves repository update state to disk.

    Called by: main.main()
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    serialized_state: str = json.dumps(state, indent=2, sort_keys=True)
    state_file.write_text(f'{serialized_state}\n', encoding='utf-8')


def current_timestamp() -> str:
    """
    Returns the current local timestamp in ISO-8601 format.

    Called by: main.main()
    """
    timestamp: str = datetime.now().astimezone().isoformat(timespec='seconds')
    return timestamp


def collect_existing_destinations(repo_urls: list[str], enclosing_dir: Path) -> list[Path]:
    """
    Collects target paths that already exist before cloning begins.

    Called by: main.main()
    """
    existing_destinations: list[Path] = []
    for repo_url in repo_urls:
        repo_dir_name: str = derive_repo_dir_name(repo_url)
        destination_dir: Path = enclosing_dir / repo_dir_name
        if destination_dir.exists():
            existing_destinations.append(destination_dir)
    return existing_destinations


def fetch_remote_main_info(repo_url: str) -> dict[str, str]:
    """
    Fetches the remote main-branch commit and HEAD branch name.

    Called by: main.main()
    """
    main_command: list[str] = ['git', 'ls-remote', repo_url, 'refs/heads/main']
    main_result: subprocess.CompletedProcess[str] = subprocess.run(
        main_command,
        check=True,
        capture_output=True,
        text=True,
    )
    main_output: str = main_result.stdout.strip()
    if not main_output:
        raise ValueError(f'Remote repository does not expose refs/heads/main: {repo_url}')

    main_line: str = main_output.splitlines()[0]
    main_parts: list[str] = main_line.split('\t')
    if len(main_parts) != 2:
        raise ValueError(f'Unexpected git ls-remote output for refs/heads/main: {main_output!r}')

    head_command: list[str] = ['git', 'ls-remote', '--symref', repo_url, 'HEAD']
    head_result: subprocess.CompletedProcess[str] = subprocess.run(
        head_command,
        check=True,
        capture_output=True,
        text=True,
    )
    head_output: str = head_result.stdout.strip()
    head_branch: str = ''
    for line in head_output.splitlines():
        if line.startswith('ref: ') and line.endswith('\tHEAD'):
            head_ref: str = line.removeprefix('ref: ').split('\t', maxsplit=1)[0]
            head_branch = head_ref.rsplit('/', maxsplit=1)[-1]
            break

    remote_main_info: dict[str, str] = {
        'branch': 'main',
        'commit': main_parts[0],
        'head_branch': head_branch,
    }
    return remote_main_info


def fetch_local_head_metadata(repo_dir: Path) -> dict[str, str]:
    """
    Fetches commit metadata from the cloned repository head.

    Called by: main.main()
    """
    command: list[str] = ['git', '-C', str(repo_dir), 'log', '-1', '--format=%H%n%cI']
    result: subprocess.CompletedProcess[str] = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    output_lines: list[str] = result.stdout.strip().splitlines()
    if len(output_lines) < 2:
        raise ValueError(f'Unexpected git log output for {repo_dir}: {result.stdout!r}')

    local_head_metadata: dict[str, str] = {
        'commit': output_lines[0],
        'timestamp': output_lines[1],
    }
    return local_head_metadata


def determine_repo_action(
    repo_state: dict[str, object],
    destination_dir: Path,
    remote_main_commit: str,
) -> str:
    """
    Determines whether a repository should be updated or skipped.

    Called by: main.main()
    """
    action: str = 'skip'
    saved_commit: object = repo_state.get('remote_head_commit')
    if not repo_state:
        action = 'update'
    elif not destination_dir.exists():
        action = 'update'
    elif saved_commit != remote_main_commit:
        action = 'update'
    return action


def confirm_overwrite(existing_dirs: list[Path]) -> bool:
    """
    Prompts for confirmation before deleting existing destination directories.

    Called by: main.main()
    """
    if not existing_dirs:
        return True

    if not sys.stdin.isatty():
        raise ValueError('Existing destination directories were found, but no interactive terminal is available.')

    print('The following destination paths already exist and will be fully deleted before recloning:')
    for existing_dir in existing_dirs:
        print(f'- {existing_dir}')

    prompt: str = 'Delete and replace these directories? Type "yes" to continue: '
    user_response: str = input(prompt).strip()
    confirmed: bool = user_response == 'yes'
    return confirmed


def remove_existing_repo_dir(repo_dir: Path) -> None:
    """
    Fully removes an existing destination path before recloning.

    Called by: main.main()
    """
    if repo_dir.is_dir():
        shutil.rmtree(repo_dir)
    else:
        repo_dir.unlink()


def clone_repo(repo_url: str, destination_dir: Path) -> None:
    """
    Clones a repository into the destination directory using a shallow clone.

    Called by: main.main()
    """
    command: list[str] = [
        'git',
        'clone',
        '--depth',
        '1',
        '--branch',
        'main',
        '--single-branch',
        repo_url,
        str(destination_dir),
    ]
    subprocess.run(command, check=True)


def find_git_dirs(repo_dir: Path) -> list[Path]:
    """
    Finds .git directories within a cloned repository tree.

    Called by: lib.repo_operations.remove_git_dirs()
    """
    git_dirs: list[Path] = []
    root_path: str
    dir_names: list[str]
    file_names: list[str]
    for root_path, dir_names, file_names in os.walk(repo_dir, topdown=True):
        root_dir: Path = Path(root_path)
        if '.git' in dir_names:
            git_dir: Path = root_dir / '.git'
            git_dirs.append(git_dir)
            dir_names.remove('.git')
    return git_dirs


def validate_git_dir_is_within_repo(repo_dir: Path, git_dir: Path) -> Path:
    """
    Validates that a discovered .git directory resolves inside the cloned repository root.

    Called by: lib.repo_operations.remove_git_dirs()
    """
    resolved_repo_dir: Path = repo_dir.resolve()
    resolved_git_dir: Path = git_dir.resolve()
    if resolved_git_dir.name != '.git':
        raise ValueError(f'Refusing to remove non-.git path: {resolved_git_dir}')
    try:
        resolved_git_dir.relative_to(resolved_repo_dir)
    except ValueError as exc:
        raise ValueError(
            f'Refusing to remove .git path outside repository root: {resolved_git_dir}',
        ) from exc
    return resolved_git_dir


def remove_git_dirs(repo_dir: Path) -> list[Path]:
    """
    Removes all .git directories found within a cloned repository tree.

    Called by: main.main()
    """
    discovered_git_dirs: list[Path] = find_git_dirs(repo_dir)
    removed_git_dirs: list[Path] = []
    for git_dir in discovered_git_dirs:
        safe_git_dir: Path = validate_git_dir_is_within_repo(repo_dir, git_dir)
        shutil.rmtree(safe_git_dir)
        removed_git_dirs.append(safe_git_dir)
    return removed_git_dirs


def validate_git_available() -> None:
    """
    Validates that git is available on PATH.

    Called by: main.main()
    """
    if shutil.which('git') is None:
        raise ValueError('git is not available on PATH.')
