import os
import sys
import tarfile
import tempfile
from pathlib import Path


def restore(archive_path, nginx_dir=Path("/etc/nginx")):
    directory = Path(nginx_dir) / "sites-available"
    names = ("emby-panel", "emby-panel-https")
    with tarfile.open(archive_path, "r:gz") as archive:
        files = []
        for name in names:
            try:
                member = archive.getmember("etc/nginx/sites-available/" + name)
            except KeyError:
                continue
            destination = directory / name
            if not member.isfile() or destination.is_symlink():
                raise RuntimeError("Panel site must be a regular file: " + name)
            files.append((destination, member.mode & 0o777, archive.extractfile(member).read()))
        if not files:
            raise RuntimeError("No panel Nginx sites in backup")
    directory.mkdir(parents=True, exist_ok=True)
    for destination, mode, content in files:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as out:
                temporary = Path(out.name)
                out.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


if __name__ == "__main__":
    restore(sys.argv[1])
