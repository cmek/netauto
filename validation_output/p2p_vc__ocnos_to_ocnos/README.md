# p2p_vc__ocnos_to_ocnos

- Service type: **p2p_vc**
- Service key: `SO101011`
- VLAN: `101`
- VNI: `5001`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer_a** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65001`, RD `65001:101011`
- **customer_b** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65002`, RD `65002:101011`

## Files

- `1_customer_a__ocnos.xml`
- `1_customer_a__ocnos.delete.xml`
- `2_customer_b__ocnos.xml`
- `2_customer_b__ocnos.delete.xml`
