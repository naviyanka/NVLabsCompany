"""Confine server-side filesystem paths to per-tenant roots.

A path a caller supplies (or one stored on a row a caller could once write) is
only trusted once it resolves inside one of the configured roots.
``resolve()`` collapses ``..`` and follows symlinks and Windows junctions
before the containment check, so neither can escape a root.

A check made on a path is only good until the path changes. Code that goes on
to create files under a checked path uses ``pinned_directory`` to keep that
path from being swapped for a link while it works.
"""

import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Set in the reparse tag of symlinks, junctions and every other reparse point
# that redirects a path to another name. Placeholders such as OneDrive's
# cloud files do not set it.
_NAME_SURROGATE = 0x20000000


def resolve_in_roots(raw: str, roots: str, company_id: uuid.UUID) -> Path | None:
    """Resolve ``raw`` and return it if it lies inside one of ``roots``, else None.

    Args:
        raw: The path to check.
        roots: Comma-separated root directories; ``{company_id}`` is substituted
            with the tenant's id, so one tenant's root never contains another's.
        company_id: The tenant the path must belong to.
    """
    path = Path(raw).expanduser().resolve()
    for root in roots.split(","):
        root = root.strip()
        if not root:
            continue
        root_path = Path(root.replace("{company_id}", str(company_id))).expanduser().resolve()
        if path.is_relative_to(root_path):
            return path
    return None


def is_link(path: Path) -> bool:
    """True if ``path`` itself is a symlink, a junction or another redirecting reparse point."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_reparse_tag", 0) & _NAME_SURROGATE)


@contextmanager
def pinned_directory(path: Path) -> Iterator[None]:
    """Hold ``path`` open while the block runs; raise ``OSError`` if it is or becomes a link.

    On Windows the directory is opened without delete sharing, so while the
    block runs neither it nor any directory above it can be renamed, removed
    or replaced by a junction or symlink, and a path checked inside the block
    stays what it was checked to be. Elsewhere nothing blocks a swap: the
    directory is compared with the one opened when the block ends, so a swap
    is reported, not prevented. Links set up above the configured roots by
    whoever deploys the server are trusted either way.
    """
    if os.name == "nt":
        handle = _open_windows_directory(path)
        try:
            if is_link(path):
                raise OSError(f"{path} is a link")
            yield
        finally:
            _close_windows_handle(handle)
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield
        if not os.path.samestat(os.fstat(fd), os.lstat(path)):
            raise OSError(f"{path} was replaced while in use")
    finally:
        os.close(fd)


def _open_windows_directory(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    handle = create(
        str(path),
        0x0001,  # FILE_LIST_DIRECTORY: sharing is only checked for opens that read or write
        0x0001 | 0x0002,  # FILE_SHARE_READ | FILE_SHARE_WRITE, not FILE_SHARE_DELETE
        None,
        3,  # OPEN_EXISTING
        # FILE_FLAG_BACKUP_SEMANTICS opens a directory; FILE_FLAG_OPEN_REPARSE_POINT
        # opens a link itself instead of its target, so is_link sees it.
        0x02000000 | 0x00200000,
        None,
    )
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _close_windows_handle(handle: int) -> None:
    import ctypes

    ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))
