#!/usr/bin/env python3
import paramiko
import time
import socket

# Core SW 01 as jump host
JUMP_HOST = "10.20.39.20"
USERNAME = "cisco"
PASSWORD = "Cisco1234"

# All switches to configure (via Core SW 01) - JUST IPs
SWITCH_IPS = [
    "10.20.39.27",  # Core switch 02
    "10.20.39.21",
    "10.20.39.22", 
    "10.20.39.23",
    "10.20.39.24",
    "10.20.39.25",
    "10.20.39.26"
]

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
    except Exception as e:
        print(f"[ERROR] Reading output: {e}")
    return output

def send_command(shell, command, delay=1.5):
    """Send command and return output"""
    print(f"\n[COMMAND] {command}")
    shell.send(f"{command}\n")
    time.sleep(delay)
    output = read_shell_output(shell)
    return output

def configure_core_sw01_first():
    """First configure Core SW 01 itself"""
    print(f"\n{'='*70}")
    print("CONFIGURING CORE SW 01 ITSELF FIRST")
    print(f"{'='*70}")
    
    try:
        # Connect to Core SW 01
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(JUMP_HOST, username=USERNAME, password=PASSWORD, timeout=15)
        print("✓ Connected to Core SW 01")
        
        shell = ssh.invoke_shell()
        shell.settimeout(10)
        time.sleep(3)
        
        # Read initial banner
        read_shell_output(shell)
        
        # Enter enable mode
        print("\n[ENABLE] Entering enable mode...")
        shell.send("enable\n")
        time.sleep(2)
        output = read_shell_output(shell)
        
        if "Password:" in output:
            shell.send(f"{PASSWORD}\n")
            time.sleep(2)
            read_shell_output(shell)
        
        # Set terminal length
        send_command(shell, "terminal length 0")
        
        # Check current config - FIXED: ip domain name (not domain-name)
        print("\n[CHECK] Current Core SW 01 configuration:")
        send_command(shell, "show running-config | include ip domain name")
        send_command(shell, "show crypto key mypubkey rsa")
        send_command(shell, "show ip ssh")
        
        # Configure domain name - FIXED: ip domain name (not domain-name)
        print("\n[CONFIG] Setting domain name...")
        send_command(shell, "configure terminal")
        send_command(shell, "ip domain name nadec.com.sa")  # FIXED
        
        # Generate RSA keys
        print("\n[CONFIG] Generating RSA keys...")
        send_command(shell, "crypto key generate rsa general-keys modulus 2048", delay=5)
        shell.send("\n")  # Press Enter
        time.sleep(3)
        read_shell_output(shell)
        
        # Configure SSH
        print("\n[CONFIG] Configuring SSH...")
        send_command(shell, "ip ssh version 2")
        send_command(shell, "ip ssh time-out 120")
        send_command(shell, "ip ssh authentication-retries 3")
        
        # Configure VTY lines
        send_command(shell, "line vty 0 4")
        send_command(shell, "transport input ssh")
        send_command(shell, "transport output ssh")
        send_command(shell, "login local")
        send_command(shell, "exit")
        
        # Create local user
        send_command(shell, f"username {USERNAME} privilege 15 secret {PASSWORD}")
        
        send_command(shell, "end")
        
        # Save config
        print("\n[SAVE] Saving configuration...")
        send_command(shell, "write memory", delay=3)
        
        # Verify - FIXED: ip domain name (not domain-name)
        print("\n[VERIFY] Final check:")
        send_command(shell, "show ip ssh")
        send_command(shell, "show crypto key mypubkey rsa | include 2048")
        send_command(shell, "show running-config | include ip domain name")  # FIXED
        
        shell.close()
        ssh.close()
        print("✓ Core SW 01 configured successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error configuring Core SW 01: {e}")
        return False

