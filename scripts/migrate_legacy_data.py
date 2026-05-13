#!/usr/bin/env python
"""
Data migration utility for Trace2Quality

Migrates data from legacy spec2test system to t2q:
- Old test cases → t2q workflow artifacts
- Old outputs → t2q run results
- Old configs → t2q integration configs

Usage:
    python scripts/migrate_legacy_data.py --source /path/to/old/data --target http://localhost:8000/api
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
import hashlib


class LegacyDataMigrator:
    """Migrate data from spec2test to t2q"""

    def __init__(self, source_dir: Path, api_url: str, dry_run: bool = False):
        self.source_dir = Path(source_dir)
        self.api_url = api_url
        self.dry_run = dry_run
        self.stats = {
            "test_cases_found": 0,
            "outputs_found": 0,
            "configs_found": 0,
            "migrated": 0,
            "failed": 0,
            "errors": []
        }

    def discover_legacy_files(self):
        """Find legacy spec2test files"""
        print("\n[*] Scanning for legacy files...")

        test_files = list(self.source_dir.glob("**/test_*.json"))
        output_files = list(self.source_dir.glob("**/output_*.json"))
        config_files = list(self.source_dir.glob("**/config_*.json"))

        self.stats["test_cases_found"] = len(test_files)
        self.stats["outputs_found"] = len(output_files)
        self.stats["configs_found"] = len(config_files)

        print(f"    Found {len(test_files)} test case files")
        print(f"    Found {len(output_files)} output files")
        print(f"    Found {len(config_files)} config files")

        return test_files, output_files, config_files

    def migrate_test_cases(self, test_files: list[Path]):
        """Migrate legacy test cases"""
        print("\n[*] Migrating test cases...")

        for test_file in test_files:
            try:
                with open(test_file) as f:
                    test_data = json.load(f)

                # Transform to t2q format
                migrated = {
                    "id": hashlib.md5(test_file.as_posix().encode()).hexdigest(),
                    "source_file": test_file.name,
                    "migrated_at": datetime.utcnow().isoformat(),
                    "original_data": test_data,
                    "test_cases": []
                }

                # Extract test cases
                if isinstance(test_data, list):
                    migrated["test_cases"] = test_data
                elif isinstance(test_data, dict):
                    if "tests" in test_data:
                        migrated["test_cases"] = test_data["tests"]
                    else:
                        migrated["test_cases"] = [test_data]

                if not self.dry_run:
                    # Store migration
                    output_file = self.source_dir / "migrated" / f"tc_{migrated['id']}.json"
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_file, 'w') as f:
                        json.dump(migrated, f, indent=2)

                self.stats["migrated"] += 1
                print(f"    ✓ {test_file.name} ({len(migrated['test_cases'])} tests)")

            except Exception as e:
                self.stats["failed"] += 1
                error_msg = f"Failed to migrate {test_file.name}: {str(e)}"
                self.stats["errors"].append(error_msg)
                print(f"    ✗ {test_file.name}: {str(e)}")

    def migrate_outputs(self, output_files: list[Path]):
        """Migrate legacy test outputs"""
        print("\n[*] Migrating test outputs...")

        for output_file in output_files:
            try:
                with open(output_file) as f:
                    output_data = json.load(f)

                # Transform to t2q artifact format
                migrated = {
                    "id": hashlib.md5(output_file.as_posix().encode()).hexdigest(),
                    "source_file": output_file.name,
                    "migrated_at": datetime.utcnow().isoformat(),
                    "content_type": "application/json",
                    "size_bytes": output_file.stat().st_size,
                    "original_data": output_data,
                    "results": {
                        "total_tests": output_data.get("total_tests", 0),
                        "passed": output_data.get("passed_tests", 0),
                        "failed": output_data.get("failed_tests", 0),
                        "skipped": output_data.get("skipped_tests", 0),
                        "errors": output_data.get("errors", [])
                    }
                }

                if not self.dry_run:
                    # Store migration
                    output_dir = self.source_dir / "migrated" / "artifacts"
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / f"output_{migrated['id']}.json"
                    with open(output_path, 'w') as f:
                        json.dump(migrated, f, indent=2)

                self.stats["migrated"] += 1
                print(f"    ✓ {output_file.name} ({migrated['results']['total_tests']} tests)")

            except Exception as e:
                self.stats["failed"] += 1
                error_msg = f"Failed to migrate {output_file.name}: {str(e)}"
                self.stats["errors"].append(error_msg)
                print(f"    ✗ {output_file.name}: {str(e)}")

    def migrate_configs(self, config_files: list[Path]):
        """Migrate legacy configurations"""
        print("\n[*] Migrating configurations...")

        for config_file in config_files:
            try:
                with open(config_file) as f:
                    config_data = json.load(f)

                # Transform to t2q integration config format
                migrated = {
                    "id": hashlib.md5(config_file.as_posix().encode()).hexdigest(),
                    "source_file": config_file.name,
                    "migrated_at": datetime.utcnow().isoformat(),
                    "original_config": config_data,
                    "integration_type": self._detect_integration_type(config_file.name),
                    "config_hash": hashlib.sha256(json.dumps(config_data).encode()).hexdigest()
                }

                if not self.dry_run:
                    # Store migration
                    config_dir = self.source_dir / "migrated" / "configs"
                    config_dir.mkdir(parents=True, exist_ok=True)
                    config_path = config_dir / f"config_{migrated['id']}.json"
                    with open(config_path, 'w') as f:
                        json.dump(migrated, f, indent=2)

                self.stats["migrated"] += 1
                print(f"    ✓ {config_file.name} ({migrated['integration_type']})")

            except Exception as e:
                self.stats["failed"] += 1
                error_msg = f"Failed to migrate {config_file.name}: {str(e)}"
                self.stats["errors"].append(error_msg)
                print(f"    ✗ {config_file.name}: {str(e)}")

    @staticmethod
    def _detect_integration_type(filename: str) -> str:
        """Detect integration type from filename"""
        if "confluence" in filename:
            return "confluence"
        elif "jira" in filename:
            return "jira"
        elif "azure" in filename:
            return "azure_devops"
        elif "gemini" in filename:
            return "gemini"
        else:
            return "unknown"

    def generate_migration_report(self):
        """Generate migration report"""
        print("\n" + "=" * 60)
        print("MIGRATION REPORT")
        print("=" * 60)

        print(f"\nDiscovered:")
        print(f"  Test Cases:    {self.stats['test_cases_found']}")
        print(f"  Outputs:       {self.stats['outputs_found']}")
        print(f"  Configs:       {self.stats['configs_found']}")

        print(f"\nMigration Results:")
        print(f"  Successfully Migrated: {self.stats['migrated']}")
        print(f"  Failed:                {self.stats['failed']}")

        if self.stats["errors"]:
            print(f"\nErrors ({len(self.stats['errors'])}):")
            for error in self.stats["errors"][:5]:
                print(f"  - {error}")
            if len(self.stats["errors"]) > 5:
                print(f"  ... and {len(self.stats['errors']) - 5} more")

        print(f"\nOutput Location:")
        print(f"  {self.source_dir / 'migrated'}")

        print(f"\nNext Steps:")
        print(f"  1. Review migrated data in the 'migrated' directory")
        print(f"  2. Run: python scripts/import_migrated_data.py --source {self.source_dir / 'migrated'} --api {self.api_url}")
        print(f"  3. Verify data in t2q UI: http://localhost:8000/ui")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy spec2test data to Trace2Quality"
    )
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Source directory with legacy spec2test data"
    )
    parser.add_argument(
        "--target",
        type=str,
        default="http://localhost:8000/api",
        help="Target t2q API URL (default: http://localhost:8000/api)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze without making changes"
    )

    args = parser.parse_args()

    # Validate source directory
    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("TRACE2QUALITY DATA MIGRATION UTILITY")
    print("=" * 60)
    print(f"\nSource: {source_dir}")
    print(f"Target: {args.target}")
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made")

    # Create migrator and run migration
    migrator = LegacyDataMigrator(source_dir, args.target, dry_run=args.dry_run)

    test_files, output_files, config_files = migrator.discover_legacy_files()
    migrator.migrate_test_cases(test_files)
    migrator.migrate_outputs(output_files)
    migrator.migrate_configs(config_files)
    migrator.generate_migration_report()

    print("\n")


if __name__ == "__main__":
    main()
