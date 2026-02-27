#!/usr/bin/env python3
import paramiko
import time
import socket
import re
from datetime import datetime

# Core switch for SSH hopping
CORE_IP = "10.20.39.20"
USERNAME = "cisco"
PASSWORD = "Cisco1234"

# Access switches - IPs from .21 to .26
ACCESS_SWITCHES = {
    "10.20.39.21": 11,
    "10.20.39.22": 12, 
    "10.20.39.23": 13,
    "10.20.39.24": 14,
    "10.20.39.25": 15,
    "10.20.39.26": 16
}

# MOTD Banner configuration
MOTD_BANNER = """***********************************************************************
*                                                                     *
*              AUTHORIZED ACCESS ONLY                                 *
*                                                                     *
* This system is the property of HLNSPC-NADEC Data Center.            *
* Unauthorized access or use is prohibited and may result in          *
* disciplinary action or criminal prosecution.                         *
*                                                                     *
* All activities on this system are logged and monitored.             *
*                                                                     *
* If you are not an authorized user, disconnect immediately.          *
*                                                                     *
***********************************************************************"""

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

def send_command(shell, command, delay=1.5, expect_enable=False):
    """Send command and return output"""
    print(f"\n[COMMAND] {command}")
    shell.send(f"{command}\n")
    
    # Handle enable mode if needed
    if expect_enable and "Password:" in read_shell_output(shell, 1):
        # Some switches might ask for enable password
        shell.send("\n")  # Send empty (no password)
        time.sleep(1)
    
    time.sleep(delay)
    output = read_shell_output(shell)
    return output

def configure_clock_and_banner(shell, switch_ip):
    """Configure clock and MOTD banner on switch"""
    print(f"\n{'~'*50}")
    print(f"CONFIGURING CLOCK & BANNER ON {switch_ip}")
    print(f"{'~'*50}")
    
    results = {}
    
    try:
        # Step 1: Set terminal length for better output
        send_command(shell, "terminal length 0")
        
        # Step 2: Check current clock
        print("\n[CHECK] Current clock status:")
        output = send_command(shell, "show clock", delay=2)
        
        # Step 3: Configure clock (GMT+3)
        print("\n[CONFIG] Setting clock to GMT+3...")
        
        # Get current date and time for reference
        now = datetime.now()
        current_year = now.year
        
        # Set timezone to GMT+3 (AST - Arabia Standard Time)
        clock_commands = [
            "configure terminal",
            "clock timezone AST 3 0",  # GMT+3 hours, 0 minutes
            "end",
            f"clock set {current_year} {now.month} {now.day} {now.hour:02d}:{now.minute:02d}:{now.second:02d}",
            "show clock"
        ]
        
        for cmd in clock_commands:
            output = send_command(shell, cmd, delay=2)
        
        # Verify clock setting
        output = send_command(shell, "show clock", delay=2)
        if "AST" in output or "+03" in output:
            print("✅ Clock configured successfully")
            results['clock'] = "SUCCESS"
        else:
            print("⚠️ Clock may not be set correctly")
            results['clock'] = "NEEDS_VERIFICATION"
        
        # Step 4: Configure MOTD Banner
        print("\n[CONFIG] Configuring MOTD banner...")
        
        banner_commands = [
            "configure terminal",
            "no banner motd",  # Clear any existing banner
        ]
        
        # Add each line of the banner
        banner_lines = MOTD_BANNER.split('\n')
        banner_commands.append("banner motd ^")
        
        for line in banner_lines:
            banner_commands.append(line)
        
        banner_commands.append("^")
        banner_commands.append("end")
        banner_commands.append("show banner motd")
        
        for cmd in banner_commands:
            output = send_command(shell, cmd, delay=1)
        
        # Verify banner
        output = send_command(shell, "show banner motd", delay=2)
        if "AUTHORIZED ACCESS ONLY" in output or "HLNSPC-NADEC" in output:
            print("✅ MOTD banner configured successfully")
            results['banner'] = "SUCCESS"
        else:
            print("⚠️ Banner may not be set correctly")
            results['banner'] = "NEEDS_VERIFICATION"
        
        # Step 5: Save configuration
        print("\n[CONFIG] Saving configuration...")
        
        # Try different save methods
        save_attempts = [
            "write memory",
            "copy running-config startup-config",
            "wr"
        ]
        
        saved = False
        for save_cmd in save_attempts:
            output = send_command(shell, save_cmd, delay=3)
            if "OK" in output or "Building configuration" in output or "[OK]" in output:
                print("✅ Configuration saved successfully")
                saved = True
                break
        
        if not saved:
            print("⚠️ Could not confirm configuration save")
        
        results['save'] = "SUCCESS" if saved else "NEEDS_VERIFICATION"
        
        # Step 6: Final verification
        print("\n[VERIFY] Final verification:")
        
        verify_commands = [
            "show clock",
            "show banner motd",
            "show running-config | include clock timezone",
            "show running-config | include banner motd"
        ]
        
        for cmd in verify_commands:
            send_command(shell, cmd, delay=1.5)
        
        return results
        
    except Exception as e:
        print(f"❌ Error configuring {switch_ip}: {e}")
        return {"error": str(e)}

