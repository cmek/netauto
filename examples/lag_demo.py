"""Full LAG build -> verify -> delete demo for Arista (ar1) and OcNOS (ipi1).

This mirrors how the library is meant to be used from a Prefect task: a
``LagManager`` over a device driver, with port-list ``create_lag`` /
``delete_lag`` building blocks.

Usage:
    # Preview only (generate config + diff, nothing committed):
    uv run python examples/lag_demo.py --dry-run

    # Commit the create + delete cycle (self-cleaning):
    uv run python examples/lag_demo.py

Override targets/ports with env vars: ARISTA_HOST, OCNOS_HOST, DEVICE_USER,
DEVICE_PASSWORD, OCNOS_PASSWORD, ARISTA_LAG_MEMBERS, OCNOS_LAG_MEMBERS,
ARISTA_LAG_NAME, OCNOS_LAG_NAME. Lab access requires the VPN to be up.
"""

import argparse
import logging
import os

from netauto.drivers import AristaDriver, OcnosDriver
from netauto.logic import LagManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

ARISTA_HOST = os.getenv("ARISTA_HOST", "172.20.30.4")
OCNOS_HOST = os.getenv("OCNOS_HOST", "172.20.30.6")
USERNAME = os.getenv("DEVICE_USER", "admin")
PASSWORD = os.getenv("DEVICE_PASSWORD", "admin")
OCNOS_PASSWORD = os.getenv("OCNOS_PASSWORD", "admin@123")

ARISTA_LAG_NAME = os.getenv("ARISTA_LAG_NAME", "Port-Channel99")
OCNOS_LAG_NAME = os.getenv("OCNOS_LAG_NAME", "po99")
ARISTA_LAG_MEMBERS = os.getenv("ARISTA_LAG_MEMBERS", "Ethernet5,Ethernet6").split(",")
OCNOS_LAG_MEMBERS = os.getenv("OCNOS_LAG_MEMBERS", "eth3,eth4").split(",")


def _interface_names(interfaces) -> set[str]:
    if isinstance(interfaces, dict):
        return set(interfaces.keys())
    return {intf.name for intf in interfaces}


def run_cycle(label, driver, lag_name, members, *, dry_run, migrate_vlans):
    print(f"\n{'=' * 60}\n{label}: LAG {lag_name} <- {members}\n{'=' * 60}")
    mgr = LagManager(driver)

    print(f"\n[{label}] CREATE (dry_run={dry_run})")
    diff = mgr.create_lag(
        lag_name, members, migrate_vlans=migrate_vlans, dry_run=dry_run
    )
    print(diff or "(no diff returned)")

    if not dry_run:
        present = lag_name in _interface_names(driver.get_interfaces())
        print(f"[{label}] verify created: {lag_name} present = {present}")

    print(f"\n[{label}] DELETE (dry_run={dry_run})")
    try:
        diff = mgr.delete_lag(lag_name, members, dry_run=dry_run)
        print(diff or "(no diff returned)")
        if not dry_run:
            gone = lag_name not in _interface_names(driver.get_interfaces())
            print(f"[{label}] verify deleted: {lag_name} gone = {gone}")
    finally:
        driver.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate config and diff without committing.",
    )
    parser.add_argument(
        "--migrate-vlans",
        action="store_true",
        help="Migrate member-port VLAN config onto the LAG.",
    )
    parser.add_argument(
        "--only",
        choices=["arista", "ocnos"],
        help="Run only one vendor.",
    )
    args = parser.parse_args()

    if args.only != "ocnos":
        arista = AristaDriver(host=ARISTA_HOST, user=USERNAME, password=PASSWORD)
        arista.connect()
        run_cycle(
            "ARISTA",
            arista,
            ARISTA_LAG_NAME,
            ARISTA_LAG_MEMBERS,
            dry_run=args.dry_run,
            migrate_vlans=args.migrate_vlans,
        )

    if args.only != "arista":
        ocnos = OcnosDriver(host=OCNOS_HOST, user=USERNAME, password=OCNOS_PASSWORD)
        run_cycle(
            "OCNOS",
            ocnos,
            OCNOS_LAG_NAME,
            OCNOS_LAG_MEMBERS,
            dry_run=args.dry_run,
            migrate_vlans=args.migrate_vlans,
        )


if __name__ == "__main__":
    main()
