"""The platform-specific paths, exercised from every platform.

None of this can be verified by running Tertius on a Mac or a Linux box - there
isn't one. What these tests can do is pin the *decisions*: that Linux looks in
`lib` and not just `bin`, that a Mac is told it is CPU-only rather than warned
about missing libraries, that nothing hard-codes a backslash path. CI runs them
on ubuntu, macos and windows, so each branch is at least executed on its own
platform rather than only mocked from Windows.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from tertius import folder_picker, launcher, system, transcribe


# ---------------------------------------------------------------- library dirs

def _fake_nvidia_package(monkeypatch, root: Path, subdirs: list[str]):
    """Stand in for an installed `nvidia` package laid out however we like."""
    for sub in subdirs:
        (root / sub).mkdir(parents=True, exist_ok=True)
    module = types.ModuleType("nvidia")
    module.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, "nvidia", module)


def test_finds_linux_style_lib_directories(monkeypatch, tmp_path):
    """The Linux wheels use `lib`, not `bin` - the original glob missed them."""
    _fake_nvidia_package(monkeypatch, tmp_path, ["cublas/lib", "cudnn/lib"])

    found = {p.name for p in transcribe.nvidia_library_dirs()}

    assert found == {"lib"}
    assert len(transcribe.nvidia_library_dirs()) == 2


def test_finds_windows_style_bin_directories(monkeypatch, tmp_path):
    _fake_nvidia_package(monkeypatch, tmp_path, ["cublas/bin", "cudnn/bin"])

    assert {p.name for p in transcribe.nvidia_library_dirs()} == {"bin"}


def test_finds_both_layouts_at_once(monkeypatch, tmp_path):
    """A machine could have either; neither is assumed from the platform."""
    _fake_nvidia_package(monkeypatch, tmp_path, ["cublas/bin", "cudnn/lib"])

    assert len(transcribe.nvidia_library_dirs()) == 2


def test_an_nvidia_package_with_neither_layout_yields_nothing(monkeypatch, tmp_path):
    """A CPU-only machine: the package may exist without any library folder."""
    _fake_nvidia_package(monkeypatch, tmp_path, ["cublas/include"])

    assert transcribe.nvidia_library_dirs() == []


# ------------------------------------------------------------------ preloading

def test_linux_preloads_shared_objects_with_cublas_first(monkeypatch, tmp_path):
    """cuDNN resolves against cuBLAS, so cuBLAS has to be loaded first."""
    for name in ("cudnn/lib/libcudnn.so.9", "cublas/lib/libcublas.so.12"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    _fake_nvidia_package(monkeypatch, tmp_path, [])

    loaded: list[str] = []

    class FakeCDLL:
        def __init__(self, path, mode=0):
            loaded.append(Path(path).name)

    monkeypatch.setattr(transcribe.ctypes, "CDLL", FakeCDLL)
    monkeypatch.setattr(transcribe.sys, "platform", "linux")

    transcribe.register_cuda_dll_directories()

    assert loaded == ["libcublas.so.12", "libcudnn.so.9"]


def test_a_library_that_will_not_load_is_skipped_not_fatal(monkeypatch, tmp_path):
    path = tmp_path / "cublas/lib/libcublas.so.12"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    _fake_nvidia_package(monkeypatch, tmp_path, [])

    def explode(*args, **kwargs):
        raise OSError("wrong architecture")

    monkeypatch.setattr(transcribe.ctypes, "CDLL", explode)
    monkeypatch.setattr(transcribe.sys, "platform", "linux")

    assert transcribe.register_cuda_dll_directories() == []


def test_macos_registers_nothing(monkeypatch, tmp_path):
    """There is no CUDA on Apple hardware, so there is nothing to wire up."""
    _fake_nvidia_package(monkeypatch, tmp_path, ["cublas/lib"])
    monkeypatch.setattr(transcribe.sys, "platform", "darwin")

    assert transcribe.register_cuda_dll_directories() == []


# --------------------------------------------------------------- runtime status

def test_macos_is_reported_as_cpu_only_not_as_a_missing_runtime(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "darwin")

    status = system.cuda_runtime_status(cuda_devices=0)

    assert status["state"] == "cpu_only"
    # The distinction that matters: nothing here should read as a fix-it.
    assert "install" not in status["detail"].lower()


def test_macos_stays_cpu_only_even_if_a_device_is_somehow_reported(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "darwin")

    assert system.cuda_runtime_status(cuda_devices=1)["state"] == "cpu_only"


def test_linux_checks_for_a_system_cublas_before_declaring_it_missing(monkeypatch):
    """The old code only did this on Windows, so Linux reported a false miss."""
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(transcribe, "nvidia_library_dirs", lambda: [])
    monkeypatch.setattr(transcribe, "register_cuda_dll_directories", lambda: [])

    tried: list[str] = []

    def fake_cdll(name):
        tried.append(name)
        if name == "libcublas.so.12":
            return object()
        raise OSError("not found")

    monkeypatch.setattr(system.ctypes, "CDLL", fake_cdll)

    status = system.cuda_runtime_status(cuda_devices=1)

    assert status["state"] == "ok"
    assert tried == ["libcublas.so.12"]


def test_linux_with_no_cublas_anywhere_is_missing_and_says_how_to_fix_it(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(transcribe, "nvidia_library_dirs", lambda: [])
    monkeypatch.setattr(transcribe, "register_cuda_dll_directories", lambda: [])
    monkeypatch.setattr(
        system.ctypes, "CDLL", lambda name: (_ for _ in ()).throw(OSError("nope"))
    )

    status = system.cuda_runtime_status(cuda_devices=1)

    assert status["state"] == "missing"
    # The fix has to be runnable on the machine that is being told about it.
    assert "\\" not in status["fix_command"]
    assert "/" in status["fix_command"]


def test_the_windows_fix_command_uses_a_windows_path(monkeypatch):
    monkeypatch.setattr(transcribe.sys, "platform", "win32")

    assert transcribe._venv_pip() == "app\\.venv\\Scripts\\pip"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_posix_fix_command_uses_a_posix_path(monkeypatch, platform):
    monkeypatch.setattr(transcribe.sys, "platform", platform)

    assert transcribe._venv_pip() == "app/.venv/bin/pip"


# ---------------------------------------------------------------- picker errors

@pytest.mark.parametrize(
    "code, expected",
    [
        (folder_picker.EXIT_NO_TKINTER, "python3-tk"),
        (folder_picker.EXIT_NO_DISPLAY, "headless"),
    ],
)
def test_picker_failures_name_the_cause(code, expected):
    from tertius.app import _picker_failure

    assert expected in _picker_failure(code)


def test_an_unrecognised_picker_failure_still_says_something_useful():
    from tertius.app import _picker_failure

    assert "paste" in _picker_failure(99)


def test_missing_tkinter_reports_its_own_exit_code(monkeypatch):
    def no_tkinter(*args, **kwargs):
        raise ImportError("No module named 'tkinter'")

    monkeypatch.setattr(folder_picker, "pick_folder", no_tkinter)

    assert folder_picker.main([]) == folder_picker.EXIT_NO_TKINTER


def test_no_display_reports_its_own_exit_code(monkeypatch):
    def no_display(*args, **kwargs):
        raise RuntimeError('no display name and no $DISPLAY environment variable')

    monkeypatch.setattr(folder_picker, "pick_folder", no_display)

    assert folder_picker.main([]) == folder_picker.EXIT_NO_DISPLAY


def test_an_unexpected_picker_error_is_not_swallowed(monkeypatch):
    """Silently returning "cancelled" for a real bug would hide it."""
    def explode(*args, **kwargs):
        raise RuntimeError("something else entirely")

    monkeypatch.setattr(folder_picker, "pick_folder", explode)

    with pytest.raises(RuntimeError):
        folder_picker.main([])


# -------------------------------------------------------------------- launcher

def test_venv_python_uses_the_right_layout_per_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    assert launcher.venv_python(tmp_path).parent.name == "Scripts"

    monkeypatch.setattr(launcher.sys, "platform", "linux")
    assert launcher.venv_python(tmp_path).parent.name == "bin"


def test_the_launcher_finds_the_project_folders():
    """app_dir is `app/`, project_dir is the folder holding the launchers."""
    assert launcher.app_dir().name == "app"
    assert (launcher.app_dir() / "src" / "tertius").is_dir()
    assert launcher.project_dir() == launcher.app_dir().parent


def test_a_busy_server_is_left_alone(monkeypatch):
    """Never interrupt a running batch - the whole point of the check."""
    monkeypatch.setattr(launcher, "probe", lambda url, timeout=3.0: {"running": True})
    stopped = []
    monkeypatch.setattr(
        launcher, "stop_existing", lambda url, say=print: stopped.append(url)
    )

    assert launcher.handle_existing("http://x/", say=lambda *a: None) == "reuse"
    assert stopped == []


def test_an_idle_server_is_replaced_so_the_new_code_is_served(monkeypatch):
    monkeypatch.setattr(launcher, "probe", lambda url, timeout=3.0: {"running": False})
    monkeypatch.setattr(launcher, "stop_existing", lambda url, say=print: True)

    assert launcher.handle_existing("http://x/", say=lambda *a: None) == "launch"


def test_a_server_that_will_not_stop_blocks_the_launch(monkeypatch):
    monkeypatch.setattr(launcher, "probe", lambda url, timeout=3.0: {"running": False})
    monkeypatch.setattr(launcher, "stop_existing", lambda url, say=print: False)

    assert launcher.handle_existing("http://x/", say=lambda *a: None) == "blocked"


def test_an_empty_port_just_launches(monkeypatch):
    monkeypatch.setattr(launcher, "probe", lambda url, timeout=3.0: None)

    assert launcher.handle_existing("http://x/", say=lambda *a: None) == "launch"


def test_desktop_integration_is_skipped_off_its_own_platform(monkeypatch):
    """Each of these must be a no-op elsewhere, never an error."""
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    assert launcher.refresh_windows_shortcut(say=lambda *a: None) is None
    assert launcher.apply_windows_folder_icon(say=lambda *a: None) is False

    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    assert launcher.refresh_linux_desktop_entry(say=lambda *a: None) is None
    assert launcher.refresh_windows_shortcut(say=lambda *a: None) is None


# --------------------------------------------------------- case-insensitive text

@pytest.mark.parametrize(
    "text_name",
    ["VolA01.txt", "vola01.txt", "VolA01.TXT", "vola01.TXT", "VolA01.Txt"],
)
def test_text_pairing_ignores_case_in_the_extension_too(tmp_path, text_name):
    """Found by CI on Linux, invisible on Windows.

    The stem was compared case-insensitively but the candidates were gathered
    with a `*.txt` glob - and glob is case-insensitive on Windows and
    case-sensitive everywhere else. So `talk.TXT` beside `talk.mp3` paired fine
    on Windows and silently did not on Linux or macOS.
    """
    from tertius.state import StateStore

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio = audio_dir / "VolA01.mp3"
    audio.write_bytes(b"\x00")
    (audio_dir / text_name).write_text("some words", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")

    assert store.find_reference_text(audio) is not None


def test_text_pairing_still_refuses_a_near_miss_whatever_the_case(tmp_path):
    """Case-insensitivity must not turn into matching the wrong file."""
    from tertius.state import StateStore

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio = audio_dir / "VolA01.mp3"
    audio.write_bytes(b"\x00")
    (audio_dir / "VOLA02.TXT").write_text("the next talk", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")

    assert store.find_reference_text(audio) is None


def test_a_non_text_file_with_a_matching_name_is_not_picked_up(tmp_path):
    """Widening the glob to "*" must not widen what counts as a text file."""
    from tertius.state import StateStore

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio = audio_dir / "VolA01.mp3"
    audio.write_bytes(b"\x00")
    (audio_dir / "VolA01.pdf").write_bytes(b"%PDF")
    (audio_dir / "VolA01.txtx").write_text("not a transcript", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")

    assert store.find_reference_text(audio) is None


# -------------------------------------------------------------- upload cleanup

def _upload(store, name: str, queued_as: str | None = None) -> Path:
    """Put a file in the store's _uploads folder, optionally queueing it."""
    from tertius.config import UPLOAD_DIRNAME

    uploads = store.path.parent / UPLOAD_DIRNAME
    uploads.mkdir(parents=True, exist_ok=True)
    path = uploads / name
    path.write_bytes(b"\x00" * 1024)
    if queued_as:
        store.add_files([path])
        store._update(path, status=queued_as)
    return path


