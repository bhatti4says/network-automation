#!/usr/bin/env python3
"""
Simple VTP Auto-Configuration
SSH to Core Switch, then to each Access Switch, run VTP commands
"""

import paramiko
import time

# Configuration - CHANGE NOTHING HERE
CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Xadmin74377"

ACCESS_SWITCHES = [
    "10.20.39.22",  # NSPC-AccSW-2A
    "10.20.39.23",  # NSPC-AccSW-2B  
    "10.20.39.24",  # NSPC-AccSW-3
    "10.20.39.25"   # NSPC-AccSW-4B
]

print("=" * 60)
print("VTP AUTO-CONFIGURATION SCRIPT")
print("=" * 60)
print(f"Core Switch: {CORE_IP}")
print(f"Username: {USERNAME}")
print(f"Access Switches: {len(ACCESS_SWITCHES)}")
print("=" * 60)

try:
    # Step 1: Connect to Core Switch
    print(f"\n[1] Connecting to Core Switch {CORE_IP}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(CORE_IP, username=USERNAME, password=PASSWORD, timeout=15)
    print("✓ Connected to Core Switch")
    
    # Step 2: Open interactive shell on Core
    shell = ssh.invoke_shell()
    time.sleep(2)
    
    # Clear any initial output
    if shell.recv_ready():
        shell.recv(4096)
    
    # Step 3: Configure each Access Switch
    print(f"\n[2] Configuring {len(ACCESS_SWITCHES)} Access Switches...")
    print("-" * 60)
    
    for i, switch_ip in enumerate(ACCESS_SWITCHES, 1):
        print(f"\nSwitch {i}/{len(ACCESS_SWITCHES)}: {switch_ip}")
        
        # SSH from Core to Access Switch
        shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
        time.sleep(3)
        
        # Send password
        shell.send(f"{PASSWORD}\n")
        time.sleep(2)
        
        # Send VTP configuration commands
        vtp_commands = [
            "vtp version 3",
            "vtp domain nadec.com.sa", 
            "vtp mode client",
            "vtp password Xadmin74377 hidden",
            "vtp pruning",
            "end",
            "wr"
        ]
        
        for cmd in vtp_commands:
            shell.send(f"{cmd}\n")
            time.sleep(1.5)
        
        # Verify
        shell.send("show vtp status\n")
        time.sleep(2)
        
        # Exit back to Core Switch
        shell.send("exit\n")
        time.sleep(2)
        
        print(f"  ✓ Configuration sent to {switch_ip}")
        
        # Small delay before next switch
        if i < len(ACCESS_SWITCHES):
            print("  Waiting 5 seconds...")
            time.sleep(5)
    
    # Step 4: Close connection
    shell.close()
    ssh.close()
    
    print("\n" + "=" * 60)
    print("SCRIPT COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print("\nManual verification (optional):")
    for switch_ip in ACCESS_SWITCHES:
        print(f"  ssh -l {USERNAME} {switch_ip}")
        print(f"  show vtp status")
        print(f"  exit")
    print("=" * 60)
    
except Exception as e:
    print(f"\n❌ ERROR: {str(e)}")
    print("\nTroubleshooting:")
    print("1. Check if Core Switch is reachable: ping 192.168.100.110")
    print("2. Check credentials (cisco/Xadmin74377)")
    print("3. Install paramiko: pip install paramiko")

input("\nPress Enter to exit...")
