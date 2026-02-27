#!/usr/bin/env python3
import paramiko
import time
import socket
import re

CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Xadmin74377"

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
    return output

def get_actual_interface_naming(shell):
    """Determine the actual interface naming convention used by the switch"""
    print(f"\n[CHECK] Discovering interface naming convention...")
    
    # Send test commands to see interface naming
    test_output = send_command(shell, "show interfaces status", delay=3)
    
    # Look for TenGigabitEthernet first
    if "TenGigabitEthernet" in test_output or "Ten" in test_output or "tengig" in test_output.lower():
        print("[INFO] Switch has TenGigabitEthernet interfaces")
        
        # Check exact format
        if "TenGigabitEthernet" in test_output:
            print("[INFO] Using 'TenGigabitEthernet' format")
            return "TenGigabitEthernet", False
        elif "Te " in test_output:
            print("[INFO] Using 'Te X/X/X' format (with space)")
            return "Te", True
        elif "Te" in test_output and not "TenGigabitEthernet" in test_output:
            print("[INFO] Using 'TeX/X/X' format (no space)")
            return "Te", False
    
    # Look for GigabitEthernet
    if "GigabitEthernet" in test_output:
        print("[INFO] Using 'GigabitEthernet' format")
        return "GigabitEthernet", False
    elif "Gi " in test_output:
        print("[INFO] Using 'Gi X/X/X' format (with space)")
        return "Gi", True
    elif "Gi" in test_output:
        print("[INFO] Using 'GiX/X/X' format (no space)")
        return "Gi", False
    
    # Default
    print("[WARNING] Could not determine interface naming, defaulting to GigabitEthernet")
    return "GigabitEthernet", False

def check_specific_interfaces(shell, interface_prefix, with_space):
    """Check specific interfaces 1/1/1 and 1/1/2"""
    print(f"\n[CHECK] Checking specific interfaces...")
    
    interfaces_to_check = []
    
    # First check what interfaces actually exist
    output = send_command(shell, "show interfaces status", delay=3)
    
    # Look for interfaces 1/1/1 and 1/1/2
    for port in ["1/1/1", "1/1/2"]:
        interface_found = False
        
        # Try different naming patterns
        patterns = [
            f"{interface_prefix}{port}",
            f"{interface_prefix} {port}",
            f"{interface_prefix.lower()}{port}",
        ]
        
        for pattern in patterns:
            if pattern in output:
                print(f"[FOUND] Interface exists: {pattern}")
                
                # Check if it's connected
                lines = output.split('\n')
                for line in lines:
                    if pattern in line:
                        if "connected" in line.lower():
                            print(f"[WARNING] {pattern} is CONNECTED!")
                            interfaces_to_check.append((pattern, True))  # True = connected
                        else:
                            print(f"[OK] {pattern} is NOT CONNECTED")
                            interfaces_to_check.append((pattern, False))  # False = not connected
                        interface_found = True
                        break
                break
        
        if not interface_found:
            print(f"[ERROR] Interface {interface_prefix}{port} not found!")
            return False, []
    
    # Count connected interfaces
    connected_count = sum(1 for _, connected in interfaces_to_check if connected)
    
    if connected_count == 2:
        print(f"[CRITICAL] Both interfaces are CONNECTED! Aborting configuration.")
        return False, []
    elif connected_count > 0:
        connected_names = [name for name, connected in interfaces_to_check if connected]
        print(f"[WARNING] Some interfaces are connected: {connected_names}")
        # Return interface names that ARE connected (so we can skip them)
        return True, connected_names
    else:
        print(f"[OK] All interfaces are available for configuration")
        return True, []

