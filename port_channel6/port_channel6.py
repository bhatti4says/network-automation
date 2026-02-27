#!/usr/bin/env python3
import paramiko
import time
import socket
import re

# Jump host configuration
JUMP_HOST_IP = "192.168.100.111"  # Core SW 01
USERNAME = "cisco"
PASSWORD = "Cisco1234"

# Access switches - updated with IP range and port channel numbers
ACCESS_SWITCHES = {
    "10.20.39.21": 11,
    "10.20.39.22": 11,
    "10.20.39.23": 12, 
    "10.20.39.24": 13,
    "10.20.39.26": 14,
    "10.20.39.28": 15
}

# Desired VLAN configuration
VLAN_CONFIG = "1-16,28,50,90-92,100"

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

def send_command(shell, command, delay=1.5):
    """Send command and return output"""
    print(f"\n[COMMAND] {command}")
    shell.send(f"{command}\n")
    time.sleep(delay)
    output = read_shell_output(shell)
    return output

def get_existing_port_channel_members(shell, po_group):
    """Get existing member interfaces from show etherchannel summary"""
    print(f"\n[CHECK] Getting existing Port-channel{po_group} members...")
    
    output = send_command(shell, "show etherchannel summary", delay=2)
    
    # Parse the output to find interfaces in the specified port-channel group
    member_interfaces = []
    
    # Look for the port-channel group in the output
    lines = output.split('\n')
    found_po = False
    
    for line in lines:
        # Look for line containing the port-channel
        if f"Po{po_group}" in line and not found_po:
            found_po = True
            print(f"[FOUND] Port-channel{po_group} line: {line.strip()}")
            
            # Extract interface names from this line
            # Interfaces are typically listed after the port-channel
            # Format example: "Po11(SU)     Gi1/1/3(P) Gi1/1/4(P)"
            parts = line.strip().split()
            
            # Skip the first part (Po11(SU))
            for part in parts[1:]:
                # Check if this part looks like an interface (contains letters and slashes)
                if any(c.isalpha() for c in part) and '/' in part:
                    # Remove status indicators like (P), (SU), etc.
                    interface = re.sub(r'\([^)]+\)', '', part).strip()
                    if interface:
                        member_interfaces.append(interface)
                        print(f"[INFO] Found member interface: {interface}")
        
        # Also check if port-channel exists in other formats
        elif f"Port-channel{po_group}" in line:
            found_po = True
            print(f"[FOUND] Port-channel{po_group} in alternative format: {line.strip()}")
    
    if not found_po:
        print(f"[INFO] Port-channel{po_group} not found in etherchannel summary")
    elif not member_interfaces:
        print(f"[WARNING] Port-channel{po_group} exists but no member interfaces found")
    
    return member_interfaces

def check_current_port_channel_config(shell, po_group):
    """Check current port channel configuration"""
    print(f"\n[CHECK] Current Port-channel{po_group} configuration...")
    
    output = send_command(shell, f"show running-config interface Port-channel{po_group}", delay=2)
    
    expected_config = [
        f"interface Port-channel{po_group}",
        "description CONFIGURED-BY-SCRIPT",
        f"switchport trunk allowed vlan {VLAN_CONFIG}",
        "switchport mode trunk",
        "spanning-tree link-type point-to-point"
    ]
    
    config_ok = True
    missing_items = []
    
    for item in expected_config:
        if item not in output:
            config_ok = False
            missing_items.append(item)
    
    return config_ok, missing_items, output

def check_member_interface_config(shell, interface, po_group):
    """Check member interface configuration"""
    print(f"\n[CHECK] Checking interface {interface}...")
    
    output = send_command(shell, f"show running-config interface {interface}", delay=2)
    
    expected_config = [
        f"interface {interface}",
        f"channel-group {po_group} mode active",
        f"switchport trunk allowed vlan {VLAN_CONFIG}",
        "switchport mode trunk",
        "spanning-tree link-type point-to-point"
    ]
    
    # For member interfaces, description is optional
    expected_minimum = [
        f"interface {interface}",
        f"channel-group {po_group} mode active",
        "switchport mode trunk"
    ]
    
    config_ok = True
    missing_items = []
    
    # Check minimum required configuration
    for item in expected_minimum:
        if item not in output:
            config_ok = False
            missing_items.append(item)
    
    return config_ok, missing_items, output

def configure_port_channel(shell, po_group):
    """Configure port channel with desired settings"""
    print(f"\n[CONFIG] Configuring Port-channel{po_group}...")
    
    commands = [
        "configure terminal",
        f"interface Port-channel{po_group}",
        "description CONFIGURED-BY-SCRIPT",
        f"switchport trunk allowed vlan {VLAN_CONFIG}",
        "switchport mode trunk",
        "spanning-tree link-type point-to-point",
        "no shutdown",
        "end"
    ]
    
    for cmd in commands:
        send_command(shell, cmd)
    
    print(f"[OK] Port-channel{po_group} configured")

def configure_member_interface(shell, interface, po_group):
    """Configure a member interface with existing channel-group"""
    print(f"\n[CONFIG] Configuring {interface}...")
    
    commands = [
        "configure terminal",
        f"interface {interface}",
        f"description **Port-channel{po_group}-Member**",
        f"switchport trunk allowed vlan {VLAN_CONFIG}",
        "switchport mode trunk",
        f"channel-group {po_group} mode active",  # Keep existing channel-group
        "spanning-tree link-type point-to-point",
        "no shutdown",
        "end"
    ]
    
    for cmd in commands:
        send_command(shell, cmd)
    
    print(f"[OK] {interface} configured for Port-channel{po_group}")

