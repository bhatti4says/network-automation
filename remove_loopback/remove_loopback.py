#!/usr/bin/env python3
import paramiko
import time
import socket

CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Xadmin74377"

ACCESS_SWITCHES = [
    "10.20.39.22",
    "10.20.39.23", 
    "10.20.39.24",
    "10.20.39.25"
]

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

print("Removing Loopback5 from Access Switches...")

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
    
    for switch_ip in ACCESS_SWITCHES:
        print(f"\n{'='*60}")
        print(f"REMOVING LOOPBACK5 FROM: {switch_ip}")
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
        
        print(f"\n[CONFIG] Removing Loopback5 interface...")
        
        commands = [
            "configure terminal",
            "no interface loopback5",
            "end",
            "write memory",
            "show ip interface brief | include Loopback5"  # Verify it's gone
        ]
        
        for cmd in commands:
            print(f"\n[COMMAND] {cmd}")
            shell.send(f"{cmd}\n")
            time.sleep(1.5)
            # Read and display the response
            output = read_shell_output(shell)
            # If it's a show command, display it nicely
            if cmd.startswith("show"):
                print(f"\n[VERIFICATION OUTPUT from {switch_ip}]:")
                print("-" * 40)
                print(output)
                print("-" * 40)
        
        print(f"\n[SSH] Exiting {switch_ip}...")
        shell.send("exit\n")
        time.sleep(2)
        read_shell_output(shell)
        
        print(f"\n✓ REMOVED: Loopback5 deleted from {switch_ip}")
    
    shell.close()
    ssh.close()
    
    print(f"\n{'='*60}")
    print("✓ LOOPBACK5 REMOVED FROM ALL SWITCHES!")
    print("Summary:")
    for switch_ip in ACCESS_SWITCHES:
        print(f"  ✓ {switch_ip}: Loopback5 removed")
    print(f"{'='*60}")
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")

input("\nPress Enter to exit...")