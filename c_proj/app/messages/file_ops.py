"""
Filesystem work for a saved message.

Everything here runs only after the database row has been committed. If the
copy fails the message still exists and can be retried; the reverse order would
leave folders on the share with no record of what they are.
"""

import shutil
from pathlib import Path


class FileOpsError(Exception):
    pass


def ensure_folder(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FileOpsError(f"Could not create folder {path}: {e}") from e
    return str(path)


def copy_intercept_folder(source_folder, destination_folder, overwrite=False):
    """
    Copy the contents of the source intercept folder (call audio, attachments,
    the data file) into the destination.

    Contents are copied rather than the folder itself, so the destination stays
    the message-number folder instead of gaining a nested Event ID folder.
    """
    src = Path(source_folder)
    if not src.exists():
        raise FileOpsError(f"Source folder no longer exists: {source_folder}")
    if not src.is_dir():
        raise FileOpsError(f"Source path is not a folder: {source_folder}")

    dst = Path(ensure_folder(destination_folder))
    copied, skipped = [], []

    for item in src.iterdir():
        target = dst / item.name
        try:
            if item.is_dir():
                if target.exists() and not overwrite:
                    skipped.append(item.name)
                    continue
                shutil.copytree(item, target, dirs_exist_ok=overwrite)
            else:
                if target.exists() and not overwrite:
                    skipped.append(item.name)
                    continue
                shutil.copy2(item, target)
            copied.append(item.name)
        except OSError as e:
            raise FileOpsError(f"Failed copying {item.name}: {e}") from e

    return {"copied": copied, "skipped": skipped, "destination": str(dst)}
