"""Golden-file guard for the EVPN validation matrix.

The committed ``validation_output/`` tree is what the network engineering team
reviews and signs off on. This test re-renders the same matrix in memory and
asserts it still matches the committed files, so any future render change that
drifts from the approved output fails CI.

To intentionally update the goldens (after a reviewed change):
    python scripts/generate_evpn_validation.py
and commit the resulting validation_output/ diff.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_evpn_validation.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_evpn_validation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load_generator()
ARTIFACTS = gen.generate_all()
OUTPUT_DIR = gen.output_dir()


def test_matrix_covers_all_scenarios():
    assert len(gen.SCENARIOS) == 7  # p2p_vc (3) + cloud_vc (4)
    assert len(gen.AZURE_SCENARIOS) == 5  # Azure standard (3) + rewrite (2)
    assert "SUMMARY.md" in ARTIFACTS
    # every scenario contributes a README and 4 endpoint files
    for scenario in gen.SCENARIOS + gen.AZURE_SCENARIOS:
        assert f"{scenario['name']}/README.md" in ARTIFACTS


@pytest.mark.parametrize("rel_path", sorted(ARTIFACTS.keys()))
def test_generated_matches_committed_golden(rel_path):
    committed = OUTPUT_DIR / rel_path
    assert committed.exists(), (
        f"Missing golden {rel_path}; run scripts/generate_evpn_validation.py"
    )
    assert committed.read_text() == ARTIFACTS[rel_path], (
        f"{rel_path} drifted from the generator; re-run "
        "scripts/generate_evpn_validation.py and review the diff."
    )


def test_no_stale_golden_files():
    """Committed validation_output files must all still be produced by the generator."""
    on_disk = {
        str(p.relative_to(OUTPUT_DIR))
        for p in OUTPUT_DIR.rglob("*")
        if p.is_file()
    }
    assert on_disk == set(ARTIFACTS.keys())
