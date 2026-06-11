# netauto — Usage

A building-blocks library for provisioning network switches. Each call configures
**one device**; multi-device orchestration (e.g. both ends of a circuit) is the
caller's job (see `examples/prefect_evpn.py`). Two service layers:
`LagManager` (port bonding) and `EvpnManager` (EVPN circuits). Architecture &
design: [docs/evpn_service.md](docs/evpn_service.md).

Every mutating call takes `dry_run=True` to preview the config diff without
committing, and returns the diff string.

## Connect to a device

```python
from netauto.drivers import AristaDriver, OcnosDriver, MockDriver

arista = AristaDriver(host="172.20.30.4", user="admin", password="admin",
                      enable_password="admin")
arista.connect()                       # eAPI / HTTP

ocnos = OcnosDriver(host="172.20.30.6", user="admin", password="admin@123")
ocnos.connect()                        # NETCONF

mock = MockDriver(platform="arista_eos")   # offline; records pushes, no device
```

## LAG management (`LagManager`)

Single-switch link aggregation. VLAN config on the members is migrated onto the
LAG by default (`migrate_vlans=True`).

```python
from netauto.logic import LagManager
mgr = LagManager(arista)

# bundle two ports into a Port-Channel (preview first)
mgr.create_lag("Port-Channel10", ["Ethernet5", "Ethernet6"],
               description="SO12345", dry_run=True)
mgr.create_lag("Port-Channel10", ["Ethernet5", "Ethernet6"], description="SO12345")

mgr.add_members("Port-Channel10", ["Ethernet7"])      # grow an existing LAG
mgr.remove_members("Port-Channel10", ["Ethernet7"])   # shrink it
mgr.delete_lag("Port-Channel10", ["Ethernet5", "Ethernet6"])   # split back to ports
```

OcNOS uses `po`-prefixed names (`mgr.create_lag("po10", ["eth5", "eth6"])`).

## EVPN circuits (`EvpnManager`)

A circuit = a service VRF (`mac-vrf` / `vlan-aware-bundle`) + the access
interface mapped to a VNI. The **VNI is allocated externally and passed in whole**
(see allocation below). `cloud_vc` (customer↔CNI) and `p2p_vc` (member↔member)
render identically — `service_type` is just a label.

```python
from netauto.evpn import EvpnManager
from netauto.models import Evpn, Vlan, RoutingInstance

evpn = Evpn(vlan=Vlan(vlan_id=100, name="SO123456"), asn=65001, vni=5000,
            description="SO123456", service_type="p2p_vc")
ri = RoutingInstance(instance_name="SO123456", instance_type="mac-vrf",
                     rd="65001:123456", rt_rd="37195:123456")   # RT = isolation key

mgr = EvpnManager(arista)
mgr.create_circuit("Ethernet6", evpn, routing_instance=ri, dry_run=True)  # preview
mgr.create_circuit("Ethernet6", evpn, routing_instance=ri)               # commit
mgr.delete_circuit("Ethernet6", evpn, routing_instance=ri, delete_vrf=True)
```

`create_vrf=False` / `delete_vrf=False` skip the VRF when it already exists / is
shared. The orchestrator runs this once per end of the circuit.

## Azure ExpressRoute (Q-in-Q)

Customer port tunnels 1–3 inner C-TAGs into one outer S-TAG; the CNI port keys on
the S-TAG. Dual-CNI = call once per CNI with its own VNI.

```python
from netauto.models import AzureEvpn

customer = AzureEvpn(description="SO654321", asn=65004, vni=6000, s_tag=500,
                     role="customer", c_tags=[10, 20, 30])
mgr.create_azure_circuit("eth4", customer, routing_instance=ri_cust)

# CNI with an S-TAG conflict on the device -> rewrite (Arista translates,
# OcNOS pops); Arista needs the internal S-TAG to translate to.
cni = AzureEvpn(description="SO654321", asn=65001, vni=6001, s_tag=500,
                role="cni", rewrite=True, internal_s_tag=2500)
mgr.create_azure_circuit("Ethernet6", cni, routing_instance=ri_cni)
```

## Read-back, verify, declarative ensure

```python
# what's actually configured (-> list[EvpnCircuit] with interface + model + RD/RT)
for c in mgr.get_circuits():
    print(c.evpn.vni, c.interface, type(c.evpn).__name__)

# did my push land / has it drifted?  -> CircuitDiff(present, matches, differences)
diff = mgr.verify_circuit("Ethernet6", evpn, ri)

# declarative: converge the device to intent (idempotent: created/updated/unchanged)
result = mgr.ensure_circuit("Ethernet6", evpn, ri)   # safe to re-run
```

Dump a device (or the fabric) from the CLI:

```bash
uv run python scripts/inspect_evpn.py 172.20.30.4 arista
uv run python scripts/inspect_evpn.py --all
```

## Identifier allocation (fabric-wide unique VNIs)

VNIs must be unique across the **whole fabric**. Use the registry, not a
per-device scan; `make_routing_instance` centralises the RD/RT convention.

```python
from netauto.allocation import JsonFileRegistry, make_routing_instance, find_conflicts

reg = JsonFileRegistry("vni_registry.json")
vni = reg.allocate("SO123456", rt="37195:123456")        # fabric-unique, idempotent
ri = make_routing_instance("SO123456", device_asn=65001, rt_asn=37195)

find_conflicts(mgr.get_circuits())   # audit: same VNI/RT used by different services
```

## More examples

- `examples/evpn_circuit.py` — EVPN create on a `MockDriver` (offline, runnable).
- `examples/prefect_evpn.py` — full Prefect orchestration: provision both ends,
  dual-CNI Azure, fabric audit, declarative reconcile.
- `examples/prefect_lag.py` — Prefect LAG provisioning.
- `scripts/live_evpn_test.py {arista|ocnos|arista-azure|ocnos-azure}` — manual,
  self-cleaning create→verify→delete against the lab.
