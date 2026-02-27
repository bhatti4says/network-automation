#!/usr/bin/env python3
import paramiko
import time
import socket

CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Cisco1234"

ACCESS_SWITCHES = [
    "10.20.39.22",
    "10.20.39.23", 
    "10.20.39.24",
    "10.20.39.25"
]

# DIFFERENT LOOPBACK IPs FOR EACH SWITCH
LOOPBACK_IPS = {
    "10.20.39.22": "5.5.5.5",
    "10.20.39.23": "6.6.6.6", 
    "10.20.39.24": "7.7.7.7",
    "10.20.39.25": "8.8.8.8"
}

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

print("Configuring Loopback5 on Access Switches...")

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
        print(f"STARTING CONFIGURATION FOR: {switch_ip}")
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
        
        # Get unique IP for this switch
        loopback_ip = LOOPBACK_IPS.get(switch_ip, "5.5.5.5")
        
        print(f"\n[CONFIG] Configuring Loopback5 with IP: {loopback_ip}")
        
        commands = [
            "configure terminal",
            f"interface loopback5",
            "description TEST-LOOPBACK",
            f"ip address {loopback_ip} 255.255.255.255",
            "no shutdown",
            "end",
            "write memory",
            "show run interface loopback5"  # Show the result!
        ]
        
        for cmd in commands:
            print(f"\n[COMMAND] {cmd}")
            shell.send(f"{cmd}\n")
            time.sleep(1.5)
            # Read and display the response
            output = read_shell_output(shell)
            # If it's a show command, display it nicely
            if cmd.startswith("show"):
                print(f"\n[OUTPUT from {switch_ip}]:")
                print("-" * 40)
                print(output)
                print("-" * 40)
        
        print(f"\n[SSH] Exiting {switch_ip}...")
        shell.send("exit\n")
        time.sleep(2)
        read_shell_output(shell)
        
        print(f"\n✓ COMPLETED: {switch_ip} → Loopback5: {loopback_ip}")
    
    shell.close()
    ssh.close()
    
    print(f"\n{'='*60}")
    print("✓ ALL SWITCHES CONFIGURED SUCCESSFULLY!")
    print("IP Assignments Summary:")
    for switch_ip in ACCESS_SWITCHES:
        print(f"  {switch_ip}: {LOOPBACK_IPS[switch_ip]}")
    print(f"{'='*60}")
    
except Exception as e:
    print(f"\n✗ ERROR: {e}")

input("\nPress Enter to exit...")