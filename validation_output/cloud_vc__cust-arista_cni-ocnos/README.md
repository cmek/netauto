# cloud_vc__cust-arista_cni-ocnos

- Service type: **cloud_vc**
- Service key: `SO202021`
- VLAN: `201`
- VNI: `6001`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`, RD `65001:202021`
- **cni** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65010`, RD `65010:202021`

## Files

- `1_customer__arista.cfg`
- `1_customer__arista.delete.cfg`
- `2_cni__ocnos.xml`
- `2_cni__ocnos.delete.xml`
