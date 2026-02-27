import time
import re
from netmiko import ConnectHandler

# 1. Connection Details
device = {
    'device_type': 'cisco_ios',
    'host': '10.20.39.21',
    'username': 'cisco',
    'password': 'Cisco1234',
}

interfaces = ["Gi1/0/8", "Gi1/0/23", "Gi1/0/24"]

def run_smart_tdr():
    try:
        net_connect = ConnectHandler(**device)
        
        # --- BATCH TRIGGER ---
        print("Triggering TDR tests...")
        for intf in interfaces:
            net_connect.send_command(f"test cable-diagnostics tdr interface {intf}")
        
        # --- THE 10-SECOND WAIT ---
        print("Waiting 10 seconds for results...")
        time.sleep(10)

        # --- RETRIEVAL & PARSING ---
        for intf in interfaces:
            output = net_connect.send_command(f"show cable-diagnostics tdr interface {intf}")
            
            # Find the speed using Regex
            speed_match = re.search(r"(\d+M|Auto)", output)
            speed = speed_match.group(1) if speed_match else "Unknown"

            print(f"\n--- Interface: {intf} | Negotiated Speed: {speed} ---")

            if speed == "100M":
                print("⚠️  WARNING: Port is capped at 100M. Pairs C and D will show 0m (Inactive).")
            elif speed == "1000M":
                print("✅ Full Gigabit Link: All 4 pairs should show valid distances.")

            # Print the actual table from the switch
            print(output)

        net_connect.disconnect()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_smart_tdr()