# EVPN circuit validation matrix

Example configuration for every supported EVPN circuit scenario, for
review by network engineering before these building blocks are trusted
against production gear. Generated offline by
`scripts/generate_evpn_validation.py` (via MockDriver — no devices).

Scope this round: non-Azure, **global transport** (EVPN/VXLAN across
different devices) `cloud_vc` (customer ↔ CNI) and `p2p_vc` (member ↔
member). Azure Q-in-Q and same-device local switching are out of scope.

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
