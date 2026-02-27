import time
import re
from netmiko import ConnectHandler

# 1. Hardware Connection Details
device = {
    'device_type': 'cisco_ios',
    'host': '10.10.40.254',
    'username': 'cisco',
    'password': 'Xadmin74377',
}

def run_connected_tdr():
    try:
        print(f"Connecting to {device['host']}...")
        net_connect = ConnectHandler(**device)
        
        # 2. IDENTIFY CONNECTED PORTS ONLY
        # This prevents running tests on empty or logical (Po) interfaces
        print("Scanning for 'connected' copper interfaces...")
        status_output = net_connect.send_command("show interfaces status")
        
        # Regex captures interfaces (e.g., Gi1/0/1) only if status is 'connected'
        connected_ports = re.findall(r"(\S+\d+/\d+/\d+|\S+\d+/\d+)\s+.*?\s+connected", status_output)

        if not connected_ports:
            print("No active connected ports found. Exiting.")
            net_connect.disconnect()
            return

        print(f"Found {len(connected_ports)} connected ports: {', '.join(connected_ports)}")

        # 3. BATCH TRIGGER (The "Batch" part of your method)
        print("Triggering TDR tests on all active ports...")
        for intf in connected_ports:
            # We don't wait for output here, just send the command
            net_connect.send_command(f"test cable-diagnostics tdr interface {intf}", expect_string=r"#")
        
        # 4. THE 10-SECOND WAIT
        print("Waiting exactly 10 seconds for hardware to generate reflections...")
        time.sleep(10)

        # 5. RETRIEVAL & ANALYSIS (The "Wait" part of your method)
        print("\n" + "="*80)
        print(f"{'Interface':<15} | {'Speed':<8} | {'Diagnosis'}")
        print("-" * 80)

        for intf in connected_ports:
            output = net_connect.send_command(f"show cable-diagnostics tdr interface {intf}")
            
            # Detect speed to explain the 0m distance on Pairs C/D
            speed_match = re.search(r"(\d+M|Auto|1000|100)", output)
            speed = speed_match.group(1) if speed_match else "N/A"

            # logic for the 0m distance you noticed
            diagnosis = "Normal"
            if "100M" in speed or "100" in speed:
                diagnosis = "Valid (100M uses 2 pairs; C/D at 0m is expected)"
            elif "1000" in speed and "0" in output:
                diagnosis = "Check Cable (Gigabit should use all 4 pairs!)"

            print(f"{intf:<15} | {speed:<8} | {diagnosis}")
            
            # Optional: Print the full raw table for this interface
            # print(output) 

        net_connect.disconnect()
        print("\nDone.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    run_connected_tdr()