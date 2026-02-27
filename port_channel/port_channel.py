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

INTERFACES = ["GigabitEthernet1/1/1", "GigabitEthernet1/1/2"]

def read_shell_output(shell, timeout=1):
    """Read available output from shell"""
    output = ""
    shell.settimeout(timeout)
    try:
        while True:
            if shell.recv_ready():
                data = shell.recv(1024).decode('utf-8', errors='ignore')
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
    return read_shell_output(shell)

def check_interface_status(shell, interface):
    """Check if interface is connected/up"""
    print(f"\n[CHECK] Checking status of {interface}...")
    output = send_command(shell, f"show interfaces {interface} status")
    
    # Look for connectivity status in output
    if "connected" in output.lower() or "up" in output.lower() and "down" not in output.lower():
        print(f"[WARNING] {interface} appears to be CONNECTED/UP!")
        return True  # Interface is connected
    else:
        print(f"[OK] {interface} is NOT CONNECTED")
        return False  # Interface is not connected

print("Configuring Port Channels on Access Switches...")

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(CORE_IP, username=USERNAME, password=PASSWORD, timeout=15)
    print("✓ Connected to Core\n")
    
    shell = ssh.invoke_shell()
    shell.settimeout(5)
    time.sleep(2)
    
    # Read initial banner/prompt
    read_shell_output(shell)
    
    for switch_ip, po_group in ACCESS_SWITCHES.items():
        print(f"\n{'='*60}")
        print(f"CONFIGURING PORT CHANNEL ON: {switch_ip}")
        print(f"Port-Channel Group: {po_group}")
        print(f"{'='*60}")
        
        # SSH to access switch
        print(f"\n[SSH] Connecting to {switch_ip}...")
        shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
        time.sleep(2)
        read_shell_output(shell)
        
        # Send password
        print(f"\n[SSH] Sending password...")
        shell.send(f"{PASSWORD}\n")
        time.sleep(2)
        read_shell_output(shell)
        
        print(f"\n[CONFIG] Setting up Port-Channel{po_group}...")
        
        # Step 1: Create Port-Channel interface
        commands = [
            "configure terminal",
            f"interface Port-channel{po_group}",
            "description CONFIGURED-BY-SCRIPT",
            "switchport mode trunk",
            "switchport trunk allowed vlan all",  # No native vlan command
            "spanning-tree portfast trunk",
            "no shutdown",
            "end"
        ]
        
        for cmd in commands:
            send_command(shell, cmd)
        
        # Step 2: Check and configure physical interfaces
        for interface in INTERFACES:
            print(f"\n{'~'*40}")
            print(f"PROCESSING INTERFACE: {interface}")
            print(f"{'~'*40}")
            
            # Check if interface is connected
            if check_interface_status(shell, interface):
                print(f"[SKIP] {interface} is CONNECTED - Skipping configuration!")
                continue
            
            # Configure interface for port channel
            int_commands = [
                "configure terminal",
                f"interface {interface}",
                "description PORT-CHANNEL-MEMBER",
                "switchport mode trunk",
                "switchport trunk allowed vlan all",  # No native vlan command
                "spanning-tree portfast trunk",
                f"channel-group {po_group} mode active",  # Using LACP active mode
                "no shutdown",
                "end"
            ]
            
            for cmd in int_commands:
                send_command(shell, cmd)
            
            print(f"[OK] {interface} added to Port-channel{po_group}")
        
        # Step 3: Verification
        print(f"\n{'~'*40}")
        print(f"VERIFICATION FOR {switch_ip}")
        print(f"{'~'*40}")
        
        # Show port-channel summary
        send_command(shell, "show etherchannel summary")
        
        # Show interface status for configured ports
        send_command(shell, "show interfaces status | include Gi1/1/")
        
        # Show port-channel interface details
        send_command(shell, f"show interfaces Port-channel{po_group} switchport")
        
        print(f"\n[SSH] Exiting {switch_ip}...")
        shell.send("exit\n")
        time.sleep(2)
        read_shell_output(shell)
        
        print(f"\n✓ COMPLETED: {switch_ip} → Port-channel{po_group}")
    
    shell.close()
    ssh.close()
    
    print(f"\n{'='*60}")
    print("✓ PORT CHANNELS CONFIGURED ON ALL SWITCHES!")
    print("Summary:")
    for switch_ip, po_group in ACCESS_SWITCHES.items():
        print(f"  ✓ {switch_ip}: Port-channel{po_group}")
    print(f"Note: Trunks configured without native VLAN assignment")
    print(f"{'='*60}")
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()

input("\nPress Enter to exit...")