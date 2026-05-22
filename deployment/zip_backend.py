import os
import zipfile

def zipdir(path, ziph):
    # Walk the directory
    for root, dirs, files in os.walk(path):
        # Skip __pycache__ and hidden folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        for file in files:
            # Skip database files or other zip files
            if file.endswith('.db') or file.endswith('.sqlite') or file.endswith('.zip') or file.endswith('.log'):
                continue
            filePath = os.path.join(root, file)
            # We want the paths inside the zip to start with 'finagent/'
            # Since 'path' is 'finagent', the parent dir is the root directory
            archivePath = os.path.relpath(filePath, os.path.dirname(path))
            ziph.write(filePath, archivePath)

def create_zip():
    # Delete existing zip if any
    if os.path.exists('backend.zip'):
        try:
            os.remove('backend.zip')
        except OSError:
            pass
            
    with zipfile.ZipFile('backend.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add Dockerfile
        if os.path.exists('Dockerfile'):
            zipf.write('Dockerfile', 'Dockerfile')
        # Add buildspec.yml
        if os.path.exists('buildspec.yml'):
            zipf.write('buildspec.yml', 'buildspec.yml')
        # Add finagent directory
        if os.path.exists('finagent'):
            zipdir('finagent', zipf)
            
    print("Successfully created backend.zip using Python")

if __name__ == '__main__':
    create_zip()
