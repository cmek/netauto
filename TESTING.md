# netauto — Testing

## Running

```bash
uv run pytest                 # offline suite (no devices needed)
uv run pytest -q tests/test_evpn_manager.py        # one file
RUN_LIVE_TESTS=1 uv run pytest tests/test_live_devices.py   # live (needs the lab + VPN)
```

Offline tests use `MockDriver` and committed fixtures — no network. Live tests
are skipped unless `RUN_LIVE_TESTS=1`. The offline suite is green.

## Offline tests (`tests/`)

| File | What it covers |
|------|----------------|
| `test_lag_manager.py` | `LagManager` create/add/remove/delete; VLAN migration; dry-run; validation errors. |
| `test_render_arista.py` | Arista Jinja renderers (LAG, interface, VLAN, EVPN, Azure Q-in-Q, VRF) — exact CLI output. |
| `test_render_ocnos.py` | OcNOS ElementTree → NETCONF renderers (same surface) — exact XML output. |
| `test_evpn_manager.py` | `EvpnManager` create/delete circuit + Azure; VNI-in-use / interface guards; **typed exceptions**; `AzureEvpn` model validators; dry-run. |
| `test_evpn_readback.py` | Read-back: Arista running-config → `EvpnCircuit`; OcNOS **render→parse round-trip**; `verify_circuit` drift detection (plain + Azure). |
| `test_ensure_reconcile.py` | Declarative `ensure_circuit` idempotency (created/unchanged/updated) + pure `plan_reconcile` (to_create/update/delete/in_sync). |
| `test_allocation.py` | `JsonFileRegistry` allocate/release/uniqueness/idempotency/persistence + RT collision; `find_conflicts`; `make_routing_instance`. |
| `test_evpn_validation_matrix.py` | Golden-file guard: regenerates the validation matrix and asserts it matches `validation_output/`. |
| `test_drivers.py` | `MockDriver` behaviour; OcNOS `_extract_interfaces` / `_extract_vnis` from XML fixtures (regression guard for the lxml `get_vnis` bug). |
| `test_models.py` | Pydantic model validation (Vlan / Interface / Lag / Vrf). |

Fixtures: `tests/ocnos_interfaces.xml`, `tests/ocnos_vxlan.xml`,
`validation_output/` (generated golden configs).

## Live tests (`tests/test_live_devices.py`)

Run against the lab (`lab_devices.md`): Arista ar1 `172.20.30.4`, OcNOS ipi1
`172.20.30.6`. **Self-cleaning** — each test creates then deletes, restoring the
port. Enable with `RUN_LIVE_TESTS=1`. Overridable via env
(`ARISTA_HOST`, `OCNOS_HOST`, `ARISTA_ASN`, `*_EVPN_PORT`, …).

| Class | Tests |
|-------|-------|
| `TestLiveDevices` | Arista/OcNOS connect; `get_vnis()` returns a list (lxml regression). |
| `TestLiveEvpn` | cloud_vc circuit create→verify-in-running-config→delete, both vendors. |
| `TestLiveAzure` | Azure CNI rewrite (Arista + OcNOS) and OcNOS customer multi-C-TAG. Arista customer Q-in-Q is **skipped** — cEOSLab has no `dot1q-tunnel` hardware support. |
| `TestLiveReadBack` | create → `get_circuits()`/`verify_circuit` match → delete → gone; `ensure_circuit` idempotent (created → unchanged). |
| `TestLiveLag` | single-switch LAG create→verify→delete, both vendors (`migrate_vlans=False`). |

## Manual scripts (`scripts/`)

Not part of the pytest suite — run by hand.

| Script | Purpose |
|--------|---------|
| `inspect_evpn.py <host> <arista\|ocnos>` / `--all` | Dump the EVPN circuits read back from a device / the whole lab fabric. |
| `live_evpn_test.py {arista\|ocnos\|arista-azure\|ocnos-azure}` | Self-cleaning live create→verify→delete with verbose diffs (incl. Azure). |
| `generate_evpn_validation.py` | Regenerate `validation_output/` (the reviewable config matrix; golden source for `test_evpn_validation_matrix.py`). |
| `evpn.py` | End-to-end demo: provision a circuit on Arista + OcNOS, parse it back, delete. |
| `parse_arista_configs.py` / `parse_ocns_configs.py` | Parse a saved Arista JSON / OcNOS XML config into models (parser demo). |

## Validation matrix (`validation_output/`)

Generated, reviewable example configs for every supported scenario (p2p_vc,
cloud_vc, Azure × vendors) with create+delete per endpoint and a `SUMMARY.md`.
Built by `scripts/generate_evpn_validation.py`; guarded by
`test_evpn_validation_matrix.py`. To change rendered output: re-run the generator
and commit the diff (it is the engineer-reviewed golden).

## Adding tests

- Render changes → assert exact output in `test_render_*` and refresh the matrix.
- New read paths → split parsing into a pure `_extract_*` and test it with an XML
  fixture (see `test_drivers.py`).
- Device-facing behaviour → a self-cleaning case in `test_live_devices.py`
  (try/finally delete), gated on `RUN_LIVE_TESTS`.
