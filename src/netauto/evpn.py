import logging
from typing import List, Optional

from .models import Asn, Evpn, Interface, RoutingInstance
from .drivers import DeviceDriver
from .exceptions import NetAutoException
from .logic import _as_interface_map

logger = logging.getLogger(__name__)


class EvpnManager:
    """Building blocks for single-device EVPN circuit create/delete.

    Mirrors :class:`~netauto.logic.LagManager`: it configures **one endpoint
    interface on one device** per call (read device state, validate, render,
    push). Stitching the two ends of a circuit together across devices is the
    orchestrator's job (Prefect) — this library only provides the per-device
    primitive.

    Scope: global transport (EVPN/VXLAN) ``cloud_vc`` and ``p2p_vc`` circuits.
    No Azure / local switching yet. The VNI is allocated by an external process
    and passed in whole on the :class:`~netauto.models.Evpn` model; it is used
    verbatim (never derived from the VLAN).
    """

    def __init__(self, driver: DeviceDriver):
        self.driver = driver

    def _normalise(self, rendered) -> List[str]:
        """Renderers return a CLI line list (Arista) or one XML string (OcNOS)."""
        return rendered if isinstance(rendered, list) else [rendered]

    def _require_interface(self, interface_name: str) -> Interface:
        """Confirm the endpoint exists. Routed (L3) ports show up in the
        interface inventory but not in get_switchports(), so check both."""
        inventory = _as_interface_map(self.driver.get_interfaces())
        switchports = _as_interface_map(self.driver.get_switchports())
        interface = inventory.get(interface_name) or switchports.get(interface_name)
        if interface is None:
            raise NetAutoException(
                f"Interface {interface_name} does not exist on device."
            )
        return interface

    def _require_vni_free(self, evpn: Evpn) -> None:
        """The VNI must not already be mapped on this device.

        VNIs are allocated by an external process; this is a safety check that
        the value handed to us isn't already in use on the device.
        """
        # get_vnis() is a dict (Arista: vni -> {vlan_id}) or a list (OcNOS).
        existing = self.driver.get_vnis()
        if evpn.vni in existing:
            detail = ""
            if isinstance(existing, dict):
                mapped = existing[evpn.vni] or {}
                detail = f" (mapped to VLAN {mapped.get('vlan_id', 'unknown')})"
            raise NetAutoException(f"VNI {evpn.vni} is already in use{detail}")

    def create_circuit(
        self,
        interface_name: str,
        evpn: Evpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        create_vrf: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Provision one EVPN circuit endpoint on ``interface_name``.

        Optionally creates the mac-vrf / vlan-aware-bundle first
        (``create_vrf``); pass ``create_vrf=False`` when the service VRF already
        exists on the device. Returns the combined config diff (or the intended
        change for ``dry_run``).

        The VRF and the circuit are pushed as two separate device transactions,
        VRF first: on OcNOS the mac-vrf must exist before the circuit references
        it, and on Arista a fresh config session avoids CLI sub-mode leaking
        between the two blocks (a bare ``vlan <id>`` after a ``vlan-aware-bundle``
        block is otherwise swallowed as a bundle member).
        """
        self._require_interface(interface_name)
        self._require_vni_free(evpn)

        interface = Interface(name=interface_name)
        diffs: List[str] = []

        if create_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when create_vrf=True"
                )
            # The vlan-aware-bundle / mac-vrf is named by the service key on both
            # the VRF push and the EVPN push; they must reference the same bundle.
            if routing_instance.instance_name != evpn.description:
                raise NetAutoException(
                    "routing_instance.instance_name "
                    f"({routing_instance.instance_name!r}) must match "
                    f"evpn.description ({evpn.description!r}) so the VRF and the "
                    "EVPN circuit reference the same service instance."
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance(
                            asn or Asn(asn=evpn.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        logger.info(
            "creating %s EVPN circuit on %s (vni %s)",
            evpn.service_type,
            interface_name,
            evpn.vni,
        )
        diffs.append(
            self.driver.push_config(
                self._normalise(self.driver.renderer.render_evpn(interface, evpn)),
                dry_run=dry_run,
            )
        )
        return "\n".join(d for d in diffs if d)

    def delete_circuit(
        self,
        interface_name: str,
        evpn: Evpn,
        routing_instance: Optional[RoutingInstance] = None,
        asn: Optional[Asn] = None,
        delete_vrf: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Tear down one EVPN circuit endpoint on ``interface_name``.

        Removes the circuit (sub-interface / access binding / VXLAN mapping).
        Pass ``delete_vrf=True`` (with ``routing_instance``) to also remove the
        service mac-vrf — only safe once no other endpoint uses it.

        Pushed as two separate transactions (circuit first, then the VRF), for
        the same per-platform reasons as ``create_circuit``.
        """
        interface = Interface(name=interface_name)

        logger.info(
            "deleting %s EVPN circuit on %s (vni %s)",
            evpn.service_type,
            interface_name,
            evpn.vni,
        )
        diffs: List[str] = [
            self.driver.push_config(
                self._normalise(
                    self.driver.renderer.render_evpn_delete(interface, evpn)
                ),
                dry_run=dry_run,
            )
        ]

        if delete_vrf:
            if routing_instance is None:
                raise NetAutoException(
                    "routing_instance is required when delete_vrf=True"
                )
            diffs.append(
                self.driver.push_config(
                    self._normalise(
                        self.driver.renderer.render_routing_instance_delete(
                            asn or Asn(asn=evpn.asn), routing_instance
                        )
                    ),
                    dry_run=dry_run,
                )
            )

        return "\n".join(d for d in diffs if d)
