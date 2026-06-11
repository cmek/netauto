# TODO — EVPN framework hardening (remaining phases)

Roadmap context in [docs/evpn_service.md](docs/evpn_service.md). Phases 0–2
(typed exceptions, VNI/RT allocator + registry, declarative ensure/reconcile)
are **done and live-validated**. The two phases below remain.

Conventions for both phases: split device reads into testable pure
`_extract_*` functions with fixtures (as in `drivers/ocnos.py`); add offline
tests + a self-cleaning live test (`RUN_LIVE_TESTS=1`, ar1/ipi1); update
`docs/evpn_service.md` and the auto-memory when each lands.

---

## Phase 3 — Production safety rails

Make every push reversible and resistant to lock-out.

- **Config snapshot before change.** Capture `driver.get_config()` immediately
  before a create/delete (timestamped file or returned pre-image) for audit and
  rollback reference. Expose as an `EvpnManager` hook or a `snapshot_config(driver)`
  helper.
- **Commit-confirm / session-timer.** Arista `configure session ... timeout`,
  OcNOS confirmed-commit. Surface via `push_config(..., confirm_timeout=...)`.
  Auto-rolls back if a push cuts the management path (lock-out protection).
- **Cross-device rollback saga.** A helper that records applied steps and reverses
  them on failure, so a half-provisioned circuit (end A OK, end B failed) is cleaned
  up. Library helper + Prefect example pattern.

Files: `src/netauto/drivers/{arista,ocnos}.py` (`push_config`),
`src/netauto/evpn.py`, `examples/prefect_evpn.py`.

Verify: snapshot captured pre-change; commit-confirm path exercised live (Arista
session timeout, OcNOS confirmed-commit); rollback saga undoes a forced mid-way
failure.

---

## Phase 4 — Operational health checks ("is it forwarding")

Configured ≠ working. A read layer for control/data-plane state, distinct from
the configured-state read-back (`get_circuits`).

- **Driver operational reads** (new, testable `_extract_*` + fixtures): Arista
  `show bgp evpn` / `show vxlan address-table` / `show vxlan vtep` (eAPI JSON);
  OcNOS EVPN-MAC / VXLAN / BGP-EVPN state (NETCONF state subtree or netmiko).
- **`CircuitHealth` model + `EvpnManager.check_health(vni)`.** Per-circuit "is it
  live": access interface up, local EVI/VTEP up, remote VTEPs learned for the VNI,
  MACs learned. Start with route-presence + remote-VTEP-learned + interface-up;
  deepen later.
- **Surfacing.** `scripts/inspect_evpn.py --health`; a Prefect health-sweep flow.

Verify: health reads parsed from fixtures (offline) + live `check_health` on a
freshly-created circuit shows interface-up / EVI-up; teardown reflected.

---

## Other backlog (lower priority)

- Service coverage: other cloud providers (AWS/GCP/Oracle/Alibaba/Huawei — VPWS,
  same shape as `cloud_vc`), same-device **local switching** (no VXLAN), **MLAG**.
- Framework hygiene: driver context-managers + retries/timeouts; a
  **containerlab-based CI** integration harness (lab is containerlab).
- Declarative intent file: define a service in YAML → provision + validate (thin
  entrypoint over `ensure`).

## Open design choices (defaults; revisit when implementing)

- Registry backend: pluggable `VniRegistry` ABC + JSON-file default (swap a DB impl
  in production).
- `ensure` drift remediation: report-by-default, apply flag, **re-push to remediate**.
- Health depth (Phase 4): route-presence + remote-VTEP-learned + interface-up first.
