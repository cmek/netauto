# cloud_vc__cust-arista_cni-arista

- Service type: **cloud_vc**
- Service key: `SO202020`
- VLAN: `200`
- VNI: `6000`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`, RD `65001:202020`
- **cni** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65010`, RD `65010:202020`

## Files

- `1_customer__arista.cfg`
- `1_customer__arista.delete.cfg`
- `2_cni__arista.cfg`
- `2_cni__arista.delete.cfg`
