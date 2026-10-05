"""Duplicare un file o una cartella dal file manager riesce anche su Android.

``shutil.copy2`` e ``copytree`` finiscono con ``copystat``, che copia anche gli
attributi estesi: su Android ``security.selinux`` non si riscrive da un'app
(EACCES). Il file era gia' copiato, ma l'errore risaliva e il client riceveva
«permission denied» — con la copia lasciata sul disco. Qui ``copystat`` e'
sostituito da uno che solleva come sul telefono, dove sul Mac gli xattr non ci
sono e il difetto non si vedrebbe.
"""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from jafta.webui.workspace_files import copy_path


@pytest.fixture
def selinux_like_copystat(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(shutil, "copystat", refuse)


def test_a_file_is_copied_with_its_content_mode_and_time(
    tmp_path: Path, selinux_like_copystat: None
) -> None:
    src = tmp_path / "nota.md"
    src.write_text("ciao\n", encoding="utf-8")
    src.chmod(0o640)
    os.utime(src, (1_700_000_000, 1_700_000_000))

    dest = tmp_path / "nota (copy).md"
    copy_path(src, dest)

    assert dest.read_text(encoding="utf-8") == "ciao\n"
    assert dest.stat().st_mode & 0o777 == 0o640
    assert int(dest.stat().st_mtime) == 1_700_000_000


def test_a_folder_is_copied_whole_and_its_links_stay_links(
    tmp_path: Path, selinux_like_copystat: None
) -> None:
    src = tmp_path / "album"
    (src / "dentro").mkdir(parents=True)
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "dentro" / "b.txt").write_text("b", encoding="utf-8")
    (src / "link").symlink_to("a.txt")

    dest = tmp_path / "album (copy)"
    copy_path(src, dest)

    assert (dest / "a.txt").read_text(encoding="utf-8") == "a"
    assert (dest / "dentro" / "b.txt").read_text(encoding="utf-8") == "b"
    assert (dest / "link").is_symlink()
    assert os.readlink(dest / "link") == "a.txt"


def test_a_copy_still_never_lands_on_something_that_exists(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("nuovo", encoding="utf-8")
    dest = tmp_path / "b.txt"
    dest.write_text("vecchio", encoding="utf-8")

    with pytest.raises(FileExistsError):
        copy_path(src, dest)
    assert dest.read_text(encoding="utf-8") == "vecchio"
