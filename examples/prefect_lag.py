"""Illustrative Prefect integration for LAG provisioning / decommissioning.

This is a *sketch* showing how the netauto LAG building blocks
(`LagManager.create_lag` / `delete_lag`) would be wired into Prefect tasks and
flows. It is not exercised by the test suite and Prefect does not need to be
installed to read it — it documents the intended shape of the integration.

Key ideas:
  * One task opens a connected driver for the target switch (vendor-dispatched).
  * Thin tasks wrap the create / delete building blocks, with retries.
  * A flow ties them together and supports dry_run to preview the diff before
    committing.
  * Credentials come from Prefect Secret blocks, not hard-coded values.

Run (once Prefect is installed and configured):
    uv run python examples/prefect_lag.py
"""

from __future__ import annotations

from prefect import flow, task, get_run_logger
from prefect.blocks.system import Secret

from netauto.drivers import AristaDriver, OcnosDriver
from netauto.drivers.base import DeviceDriver
from netauto.logic import LagManager


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #
@task(retries=2, retry_delay_seconds=10)
def open_driver(platform: str, host: str) -> DeviceDriver:
    """Return a connected driver for the target switch.

    Credentials are pulled from Prefect Secret blocks (create them once with
    `Secret(value=...).save("device-password")`), keeping them out of code and
    flow parameters.
    """
    logger = get_run_logger()
    password = Secret.load("device-password").get()

    if platform == "arista_eos":
        driver = AristaDriver(host=host, user="admin", password=password)
        driver.connect()  # eAPI / HTTP
    elif platform == "ipinfusion_ocnos":
        # OcNOS connects over NETCONF in its constructor.
        ocnos_password = Secret.load("ocnos-password").get()
        driver = OcnosDriver(host=host, user="admin", password=ocnos_password)
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    logger.info("connected to %s (%s)", host, platform)
    return driver


# --------------------------------------------------------------------------- #
# LAG building-block tasks
# --------------------------------------------------------------------------- #
@task
def create_lag(
    driver: DeviceDriver,
    lag_name: str,
    member_ports: list[str],
    lacp_mode: str = "active",
    description: str | None = None,
    migrate_vlans: bool = True,
    dry_run: bool = False,
) -> str:
    """Bundle member ports into a LAG; returns the config diff."""
    logger = get_run_logger()
    mgr = LagManager(driver)
    diff = mgr.create_lag(
        lag_name,
        member_ports,
        lacp_mode=lacp_mode,
        description=description,
        migrate_vlans=migrate_vlans,
        dry_run=dry_run,
    )
    logger.info("create_lag %s (dry_run=%s) diff:\n%s", lag_name, dry_run, diff)
    return diff


@task
def delete_lag(
    driver: DeviceDriver,
    lag_name: str,
    member_ports: list[str],
    dry_run: bool = False,
) -> str:
    """Split a LAG back into standalone ports; returns the config diff."""
    logger = get_run_logger()
    mgr = LagManager(driver)
    diff = mgr.delete_lag(lag_name, member_ports, dry_run=dry_run)
    logger.info("delete_lag %s (dry_run=%s) diff:\n%s", lag_name, dry_run, diff)
    return diff


@task
def close_driver(driver: DeviceDriver) -> None:
    driver.disconnect()


# --------------------------------------------------------------------------- #
# Flows
# --------------------------------------------------------------------------- #
@flow(name="provision-lag")
def provision_lag(
    platform: str,
    host: str,
    lag_name: str,
    member_ports: list[str],
    lacp_mode: str = "active",
    description: str | None = None,
    migrate_vlans: bool = True,
    dry_run: bool = False,
) -> str:
    """Provision a single-switch LAG on one device."""
    driver = open_driver(platform, host)
    try:
        return create_lag(
            driver,
            lag_name,
            member_ports,
            lacp_mode=lacp_mode,
            description=description,
            migrate_vlans=migrate_vlans,
            dry_run=dry_run,
        )
    finally:
        close_driver(driver)


@flow(name="decommission-lag")
def decommission_lag(
    platform: str,
    host: str,
    lag_name: str,
    member_ports: list[str],
    dry_run: bool = False,
) -> str:
    """Tear a LAG down, returning its members to standalone ports."""
    driver = open_driver(platform, host)
    try:
        return delete_lag(driver, lag_name, member_ports, dry_run=dry_run)
    finally:
        close_driver(driver)


if __name__ == "__main__":
    # Example invocations. Use dry_run=True first to review the diff, then flip
    # to dry_run=False to commit.
    provision_lag(
        platform="arista_eos",
        host="172.20.30.4",
        lag_name="Port-Channel99",
        member_ports=["Ethernet5", "Ethernet6"],
        description="SO12345",
        dry_run=True,
    )

    decommission_lag(
        platform="ipinfusion_ocnos",
        host="172.20.30.6",
        lag_name="po99",
        member_ports=["eth3", "eth4"],
        dry_run=True,
    )
