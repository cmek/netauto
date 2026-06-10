# cloud_vc__cust-ocnos_cni-arista

- Service type: **cloud_vc**
- Service key: `SO202022`
- VLAN: `202`
- VNI: `6002`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65001`, RD `65001:202022`
- **cni** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65010`, RD `65010:202022`

## Files

- `1_customer__ocnos.xml`
- `1_customer__ocnos.delete.xml`
- `2_cni__arista.cfg`
- `2_cni__arista.delete.cfg`
