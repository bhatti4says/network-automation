import time
import re
from netmiko import ConnectHandler

# -------------------------------
# Jump host details (Cisco IOS)
# -------------------------------
jump_host = {
    "device_type": "cisco_ios",
    "host": "10.10.40.254",
    "username": "cisco",
    "password": "Cisco1234",
    "fast_cli": False,
    # IMPORTANT: Do NOT enable session_log here; it would capture passwords in plain text.
    # "session_log": "netmiko_session.log",
}

# -------------------------------
# Target switches (SSH from jump)
# -------------------------------
switch_list = [
    '10.10.40.245',
    '10.10.40.10',
    '10.10.40.38',
    '10.10.40.240',
    '10.10.40.248',
    '10.10.40.249'
]

SW_USERNAME = "cisco"          # Only if a switch ever asks for Username:
SW_PASSWORD = "Cisco1234"    # Switches prompt for password directly in your environment

# Optional: write a sanitized activity log (no secrets)
ACTIVITY_LOG_FILE = None  # e.g., set to "tdr_activity.log" if you want a masked log

def _activity_log(line: str):
    """Write high-level, sanitized steps to a log file (no secrets)."""
    if ACTIVITY_LOG_FILE:
        with open(ACTIVITY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")

# -------------------------------
# Utility: Echo commands safely
# -------------------------------
def send_cmd(conn, command, **kwargs):
    """Print and (optionally) log the command before sending."""
    print(f">>> {command}")
    _activity_log(f">>> {command}")
    return conn.send_command(command, **kwargs)

def send_cmd_timing(conn, command, mask=False):
    """
    Print and (optionally) log the command before sending.
    If mask=True, show '******' instead of the real command (for passwords).
    """
    shown = "******" if mask else command
    print(f">>> {shown}")
    _activity_log(f">>> {shown}")
    return conn.send_command_timing(command)

# -------------------------------
# Prompt/session helpers
# -------------------------------
def _handle_ssh_prompts_via_timing(conn, first_output):
    """
    Handle SSH prompts when running 'ssh <ip>' from within the jump host.
    Ensures passwords are never echoed in clear text.
    """
    out = first_output

    # First-time host key prompt
    if "yes/no" in out.lower():
        out = send_cmd_timing(conn, "yes")

    # Some devices may ask Username (rare in your case)
    if "username" in out.lower():
        out = send_cmd_timing(conn, SW_USERNAME)

    # Password prompt (matches 'password'/'Password')
    if "assword" in out:
        out = send_cmd_timing(conn, SW_PASSWORD, mask=True)

    # We are NOT sending 'enable' per your environment
    # If needed in the future, you could conditionally add it back here.

    # Flush banners if needed
    if not out.strip().endswith(("#", ">")):
        out = send_cmd_timing(conn, "\n")

    return out

def _pager_off(conn):
    """Disable paging; works in user exec on IOS."""
    send_cmd_timing(conn, "terminal length 0")

# -------------------------------
# Discovery & parsing
# -------------------------------
def _get_connected_copper_ports(conn):
    """
    Parse 'show interfaces status' where status is 'connected'
    and interface looks like Gi*, Fa*, Te*, Eth* (ignore Po/Vl).
    """
    show_status = send_cmd(conn, "show interfaces status")
    connected_ports = []
    for line in show_status.splitlines():
        if "connected" in line:
            parts = line.split()
            if parts:
                intf = parts[0]
                if intf.startswith(("Gi", "Fa", "Te", "Eth")) and not intf.startswith(("Po", "Vl")):
                    connected_ports.append(intf)
    return connected_ports

def _parse_speed_from_tdr(output_text):
    """
    Extract speed like '1000M', '100M', else 'N/A'.
    """
    m = re.search(r"\n\s*\S+\s+(\d{2,4}M)\s", output_text)
    if m:
        return m.group(1)
    m2 = re.search(r"Speed\s*[:=]\s*(\d{2,4}M)", output_text, re.IGNORECASE)
    return m2.group(1) if m2 else "N/A"

def _parse_pairs_status(output_text):
    """
    Returns:
      pairs: dict { 'A': {'status': 'Normal', 'length': 12}, ... }
      not_supported: True if output indicates TDR not supported
    """
    pairs = {}
    not_supported = False

    if re.search(r"not\s+supported", output_text, re.IGNORECASE):
        return pairs, True

    pair_line = re.compile(
        r"Pair\s+([ABCD])\s+(\d+|-\s?)\s+\+/-\s+\d+\s+meters\s+Pair\s+[ABCD]\s+(\S+)",
        re.IGNORECASE
    )

    for line in output_text.splitlines():
        m = pair_line.search(line)
        if m:
            p = m.group(1).upper()
            length_raw = m.group(2).strip()
            status = m.group(3)
            try:
                length_val = int(length_raw) if length_raw.isdigit() else None
            except ValueError:
                length_val = None
            pairs[p] = {"status": status, "length": length_val}

    return pairs, not_supported

def _summarize_interface(speed, pairs):
    """
    Single-line status string & emoji for the interface row.
    """
    speed = speed.upper() if speed else "N/A"

    if speed == "N/A":
        return "⚪ Not Supported (SFP/Fiber)"

    def is_normal(p): return p in pairs and pairs[p].get("status", "").lower() == "normal"

    if speed.startswith("1000"):
        if all(is_normal(p) for p in ("A", "B", "C", "D")):
            return "✅ 1000M – ALL pairs active"
        else:
            return "⛔ 1000M – Check cable/pairs"
    elif speed.startswith("100"):
        if is_normal("A") and is_normal("B"):
            return "⚠️ 100M – Pair C/D inactive (Expected 0m)"
        else:
            return "⛔ 100M – Check cable"
    else:
        if all(is_normal(p) for p in ("A", "B", "C", "D") if p in pairs):
            return f"✅ {speed} – Pairs OK"
        return f"⛔ {speed} – Check cable/pairs"

# -------------------------------
# TDR run & collection
# -------------------------------
def _run_tdr_batch_and_collect_table(conn, ports):
    """
    Trigger TDR on all 'ports', wait, then return list of rows:
      [{'intf': 'Gi1/0/1', 'speed': '1000M', 'status': '✅ ...'}, ...]
    """
    for intf in ports:
        send_cmd(conn, f"test cable-diagnostics tdr interface {intf}", expect_string=r"#")

    print("...waiting 10 seconds for TDR to complete...")
    _activity_log("...waiting 10 seconds for TDR to complete...")
    time.sleep(10)

    rows = []
    for intf in ports:
        print(f">>> show cable-diagnostics tdr interface {intf}")
        _activity_log(f">>> show cable-diagnostics tdr interface {intf}")
        raw = conn.send_command(f"show cable-diagnostics tdr interface {intf}")
        speed = _parse_speed_from_tdr(raw)
        pairs, not_supported = _parse_pairs_status(raw)
        if not_supported:
            rows.append({"intf": intf, "speed": "N/A", "status": "⚪ Not Supported (SFP/Fiber)"})
            continue

        status = _summarize_interface(speed, pairs)
        rows.append({"intf": intf, "speed": speed, "status": status})

    return rows

def _print_switch_table(sw_ip, rows):
    """Print a single compact table: Interface | Speed | Status"""
    print(f"\nTDR SUMMARY — {sw_ip}")
    print("=" * 74)
    print(f"{'Interface':<12} | {'Speed':<7} | Status")
    print("-" * 74)
    for r in rows:
        print(f"{r['intf']:<12} | {r['speed']:<7} | {r['status']}")
    print()

# -------------------------------
# Main workflow
# -------------------------------
def run_tdr_via_jump():
    print(f"Connecting to jump host {jump_host['host']}...")
    _activity_log(f"Connecting to jump host {jump_host['host']}...")
    jump = ConnectHandler(**jump_host)

    # No 'enable' required; just turn paging off
    _pager_off(jump)

    for sw_ip in switch_list:
        print("\n" + "="*74)
        print(f"Connecting from jump host to switch {sw_ip} (ssh {sw_ip})")
        _activity_log(f"Connecting to {sw_ip}")

        # Start SSH to switch (no username in cmd)
        first = send_cmd_timing(jump, f"ssh {sw_ip}")

        # Handle prompts safely (mask passwords)
        _handle_ssh_prompts_via_timing(jump, first)

        # Ensure no paging on the target switch session
        _pager_off(jump)

        # Discover ports
        ports = _get_connected_copper_ports(jump)
        if not ports:
            print(f"No connected copper ports found on {sw_ip}. Skipping.")
            _activity_log(f"No connected ports on {sw_ip}; skipping.")
            send_cmd_timing(jump, "exit")
            continue

        # Run and gather a single summary table
        rows = _run_tdr_batch_and_collect_table(jump, ports)
        _print_switch_table(sw_ip, rows)

        # Exit back to jump host
        send_cmd_timing(jump, "exit")
        print(f"Completed {sw_ip}")
        _activity_log(f"Completed {sw_ip}")

    jump.disconnect()
    print("\nAll switches completed.")
    _activity_log("All switches completed.")

if __name__ == "__main__":
    run_tdr_via_jump()
