# EVPN circuit validation matrix

Example configuration for every supported EVPN circuit scenario, for
review by network engineering before these building blocks are trusted
against production gear. Generated offline by
`scripts/generate_evpn_validation.py` (via MockDriver — no devices).

Scope: **global transport** (EVPN/VXLAN across different devices) for
`cloud_vc` (customer ↔ CNI), `p2p_vc` (member ↔ member), and **Azure**
ExpressRoute Q-in-Q (S-TAG + 1-3 C-TAGs, incl. S-TAG rewrite). Same-device
local switching is out of scope.

## Lab environment

The lab devices already carry the EVPN **underlay** (BGP, a VXLAN VTEP
source, and the L2VPN-EVPN address-family). These building blocks add
only the per-service circuit on top — they do not configure the underlay.

| Device | Mgmt IP | Platform | Role | Notes |
|--------|---------|----------|------|-------|
| ar1 | 172.20.30.4 | Arista cEOS | leaf | BGP ASN 65001 · **live-validated** |
| ar2 | 172.20.30.5 | Arista cEOS | leaf | BGP ASN 65002 |
| ipi1 | 172.20.30.6 | IP Infusion OcNOS-SP | leaf | VTEP 10.0.0.6 · **live-validated** |
| ipi2 | 172.20.30.7 | IP Infusion OcNOS-SP | leaf | |
| spine1 / spine2 | 172.20.30.2 / .3 | Arista cEOS | spine | EVPN route reflectors |

A full create → verify → delete cycle was run live on ar1 and ipi1 (see `tests/test_live_devices.py::TestLiveEvpn`).

## How a circuit is built

`EvpnManager` is a **per-device building block**: one call configures one
endpoint interface on one device. The orchestrator (Prefect) calls it once
per end of the circuit. `create_circuit` pushes two transactions:

1. **Service VRF** — the `mac-vrf` / `vlan-aware-bundle` with RD + route-target.
2. **Circuit** — the access sub-interface / switchport, the VLAN↔VNI VXLAN
   mapping, and the EVPN access binding.

`delete_circuit` reverses both. Arista output is EOS CLI; OcNOS output is
a NETCONF `edit-config` payload. The **VNI** is allocated externally and
used verbatim for the VXLAN id / vpn-id and the bundle name — never derived
from the VLAN. cloud_vc and p2p_vc render identically given the same
vni/vlan; the route-target prefix is `37195` and is shared across
both endpoints of a circuit.

## Scenarios

Each scenario is a complete circuit (both endpoints). Click a scenario for
its README, or jump straight to a config below.

| Scenario | Service | Endpoints | VLAN | VNI |
|----------|---------|-----------|------|-----|
| [`p2p_vc__arista_to_arista`](p2p_vc__arista_to_arista/README.md) | p2p_vc | customer_a/arista ↔ customer_b/arista | 100 | 5000 |
| [`p2p_vc__ocnos_to_ocnos`](p2p_vc__ocnos_to_ocnos/README.md) | p2p_vc | customer_a/ocnos ↔ customer_b/ocnos | 101 | 5001 |
| [`p2p_vc__arista_to_ocnos`](p2p_vc__arista_to_ocnos/README.md) | p2p_vc | customer_a/arista ↔ customer_b/ocnos | 102 | 5002 |
| [`cloud_vc__cust-arista_cni-arista`](cloud_vc__cust-arista_cni-arista/README.md) | cloud_vc | customer/arista ↔ cni/arista | 200 | 6000 |
| [`cloud_vc__cust-arista_cni-ocnos`](cloud_vc__cust-arista_cni-ocnos/README.md) | cloud_vc | customer/arista ↔ cni/ocnos | 201 | 6001 |
| [`cloud_vc__cust-ocnos_cni-arista`](cloud_vc__cust-ocnos_cni-arista/README.md) | cloud_vc | customer/ocnos ↔ cni/arista | 202 | 6002 |
| [`cloud_vc__cust-ocnos_cni-ocnos`](cloud_vc__cust-ocnos_cni-ocnos/README.md) | cloud_vc | customer/ocnos ↔ cni/ocnos | 203 | 6003 |

## Azure ExpressRoute (Q-in-Q)

