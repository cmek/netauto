# p2p_vc__arista_to_arista

- Service type: **p2p_vc**
- Service key: `SO101010`
- VLAN: `100`
- VNI: `5000`  (allocated externally, used verbatim for the VXLAN id and the mac-vrf / vlan-aware-bundle)
- Route-target prefix: `37195` (shared across both endpoints)

## Endpoints

- **customer_a** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65001`, RD `65001:101010`
- **customer_b** — arista (Arista EOS CLI), interface `Ethernet6`, local ASN `65002`, RD `65002:101010`

## Files

- `1_customer_a__arista.cfg`
- `1_customer_a__arista.delete.cfg`
- `2_customer_b__arista.cfg`
- `2_customer_b__arista.delete.cfg`
