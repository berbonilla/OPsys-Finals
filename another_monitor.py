import psutil
import time
import curses

def get_size(bytes, suffix="B"):
    """Scale bytes to its proper format."""
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor

def get_processes_info(sort_by="cpu", ascending=False):
    """Retrieve and format information of all running processes."""
    processes = []
    for process in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'io_counters']):
        try:
            pid = process.info['pid']
            name = process.info['name'] or "Unknown"
            cpu_percent = process.info['cpu_percent']
            memory_usage = get_size(process.info['memory_info'].rss)
            memory_percent = process.info['memory_info'].rss  # Raw bytes for sorting
            # Disk I/O bytes read and written
            io_counters = process.info['io_counters']
            disk_usage = get_size(io_counters.read_bytes + io_counters.write_bytes) if io_counters else "0B"
            disk_bytes = (io_counters.read_bytes + io_counters.write_bytes) if io_counters else 0

            processes.append((pid, name, cpu_percent, memory_usage, memory_percent, disk_usage, disk_bytes))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    # Sort by specified column
    key_index = 2 if sort_by == "cpu" else 4  # 2 for CPU percent, 4 for memory percent
    processes = sorted(processes, key=lambda x: x[key_index], reverse=not ascending)
    return processes

def display_bar(stdscr, usage, label, y, width):
    """Displays a usage bar with color according to usage level."""
    bar_length = min(int((usage / 100) * (width - 20)), width - 20)
    bar = "|" * bar_length
    stdscr.addstr(y, 0, f"{label}: [{bar:<{width - 20}}] {usage:.2f}%", curses.A_BOLD)

def monitor_processes(stdscr):
    """Curses screen for monitoring processes with filtering, sorting, and resource bars."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()

    # Define color pairs for high, moderate, and low resource usage
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)    # High usage
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK) # Moderate usage
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Low usage

    sort_by = "cpu"
    ascending = False
    filter_pid = None
    last_message = ""  # To show feedback messages (e.g., kill status)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Display CPU and Memory Usage Bars
        cpu_usage = psutil.cpu_percent()
        memory_info = psutil.virtual_memory()
        memory_usage_percent = memory_info.percent

        # Disk usage statistics
        disk_usage_info = psutil.disk_usage('/')
        total_disk = get_size(disk_usage_info.total)
        used_disk = get_size(disk_usage_info.used)
        disk_usage_percent = disk_usage_info.percent

        # Safely display the bars, respecting screen width
        display_bar(stdscr, cpu_usage, "CPU Usage", 0, width)
        display_bar(stdscr, memory_usage_percent, "Memory Usage", 1, width)
        display_bar(stdscr, disk_usage_percent, "Disk Usage", 2, width)

        # Display per-core CPU usage
        core_usages = psutil.cpu_percent(percpu=True)
        for i, core_usage in enumerate(core_usages):
            if i + 3 < height:  # Avoid overflow
                label = f"Core {i}"
                display_bar(stdscr, core_usage, label, 3 + i, width)

        # Display header with instructions and search bar
        try:
            stdscr.addstr(3 + len(core_usages) + 1, 0, "Process Monitor (Press 'q' to Quit)".ljust(width - 1))
            stdscr.addstr(4 + len(core_usages) + 1, 0, "Commands: [f] Filter by PID | [s] Toggle Sort CPU/Mem | [a] Toggle Asc/Desc | [k] Kill Process".ljust(width - 1))
            stdscr.addstr(5 + len(core_usages) + 1, 0, f"Filter PID (leave empty to reset): {str(filter_pid) if filter_pid else 'None'}".ljust(width - 1))
        except curses.error:
            pass  # Safely handle any overflow issues

        # Fetch and filter process information
        processes = get_processes_info(sort_by=sort_by, ascending=ascending)
        
        if filter_pid:
            processes = [p for p in processes if p[0] == filter_pid]
        
        # Display process table headers
        header_start_row = 6 + len(core_usages)
        try:
            stdscr.addstr(header_start_row, 0, "PID".ljust(10) + "Process Name".ljust(30) + "CPU%".ljust(10) + "Memory".ljust(10) + "Disk I/O")
            stdscr.addstr(header_start_row + 1, 0, "-" * min(width - 1, 80))
        except curses.error:
            pass  # Skip errors if dimensions are too small

        # Display process information, limit to terminal window size
        max_displayable_processes = min(height - (header_start_row + 5), len(processes))

        for idx, process in enumerate(processes[:max_displayable_processes], start=header_start_row + 2):
            pid, name, cpu_percent, memory_usage, disk_usage, _, _ = process
            
            # Determine color based on resource usage
            if cpu_percent > 80:
                color = curses.color_pair(1)  # High CPU usage
            elif cpu_percent > 40:
                color = curses.color_pair(2)  # Moderate CPU usage
            else:
                color = curses.color_pair(3)  # Low CPU usage
            
            # Display process with the appropriate color
            try:
                stdscr.addstr(idx, 0, f"{pid:<10}{name[:28]:<30}{cpu_percent:<10}{memory_usage:<10}{disk_usage}".ljust(width - 1), color)
            except curses.error:
                pass  # Ignore errors if attempting to write beyond the screen boundaries

        # Display last action message, if any
        stdscr.addstr(height - 2, 0, last_message.ljust(width - 1), curses.A_BOLD)
        stdscr.refresh()

        # Check for input
        try:
            key = stdscr.getch()
            if key == ord('q'):
                break
            elif key == ord('f'):  # Filter by PID
                curses.echo()
                stdscr.addstr(5, 25, " " * (width - 25))  # Clear previous input
                stdscr.addstr(5, 25, "Enter PID: ")
                pid_input = stdscr.getstr(5, 36, 10).decode('utf-8')
                filter_pid = int(pid_input) if pid_input.isdigit() else None
                curses.noecho()
                last_message = ""
            elif key == ord('s'):  # Toggle sorting between CPU and memory
                sort_by = "memory" if sort_by == "cpu" else "cpu"
                filter_pid = None
                last_message = f"Sorting by {sort_by.upper()}"
            elif key == ord('a'):  # Toggle ascending/descending order
                ascending = not ascending
                last_message = f"Sorting in {'ascending' if ascending else 'descending'} order"
            elif key == ord('k'):  # Kill a process
                curses.echo()
                stdscr.addstr(height - 2, 0, "Enter PID to kill: ".ljust(width - 1))
                kill_pid_input = stdscr.getstr(height - 2, 16, 10).decode('utf-8')
                try:
                    kill_pid = int(kill_pid_input)
                    process = psutil.Process(kill_pid)
                    process.terminate()
                    last_message = f"Process {kill_pid} terminated successfully."
                except (ValueError, psutil.NoSuchProcess):
                    last_message = f"Error: Invalid PID {kill_pid_input}."
                except psutil.AccessDenied:
                    last_message = f"Error: Access denied to kill PID {kill_pid_input}."
                curses.noecho()

        except curses.error:
            pass  # Ignore errors from getch in this loop

if __name__ == "__main__":
    print("System Resource Monitor Tool")
    print("Press 'q' to exit\n")
    try:
        curses.wrapper(monitor_processes)
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")