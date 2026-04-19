# gather-repos-code

This script gathers a set of repositories into a single local enclosing directory so tools like Codex or Claude Code can inspect how those codebases relate to each other.

The goal is to collect working trees for analysis and documentation, not to maintain local Git clones. Each repository is cloned shallowly, then any `.git/` directories found within that cloned repository tree are removed. After that, the script sanitizes the cloned working tree to obfuscate sensitive text such as internal email addresses, secret-like literals, and internal hostnames or URLs before downstream LLM analysis.

## Overview

`main.py` supports two usage modes:

- all-repos mode:
  - reads `REPOS_TO_CLONE_JSON` from the environment
  - expects that value to be a JSON list of Git repository URLs
- single-repo mode:
  - accepts one repo URL from `--github-repo-url`
  - does not require `REPOS_TO_CLONE_JSON`

In both modes, the script:

- creates the enclosing directory if needed
- stores update state in `../gather_repos_state.json` relative to `gather_repos_code/main.py`
- derives a local directory name for each repo from the repo URL
- checks each repo's remote `main` branch before deciding whether local work is needed
- asks for confirmation before fully deleting only the destination directories that actually need refresh
- runs `git clone --depth 1 --branch main --single-branch` for each repo that needs refresh
- finds and removes `.git/` directories anywhere inside each cloned repository
- validates that each `.git/` removal target resolves inside that cloned repository before deletion
- sanitizes text files in each cloned repo to remove or obfuscate possibly sensitive values while leaving likely binary files untouched

## Requirements

- Python 3.12
- `uv`
- `git` on `PATH`
- working credentials for any private GitHub repositories you ask the script to clone

## Environment Variable

For all-repos usage, the script expects `REPOS_TO_CLONE_JSON` to be available in the environment, typically through `uv run --env-file=...`.

For single-repo usage with `--github-repo-url`, `REPOS_TO_CLONE_JSON` is not used.

Example:

```bash
REPOS_TO_CLONE_JSON='[
    "git@github.com:Brown-University-Library/repo_a.git",
    "git@github.com:Brown-University-Library/repo_b.git"
]'
```

## Usage

From this project directory...

All-repos mode, using `REPOS_TO_CLONE_JSON` from the `.env`:

```bash
uv run --env-file="/path/to/.env" ./main.py --enclosing-dir "/path/to/enclosing_dir/"
```

Single-repo mode, using `--github-repo-url` and no `REPOS_TO_CLONE_JSON`:

```bash
uv run ./main.py --enclosing-dir "/path/to/enclosing_dir/" --github-repo-url "git@github.com:Brown-University-Library/the_repo.git"
```

Show help:

```bash
uv run ./main.py --help
```

## What Happens On Run

1. The script validates that `git` is available.
2. It resolves the repo list from one of these sources:
   - all-repos mode: `REPOS_TO_CLONE_JSON`
   - single-repo mode: `--github-repo-url`
3. It creates the enclosing directory if it does not already exist.
4. It loads or initializes `../gather_repos_state.json` relative to `gather_repos_code/main.py`.
5. It checks each target repo's remote `main` branch commit with `git ls-remote`.
6. It compares that remote `main` commit to the last saved commit for the repo.
7. It prompts only for destination directories that need refresh because the repo changed or the local directory is missing.
8. It clones each changed repository into the enclosing directory with `--depth 1 --branch main --single-branch`.
9. It records the cloned commit SHA and committer timestamp in the state file.
10. It finds `.git/` directories anywhere inside the cloned repo.
11. It validates that each `.git/` path resolves inside that repo's root.
12. It deletes those `.git/` directories.
13. It scans files in that cloned repo and deletes or obfuscates likely sensitive values before the repo is left in place for analysis.

## Mode Differences

All-repos mode:

- uses every repo listed in `REPOS_TO_CLONE_JSON`
- is the mode where an `.env` file is typically involved
- is useful for gathering a related set of repositories into one bundle

Single-repo mode:

- uses only the repo passed to `--github-repo-url`
- does not require `REPOS_TO_CLONE_JSON`
- is useful for refreshing or inspecting one repository without maintaining an env-based repo list

## Existing Directory Behavior

If one or more destination directories need refresh, the script lists only those directories and prompts for confirmation before deleting them.

- Typing `yes` allows the script to fully delete and replace those directories.
- Any other response causes the script to exit without making changes.

If all repos are already current and their local directories still exist, the script skips them without prompting.

Because this confirmation uses an interactive prompt, reruns that actually need replacement require a terminal session with stdin attached.

## State File

The script keeps per-repo update state in a JSON file located at:

```text
<project_root>/gather_repos_state.json
```

That file records:

- the last seen remote `main` commit SHA for each repo
- the last saved commit timestamp from a successful refresh
- when each repo was last checked
- when each repo was last refreshed locally

This state file is kept outside `gather_repos_code/` at a fixed project-level location, independent of the chosen `--enclosing-dir`.

## Output Layout

All-repos example:

Given:

```bash
REPOS_TO_CLONE_JSON='[
    "git@github.com:Brown-University-Library/repo_a.git",
    "git@github.com:Brown-University-Library/repo_b.git"
]'
```

and:

```bash
--enclosing-dir "/tmp/repo_bundle"
```

the resulting layout will be:

```text
/tmp/repo_bundle/
    repo_a/
    repo_b/
```

Single-repo example:

Given:

```bash
--github-repo-url "git@github.com:Brown-University-Library/the_repo.git"
```

and:

```bash
--enclosing-dir "/tmp/repo_bundle"
```

the resulting layout will be:

```text
/tmp/repo_bundle/
    the_repo/
```

In either mode, each repo directory will contain the working tree content, but not any `.git/` directories found inside that cloned repo tree. Sensitive text detected by the cleanup pass will be replaced with deterministic placeholder values. The project-level `gather_repos_state.json` file will hold refresh-tracking metadata outside that output bundle.

## Notes

- The script processes repositories sequentially.
- It stops on the first hard failure.
- Only the remote `main` branch is considered when deciding whether a repo needs refresh.
- `REPOS_TO_CLONE_JSON` is required only for all-repos mode.
- `--github-repo-url` bypasses `REPOS_TO_CLONE_JSON` and targets exactly one repo.
- It removes `.git/` directories recursively within each cloned repo.
- Before deleting any discovered `.git/` directory, it validates that the resolved path is still inside that repo's root.
- The cleanup step rewrites text files in place and skips files that look binary based on suffixes and content.
- The cleanup step is intentionally conservative about structure: it aims to preserve code shape while obfuscating sensitive values.