def handle_enable_mode(shell, switch_ip):
    """Handle enable mode if required"""
    print(f"\n[CHECK] Checking if enable mode is required on {switch_ip}...")
    
    # Send enable command
    shell.send("enable\n")
    time.sleep(2)
    
    output = read_shell_output(shell)
    
    if "Password:" in output:
        print("[INFO] Switch requires enable password")
        # Try empty password (some switches have no enable secret)
        shell.send("\n")
        time.sleep(2)
        output = read_shell_output(shell)
        
        if "Password:" in output or "Access denied" in output:
            # Try the same password as login
            shell.send(f"{PASSWORD}\n")
            time.sleep(2)
            output = read_shell_output(shell)
    
    # Check if we're in enable mode
    if "#" in output:
        print("✅ Successfully entered enable mode")
        return True
    else:
        print("⚠️ Not in enable mode, may have limited privileges")
        return False

def main():
    print("="*70)
    print("ACCESS SWITCH CLOCK & BANNER CONFIGURATION SCRIPT")
    print("="*70)
    print("Tasks:")
    print("1. Set clock to GMT+3 (AST)")
    print("2. Configure MOTD banner")
    print("3. Save configuration")
    print("="*70)
    
    all_results = {}
    
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
            print(f"{'='*70}")
            
            try:
                # SSH to access switch
                print(f"\n[SSH] Connecting to {switch_ip}...")
                shell.send(f"ssh -l {USERNAME} {switch_ip}\n")
                time.sleep(3)
                output = read_shell_output(shell)
                
                # Check if SSH connection was successful
                if "refused" in output.lower() or "failed" in output.lower():
                    print(f"❌ Cannot connect to {switch_ip}")
                    all_results[switch_ip] = {"status": "CONNECTION_FAILED"}
                    continue
                
                # Send password
                print(f"\n[SSH] Sending password...")
                shell.send(f"{PASSWORD}\n")
                time.sleep(3)
                read_shell_output(shell)
                
                # Handle enable mode if needed
                in_enable = handle_enable_mode(shell, switch_ip)
                
                # Configure clock and banner
                results = configure_clock_and_banner(shell, switch_ip)
                
                # Store results
                all_results[switch_ip] = {
                    "status": "COMPLETED",
                    "in_enable_mode": in_enable,
                    "results": results
                }
                
                print(f"\n✅ Completed configuration on {switch_ip}")
                
            except Exception as e:
                print(f"❌ Error on {switch_ip}: {e}")
                all_results[switch_ip] = {"status": "ERROR", "error": str(e)}
            
            finally:
                # Exit switch
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
        for switch_ip in ACCESS_SWITCHES:
            result = all_results.get(switch_ip, {})
            status = result.get("status", "UNKNOWN")
            
            if status == "COMPLETED":
                # Check individual component results
                comp_results = result.get("results", {})
                clock_status = comp_results.get('clock', 'UNKNOWN')
                banner_status = comp_results.get('banner', 'UNKNOWN')
                save_status = comp_results.get('save', 'UNKNOWN')
                
                all_ok = (clock_status == "SUCCESS" and 
                         banner_status == "SUCCESS" and 
                         save_status == "SUCCESS")
                
                if all_ok:
                    print(f"  ✅ {switch_ip}: COMPLETE SUCCESS")
                    success_count += 1
                else:
                    print(f"  ⚠️ {switch_ip}: PARTIAL - Clock:{clock_status}, Banner:{banner_status}, Save:{save_status}")
            elif status == "CONNECTION_FAILED":
                print(f"  ❌ {switch_ip}: CONNECTION FAILED")
            elif status == "ERROR":
                error_msg = result.get("error", "Unknown error")
                print(f"  ❌ {switch_ip}: ERROR - {error_msg[:50]}...")
            else:
                print(f"  ❓ {switch_ip}: UNKNOWN STATUS")
        
        print(f"\nSummary: {success_count}/{len(ACCESS_SWITCHES)} switches configured successfully")
        print("="*70)
        
        if success_count == len(ACCESS_SWITCHES):
            print("🎉 ALL SWITCHES CONFIGURED SUCCESSFULLY!")
        elif success_count > 0:
            print("ℹ️ Some switches configured, check individual results above")
        else:
            print("❌ No switches were configured successfully")
        
    except Exception as e:
        print(f"\n❌ MAIN ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()