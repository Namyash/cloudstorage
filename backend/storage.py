"""Validate the location of SpareDrive's data on the host computer."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import string
from uuid import UUID


def system_drive():
    return os.environ.get('SystemDrive', 'C:').rstrip('\\/').casefold()


def is_windows_data_drive(root, allow_system=False):
    return (allow_system or root.drive.casefold() != system_drive()) and ctypes.windll.kernel32.GetDriveTypeW(str(root)) in (2, 3)


def drive_inventory():
    if os.name != 'nt':
        return []
    kinds = {2: 'Removable', 3: 'Fixed disk', 4: 'Network', 5: 'Optical', 6: 'RAM disk'}
    drives = []
    for letter in string.ascii_uppercase:
        root = Path(f'{letter}:\\')
        kind = ctypes.windll.kernel32.GetDriveTypeW(str(root))
        if kind not in kinds:
            continue
        system = root.drive.casefold() == system_drive()
        ready = False
        label = ''
        capacity = free = None
        try:
            if kind in (2, 3):
                usage = shutil.disk_usage(root)
                capacity, free = usage.total, usage.free
                ready = True
                name = ctypes.create_unicode_buffer(261)
                if ctypes.windll.kernel32.GetVolumeInformationW(str(root), name, len(name), None, None, None, None, 0):
                    label = name.value
        except OSError:
            pass  # A removable reader can have a drive letter with no media.
        drives.append({'drive': root.drive, 'label': label, 'kind': kinds[kind], 'system': system,
                       'ready': ready, 'eligible': ready and not system, 'capacity': capacity, 'free': free})
    return drives


class DiskDevice(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('class_guid', ctypes.c_ubyte * 16),
                ('node', wintypes.DWORD), ('reserved', ctypes.c_size_t)]


def physical_disks():
    if os.name != 'nt':
        return []
    api = ctypes.windll.setupapi
    class_guid = (ctypes.c_ubyte * 16).from_buffer_copy(UUID('4d36e967-e325-11ce-bfc1-08002be10318').bytes_le)
    get_devices = api.SetupDiGetClassDevsW
    get_devices.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD)
    get_devices.restype = wintypes.HANDLE
    enum = api.SetupDiEnumDeviceInfo
    enum.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DiskDevice))
    prop = api.SetupDiGetDeviceRegistryPropertyW
    prop.argtypes = (wintypes.HANDLE, ctypes.POINTER(DiskDevice), wintypes.DWORD,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
    close = api.SetupDiDestroyDeviceInfoList
    close.argtypes = (wintypes.HANDLE,)
    handle = get_devices(class_guid, None, None, 2)  # DIGCF_PRESENT
    if handle in (None, ctypes.c_void_p(-1).value):
        return None
    names = []
    try:
        device = DiskDevice(size=ctypes.sizeof(DiskDevice))
        while enum(handle, len(names), ctypes.byref(device)):
            description = ctypes.create_unicode_buffer(512)
            for property_id in (12, 0):  # Friendly name, then device description.
                if prop(handle, ctypes.byref(device), property_id, None, description, ctypes.sizeof(description), None):
                    break
            names.append(description.value or 'Disk device')
    finally:
        close(handle)
    return names


def storage_folder(value, allow_system=False):
    folder = Path(value).expanduser()
    if not folder.is_absolute() or folder == folder.parent:
        raise ValueError('Choose a full path to a dedicated folder, such as E:\\SpareDriveData.')
    target = folder.resolve()
    root = Path(target.anchor)
    if target == root or not root.is_dir():
        raise ValueError('Connect the drive and choose a folder on it.')
    if os.name == 'nt' and not is_windows_data_drive(root, allow_system):
        raise ValueError('Choose a ready local drive. Enable the system-drive option to select the Windows drive.')
    return target


def joined_folder(drive, relative, allow_system=False):
    if os.name != 'nt' or not isinstance(drive, str) or not re.fullmatch(r'[A-Z]:', drive):
        raise ValueError('Choose a connected Windows data drive.')
    root = Path(f'{drive}\\')
    if not is_windows_data_drive(root, allow_system) or not root.is_dir() or root.resolve().drive.casefold() != drive.casefold():
        raise ValueError('Choose a ready local drive. Enable the system-drive option to browse the Windows drive.')
    if not isinstance(relative, str) or len(relative) > 4096:
        raise ValueError('Invalid folder path.')
    parts = relative.split('/') if relative else []
    current = root
    for part in parts:
        if not part or part.endswith(('.', ' ')) or PureWindowsPath(part).is_reserved() or PureWindowsPath(part).name != part or '\\' in part or ':' in part:
            raise ValueError('Invalid folder path.')
        if (current / '.family-drive-id').is_file():
            raise PermissionError('This folder contains protected SpareDrive data.')
        current /= part
        if current.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError('Linked folders are unavailable in the storage explorer.')
    if not current.is_dir() or not current.resolve().is_relative_to(root):
        raise ValueError('This folder is unavailable.')
    return current


def folder_contents(drive, relative, offset, allow_system=False):
    if not 0 <= offset <= 1_000_000:
        raise ValueError('Invalid folder page.')
    folder = joined_folder(drive, relative, allow_system)
    if (folder / '.family-drive-id').is_file():
        return {'entries': [], 'managed': True, 'more': False}
    with os.scandir(folder) as listing:
        entries = []
        for entry in listing:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            directory = stat.S_ISDIR(info.st_mode)
            entries.append({'name': entry.name, 'directory': directory,
                            'size': None if directory else info.st_size, 'modified': int(info.st_mtime)})
    entries.sort(key=lambda item: (not item['directory'], item['name'].casefold(), item['name']))
    return {'entries': entries[offset:offset + 100], 'managed': False, 'more': len(entries) > offset + 100}


def selected_folder(drive, relative, new_name, allow_system=False):
    parent = joined_folder(drive, relative, allow_system)
    if not isinstance(new_name, str) or len(new_name) > 100:
        raise ValueError('Enter a folder name of up to 100 characters.')
    if new_name:
        if (re.search(r'[<>:"/\\|?*\x00-\x1f]', new_name) or new_name.endswith(('.', ' '))
                or PureWindowsPath(new_name).is_reserved() or (parent / '.family-drive-id').is_file()):
            raise ValueError('Choose a valid name outside an existing SpareDrive folder.')
        target = parent / new_name
        if target.exists():
            prefix = f'{relative}/' if relative else ''
            target = joined_folder(drive, prefix + new_name, allow_system)
    else:
        target = parent
    target = storage_folder(target, allow_system)
    if target.exists() and not (target / '.family-drive-id').is_file() and next(target.iterdir(), None) is not None:
        raise ValueError('Select an empty folder or create a dedicated folder for SpareDrive.')
    return target


def folder_choice(values):
    new_name = values.get('newName', '')
    if isinstance(new_name, str):
        new_name = new_name.strip()
    return selected_folder(values.get('drive'), values.get('path', ''), new_name, values.get('allowSystem') is True)
