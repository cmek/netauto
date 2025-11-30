import pytest
from unittest.mock import MagicMock, patch
from netauto.drivers import AristaDriver, OcnosDriver

class TestRealDriversSyntax:
    """
    Tests to verify that real drivers can be instantiated and methods called 
    without syntax errors, using mocks for the actual connection.
    """

    @patch('netauto.drivers.jsonrpclib.Server')
    def test_arista_driver_syntax(self, mock_server_cls):
        """Test AristaDriver instantiation and method syntax."""
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        
        # Test instantiation
        driver = AristaDriver("1.1.1.1", "user", "pass")
        assert driver.platform == "arista_eos"
        
        # Test connect (eAPI runs show version)
        driver.connect()
        mock_server.runCmds.assert_called_with(1, ["show version"])
        
        # Test disconnect (no-op)
        driver.disconnect()
        
        # Test get_interfaces (mocking JSON response)
        # runCmds returns a list of results, one for each command
        # We send ["show interfaces", "show interfaces switchport"]
        mock_server.runCmds.return_value = [
            {"interfaces": {"Ethernet1": {"forwardingModel": "routed"}}},
            {"switchports": {}}
        ]
        
        interfaces = driver.get_interfaces()
        assert "Ethernet1" in interfaces
        assert interfaces["Ethernet1"].mode == "routed"

    @patch('netauto.drivers.ScrapliNetconfDriver')
    def test_ocnos_driver_syntax(self, mock_nc_cls):
        """Test OcnosDriver instantiation and method syntax."""
        mock_conn = MagicMock()
        mock_nc_cls.return_value = mock_conn
        
        # Test instantiation
        driver = OcnosDriver("1.1.1.1", "user", "pass")
        assert driver.platform == "ipinfusion_ocnos"
        
        # Test connect/disconnect
        driver.connect()
        mock_conn.open.assert_called_once()
        driver.disconnect()
        mock_conn.close.assert_called_once()
        
        # Test get_vlans (mocking XML response)
        mock_conn.get.return_value.result = """
        <rpc-reply>
            <data>
                <vlan-database xmlns="http://www.ipinfusion.com/yang/ocnos/ipi-vlan">
                    <vlan>
                        <id>10</id>
                        <name>VLAN10</name>
                    </vlan>
                </vlan-database>
            </data>
        </rpc-reply>
        """
        
        vlans = driver.get_vlans()
        assert 10 in vlans
        assert vlans[10].name == "VLAN10"
        
        # Test push_config (uses edit_config)
        driver.push_config(["<config>...</config>"])
        mock_conn.edit_config.assert_called_with(config="<config>...</config>", target="candidate")
