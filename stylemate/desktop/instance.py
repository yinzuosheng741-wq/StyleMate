"""Prevent concurrent clients from editing the same portable directory."""
from PySide6.QtCore import QLockFile


def acquire_instance_lock(root):
    directory = root / "data/desktop"
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "instance.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(0):
        return lock
    if lock.error() == QLockFile.LockError.LockFailedError:
        return None
    raise OSError("客户端数据目录不可写，请移动到可写目录后重试。")
