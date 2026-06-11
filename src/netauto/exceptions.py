class NetAutoException(Exception):
    """Base for all netauto errors. Every typed error below subclasses this, so
    existing ``except NetAutoException`` handlers keep working while callers
    (e.g. Prefect tasks) can branch on the specific failure type."""

    def __init__(self, error_info):
        self.error_info = error_info
        super().__init__(error_info)


class InterfaceNotFound(NetAutoException):
    """The target interface does not exist on the device."""


class VniInUse(NetAutoException):
    """The requested VNI is already mapped on the device / fabric."""


class RtCollision(NetAutoException):
    """A route-target (or VNI) is already assigned to a different service.

    The isolation-breaking case in an IX: the same identifier reused across
    unrelated services.
    """


class CircuitConflict(NetAutoException):
    """The requested circuit conflicts with existing config (e.g. the VLAN/port
    is already bound to a different service)."""


class PushFailed(NetAutoException):
    """A configuration push was rejected by the device.

    Wraps the underlying transport/vendor error (pyeapi / ncclient) so callers
    get a uniform type; the original is available via ``__cause__``.
    """