def test_finished_uploads_are_cleared_at_startup(tmp_path):
    """The transcript is what is worth keeping; the copy is dead weight."""
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")
    done = _upload(store, "finished.mp3", queued_as="done")
    orphan = _upload(store, "never-queued.mp3")

    removed, reclaimed = store.purge_uploads()

    assert not done.exists()
    assert not orphan.exists()
    assert removed == 2
    assert reclaimed == 2048


def test_an_interrupted_batch_keeps_the_files_it_still_needs(tmp_path):
    """Clearing these would silently break resume - the one hard-tested feature."""
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")
    pending = _upload(store, "still-queued.mp3", queued_as="pending")
    running = _upload(store, "mid-flight.mp3", queued_as="in_progress")
    done = _upload(store, "finished.mp3", queued_as="done")

    removed, _ = store.purge_uploads()

    assert pending.exists()
    assert running.exists()
    assert not done.exists()
    assert removed == 1


def test_failed_uploads_are_cleared_too(tmp_path):
    """A failed file is not resumable work - retry re-queues it as pending."""
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")
    failed = _upload(store, "broken.mp3", queued_as="failed")

    store.purge_uploads()

    assert not failed.exists()


def test_purging_leaves_the_uploads_folder_itself_alone(tmp_path):
    """The server expects the folder to exist; only its contents go."""
    from tertius.config import UPLOAD_DIRNAME
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")
    _upload(store, "gone.mp3")

    store.purge_uploads()

    assert (store.path.parent / UPLOAD_DIRNAME).is_dir()


