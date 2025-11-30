# Network Automation Project

This project implements network automation for EVPN and management for network switch ports (creating LAG interfaces).

## Architecture

The system follows a layered architecture compliant with IETF RFC 8309, separating the Service Layer from the Network Element Layer.

### 1. Network Element Layer
Abstracts networking device specific features like interfaces, VLANs, etc.
- **Data Modeling**: Uses **Pydantic** models to strictly define the schema for interfaces, VLANs, and other elements, loosely based on IETF YANG models.
- **Southbound Interface**: Uses an **Adapter Pattern** to support multiple vendors and connection methods.
- **Drivers**: Abstract Base Classes define the interface. Implementations include:
        - `NetconfDriver` (for OcNOS, modern EOS)
        - `EapiDriver` (for legacy EOS)
        - `MockDriver` (for testing)

### 2. Network Service Layer
Abstracts services built on top of the network element layer.
- **EVPN Service**: Composes lower-level elements (VRFs, VXLANs, BGP) to deploy L2VPN services.
- **LAG Management**: A stateful service that manages port bonding. It handles the complexity of migrating existing configurations (VLANs) from physical ports to the new aggregate interface.

## Supported Vendors
- **Arista EOS**
- **IPInfusion OcNOS**

## Key Features
- **Pluggable Architecture**: Easy to add new vendors or protocols.
- **Stateful Orchestration**: Capable of reading device state before applying changes (critical for brownfield migrations).
- **Testability**: Fully testable without physical hardware using Mock Drivers.

# Overview
A production-ready network automation system for EVPN and LAG management with vendor-specific Jinja2 templates, comprehensive testing, and full CRUD operations with validation.

Final Architecture
```
src/netauto/
├── models.py           # Pydantic models (100% coverage)
├── drivers.py          # Device drivers (Arista eAPI, OcNOS Netconf, Mock)
├── renderer.py         # Template rendering engine (100% coverage)
├── ocnos_xml.py        # OcNOS XML payload builder
├── logic.py            # LAG manager (100% coverage)
├── evpn.py             # EVPN manager with VNI validation (100% coverage)
└── templates/
    ├── arista_eos/
    │   ├── lag.j2, lag_delete.j2
    │   └── evpn_service.j2, evpn_delete.j2
    └── ipinfusion_ocnos/
        └── (Replaced by ocnos_xml.py)
```

- ✅ Real Device Drivers
AristaDriver: Uses jsonrpclib for eAPI interaction (stateless, HTTP-based). Parses JSON output.
OcnosDriver: Uses scrapli_netconf for Netconf interaction. Uses xml.etree.ElementTree for payload generation and parsing.
MockDriver: For testing without devices.
- ✅ Complete CRUD Operations
LAG: Create, Delete
EVPN: Deploy, Delete
- ✅ Validation
VNI Conflict Detection: Prevents deploying EVPN services with duplicate VNIs
Port Conflict Detection: Prevents adding ports already in a LAG
Model Validation: Pydantic ensures data integrity
- ✅ Multi-Vendor Support
Arista EOS (eAPI, JSON parsing, Jinja2 templates)
IPInfusion OcNOS (Netconf, XML parsing, Programmatic XML generation)
- ✅ Optional S-TAG Support
Models: 
Vlan
 and 
EvpnService
 support optional s_tag.
Templates/XML: Configures S-TAG aware naming/description.


Makefile:
make test: Run all tests (skips live tests by default)
make demo: Run mock demo script
make demo-live: Run live device demo (requires env vars)


## Test Coverage
63 tests total across 8 test files:

test_lag_manager.py
 (12 tests)
test_evpn_manager.py
 (11 tests)
test_models.py
 (17 tests)
test_drivers.py
 (9 tests)
test_renderer.py
 (5 tests)
test_real_drivers_syntax.py
 (2 tests)
test_ocnos_xml.py
 (4 tests)
test_live_devices.py
 (3 tests, skipped by default)
Coverage: 87% overall, 100% on core logic

## Usage Examples
Live Device Demo

### Set credentials (optional, defaults to admin/admin)

```
export DEVICE_USER=admin
export ARISTA_HOST=172.20.30.4
export OCNOS_HOST=172.20.30.6
export OCNOS_DEVICE_PASSWORD=secret
export ARISTA_DEVICE_PASSWORD=othersecret
```

### Run the demo
```
make demo-live
```

Running Live Tests

```
export RUN_LIVE_TESTS=1
make test
```

### Technology Stack
Language: Python 3.12
Data Validation: Pydantic
Templating: Jinja2 (Arista) / XML Builder (OcNOS)
Testing: Pytest
Package Management: uv
Device Connectivity:
Arista: jsonrpclib (eAPI)
OcNOS: scrapli_netconf (Netconf)
