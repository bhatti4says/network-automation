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
    "password": "Xadmin74377",
    "fast_cli": False,  # safer for interactive ssh prompts
}

# -------------------------------
# Target switches (SSH from jump)
# -------------------------------
switch_list = [
    '10.10.40.245',
    '10.10.40.10',
    '10.10.40.38',
    '10.10.40.248'
]

SW_USERNAME = "cisco"          # Only used if a switch ever asks for Username:
SW_PASSWORD = "Xadmin74377"    # Per your note: switch typically asks for password directly

# -------------------------------
# Prompt/Session helpers
# -------------------------------
def _handle_ssh_prompts_via_timing(conn, first_output):
    """
    Handle common SSH prompts when running 'ssh <ip>' from within the jump host.
    Returns once we believe we’re at a device prompt.
    """
    out = first_output

    # First time host key prompt
    if "yes/no" in out.lower():
        out = conn.send_command_timing("yes")

    # Some devices may ask Username (rare in your case)
    if "username" in out.lower():
        out = conn.send_command_timing(SW_USERNAME)

    # Password prompt (matches 'password'/'Password')
    if "assword" in out:
        out = conn.send_command_timing(SW_PASSWORD)

    # If we land at user exec '>'
    if ">" in out:
        out = conn.send_command_timing("enable")
        if "assword" in out:
            out = conn.send_command_timing(SW_PASSWORD)

    # Flush banners if needed
    if not out.strip().endswith(("#", ">")):
        out = conn.send_command_timing("\n")

    return out

def _enter_enable_and_pager_off(conn):
    """Ensure we’re privileged and disable paging."""
    out = conn.send_command_timing("enable")
    if "assword" in out:
        conn.send_command_timing(SW_PASSWORD)
    conn.send_command_timing("terminal length 0")


# -------------------------------
# Discovery & parsing
# -------------------------------
def _get_connected_copper_ports(conn):
    """
    Parse 'show interfaces status' where status is 'connected'
    and interface looks like Gi*, Fa*, Te*, Eth* (ignore Po/Vl).
    """
    show_status = conn.send_command("show interfaces status")
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
    From 'show cable-diagnostics tdr interface X' output,
    extract speed like '1000M', '100M', or return 'N/A'.
    """
    # Look for a header line that contains the speed (Cisco usually prints it in the table)
    # Example:
    # Interface   Speed ...
    # Gi1/0/11    1000M ...
    speed_match = re.search(r"\n\s*\S+\s+(\d{2,4}M)\s", output_text)
    if speed_match:
        return speed_match.group(1)
    # Fallbacks seen on some platforms
    m2 = re.search(r"Speed\s*[:=]\s*(\d{2,4}M)", output_text, re.IGNORECASE)
    return m2.group(1) if m2 else "N/A"


def _parse_pairs_status(output_text):
    """
    Returns:
      pairs: dict like { 'A': {'status': 'Normal', 'length': 12}, ... }
      not_supported: True if output indicates TDR not supported
    """
    pairs = {}
    not_supported = False

    if re.search(r"not\s+supported", output_text, re.IGNORECASE):
        return pairs, True

    # Typical TDR table lines like:
    # Pair A     12   +/- 10 meters  Pair A      Normal
    # Pair B     12   +/- 10 meters  Pair B      Normal
    # Sometimes length may be '-', or '0'
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
    Decide the single-line status string & emoji for the interface row.
    Rules:
      - 1000M: Expect ALL pairs A-D 'Normal' and non-zero-ish length → ✅ 1000M – ALL pairs active
               If any pair not Normal or missing → ⛔ 1000M – Check cable/pairs
      - 100M:  Expect only pairs A/B active; C/D often show 0m or not present
               If A/B Normal → ⚠️ 100M – Pair C/D inactive (Expected 0m)
               Else ⛔ 100M – Check cable
      - N/A or Not Supported: ⚪ Not Supported (SFP/Fiber or no copper)
    """
    speed = speed.upper() if speed else "N/A"

    if speed == "N/A":
        return "⚪ Not Supported (SFP/Fiber)"

    # Build quick verdicts
    def is_normal(p): return p in pairs and pairs[p].get("status", "").lower() == "normal"

    if speed.startswith("1000"):
        if all(is_normal(p) for p in ("A", "B", "C", "D")):
            return "✅ 1000M – ALL pairs active"
        else:
            return "⛔ 1000M – Check cable/pairs"
    elif speed.startswith("100"):
        # For 100M, A/B should be Normal. C/D commonly 0m or absent.
        if is_normal("A") and is_normal("B"):
            return "⚠️ 100M – Pair C/D inactive (Expected 0m)"
        else:
            return "⛔ 100M – Check cable"
    else:
        # Other speeds (10M, 2500M, etc.) – keep conservative
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
    # Trigger
    for intf in ports:
        conn.send_command(f"test cable-diagnostics tdr interface {intf}", expect_string=r"#")

    # Wait for hardware to finish
    time.sleep(10)

    # Collect and summarize
    rows = []
    for intf in ports:
        raw = conn.send_command(f"show cable-diagnostics tdr interface {intf}")
        # Parse speed & pairs
        speed = _parse_speed_from_tdr(raw)
        pairs, not_supported = _parse_pairs_status(raw)
        if not_supported:
            rows.append({"intf": intf, "speed": "N/A", "status": "⚪ Not Supported (SFP/Fiber)"})
            continue

        status = _summarize_interface(speed, pairs)
        rows.append({"intf": intf, "speed": speed, "status": status})

    return rows


def _print_switch_table(sw_ip, rows):
    """
    Print a single compact table: Interface | Speed | Status
    """
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
    jump = ConnectHandler(**jump_host)
    _enter_enable_and_pager_off(jump)

    for sw_ip in switch_list:
        print("\n" + "="*74)
        print(f"Connecting from jump host to switch {sw_ip} (ssh {sw_ip})")

        # Start SSH to switch (no username in cmd, per your behavior)
        first = jump.send_command_timing(f"ssh {sw_ip}")

        # Handle prompts (password directly; robust to username/hostkey)
        _handle_ssh_prompts_via_timing(jump, first)

        # Ensure enable and no paging on the target switch session
        _enter_enable_and_pager_off(jump)

        # Discover ports
        ports = _get_connected_copper_ports(jump)
        if not ports:
            print(f"No connected copper ports found on {sw_ip}. Skipping.")
            jump.send_command_timing("exit")
            continue

        # Run and gather a single summary table
        rows = _run_tdr_batch_and_collect_table(jump, ports)
        _print_switch_table(sw_ip, rows)

        # Exit back to jump host
        jump.send_command_timing("exit")
        print(f"Completed {sw_ip}")

    jump.disconnect()
    print("\nAll switches completed.")


if __name__ == "__main__":
    run_tdr_via_jump()