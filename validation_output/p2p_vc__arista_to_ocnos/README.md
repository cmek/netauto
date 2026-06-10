# p2p_vc__arista_to_ocnos

- Service type: **p2p_vc**
- Service key: `SO101012`
- VLAN: `102`
- VNI: `5002`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer_a** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`, RD `65001:101012`
- **customer_b** — ocnos (OcNOS NETCONF edit-config payload), interface `eth4`, local ASN `65002`, RD `65002:101012`

## Files

- `1_customer_a__arista.cfg`
- `1_customer_a__arista.delete.cfg`
- `2_customer_b__ocnos.xml`
- `2_customer_b__ocnos.delete.xml`
