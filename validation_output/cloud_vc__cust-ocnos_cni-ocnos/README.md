# cloud_vc__cust-ocnos_cni-ocnos

- Service type: **cloud_vc**
- Service key: `SO202023`
- VLAN: `203`
- VNI: `6003`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65001`, RD `65001:202023`
- **cni** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65010`, RD `65010:202023`

## Files

- `1_customer__ocnos.xml`
- `1_customer__ocnos.delete.xml`
- `2_cni__ocnos.xml`
- `2_cni__ocnos.delete.xml`
