# azure__cust-ocnos_cni-ocnos

- Service type: **azure** (ExpressRoute Q-in-Q / 802.1ad)
- Service key: `SO303031`
- S-TAG (outer): `701`
- C-TAGs (inner, customer side): `[11, 21]`
- VNI: `7001`  (one circuit; dual-CNI uses one VNI per CNI)
- Route-target prefix: `37186`

The customer port tunnels each C-TAG into the S-TAG; the CNI port keys on the S-TAG (C-TAGs are encapsulated). Azure mandates dual CNI — the orchestrator repeats the CNI config on the secondary CNI with its own VNI.

## Endpoints

- **customer** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65001`
- **cni** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65010`

## Files

- `1_customer__ocnos.xml`
- `1_customer__ocnos.delete.xml`
- `2_cni__ocnos.xml`
- `2_cni__ocnos.delete.xml`
