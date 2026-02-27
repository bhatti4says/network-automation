#!/usr/bin/env python3
import paramiko
import time
import socket
import re

CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Cisco1234"

# Access switches with their port channel group numbers
ACCESS_SWITCHES = {
    "10.20.39.22": 11,
    "10.20.39.23": 12, 
    "10.20.39.24": 13,
    "10.20.39.25": 14
}

def read_shell_output(shell, timeout=2):
    """Read available output from shell"""
    output = ""
    shell.settimeout(timeout)
    try:
        while True:
            if shell.recv_ready():
                data = shell.recv(4096).decode('utf-8', errors='ignore')
                output += data
                print(data, end='')
            else:
                break
    except socket.timeout:
        pass
    return output

def send_command(shell, command, delay=2.0):
    """Send command and return output"""
    print(f"\n[COMMAND] {command}")
    shell.send(f"{command}\n")
    time.sleep(delay)
    output = read_shell_output(shell)
    # Add extra delay for certain commands
    if any(keyword in command.lower() for keyword in ['configure', 'interface', 'show']):
        time.sleep(1)
    return output

def get_interface_prefix(shell):
    """Determine if switch uses GigabitEthernet or TenGigabitEthernet"""
    print(f"\n[CHECK] Determining interface naming convention...")
    
    # Try show interfaces brief to see naming
    output = send_command(shell, "show ip interface brief", delay=2)
    
    if "TenGigabitEthernet" in output:
        print("[INFO] Switch uses TenGigabitEthernet naming")
        return "TenGigabitEthernet"
    elif "GigabitEthernet" in output:
        print("[INFO] Switch uses GigabitEthernet naming")
        return "GigabitEthernet"
    elif "Gi" in output:
        print("[INFO] Switch uses abbreviated Gi naming")
        return "GigabitEthernet"  # Full name will be expanded
    else:
        # Default to GigabitEthernet
        print("[WARNING] Could not determine interface naming, defaulting to GigabitEthernet")
        return "GigabitEthernet"

def check_interface_range_availability(shell, interface_prefix, port_range="1/1/1-2"):
    """Check if interface range exists and is not connected"""
    full_range = f"{interface_prefix}{port_range}"
    print(f"\n[CHECK] Checking interface range: {full_range}")
    
    # First check if interfaces exist
    output = send_command(shell, f"show interfaces {interface_prefix}1/1/1 status", delay=2)
    
    # Check if interface exists
    if "Invalid input" in output or "Invalid interface" in output:
        # Try abbreviated form
        if interface_prefix == "GigabitEthernet":
            output = send_command(shell, "show interfaces Gi1/1/1 status", delay=2)
            if "Invalid input" in output or "Invalid interface" in output:
                print(f"[ERROR] Interface {interface_prefix}1/1/1 does not exist!")
                return False, []
    
    # Check connectivity for both interfaces
    connected_interfaces = []
    for port in ["1", "2"]:
        interface = f"{interface_prefix}1/1/{port}"
        print(f"\n[CHECK] Checking status of {interface}...")
        
        # Try both full and abbreviated names
        if interface_prefix == "GigabitEthernet":
            cmd = f"show interfaces Gi1/1/{port} status"
        else:
            cmd = f"show interfaces {interface} status"
        
        output = send_command(shell, cmd, delay=2)
        
        # Check for connected status
        if "connected" in output.lower() or ("up" in output.lower() and "down" not in output.lower()):
            print(f"[WARNING] {interface} appears to be CONNECTED/UP!")
            connected_interfaces.append(interface)
        else:
            print(f"[OK] {interface} is NOT CONNECTED")
    
    if len(connected_interfaces) == 2:
        print(f"[CRITICAL] Both interfaces in range are CONNECTED! Aborting configuration.")
        return False, connected_interfaces
    elif len(connected_interfaces) > 0:
        print(f"[WARNING] Some interfaces are connected: {connected_interfaces}")
        print("[INFO] Will only configure non-connected interfaces individually")
        return True, connected_interfaces
    else:
        print(f"[OK] All interfaces in range are available for configuration")
        return True, []

def configure_port_channel(shell, interface_prefix, po_group, connected_interfaces):
    """Configure port channel based on interface availability"""
    print(f"\n[CONFIG] Setting up Port-Channel{po_group}...")
    
    # Step 1: Create Port-Channel interface
    commands = [
        "configure terminal",
        f"interface Port-channel{po_group}",
        "description CONFIGURED-BY-SCRIPT",
        "switchport mode trunk",
        "switchport trunk allowed vlan all",
        "spanning-tree portfast trunk",
        "no shutdown",
        "end"
    ]
    
    for cmd in commands:
        send_command(shell, cmd)
    
    # Step 2: Configure interfaces
    if connected_interfaces:
        # Some interfaces are connected, configure individually
        print(f"[WARNING] Configuring interfaces individually (some are connected)")
        
        for port in ["1", "2"]:
            interface = f"{interface_prefix}1/1/{port}"
            
            if interface in connected_interfaces:
                print(f"[SKIP] Skipping {interface} - it's connected!")
                continue
            
            print(f"\n{'~'*40}")
            print(f"CONFIGURING: {interface}")
            print(f"{'~'*40}")
            
            int_commands = [
                "configure terminal",
                f"interface {interface}",
                "description PORT-CHANNEL-MEMBER",
                "switchport mode trunk",
                "switchport trunk allowed vlan all",
                "spanning-tree portfast trunk",
                f"channel-group {po_group} mode active",
                "no shutdown",
                "end"
            ]
            
            for cmd in int_commands:
                send_command(shell, cmd)
            
            print(f"[OK] {interface} added to Port-channel{po_group}")
    else:
        # All interfaces are available, use interface range
        print(f"\n{'~'*40}")
        print(f"CONFIGURING INTERFACE RANGE: {interface_prefix}1/1/1-2")
        print(f"{'~'*40}")
        
        # Use interface range command
        range_commands = [
            "configure terminal",
            f"interface range {interface_prefix}1/1/1-2",
            "description PORT-CHANNEL-MEMBER",
            "switchport mode trunk",
            "switchport trunk allowed vlan all",
            "spanning-tree portfast trunk",
            f"channel-group {po_group} mode active",
            "no shutdown",
            "end"
        ]
        
        for cmd in range_commands:
            send_command(shell, cmd)
        
        print(f"[OK] Interface range added to Port-channel{po_group}")
    
    return True

