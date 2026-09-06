"""Create a local, checksummed source/build snapshot without Git mutations."""

import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"node_modules", ".venv", "__pycache__", ".pytest_cache", ".git"}


def main() -> None:
    output = ROOT / "release"
    output.mkdir(exist_ok=True)
    paths = [ROOT / name for name in ("README.md", "AGENTS.md", "requirements.txt", "pytest.ini", ".gitignore")
             if (ROOT / name).is_file()]
    for folder in ("backend", "frontend", "data", "docs", "scripts", "tests"):
        paths.extend(p for p in (ROOT / folder).rglob("*") if p.is_file()
                     and not p.is_symlink()
                     and not any(part in EXCLUDED or (part.startswith(".") and part != ".gitignore")
                                 for part in p.relative_to(ROOT).parts)
                     and p.suffix not in {".pyc", ".pyo"})
    paths.sort()
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    archive = output / "StudyFlow-RC-20260906.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for p in paths:
            bundle.write(p, "StudyFlow/" + str(p.relative_to(ROOT)))
        bundle.writestr("StudyFlow/SOURCE_SHA256.json", json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert all(hashlib.sha256(bundle.read("StudyFlow/" + name)).hexdigest() == value
                   for name, value in manifest.items())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + ".sha256")).write_text(f"{digest}  {archive.name}\n")
    print(f"Verified {len(manifest)} files: {archive}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
