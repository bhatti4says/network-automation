from netmiko import ConnectHandler
from getpass import getpass
from datetime import datetime
import sys

# ==============================
# USER INPUT SECTION
# ==============================

USERNAME = "cisco"
PASSWORD = getpass("Enter SSH password: ")

ACCESS_SWITCHES = {
    "10.20.39.22": 11,
    "10.20.39.23": 12,
    "10.20.39.24": 13,
    "10.20.39.25": 14,
}

PORT_CHANNEL_ID = 2
MEMBER_INTERFACES = ["GigabitEthernet1/0/47", "GigabitEthernet1/0/48"]
TRUNK_ALLOWED_VLANS = "10,20,30,39"

# ==============================
# FUNCTIONS
# ==============================

def configure_port_channel(host, vlan):
    device = {
        "device_type": "cisco_ios",
        "host": host,
        "username": USERNAME,
        "password": PASSWORD,
        "fast_cli": False,
    }

    print(f"\n[{host}] Connecting...")
    conn = ConnectHandler(**device)
    conn.enable()
    conn.send_command("terminal length 0")

    config_commands = [
        f"interface Port-channel{PORT_CHANNEL_ID}",
        "description *** UPLINK TO CORE ***",
        "switchport",
        "switchport mode trunk",
        f"switchport trunk allowed vlan {TRUNK_ALLOWED_VLANS}",
        "spanning-tree portfast trunk",
        "no shutdown",
        "exit",
    ]

    for intf in MEMBER_INTERFACES:
        config_commands.extend([
            f"interface {intf}",
            "switchport",
            "switchport mode trunk",
            f"channel-group {PORT_CHANNEL_ID} mode active",
            "no shutdown",
            "exit",
        ])

    print(f"[{host}] Applying configuration...")
    conn.send_config_set(config_commands)

    print(f"[{host}] Verifying Port-Channel...")
    verify = conn.send_command(
        f"show run interface port-channel {PORT_CHANNEL_ID}"
    )

    if f"interface Port-channel{PORT_CHANNEL_ID}" not in verify:
        conn.disconnect()
        raise RuntimeError(f"[{host}] Verification FAILED")

    print(f"[{host}] SUCCESS")
    conn.disconnect()


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    start = datetime.now()
    print(f"=== Deployment started at {start} ===")

    try:
        for switch_ip, vlan in ACCESS_SWITCHES.items():
            configure_port_channel(switch_ip, vlan)

    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    end = datetime.now()
    print(f"\n=== Deployment completed at {end} ===")