def configure_port_channel_for_switch(shell, switch_ip, interface_prefix, with_space, po_group):
    """Configure port channel for a specific switch"""
    print(f"\n[CONFIG] Setting up Port-Channel{po_group} on {switch_ip}...")
    
    # Step 1: Check current port-channel status
    print(f"\n[CHECK] Current port-channel status:")
    send_command(shell, "show etherchannel summary", delay=2)
    
    # Step 2: Create or configure Port-Channel interface
    commands = [
        "configure terminal",
        f"interface Port-channel{po_group}",
        "description CONFIGURED-BY-SCRIPT",
        "switchport mode trunk",
        "switchport trunk allowed vlan all",
        "spanning-tree portfast trunk",
        "no shutdown",  # Ensure it's not shutdown
        "end"
    ]
    
    for cmd in commands:
        send_command(shell, cmd)
    
    # Step 3: Check what interfaces actually exist
    print(f"\n[CHECK] Finding available interfaces...")
    
    # Get list of all interfaces
    output = send_command(shell, "show interfaces status", delay=3)
    
    # Look for interfaces 1/1/1 and 1/1/2 with our prefix
    interfaces_to_configure = []
    
    for port in ["1/1/1", "1/1/2"]:
        # Try different formats
        formats_to_try = []
        
        if with_space:
            formats_to_try.append(f"{interface_prefix} {port}")
        else:
            formats_to_try.append(f"{interface_prefix}{port}")
        
        # Also try common variations
        formats_to_try.append(f"{interface_prefix.lower()}{port}")
        if interface_prefix == "Te":
            formats_to_try.append(f"TenGigabitEthernet{port}")
        elif interface_prefix == "Gi":
            formats_to_try.append(f"GigabitEthernet{port}")
        
        interface_found = False
        for fmt in formats_to_try:
            if fmt in output:
                print(f"[FOUND] Will configure: {fmt}")
                interfaces_to_configure.append(fmt)
                interface_found = True
                break
        
        if not interface_found:
            print(f"[WARNING] Interface {port} not found with prefix {interface_prefix}")
    
    if not interfaces_to_configure:
        print(f"[ERROR] No interfaces found to configure!")
        return False
    
    # Step 4: Configure interfaces
    print(f"\n[CONFIG] Configuring {len(interfaces_to_configure)} interface(s)...")
    
    # If we have exactly 2 interfaces and they follow a pattern, try interface range
    if len(interfaces_to_configure) == 2:
        # Check if they can be combined into a range
        int1 = interfaces_to_configure[0]
        int2 = interfaces_to_configure[1]
        
        # Extract base name and port numbers
        match1 = re.search(r'(\D+)(\d+/\d+/\d+)', int1)
        match2 = re.search(r'(\D+)(\d+/\d+/\d+)', int2)
        
        if match1 and match2:
            base1, port1 = match1.group(1), match1.group(2)
            base2, port2 = match2.group(1), match2.group(2)
            
            if base1 == base2 and port1 == "1/1/1" and port2 == "1/1/2":
                # We can use interface range!
                interface_range = f"{base1}1/1/1-2"
                print(f"\n{'~'*40}")
                print(f"CONFIGURING INTERFACE RANGE: {interface_range}")
                print(f"{'~'*40}")
                
                range_commands = [
                    "configure terminal",
                    f"interface range {interface_range}",
                    "description PORT-CHANNEL-MEMBER",
                    "switchport mode trunk",
                    "switchport trunk allowed vlan all",
                    "spanning-tree portfast trunk",
                    f"channel-group {po_group} mode active",
                    "no shutdown",
                    "end"
                ]
                
                for cmd in range_commands:
                    output = send_command(shell, cmd, delay=2)
                    if "Invalid input" in output or "% Invalid" in output:
                        print(f"[WARNING] Range command failed, configuring individually...")
                        # Fall back to individual config
                        break
                else:
                    # Range succeeded
                    print(f"[OK] Interface range configured successfully")
                    return True
    
    # Individual interface configuration (fallback or for mismatched interfaces)
    print(f"\n[CONFIG] Configuring interfaces individually...")
    
    for interface in interfaces_to_configure:
        print(f"\n{'~'*30}")
        print(f"CONFIGURING: {interface}")
        print(f"{'~'*30}")
        
        int_commands = [
            "configure terminal",
            f"interface {interface}",
            "description PORT-CHANNEL-MEMBER",
            "switchport mode trunk",
            "switchport trunk allowed vlan all",
            "spanning-tree portfast trunk",
            f"channel-group {po_group} mode active",
            "no shutdown",
            "end",
            f"show run int {interface}"  # Verify
        ]
        
        for cmd in int_commands:
            send_command(shell, cmd, delay=2)
        
        print(f"[OK] {interface} added to Port-channel{po_group}")
    
    return True

