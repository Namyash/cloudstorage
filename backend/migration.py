"""Copy a stopped household database and its file objects to a new data folder."""

from contextlib import closing
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import TemporaryDirectory


COPY_BLOCK = 4 * 1024 * 1024


def move_household(source, target, storage_id, new_storage_id, reserve, report):
    source, target = Path(source), Path(target)
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('Choose a new folder outside the current SpareDrive folder.')
    marker = source / '.family-drive-id'
    if marker.read_text(encoding='ascii') != storage_id:
        raise ValueError('The original drive is unavailable.')

    db_file = source / 'family-drive.sqlite3'
    with closing(sqlite3.connect(db_file.as_uri() + '?mode=ro', uri=True, timeout=15)) as original:
        if original.execute("SELECT 1 FROM files WHERE state = 'uploading' LIMIT 1").fetchone():
            raise ValueError('Finish or cancel private and shared uploads before moving storage.')
        files = original.execute("SELECT id, stored FROM files WHERE state = 'ready'").fetchall()
        allocated = original.execute('SELECT COALESCE(SUM(quota), 0) FROM users').fetchone()[0]
        allocated += int(original.execute("SELECT value FROM config WHERE key = 'family_quota'").fetchone()[0])
        database_size = original.execute('PRAGMA page_count').fetchone()[0] * original.execute('PRAGMA page_size').fetchone()[0]
        total = sum(size for _, size in files)
        if shutil.disk_usage(target.parent).free < max(total, allocated) + database_size + reserve:
            raise ValueError('The destination needs enough free space for current files and assigned quotas.')
        report('copying', 0, total, 0, len(files))

        # Stage on the destination volume so the final folder rename is atomic.
        with TemporaryDirectory(dir=target.parent, prefix='.family-drive-move-') as stage:
            staging = Path(stage) / 'data'
            staging.mkdir()
            objects = staging / 'objects'
            objects.mkdir()
            copied = 0
            for index, (file_id, expected) in enumerate(files):
                if not re.fullmatch(r'[0-9a-f]{32}', file_id):
                    raise ValueError('A file record on the original drive is invalid.')
                original_object, new_object = source / 'objects' / file_id, objects / file_id
                if original_object.is_symlink() or not original_object.is_file() or original_object.stat().st_size != expected:
                    raise ValueError('A file on the original drive is missing, linked, or incomplete.')
                digest = hashlib.sha256()
                size = 0
                with original_object.open('rb') as reader, new_object.open('xb') as writer:
                    while chunk := reader.read(COPY_BLOCK):
                        writer.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        report('copying', copied + size, total, index, len(files))
                    writer.flush()
                    os.fsync(writer.fileno())
                with new_object.open('rb') as reader:
                    copied_digest = hashlib.sha256()
                    while chunk := reader.read(COPY_BLOCK):
                        copied_digest.update(chunk)
                if size != expected or copied_digest.digest() != digest.digest():
                    raise ValueError('A copied file could not be verified.')
                copied += size
                report('copying', copied, total, index + 1, len(files))

            report('verifying', copied, total, len(files), len(files))
            with closing(sqlite3.connect(staging / 'family-drive.sqlite3')) as result:
                original.backup(result)
                if result.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('The copied household database could not be verified.')
            if marker.read_text(encoding='ascii') != storage_id:
                raise ValueError('The original drive disconnected during the move.')
            with (staging / '.family-drive-id').open('x', encoding='ascii') as identity:
                identity.write(new_storage_id)
                identity.flush()
                os.fsync(identity.fileno())
            staging.rename(target)