def verify_configuration(shell, interface_prefix, po_group):
    """Verify port channel configuration"""
    print(f"\n{'~'*40}")
    print(f"VERIFICATION FOR Port-channel{po_group}")
    print(f"{'~'*40}")
    
    # 1. Show port-channel summary
    print("\n[VERIFY] Port-channel Summary:")
    send_command(shell, "show etherchannel summary")
    
    # 2. Show interface status
    print("\n[VERIFY] Interface Status:")
    if interface_prefix == "GigabitEthernet":
        send_command(shell, "show interfaces status | include Gi1/1/")
    else:
        send_command(shell, f"show interfaces status | include {interface_prefix}1/1/")
    
    # 3. Show port-channel details
    print("\n[VERIFY] Port-channel Details:")
    send_command(shell, f"show interfaces Port-channel{po_group}")
    
    # 4. Show running config for interfaces
    print("\n[VERIFY] Running Config for Interfaces:")
    for port in ["1", "2"]:
        interface = f"{interface_prefix}1/1/{port}"
        if interface_prefix == "GigabitEthernet":
            send_command(shell, f"show run int Gi1/1/{port}")
        else:
            send_command(shell, f"show run int {interface}")
    
    # 5. Show port-channel switchport config
    print("\n[VERIFY] Port-channel Switchport Configuration:")
    send_command(shell, f"show interfaces Port-channel{po_group} switchport")

def main():
    print("="*70)
    print("PORT CHANNEL CONFIGURATION SCRIPT")
    print("="*70)
    print("Features:")
    print("- Auto-detects GigabitEthernet vs TenGigabitEthernet")
    print("- Uses interface range (gig1/1/1-2) when possible")
    print("- Checks interface connectivity before configuring")
    print("- Configures individual interfaces if range has connected ports")
    print("- Full verification after configuration")
    print("="*70)
    
    try:
        # Connect to core switch
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(CORE_IP, username=USERNAME, password=PASSWORD, timeout=20)
        print("✓ Connected to Core Switch")
        
        shell = ssh.invoke_shell()
        shell.settimeout(10)
        time.sleep(3)
        
        # Read initial banner
        read_shell_output(shell)
        
        for switch_ip, po_group in ACCESS_SWITCHES.items():
            print(f"\n{'='*70}")
            print(f"CONFIGURING: {switch_ip}")
            print(f"Port-Channel Group: {po_group}")
            print(f"{'='*70}")
            
            # SSH to access switch
            print(f"\n[SSH] Connecting to {switch_ip}...")
            shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
            time.sleep(3)
            read_shell_output(shell)
            
            # Send password
            print(f"\n[SSH] Sending password...")
            shell.send(f"{PASSWORD}\n")
            time.sleep(3)
            read_shell_output(shell)
            
            # Determine interface naming convention
            interface_prefix = get_interface_prefix(shell)
            
            # Check interface availability
            available, connected_interfaces = check_interface_range_availability(shell, interface_prefix)
            
            if not available:
                print(f"\n❌ Cannot configure {switch_ip} - interfaces not available")
                print("[SSH] Exiting switch...")
                shell.send("exit\n")
                time.sleep(2)
                read_shell_output(shell)
                continue
            
            # Configure port channel
            success = configure_port_channel(shell, interface_prefix, po_group, connected_interfaces)
            
            if success:
                # Verify configuration
                verify_configuration(shell, interface_prefix, po_group)
                
                print(f"\n[SSH] Exiting {switch_ip}...")
                shell.send("exit\n")
                time.sleep(2)
                read_shell_output(shell)
                
                print(f"\n✅ SUCCESS: {switch_ip} → Port-channel{po_group} configured")
            else:
                print(f"\n❌ FAILED: Could not configure Port-channel{po_group} on {switch_ip}")
                print("[SSH] Exiting switch...")
                shell.send("exit\n")
                time.sleep(2)
                read_shell_output(shell)
        
        shell.close()
        ssh.close()
        
        print(f"\n{'='*70}")
        print("CONFIGURATION SUMMARY")
        print("="*70)
        for switch_ip, po_group in ACCESS_SWITCHES.items():
            print(f"  {switch_ip}: Port-channel{po_group}")
        print("="*70)
        print("✓ Script execution completed")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
    main()