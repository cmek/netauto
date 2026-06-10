# azure__rewrite_cni-arista

- Service type: **azure** (ExpressRoute Q-in-Q / 802.1ad)
- Service key: `SO303033`
- S-TAG (outer): `703`
- C-TAGs (inner, customer side): `[13, 23]`
- VNI: `7003`  (one circuit; dual-CNI uses one VNI per CNI)
- Route-target prefix: `37186`

The customer port tunnels each C-TAG into the S-TAG; the CNI port keys on the S-TAG (C-TAGs are encapsulated). Azure mandates dual CNI — the orchestrator repeats the CNI config on the secondary CNI with its own VNI.

## Endpoints

- **customer** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`
- **cni** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65010` · **S-TAG rewrite** (Azure 703 → internal 2703)

## Files

- `1_customer__arista.cfg`
- `1_customer__arista.delete.cfg`
- `2_cni__arista.cfg`
- `2_cni__arista.delete.cfg`