The customer port wraps 1-3 inner C-TAGs into one outer S-TAG (Arista
`dot1q-tunnel`; OcNOS `rewrite push`); the CNI port keys on the S-TAG. A
rewrite scenario resolves an S-TAG conflict on the CNI (Arista translates
to an internal S-TAG; OcNOS pops the S-TAG and disables arp/nd caching).
Azure mandates dual CNI — the orchestrator repeats the CNI config per CNI
with its own VNI; each scenario below shows one circuit (one VNI).

Live validation: the Arista CNI-rewrite and both OcNOS paths (customer +
CNI-rewrite) were run create→verify→delete on ar1/ipi1. The Arista **customer** Q-in-Q path uses `switchport ... dot1q-tunnel`, which the cEOSLab virtual platform does not support — it is valid on real EOS hardware but cannot be exercised on this lab.

| Scenario | Endpoints | S-TAG | C-TAGs | VNI | Rewrite |
|----------|-----------|-------|--------|-----|---------|
| [`azure__cust-arista_cni-arista`](azure__cust-arista_cni-arista/README.md) | customer/arista ↔ cni/arista | 700 | [10, 20, 30] | 7000 | — |
| [`azure__cust-ocnos_cni-ocnos`](azure__cust-ocnos_cni-ocnos/README.md) | customer/ocnos ↔ cni/ocnos | 701 | [11, 21] | 7001 | — |
| [`azure__cust-arista_cni-ocnos`](azure__cust-arista_cni-ocnos/README.md) | customer/arista ↔ cni/ocnos | 702 | [12, 22, 32] | 7002 | — |
| [`azure__rewrite_cni-arista`](azure__rewrite_cni-arista/README.md) | customer/arista ↔ cni/arista | 703 | [13, 23] | 7003 | → 2703 |
| [`azure__rewrite_cni-ocnos`](azure__rewrite_cni-ocnos/README.md) | customer/ocnos ↔ cni/ocnos | 704 | [14, 24] | 7004 | pop |

## Generated configs

### [`p2p_vc__arista_to_arista`](p2p_vc__arista_to_arista/README.md)
- customer_a (arista): [create](p2p_vc__arista_to_arista/1_customer_a__arista.cfg) · [delete](p2p_vc__arista_to_arista/1_customer_a__arista.delete.cfg)
- customer_b (arista): [create](p2p_vc__arista_to_arista/2_customer_b__arista.cfg) · [delete](p2p_vc__arista_to_arista/2_customer_b__arista.delete.cfg)

### [`p2p_vc__ocnos_to_ocnos`](p2p_vc__ocnos_to_ocnos/README.md)
- customer_a (ocnos): [create](p2p_vc__ocnos_to_ocnos/1_customer_a__ocnos.xml) · [delete](p2p_vc__ocnos_to_ocnos/1_customer_a__ocnos.delete.xml)
- customer_b (ocnos): [create](p2p_vc__ocnos_to_ocnos/2_customer_b__ocnos.xml) · [delete](p2p_vc__ocnos_to_ocnos/2_customer_b__ocnos.delete.xml)

### [`p2p_vc__arista_to_ocnos`](p2p_vc__arista_to_ocnos/README.md)
- customer_a (arista): [create](p2p_vc__arista_to_ocnos/1_customer_a__arista.cfg) · [delete](p2p_vc__arista_to_ocnos/1_customer_a__arista.delete.cfg)
- customer_b (ocnos): [create](p2p_vc__arista_to_ocnos/2_customer_b__ocnos.xml) · [delete](p2p_vc__arista_to_ocnos/2_customer_b__ocnos.delete.xml)

### [`cloud_vc__cust-arista_cni-arista`](cloud_vc__cust-arista_cni-arista/README.md)
- customer (arista): [create](cloud_vc__cust-arista_cni-arista/1_customer__arista.cfg) · [delete](cloud_vc__cust-arista_cni-arista/1_customer__arista.delete.cfg)
- cni (arista): [create](cloud_vc__cust-arista_cni-arista/2_cni__arista.cfg) · [delete](cloud_vc__cust-arista_cni-arista/2_cni__arista.delete.cfg)