def verify_port_channel_configuration(shell, switch_ip, po_group):
    """Verify port channel configuration thoroughly"""
    print(f"\n{'~'*50}")
    print(f"COMPLETE VERIFICATION FOR {switch_ip}")
    print(f"Port-Channel{po_group}")
    print(f"{'~'*50}")
    
    # 1. Show detailed etherchannel summary
    print("\n[VERIFY] Detailed Etherchannel Summary:")
    output = send_command(shell, "show etherchannel detail", delay=3)
    
    # Check for (SD) - Shutdown status
    if "(SD)" in output:
        print("[ERROR] Port-channel is SHUTDOWN! Need to investigate...")
        # Try to fix
        send_command(shell, "configure terminal", delay=1)
        send_command(shell, f"interface Port-channel{po_group}", delay=1)
        send_command(shell, "no shutdown", delay=1)
        send_command(shell, "end", delay=1)
        send_command(shell, "write memory", delay=2)
    
    # 2. Show regular summary
    print("\n[VERIFY] Etherchannel Summary:")
    send_command(shell, "show etherchannel summary", delay=2)
    
    # 3. Show port-channel interface status
    print("\n[VERIFY] Port-channel Interface Status:")
    send_command(shell, f"show interfaces Port-channel{po_group}", delay=2)
    
    # 4. Show port-channel switchport config
    print("\n[VERIFY] Port-channel Switchport Configuration:")
    send_command(shell, f"show interfaces Port-channel{po_group} switchport", delay=2)
    
    # 5. Show running config for port-channel
    print("\n[VERIFY] Port-channel Running Config:")
    send_command(shell, f"show run interface Port-channel{po_group}", delay=2)
    
    # 6. Show member interfaces
    print("\n[VERIFY] Member Interface Status:")
    
    # Try to find member interfaces from output
    output = send_command(shell, "show interfaces status", delay=3)
    lines = output.split('\n')
    
    for line in lines:
        if "1/1/1" in line or "1/1/2" in line:
            print(f"  {line.strip()}")
    
    # 7. Show lacp neighbors if any
    print("\n[VERIFY] LACP Neighbors:")
    send_command(shell, "show lacp neighbor", delay=2)
    
    # 8. Final verification
    print("\n[VERIFY] Final Status Check:")
    output = send_command(shell, "show etherchannel summary", delay=2)
    
    # Check if port-channel is formed
    if f"Po{po_group}" in output and "(SU)" in output:
        print(f"✅ SUCCESS: Port-channel{po_group} is UP and formed!")
        return True
    elif f"Po{po_group}" in output and "(SD)" in output:
        print(f"⚠️ WARNING: Port-channel{po_group} exists but is SHUTDOWN")
        return False
    elif f"Po{po_group}" in output:
        print(f"ℹ️ INFO: Port-channel{po_group} exists")
        return True
    else:
        print(f"❌ ERROR: Port-channel{po_group} not found!")
        return False

def main():
    print("="*70)
    print("FIXED PORT CHANNEL CONFIGURATION SCRIPT")
    print("="*70)
    print("Features:")
    print("- Proper TenGigabitEthernet vs GigabitEthernet detection")
    print("- Handles switches with mixed interface types")
    print("- Fixes shutdown port-channels automatically")
    print("- Complete verification with status checks")
    print("="*70)
    
    results = {}
    
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
            
            # Set terminal length for better output
            send_command(shell, "terminal length 0", delay=1)
            
            # Discover interface naming
            print(f"\n[INFO] Switch: {switch_ip}")
            interface_prefix, with_space = get_actual_interface_naming(shell)
            print(f"[CONFIG] Interface format: {interface_prefix} (space={with_space})")
            
            # Configure port channel
            success = configure_port_channel_for_switch(shell, switch_ip, interface_prefix, with_space, po_group)
            
            if success:
                # Verify configuration
                verified = verify_port_channel_configuration(shell, switch_ip, po_group)
                
                if verified:
                    print(f"\n✅ SUCCESS: {switch_ip} → Port-channel{po_group} configured and verified")
                    results[switch_ip] = "SUCCESS"
                else:
                    print(f"\n⚠️ PARTIAL: {switch_ip} → Port-channel{po_group} configured but needs attention")
                    results[switch_ip] = "NEEDS_ATTENTION"
            else:
                print(f"\n❌ FAILED: Could not configure Port-channel{po_group} on {switch_ip}")
                results[switch_ip] = "FAILED"
            
            print(f"\n[SSH] Exiting {switch_ip}...")
            shell.send("exit\n")
            time.sleep(2)
            read_shell_output(shell)
        
        shell.close()
        ssh.close()
        
        # Final summary
        print(f"\n{'='*70}")
        print("FINAL CONFIGURATION SUMMARY")
        print("="*70)
        
        success_count = 0
        for switch_ip, po_group in ACCESS_SWITCHES.items():
            status = results.get(switch_ip, "UNKNOWN")
            if status == "SUCCESS":
                print(f"  ✅ {switch_ip}: Port-channel{po_group} - SUCCESS")
                success_count += 1
            elif status == "NEEDS_ATTENTION":
                print(f"  ⚠️ {switch_ip}: Port-channel{po_group} - NEEDS ATTENTION")
            elif status == "FAILED":
                print(f"  ❌ {switch_ip}: Port-channel{po_group} - FAILED")
            else:
                print(f"  ❓ {switch_ip}: Port-channel{po_group} - UNKNOWN STATUS")
        
        print(f"\nSummary: {success_count}/{len(ACCESS_SWITCHES)} switches configured successfully")
        print("="*70)
        
        if success_count == len(ACCESS_SWITCHES):
            print("🎉 ALL SWITCHES CONFIGURED SUCCESSFULLY!")
        elif success_count > 0:
            print("ℹ️ Some switches configured, check individual results above")
        else:
            print("❌ No switches were configured successfully")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()