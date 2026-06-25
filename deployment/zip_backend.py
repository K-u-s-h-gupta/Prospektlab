import os
import zipfile

def resolve_source_dir() -> str:
    """Prefer the real backend package under backend/finagent."""
    candidate = os.path.join("backend", "finagent")
    if os.path.isdir(candidate):
        return candidate
    return "finagent"


def zipdir(path, ziph, archive_root=None):
    # Walk the directory
    for root, dirs, files in os.walk(path):
        # Skip __pycache__ and hidden folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            # Skip hidden files and local state that should never be baked into the image.
            if file.startswith('.'):
                continue
            # Skip database files or other zip files
            if file.endswith('.db') or file.endswith('.sqlite') or file.endswith('.zip') or file.endswith('.log'):
                continue
            filePath = os.path.join(root, file)
            rel_path = os.path.relpath(filePath, path)
            archivePath = os.path.join(archive_root, rel_path) if archive_root else os.path.relpath(filePath, ".")
            ziph.write(filePath, archivePath.replace(os.sep, "/"))

def create_zip():
    source_dir = resolve_source_dir()
    # Delete existing zip if any
    if os.path.exists('backend.zip'):
        try:
            os.remove('backend.zip')
        except OSError:
            pass
            
    with zipfile.ZipFile('backend.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        TARGETS = [
            "Dockerfile",
            "buildspec.yml",
            "buildspec-prod.yml",
            "pyproject.toml",
            "backend",
            "scripts"
        ]
        for target in TARGETS:
            if os.path.exists(target):
                if os.path.isdir(target):
                    zipdir(target, zipf, archive_root=target)
                else:
                    zipf.write(target, target)
            
    print("Successfully created backend.zip using Python")

if __name__ == '__main__':
    create_zip()
