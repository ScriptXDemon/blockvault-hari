from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _client(args: argparse.Namespace):
    session = boto3.session.Session()
    return session.client(
        "s3",
        endpoint_url=args.endpoint_url,
        region_name=args.region,
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key,
        config=BotoConfig(s3={"addressing_style": "path" if args.force_path_style else "auto"}),
    )


def _storage_key(prefix: str, profile: str, relative_path: Path) -> str:
    normalized_prefix = prefix.strip("/")
    if normalized_prefix:
        return f"{normalized_prefix}/{profile}/{relative_path.as_posix()}"
    return f"{profile}/{relative_path.as_posix()}"


def _collect_runtime_files(profile_dir: Path) -> list[Path]:
    manifest_path = profile_dir / "artifact-manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"Missing artifact manifest for profile '{profile_dir.name}': {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    required = [manifest_path]
    for relative in (
        files.get("wasm"),
        files.get("zkey"),
        files.get("verification_key"),
    ):
        if not relative:
            continue
        required.append(profile_dir / relative)
    missing = [path for path in required if not path.exists()]
    if missing:
        details = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Profile '{profile_dir.name}' is missing required runtime files: {details}")
    return required


def upload_profile(args: argparse.Namespace, profile: str) -> None:
    profile_dir = repo_root() / "circuits" / "zkpt" / profile
    if not profile_dir.exists():
        raise SystemExit(f"Profile directory not found: {profile_dir}")
    client = _client(args)
    for file_path in _collect_runtime_files(profile_dir):
        relative_path = file_path.relative_to(profile_dir)
        key = _storage_key(args.prefix, profile, relative_path)
        client.upload_file(str(file_path), args.bucket, key)
        print(f"uploaded {profile}: s3://{args.bucket}/{key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload BlockVault ZKPT runtime artifacts to S3.")
    parser.add_argument("--bucket", required=True, help="Destination S3 bucket")
    parser.add_argument("--prefix", default="zkpt-artifacts", help="S3 prefix for artifact uploads")
    parser.add_argument("--profile", action="append", dest="profiles", help="Profile to upload (repeatable)")
    parser.add_argument("--region", default="us-east-1", help="S3 region")
    parser.add_argument("--endpoint-url", default=None, help="Optional custom S3 endpoint")
    parser.add_argument("--access-key-id", default=None, help="Optional S3 access key")
    parser.add_argument("--secret-access-key", default=None, help="Optional S3 secret key")
    parser.add_argument("--force-path-style", action="store_true", help="Use path-style S3 addressing")
    args = parser.parse_args()

    profiles = args.profiles or ["v4_sparse", "v3a"]
    for profile in profiles:
        upload_profile(args, profile)


if __name__ == "__main__":
    main()