def configure_switch_via_core(switch_ip):
    """Configure a switch via Core SW 01"""
    print(f"\n{'='*70}")
    print(f"CONFIGURING: {switch_ip} via Core SW 01")
    print(f"{'='*70}")
    
    try:
        # Connect to Core SW 01
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(JUMP_HOST, username=USERNAME, password=PASSWORD, timeout=15)
        
        shell = ssh.invoke_shell()
        shell.settimeout(10)
        time.sleep(3)
        
        # Read initial banner
        read_shell_output(shell)
        
        # Enter enable mode on Core
        shell.send("enable\n")
        time.sleep(2)
        output = read_shell_output(shell)
        
        if "Password:" in output:
            shell.send(f"{PASSWORD}\n")
            time.sleep(2)
            read_shell_output(shell)
        
        # Set terminal length
        send_command(shell, "terminal length 0")
        
        # SSH to target switch - CORRECT FORMAT: ssh 10.20.39.21
        print(f"\n[SSH] Connecting to {switch_ip}...")
        shell.send(f"ssh {switch_ip}\n")
        time.sleep(5)
        
        # Check for password prompt
        output = read_shell_output(shell)
        
        # Look for various password prompts
        password_prompts = ["Password:", "password:", "Pass:"]
        if any(prompt in output for prompt in password_prompts):
            print("[SSH] Sending password...")
            shell.send(f"{PASSWORD}\n")
            time.sleep(3)
            output = read_shell_output(shell)
        
        # Check if we're connected
        if ">" not in output and "#" not in output:
            # Try to get prompt
            shell.send("\n")
            time.sleep(2)
            output = read_shell_output(shell)
            
            if ">" not in output and "#" not in output:
                print(f"❌ Could not connect to {switch_ip}")
                print(f"Output: {output[:200]}")
                return {"status": "CONNECTION_FAILED"}
        
        # Enter enable mode on target
        print("\n[ENABLE] Entering enable mode on target...")
        shell.send("enable\n")
        time.sleep(2)
        output = read_shell_output(shell)
        
        if "Password:" in output:
            # Try empty password
            shell.send("\n")
            time.sleep(2)
            output = read_shell_output(shell)
            
            if "Password:" in output:
                # Try login password
                shell.send(f"{PASSWORD}\n")
                time.sleep(2)
                read_shell_output(shell)
        
        # Check if in enable mode
        shell.send("\n")
        time.sleep(1)
        output = read_shell_output(shell)
        
        if "#" not in output:
            print("⚠️ Not in enable mode, trying config anyway...")
        
        # Set terminal length
        send_command(shell, "terminal length 0")
        
        # Configure domain name - FIXED: ip domain name (not domain-name)
        print("\n[CONFIG] Setting domain name...")
        output = send_command(shell, "show running-config | include ip domain name")  # FIXED
        
        if "nadec.com.sa" not in output:
            send_command(shell, "configure terminal")
            send_command(shell, "ip domain name nadec.com.sa")  # FIXED
            send_command(shell, "end")
            print("✓ Domain name configured")
        else:
            print("✓ Domain name already set")
        
        # Generate RSA keys
        print("\n[CONFIG] Checking RSA keys...")
        output = send_command(shell, "show crypto key mypubkey rsa", delay=3)
        
        if "2048" not in output and "usage" not in output:
            send_command(shell, "configure terminal")
            send_command(shell, "crypto key generate rsa general-keys modulus 2048", delay=5)
            shell.send("\n")
            time.sleep(3)
            read_shell_output(shell)
            send_command(shell, "end")
            print("✓ RSA keys generated")
        else:
            print("✓ RSA keys already exist")
        
        # Configure SSH
        print("\n[CONFIG] Configuring SSH...")
        send_command(shell, "configure terminal")
        send_command(shell, "ip ssh version 2")
        send_command(shell, "ip ssh time-out 120")
        send_command(shell, "ip ssh authentication-retries 3")
        
        # Configure VTY lines
        send_command(shell, "line vty 0 4")
        send_command(shell, "transport input ssh")
        send_command(shell, "transport output ssh")
        send_command(shell, "login local")
        send_command(shell, "exit")
        
        # Create local user
        send_command(shell, f"username {USERNAME} privilege 15 secret {PASSWORD}")
        
        send_command(shell, "end")
        
        # Save config
        print("\n[SAVE] Saving configuration...")
        send_command(shell, "write memory", delay=3)
        
        # Verify - FIXED: ip domain name (not domain-name)
        print("\n[VERIFY] Final check:")
        send_command(shell, "show ip ssh")
        send_command(shell, "show crypto key mypubkey rsa")
        send_command(shell, "show running-config | include ip domain name")  # FIXED
        
        # Exit target switch
        print(f"\n[EXIT] Exiting {switch_ip}...")
        shell.send("exit\n")
        time.sleep(2)
        read_shell_output(shell)
        
        shell.close()
        ssh.close()
        
        print(f"✓ {switch_ip} configured successfully")
        return {"status": "SUCCESS"}
        
    except Exception as e:
        print(f"❌ Error configuring {switch_ip}: {e}")
        try:
            shell.close()
            ssh.close()
        except:
            pass
        return {"status": "ERROR", "error": str(e)}

def main():
    print("="*70)
    print("SSH & DOMAIN CONFIGURATION VIA CORE SW 01")
    print("="*70)
    print(f"Jump Host: {JUMP_HOST} (Core SW 01)")
    print(f"Target Switches: {', '.join(SWITCH_IPS)}")
    print("="*70)
    
    # Configure Core SW 01 first
    core_success = configure_core_sw01_first()
    
    if not core_success:
        print("\n⚠️ Core SW 01 configuration failed")
        print("Continuing with other switches anyway...")
    
    # Configure all switches
    print(f"\n{'='*70}")
    print("CONFIGURING ALL SWITCHES")
    print(f"{'='*70}")
    
    results = {}
    for switch_ip in SWITCH_IPS:
        result = configure_switch_via_core(switch_ip)
        results[switch_ip] = result
        time.sleep(2)  # Pause between switches
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print("="*70)
    
    success_count = 0
    for switch_ip in SWITCH_IPS:
        result = results.get(switch_ip, {})
        if result.get("status") == "SUCCESS":
            print(f"  ✅ {switch_ip}: SUCCESS")
            success_count += 1
        else:
            print(f"  ❌ {switch_ip}: FAILED")
    
    print(f"\nSuccessfully configured: {success_count}/{len(SWITCH_IPS)} switches")
    
    if success_count == len(SWITCH_IPS):
        print("🎉 ALL SWITCHES CONFIGURED!")
    elif success_count > 0:
        print("⚠️ Some switches configured")
    else:
        print("❌ No switches configured")
    
    print("="*70)
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()