def verify_and_fix_configuration(shell, switch_ip, po_group):
    """Verify and fix configuration for a switch using existing interfaces"""
    print(f"\n{'='*60}")
    print(f"PROCESSING: {switch_ip} (Port-channel{po_group})")
    print(f"{'='*60}")
    
    # Step 1: Get existing member interfaces from etherchannel summary
    member_interfaces = get_existing_port_channel_members(shell, po_group)
    
    if not member_interfaces:
        print(f"[SKIP] No member interfaces found in Port-channel{po_group}. Skipping...")
        return False
    
    print(f"[INFO] Using existing member interfaces: {member_interfaces}")
    
    # Step 2: Check current port channel config
    po_config_ok, po_missing, po_output = check_current_port_channel_config(shell, po_group)
    
    if not po_config_ok:
        print(f"[ACTION] Port-channel{po_group} needs configuration")
        print(f"Missing items: {po_missing}")
        configure_port_channel(shell, po_group)
    else:
        print(f"[OK] Port-channel{po_group} is already properly configured")
    
    # Step 3: Check and configure each existing member interface
    for interface in member_interfaces:
        member_config_ok, member_missing, member_output = check_member_interface_config(shell, interface, po_group)
        
        if not member_config_ok:
            print(f"[ACTION] {interface} needs configuration")
            print(f"Missing items: {member_missing}")
            configure_member_interface(shell, interface, po_group)
        else:
            print(f"[OK] {interface} is already properly configured")
    
    # Step 4: Final verification
    print(f"\n[VERIFY] Final verification for {switch_ip}...")
    
    # Verify port channel
    po_config_ok, _, _ = check_current_port_channel_config(shell, po_group)
    if po_config_ok:
        print(f"✅ Port-channel{po_group}: CONFIGURED")
    else:
        print(f"❌ Port-channel{po_group}: MISCONFIGURED")
    
    # Verify member interfaces
    all_members_ok = True
    for interface in member_interfaces:
        member_config_ok, _, _ = check_member_interface_config(shell, interface, po_group)
        if member_config_ok:
            print(f"✅ {interface}: CONFIGURED")
        else:
            print(f"❌ {interface}: MISCONFIGURED")
            all_members_ok = False
    
    # Show final etherchannel summary
    print(f"\n[VERIFY] Final etherchannel summary:")
    send_command(shell, "show etherchannel summary", delay=2)
    
    # Save configuration
    print(f"\n[SAVE] Saving configuration...")
    send_command(shell, "write memory", delay=3)
    
    return po_config_ok and all_members_ok

def main():
    print("="*70)
    print("PORT CHANNEL CONFIGURATION VERIFICATION & FIX SCRIPT")
    print("="*70)
    print(f"Jump Host: {JUMP_HOST_IP} (Core SW 01)")
    print(f"Access Switches: {', '.join(ACCESS_SWITCHES.keys())}")
    print(f"VLAN Configuration: {VLAN_CONFIG}")
    print("="*70)
    print("NOTE: This script uses EXISTING interfaces from port-channel groups")
    print("It will NOT add or remove interfaces from port-channels")
    print("="*70)
    
    results = {}
    
    try:
        # Connect to jump host (Core SW 01)
        print(f"\n[CONNECT] Connecting to jump host {JUMP_HOST_IP}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(JUMP_HOST_IP, username=USERNAME, password=PASSWORD, timeout=20)
        print("✓ Connected to Core SW 01")
        
        shell = ssh.invoke_shell()
        shell.settimeout(10)
        time.sleep(3)
        
        # Read initial banner
        read_shell_output(shell)
        
        for switch_ip, po_group in ACCESS_SWITCHES.items():
            print(f"\n{'='*70}")
            print(f"PROCESSING SWITCH: {switch_ip}")
            print(f"Port-Channel Group: {po_group}")
            print(f"{'='*70}")
            
            # SSH to access switch
            print(f"\n[SSH] Connecting to {switch_ip}...")
            shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
            time.sleep(3)
            read_shell_output(shell)
            
            # Send password if prompted
            print(f"\n[SSH] Sending credentials...")
            shell.send(f"{PASSWORD}\n")
            time.sleep(3)
            read_shell_output(shell)
            
            # Set terminal length for better output
            send_command(shell, "terminal length 0", delay=1)
            
            # Verify and fix configuration using existing interfaces
            success = verify_and_fix_configuration(shell, switch_ip, po_group)
            
            if success:
                print(f"\n✅ COMPLETE: {switch_ip} is properly configured")
                results[switch_ip] = "SUCCESS"
            else:
                print(f"\n⚠️ ATTENTION: {switch_ip} may need manual verification")
                results[switch_ip] = "NEEDS_ATTENTION"
            
            # Exit from access switch
            print(f"\n[SSH] Exiting {switch_ip}...")
            shell.send("exit\n")
            time.sleep(2)
            read_shell_output(shell)
        
        # Close connection
        shell.close()
        ssh.close()
        
        # Final summary
        print(f"\n{'='*70}")
        print("CONFIGURATION SUMMARY")
        print("="*70)
        
        success_count = 0
        for switch_ip, po_group in ACCESS_SWITCHES.items():
            status = results.get(switch_ip, "UNKNOWN")
            status_symbol = "✅" if status == "SUCCESS" else "⚠️" if status == "NEEDS_ATTENTION" else "❌"
            print(f"  {status_symbol} {switch_ip}: Port-channel{po_group} - {status}")
            if status == "SUCCESS":
                success_count += 1
        
        print(f"\nTotal: {success_count}/{len(ACCESS_SWITCHES)} switches properly configured")
      print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()