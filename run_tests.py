"""
Runs the repository test suite with optional granular selection.

Usage

Run all tests:
`uv run ./run_tests.py`

Run discovery with a custom filename pattern:
`uv run ./run_tests.py --pattern "test_*.py"`

Run specific unittest targets:
`uv run ./run_tests.py test_main`
`uv run ./run_tests.py test_main.MainTests`
`uv run ./run_tests.py tests.test_repo_operations`

Use `uv run ./run_tests.py --help` for the CLI reference.
"""

import argparse
import unittest
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments for the test runner.

    Called by: main()
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description='Run the repository test suite or selected unittest targets.',
    )
    parser.add_argument(
        'targets',
        nargs='*',
        help='Optional unittest targets such as test_main, test_main.MainTests, or tests.test_repo_operations.',
    )
    parser.add_argument(
        '--pattern',
        default='test*.py',
        help='Filename pattern for unittest discovery when no explicit targets are provided.',
    )
    parser.add_argument(
        '--start-dir',
        default='tests',
        help='Directory to start unittest discovery from when no explicit targets are provided.',
    )
    args: argparse.Namespace = parser.parse_args()
    return args


def normalize_test_targets(targets: list[str]) -> list[str]:
    """
    Normalizes shorthand target names to the tests package.

    Called by: build_test_suite()
    """
    normalized_targets: list[str] = []
    target: str
    for target in targets:
        normalized_target: str = target
        if '.' not in target:
            normalized_target = f'tests.{target}'
        elif not target.startswith('tests.'):
            normalized_target = f'tests.{target}'
        normalized_targets.append(normalized_target)
    return normalized_targets


def build_test_suite(targets: list[str], pattern: str, start_dir: str) -> unittest.TestSuite:
    """
    Builds the unittest suite from explicit targets or discovery.

    Called by: main()
    """
    loader: unittest.TestLoader = unittest.TestLoader()
    suite: unittest.TestSuite
    if targets:
        normalized_targets: list[str] = normalize_test_targets(targets)
        suite = loader.loadTestsFromNames(normalized_targets)
    else:
        start_directory: str = str(Path(start_dir).resolve())
        suite = loader.discover(start_dir=start_directory, pattern=pattern)
    return suite


def main() -> None:
    """
    Orchestrates test loading, execution, and exit status.

    Called by: __main__
    """
    args: argparse.Namespace = parse_args()
    test_suite: unittest.TestSuite = build_test_suite(args.targets, args.pattern, args.start_dir)
    runner: unittest.TextTestRunner = unittest.TextTestRunner(verbosity=2)
    result: unittest.TestResult = runner.run(test_suite)
    exit_code: int = 0 if result.wasSuccessful() else 1
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
