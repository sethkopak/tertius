"""Machine capability detection and per-model suitability advice."""

from __future__ import annotations

import pytest
from tertius.config import MODEL_SIZES
from tertius.system import (
    GB,
    MODEL_CATALOG,
    assess_model,
    check_compute_type,
    describe_system,
    effective_device,
    total_ram_bytes,
)


def machine(ram_gb=None, vram_gb=None, cuda=0, compute_types=None):
    return {
        "ram_bytes": int(ram_gb * GB) if ram_gb else None,
        "vram_bytes": int(vram_gb * GB) if vram_gb else None,
        "cuda_devices": cuda,
        "compute_types": compute_types or {},
    }


def test_every_offered_model_is_in_the_catalog():
    """The dropdown must not offer a model the comparison table can't describe."""
    assert set(MODEL_SIZES) <= set(MODEL_CATALOG)


def test_catalog_sizes_are_plausible_and_ordered():
    order = ["tiny", "base", "small", "medium", "large-v3"]
    sizes = [MODEL_CATALOG[m]["download_bytes"] for m in order]
    assert sizes == sorted(sizes)
    # turbo is smaller than large-v3 but far bigger than small
    assert (
        MODEL_CATALOG["small"]["download_bytes"]
        < MODEL_CATALOG["large-v3-turbo"]["download_bytes"]
        < MODEL_CATALOG["large-v3"]["download_bytes"]
    )


def test_aliases_are_not_offered_as_separate_choices():
    """One model, one row. `turbo` and `large-v3-turbo` are the same weights."""
    assert "turbo" not in MODEL_SIZES
    assert "turbo" not in MODEL_CATALOG
    assert "large" not in MODEL_SIZES


@pytest.mark.parametrize(
    "device,cuda,expected",
    [("auto", 1, "cuda"), ("auto", 0, "cpu"), ("cpu", 1, "cpu"), ("cuda", 0, "cuda")],
)
def test_effective_device(device, cuda, expected):
    assert effective_device(device, cuda) == expected


def test_big_model_on_a_small_machine_is_flagged():
    """3 GB of weights on a 4 GB machine does not "just fit" - the OS needs RAM."""
    verdict = assess_model("large-v3", "cpu", machine(ram_gb=4))
    assert verdict["verdict"] == "risky"
    assert "4.0 GB" in verdict["reason"] and "GB of RAM" in verdict["reason"]


def test_a_6gb_gpu_running_large_v3_is_tight_not_impossible():
    verdict = assess_model("large-v3", "cuda", machine(ram_gb=32, vram_gb=6, cuda=1))
    assert verdict["verdict"] == "tight"


def test_8gb_machine_can_still_use_turbo():
    verdict = assess_model("large-v3-turbo", "cpu", machine(ram_gb=8))
    assert verdict["verdict"] == "ok"


def test_small_model_on_a_big_machine_is_fine():
    verdict = assess_model("small", "cpu", machine(ram_gb=32))
    assert verdict["verdict"] == "ok"
    assert verdict["reason"] == ""


def test_gpu_verdict_uses_vram_not_ram():
    """A machine with plenty of RAM but a small GPU must still be warned."""
    tiny_gpu = machine(ram_gb=64, vram_gb=2, cuda=1)
    verdict = assess_model("large-v3", "cuda", tiny_gpu)
    assert verdict["runs_on"] == "cuda"
    assert verdict["verdict"] == "risky"
    assert "VRAM" in verdict["reason"]


def test_turbo_fits_a_6gb_gpu():
    verdict = assess_model("large-v3-turbo", "auto", machine(ram_gb=32, vram_gb=6, cuda=1))
    assert verdict["verdict"] == "ok"


def test_large_models_on_cpu_are_called_slow():
    verdict = assess_model("large-v3", "cpu", machine(ram_gb=64))
    assert verdict["verdict"] == "tight"
    assert "slow without a GPU" in verdict["reason"]


def test_unknown_memory_is_reported_honestly():
    verdict = assess_model("small", "cpu", machine())
    assert verdict["verdict"] == "unknown"
    assert "Could not read" in verdict["reason"]


def test_verdict_carries_catalog_details():
    verdict = assess_model("tiny", "cpu", machine(ram_gb=16), cached=True)
    assert verdict["download_bytes"] == MODEL_CATALOG["tiny"]["download_bytes"]
    assert verdict["speed"] == "Fastest"
    assert verdict["cached"] is True


def test_compute_type_unsupported_on_device_is_flagged():
    cpu_only = machine(ram_gb=16, compute_types={"cpu": ["float32", "int8"]})
    assert "float16" in check_compute_type("float16", "cpu", cpu_only)
    assert check_compute_type("int8", "cpu", cpu_only) is None
    assert check_compute_type("default", "cpu", cpu_only) is None


def test_compute_type_check_is_quiet_when_capabilities_are_unknown():
    assert check_compute_type("float16", "cpu", machine(ram_gb=8)) is None


def test_describe_system_reports_this_machine():
    info = describe_system()
    assert info["cpu_count"] and info["cpu_count"] > 0
    assert isinstance(info["cuda_devices"], int)
    assert info["platform"]
    if info["ram_bytes"] is not None:
        assert info["ram_bytes"] > GB  # nobody runs this on under 1 GB


def test_total_ram_is_readable_here():
    ram = total_ram_bytes()
    assert ram is None or ram > GB
