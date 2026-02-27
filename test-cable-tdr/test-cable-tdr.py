```python
#!/usr/bin/env python3
import paramiko
import time
import re
from tabulate import tabulate

# Access switches to test
ACCESS_SWITCHES = {
    "10.20.39.21": 11,
    "10.20.39.22": 11
}

USERNAME = "cisco"
PASSWORD = "Cisco1234"

def read_shell_output(shell, timeout=2):
    """Read available output from shell"""
    output = ""
    shell.settimeout(timeout)
    try:
        while True:
            if shell.recv_ready():
                data = shell.recv(4096).decode('utf-8', errors='ignore')
                output += data
            else:
                break
    except socket.timeout:
        pass
    return output

def send_command(shell, command, delay=1.5):
    """Send command and return output"""
    shell.send(f"{command}\n")
    time.sleep(delay)
    return read_shell_output(shell)

def get_connected_interfaces(shell):
    """Get list of connected interfaces"""
    print(f"\n[INFO] Checking connected interfaces...")
    output = send_command(shell, "show interface status | include connected", delay=2)
    
    connected_interfaces = []
    lines = output.split('\n')
    
    for line in lines:
        if 'connected' in line.lower():
            parts = line.split()
            if parts:
                interface = parts[0]
                connected_interfaces.append(interface)
                print(f"[FOUND] Connected interface: {interface}")
    
    return connected_interfaces

def run_cable_diagnostics(shell, interface):
    """Run TDR test on interface"""
    print(f"\n[TEST] Running TDR test on {interface}...")
    
    # Run TDR test
    output = send_command(shell, f"test cable-diagnostics tdr interface {interface}", delay=3)
    
    # Wait for test to complete
    time.sleep(3)
    
    # Get TDR results and shows in nice format
    results_output = send_command(shell, f"show cable-diagnostics tdr interface {interface}", delay=2)
    
    return results_output

def parse_tdr_results(results, interface):
    """Parse TDR results into dictionary"""
    result_data = {
        'Interface': interface,
        'Status': 'Unknown',
        'Length(m)': 'N/A',
        'Fault': 'N/A',
        'Distance(m)': 'N/A'
    }
    
    # Parse TDR results
    lines = results.split('\n')
    for line in lines:
        line = line.strip()
        if 'Pair A' in line:
            parts = line.split()
            if len(parts) >= 5:
                result_data['Status'] = parts[2]  # OK/Open/Short
                result_data['Length(m)'] = parts[3] if parts[3] != 'N/A' else 'N/A'
                if len(parts) >= 6:
                    result_data['Fault'] = parts[4] if parts[4] != 'N/A' else 'N/A'
                    result_data['Distance(m)'] = parts[5] if len(parts) > 5 and parts[5] != 'N/A' else 'N/A'
    
    # If no Pair A found, check for standard results
    if result_data['Status'] == 'Unknown':
        for line in lines:
            if 'TDR test' in line or 'cable' in line.lower():
                if 'passed' in line.lower() or 'ok' in line.lower():
                    result_data['Status'] = 'OK'
                elif 'fail' in line.lower():
                    result_data['Status'] = 'FAIL'
    
    return result_data

def check_interface_status(shell, interface):
    """Check basic interface status"""
    output = send_command(shell, f"show interface {interface}", delay=2)
    
    status_data = {
        'Admin': 'down',
        'Operational': 'down',
        'Speed': 'N/A',
        'Duplex': 'N/A',
        'Errors': '0'
    }
    
    lines = output.split('\n')
    for line in lines:
        line = line.strip()
        if 'line protocol' in line:
            if 'up' in line:
                status_data['Admin'] = 'up'
            if 'up' in line.split()[-1]:
                status_data['Operational'] = 'up'
        elif 'BW' in line and 'DLY' in line:
            parts = line.split(',')
            for part in parts:
                if 'b/s' in part:
                    status_data['Speed'] = part.strip()
                elif 'duplex' in part:
                    status_data['Duplex'] = part.strip()
        elif 'input errors' in line:
            parts = line.split()
            if len(parts) > 0:
                status_data['Errors'] = parts[0]
    
    return status_data

def main():
    print("="*80)
    print("CABLE DIAGNOSTICS TDR TEST SCRIPT")
    print("="*80)
    print(f"Testing switches: {list(ACCESS_SWITCHES.keys())}")
    print("Only testing CONNECTED interfaces")
    print("="*80)
    
    all_results = []
    
    for switch_ip, po_group in ACCESS_SWITCHES.items():
        print(f"\n{'='*80}")
        print(f"PROCESSING SWITCH: {switch_ip}")
        print(f"{'='*80}")
        
        try:
            # Connect directly to switch
            print(f"[CONNECT] Connecting to {switch_ip}...")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(switch_ip, username=USERNAME, password=PASSWORD, timeout=20)
            print(f"✓ Connected to {switch_ip}")
            
            shell = ssh.invoke_shell()
            shell.settimeout(10)
            time.sleep(3)
            
            # Read initial banner
            read_shell_output(shell)
            
            # Set terminal length
            send_command(shell, "terminal length 0", delay=1)
            
            # Get connected interfaces
            connected_interfaces = get_connected_interfaces(shell)
            
            if not connected_interfaces:
                print(f"[WARNING] No connected interfaces found on {switch_ip}")
                all_results.append({
                    'Switch': switch_ip,
                    'Interface': 'N/A',
                    'Status': 'No connected interfaces',
                    'Length(m)': 'N/A',
                    'Fault': 'N/A',
                    'Distance(m)': 'N/A'
                })
            else:
                print(f"\n[INFO] Found {len(connected_interfaces)} connected interfaces")
                
                # Test each connected interface
                for interface in connected_interfaces:
                    print(f"\n[TEST] Testing interface {interface}...")
                    
                    # Check interface status first
                    print(f"[STATUS] Checking interface status...")
                    status_data = check_interface_status(shell, interface)
                    
                    # Run TDR test
                    tdr_results = run_cable_diagnostics(shell, interface)
                    
                    # Parse results
                    parsed_data = parse_tdr_results(tdr_results, interface)
                    
                    # Combine with switch info
                    final_data = {
                        'Switch': switch_ip,
                        'Interface': interface,
                        'Status': parsed_data['Status'],
                        'Length(m)': parsed_data['Length(m)'],
                        'Fault': parsed_data['Fault'],
                        'Distance(m)': parsed_data['Distance(m)'],
                        'Admin': status_data['Admin'],
                        'Operational': status_data['Operational'],
                        'Speed': status_data['Speed'],
                        'Duplex': status_data['Duplex']
                    }
                    
                    all_results.append(final_data)
                    
                    # Print individual results
                    print(f"\n[TDR RESULTS] {interface}:")
                    print(f"  Status: {parsed_data['Status']}")
                    print(f"  Length: {parsed_data['Length(m)']}m")
                    print(f"  Fault: {parsed_data['Fault']}")
                    print(f"  Distance to fault: {parsed_data['Distance(m)']}m")
                    print(f"  Admin/Operational: {status_data['Admin']}/{status_data['Operational']}")
                    print(f"  Speed/Duplex: {status_data['Speed']} / {status_data['Duplex']}")
            
            # Close connection
            shell.close()
            ssh.close()
            print(f"\n[INFO] Disconnected from {switch_ip}")
            
        except Exception as e:
            print(f"\n❌ ERROR connecting to {switch_ip}: {e}")
            all_results.append({
                'Switch': switch_ip,
                'Interface': 'Connection Failed',
                'Status': f'ERROR: {str(e)[:50]}',
                'Length(m)': 'N/A',
                'Fault': 'N/A',
                'Distance(m)': 'N/A'
            })
    
    # Display results in table format
    print(f"\n{'='*80}")
    print("CABLE DIAGNOSTICS RESULTS SUMMARY")
    print("="*80)
    
    if all_results:
        # Prepare table data
        table_data = []
        for result in all_results:
            table_data.append([
                result['Switch'],
                result['Interface'],
                result['Status'],
                result['Length(m)'],
                result['Fault'],
                result['Distance(m)'],
                f"{result['Admin']}/{result.get('Operational', 'N/A')}",
                result.get('Speed', 'N/A'),
                result.get('Duplex', 'N/A')
            ])
        
        # Display table
        headers = ['Switch', 'Interface', 'TDR Status', 'Length(m)', 'Fault', 'Dist(m)', 'Admin/Oper', 'Speed', 'Duplex']
        print(tabulate(table_data, headers=headers, tablefmt='grid'))
        
        # Summary statistics
        total_tests = len([r for r in all_results if r['Interface'] != 'N/A' and 'Connection' not in r['Interface']])
        passed_tests = len([r for r in all_results if r['Status'] == 'OK'])
        failed_tests = len([r for r in all_results if r['Status'] in ['FAIL', 'Open', 'Short']])
        
        print(f"\nSUMMARY:")
        print(f"  Total switches tested: {len(ACCESS_SWITCHES)}")
        print(f"  Total interfaces tested: {total_tests}")
        print(f"  Passed: {passed_tests}")
        print(f"  Failed: {failed_tests}")
        print(f"  Connection errors: {len([r for r in all_results if 'ERROR' in r['Status']])}")
    
    print(f"\n{'='*80}")
    print("TEST COMPLETED")
    print("="*80)

if __name__ == "__main__":
    main()
```
