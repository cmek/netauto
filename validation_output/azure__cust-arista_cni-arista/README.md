# azure__cust-arista_cni-arista

- Service type: **azure** (ExpressRoute Q-in-Q / 802.1ad)
- Service key: `SO303030`
- S-TAG (outer): `700`
- C-TAGs (inner, customer side): `[10, 20, 30]`
- VNI: `7000`  (one circuit; dual-CNI uses one VNI per CNI)
- Route-target prefix: `37186`

The customer port tunnels each C-TAG into the S-TAG; the CNI port keys on the S-TAG (C-TAGs are encapsulated). Azure mandates dual CNI — the orchestrator repeats the CNI config on the secondary CNI with its own VNI.

## Endpoints

- **customer** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`
- **cni** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65010`

## Files

- `1_customer__arista.cfg`
- `1_customer__arista.delete.cfg`
- `2_cni__arista.cfg`
- `2_cni__arista.delete.cfg`