### [`cloud_vc__cust-arista_cni-ocnos`](cloud_vc__cust-arista_cni-ocnos/README.md)
- customer (arista): [create](cloud_vc__cust-arista_cni-ocnos/1_customer__arista.cfg) · [delete](cloud_vc__cust-arista_cni-ocnos/1_customer__arista.delete.cfg)
- cni (ocnos): [create](cloud_vc__cust-arista_cni-ocnos/2_cni__ocnos.xml) · [delete](cloud_vc__cust-arista_cni-ocnos/2_cni__ocnos.delete.xml)

### [`cloud_vc__cust-ocnos_cni-arista`](cloud_vc__cust-ocnos_cni-arista/README.md)
- customer (ocnos): [create](cloud_vc__cust-ocnos_cni-arista/1_customer__ocnos.xml) · [delete](cloud_vc__cust-ocnos_cni-arista/1_customer__ocnos.delete.xml)
- cni (arista): [create](cloud_vc__cust-ocnos_cni-arista/2_cni__arista.cfg) · [delete](cloud_vc__cust-ocnos_cni-arista/2_cni__arista.delete.cfg)

### [`cloud_vc__cust-ocnos_cni-ocnos`](cloud_vc__cust-ocnos_cni-ocnos/README.md)
- customer (ocnos): [create](cloud_vc__cust-ocnos_cni-ocnos/1_customer__ocnos.xml) · [delete](cloud_vc__cust-ocnos_cni-ocnos/1_customer__ocnos.delete.xml)
- cni (ocnos): [create](cloud_vc__cust-ocnos_cni-ocnos/2_cni__ocnos.xml) · [delete](cloud_vc__cust-ocnos_cni-ocnos/2_cni__ocnos.delete.xml)

### [`azure__cust-arista_cni-arista`](azure__cust-arista_cni-arista/README.md)
- customer (arista): [create](azure__cust-arista_cni-arista/1_customer__arista.cfg) · [delete](azure__cust-arista_cni-arista/1_customer__arista.delete.cfg)
- cni (arista): [create](azure__cust-arista_cni-arista/2_cni__arista.cfg) · [delete](azure__cust-arista_cni-arista/2_cni__arista.delete.cfg)

### [`azure__cust-ocnos_cni-ocnos`](azure__cust-ocnos_cni-ocnos/README.md)
- customer (ocnos): [create](azure__cust-ocnos_cni-ocnos/1_customer__ocnos.xml) · [delete](azure__cust-ocnos_cni-ocnos/1_customer__ocnos.delete.xml)
- cni (ocnos): [create](azure__cust-ocnos_cni-ocnos/2_cni__ocnos.xml) · [delete](azure__cust-ocnos_cni-ocnos/2_cni__ocnos.delete.xml)

### [`azure__cust-arista_cni-ocnos`](azure__cust-arista_cni-ocnos/README.md)
- customer (arista): [create](azure__cust-arista_cni-ocnos/1_customer__arista.cfg) · [delete](azure__cust-arista_cni-ocnos/1_customer__arista.delete.cfg)
- cni (ocnos): [create](azure__cust-arista_cni-ocnos/2_cni__ocnos.xml) · [delete](azure__cust-arista_cni-ocnos/2_cni__ocnos.delete.xml)

### [`azure__rewrite_cni-arista`](azure__rewrite_cni-arista/README.md)
- customer (arista): [create](azure__rewrite_cni-arista/1_customer__arista.cfg) · [delete](azure__rewrite_cni-arista/1_customer__arista.delete.cfg)
- cni (arista): [create](azure__rewrite_cni-arista/2_cni__arista.cfg) · [delete](azure__rewrite_cni-arista/2_cni__arista.delete.cfg)

### [`azure__rewrite_cni-ocnos`](azure__rewrite_cni-ocnos/README.md)
- customer (ocnos): [create](azure__rewrite_cni-ocnos/1_customer__ocnos.xml) · [delete](azure__rewrite_cni-ocnos/1_customer__ocnos.delete.xml)
- cni (ocnos): [create](azure__rewrite_cni-ocnos/2_cni__ocnos.xml) · [delete](azure__rewrite_cni-ocnos/2_cni__ocnos.delete.xml)