def test_purging_with_no_uploads_folder_is_harmless(tmp_path):
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")

    assert store.purge_uploads() == (0, 0)


def test_paired_text_files_are_cleared_with_their_audio(tmp_path):
    """Uploaded .txt partners land in _uploads too and are just as disposable."""
    from tertius.state import StateStore

    store = StateStore.for_output_dir(tmp_path / "out")
    audio = _upload(store, "talk.mp3", queued_as="done")
    text = _upload(store, "talk.txt")

    store.purge_uploads()

    assert not audio.exists()
    assert not text.exists()


# ------------------------------------------------------------------ shipped files

def test_the_shell_launchers_are_committed_with_unix_line_endings():
    """A CRLF shebang makes the kernel look for an interpreter called "/bin/sh\\r".

    This is the failure that would have made both the macOS and Linux launchers
    unusable, with an error naming a file that plainly exists.
    """
    project = launcher.project_dir()
    for name in ("start-tertius.sh", "Tertius.app/Contents/MacOS/Tertius"):
        path = project / name
        assert path.is_file(), f"{name} is missing"
        assert b"\r\n" not in path.read_bytes(), f"{name} has CRLF line endings"


def test_every_icon_the_launchers_reference_exists():
    assets = launcher.app_dir() / "assets"
    for name in ("tertius.ico", "tertius.icns", "tertius-512.png", "tertius.svg"):
        assert (assets / name).is_file(), f"{name} is missing"


def test_the_mac_bundle_is_shaped_the_way_finder_expects():
    bundle = launcher.project_dir() / "Tertius.app"
    assert (bundle / "Contents" / "Info.plist").is_file()
    assert (bundle / "Contents" / "MacOS" / "Tertius").is_file()
    # CFBundleIconFile says "tertius", so this exact name is what Finder loads.
    assert (bundle / "Contents" / "Resources" / "tertius.icns").is_file()


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit")
def test_the_unix_launchers_are_executable():
    project = launcher.project_dir()
    for name in ("start-tertius.sh", "Tertius.app/Contents/MacOS/Tertius"):
        assert os.access(project / name, os.X_OK), f"{name} is not executable"
