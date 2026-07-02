"""`caduceus doctor` environment checks (U8) with docker calls monkeypatched."""

from __future__ import annotations

from caduceus.config import doctor as doc


def _patch(monkeypatch, *, which="/usr/bin/docker", version_rc=0, version_out="27.0",
           image_rc=0, runtimes=None):
    runtimes = runtimes if runtimes is not None else {"runc"}
    monkeypatch.setattr(doc.shutil, "which", lambda _n: which)

    def fake_docker(*args, timeout=15.0):
        if args[:2] == ("version", "--format"):
            return version_rc, version_out
        if args[:2] == ("image", "inspect"):
            return image_rc, ""
        return 0, ""
    monkeypatch.setattr(doc, "_docker", fake_docker)
    monkeypatch.setattr(doc, "_docker_runtimes", lambda: set(runtimes))


def test_docker_missing(monkeypatch):
    monkeypatch.setattr(doc.shutil, "which", lambda _n: None)
    report = doc.run_doctor()
    assert not report.ok
    assert report.checks[0].name == "docker" and not report.checks[0].ok


def test_server_unreachable(monkeypatch):
    _patch(monkeypatch, version_rc=1, version_out="")
    report = doc.run_doctor()
    assert not report.ok


def test_runc_default_ok(monkeypatch):
    _patch(monkeypatch, image_rc=0, runtimes={"runc"})
    report = doc.run_doctor(container_runtime="runc", daemon_up=True)
    assert report.ok
    names = {c.name for c in report.checks}
    assert "container runtime" in names


def test_runsc_configured_but_unavailable(monkeypatch):
    _patch(monkeypatch, runtimes={"runc"})  # no runsc
    report = doc.run_doctor(container_runtime="runsc")
    assert not report.ok  # required runtime check fails
    rt = next(c for c in report.checks if c.name.startswith("container runtime"))
    assert not rt.ok and "gVisor" in rt.hint


def test_runsc_available(monkeypatch):
    _patch(monkeypatch, runtimes={"runc", "runsc"})
    report = doc.run_doctor(container_runtime="runsc")
    assert report.ok
    gv = next(c for c in report.checks if c.name.startswith("gVisor"))
    assert gv.ok


def test_image_not_built_is_nonfatal(monkeypatch):
    _patch(monkeypatch, image_rc=1, runtimes={"runc"})
    report = doc.run_doctor(container_runtime="runc")
    assert report.ok  # image check is non-required
    img = next(c for c in report.checks if c.name == "hermes image")
    assert not img.ok and not img.required


def test_default_image_tag_is_the_pinned_hermes_image(monkeypatch):
    # R2: doctor must inspect the image agents actually use (was a stale pre-U8 tag).
    from caduceus.agents.images import DEFAULT_TAG

    inspected = []

    def fake_docker(*args, timeout=15.0):
        if args[:2] == ("image", "inspect"):
            inspected.append(args[2])
            return 0, ""
        if args[0] == "version":
            return 0, "29.0"
        if args[0] == "info":
            return 0, '{"runc": {}}'
        return 0, ""

    monkeypatch.setattr(doc, "_docker", fake_docker)
    monkeypatch.setattr(doc.shutil, "which", lambda _: "/usr/bin/docker")
    doc.run_doctor()
    assert inspected == [DEFAULT_TAG]
