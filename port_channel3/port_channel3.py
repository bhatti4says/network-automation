#!/usr/bin/env python3
import paramiko
import time
import socket
import re

# --- Configuration ---
CORE_IP = "192.168.100.110"
USERNAME = "cisco"
PASSWORD = "Cisco1234"

ACCESS_SWITCHES = {
    "10.20.39.22": 11,
    "10.20.39.23": 12, 
    "10.20.39.24": 13, # Known unreachable
    "10.20.39.25": 14  
}

def read_shell_output(shell, timeout=2):
    """Read available output from the shell."""
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

def send_safe_cmd(shell, command, wait=1.5):
    """Flush buffer and send command."""
    read_shell_output(shell, timeout=0.5) 
    shell.send(f"{command}\n")
    time.sleep(wait)
    return read_shell_output(shell)

def get_prefix(shell):
    """Detect if switch uses Te (TenGigabit) or Gi (Gigabit)."""
    output = send_safe_cmd(shell, "show ip interface brief")
    if "Te1/1/1" in output or "TenGigabit" in output:
        return "Te"
    return "Gi"

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(CORE_IP, username=USERNAME, password=PASSWORD, timeout=20)
    
    shell = ssh.invoke_shell()
    time.sleep(2)
    read_shell_output(shell) # Clear core banner

    for switch_ip, po_group in ACCESS_SWITCHES.items():
        print(f"\n\n{'='*60}")
        print(f">>> TARGETING: {switch_ip} (Group {po_group})")
        print(f"{'='*60}")
        
        # Clear buffer before jumping
        read_shell_output(shell, timeout=0.5)
        shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
        
        # FIX: Loop to wait for Password prompt
        authenticated = False
        for _ in range(5): # Try for 10 seconds total
            time.sleep(2)
            response = read_shell_output(shell)
            if "Password:" in response or "word:" in response:
                shell.send(f"{PASSWORD}\n")
                time.sleep(3)
                authenticated = True
                break
            elif "timed out" in response or "refused" in response:
                print(f"\n[!] SKIP: Host {switch_ip} is UNREACHABLE.")
                break
        
        if not authenticated:
            print(f"\n[!] SKIP: No response/Password prompt from {switch_ip}.")
            shell.send("\x03") # Ctrl+C to cancel hung SSH
            time.sleep(1)
            continue

        # Verify successful login
        prompt_check = read_shell_output(shell)
        if "#" not in prompt_check and ">" not in prompt_check:
            print(f" [!] ERROR: Login failed on {switch_ip}.")
            shell.send("exit\n")
            continue

        # CONFIGURATION BLOCK
        send_safe_cmd(shell, "terminal length 0")
        prefix = get_prefix(shell)
        print(f" [INFO] Detected Interface Prefix: {prefix}")
        
        # Safety Check
        status = send_safe_cmd(shell, "show interface status")
        if f"{prefix}1/1/1" in status and "connected" in status.lower():
            print(f" [!] SKIPPING: Interfaces on {switch_ip} are already CONNECTED.")
            send_safe_cmd(shell, "exit")
            continue

        commands = [
            "configure terminal",
            f"interface port-channel {po_group}",
            "switchport mode trunk",
            "exit",
            f"interface range {prefix}1/1/1 - 2",
            "switchport mode trunk",
            f"channel-group {po_group} mode active",
            "end",
            "write memory",
            "show etherchannel summary" 
        ]
        
        for cmd in commands:
            send_safe_cmd(shell, cmd)
        
        print(f"\n [✓] SUCCESS: {switch_ip} is configured.")
        send_safe_cmd(shell, "exit") # Return to Core

    ssh.close()
    print("\n" + "="*60)
    print("ALL ACCESSIBLE HOSTS PROCESSED.")
    print("="*60)

except Exception as e:
    print(f"\n[CRITICAL ERROR] {e}")

input("\nPress Enter to close...")