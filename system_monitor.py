import psutil
import curses
import os

def get_size(bytes, suffix="B"):
    """Scale bytes to its proper format."""
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor:
            return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor

def get_total_disk_io():
    """Calculate the total disk I/O for all processes (read + write bytes)."""
    total_io = 0
    for proc in psutil.process_iter(attrs=['pid']):
        try:
            io_counters = proc.io_counters()
            total_io += io_counters.read_bytes + io_counters.write_bytes
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total_io

def get_processes_info(sort_by="cpu", ascending=False):
    """Retrieve and format information of all running processes with live disk I/O usage."""
    processes = []
    total_io = get_total_disk_io()  # Get total disk I/O for percentage calculation
    
    for process in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'io_counters']):
        try:
            pid = process.info['pid']
            name = process.info['name'] or "Unknown"
            cpu_percent = process.info['cpu_percent']
            memory_usage = get_size(process.info['memory_info'].rss)

            # Live disk I/O bytes read and written
            io_counters = process.info['io_counters']
            read_bytes = io_counters.read_bytes if io_counters else 0
            write_bytes = io_counters.write_bytes if io_counters else 0
            process_io = read_bytes + write_bytes
            
            # Calculate percentage of total disk usage for this process
            percent_usage = (process_io / total_io * 100) if total_io > 0 else 0
            disk_usage = f"R: {get_size(read_bytes)} W: {get_size(write_bytes)} | %: {percent_usage:.2f}%"

            processes.append((pid, name, cpu_percent, memory_usage, disk_usage, process_io))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    # Sort by specified column
    key_index = 2 if sort_by == "cpu" else 4  # 2 for CPU percent, 4 for process I/O
    processes = sorted(processes, key=lambda x: x[key_index], reverse=not ascending)
    return processes

def display_bar(stdscr, usage, label, y, width, max_value=100):
    """Displays a usage bar with color according to usage level."""
    bar_length = min(int((usage / max_value) * (width - 20)), width - 20)
    bar = "|" * bar_length
    stdscr.addstr(y, 0, f"{label}: [{bar:<{width - 20}}] {usage:.2f}%", curses.A_BOLD)

def monitor_processes(stdscr):
    """Curses screen for monitoring processes with filtering, sorting, and resource bars."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()

    # Define color pairs for high, moderate, and low resource usage
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)    # High usage (Critical)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK) # Moderate usage (Warning)
    curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Low usage (Good)

    sort_by = "cpu"
    ascending = False
    filter_name = ""  # For process name filtering
    filter_pid = None  # For PID filtering
    last_message = ""  # To show feedback messages (e.g., kill status)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Display CPU and Memory Usage Bars
        cpu_usage = psutil.cpu_percent()
        memory_info = psutil.virtual_memory()
        memory_usage_percent = memory_info.percent

        # Safely display the bars, respecting screen width
        if height > 3:  # Ensure there is space for the bars
            display_bar(stdscr, cpu_usage, "CPU   ", 0, width)
            display_bar(stdscr, memory_usage_percent, "Memory", 1, width)

        # Display Total Disk Usage Bar
        total_disk_io = get_total_disk_io()
        total_disk_capacity = psutil.disk_usage('/').total
        # Calculate percentage for the total disk usage in the bar
        total_disk_usage_percentage = (total_disk_io / total_disk_capacity) * 100
        display_bar(stdscr, total_disk_usage_percentage, "Disk  ", 2, width)

        # Display per-core CPU usage
        core_usages = psutil.cpu_percent(percpu=True)
        for i, core_usage in enumerate(core_usages):
            if i + 4 < height:  # Avoid overflow
                label = f"Core {i}"
                display_bar(stdscr, core_usage, label, 4 + i, width)

        # Display header with instructions and search bar
        try:
            if height > 9:  # Ensure there's enough space to display header
                stdscr.addstr(5 + len(core_usages) + 1, 0, "Process Monitor (Press 'q' to Quit)".ljust(width - 1))
                stdscr.addstr(6 + len(core_usages) + 1, 0, "Commands: [f] Filter by Name | [p] Filter by PID | [s] Toggle Sort CPU/Mem | [a] Toggle Asc/Desc | [k] Kill Process".ljust(width - 1))

                # Search Bars
                search_bar_name = "Search Process Name: "
                stdscr.addstr(7 + len(core_usages) + 1, 0, search_bar_name.ljust(width - 1))
                stdscr.addstr(7 + len(core_usages) + 1, len(search_bar_name), filter_name.ljust(width - len(search_bar_name)))

                search_bar_pid = "Filter PID: "
                stdscr.addstr(8 + len(core_usages) + 1, 0, search_bar_pid.ljust(width - 1))
                stdscr.addstr(8 + len(core_usages) + 1, len(search_bar_pid), str(filter_pid) if filter_pid else "None".ljust(width - len(search_bar_pid)))
        except curses.error:
            pass  # Safely handle any overflow issues

        # Fetch and filter process information
        processes = get_processes_info(sort_by=sort_by, ascending=ascending)

        # Apply filters based on name and PID
        if filter_name:
            processes = [p for p in processes if filter_name.lower() in p[1].lower()]
        if filter_pid is not None:
            processes = [p for p in processes if p[0] == filter_pid]

        # Display process table headers
        header_start_row = 9 + len(core_usages)
        try:
            stdscr.addstr(header_start_row, 0, "PID".ljust(10) + "Process Name".ljust(30) + "CPU%".ljust(10) + "Memory".ljust(10) + "Disk I/O")
            stdscr.addstr(header_start_row + 1, 0, "-" * min(width - 1, 80))
        except curses.error:
            pass  # Skip errors if dimensions are too small

        # Display process information, limit to terminal window size
        max_displayable_processes = min(height - (header_start_row + 5), len(processes))

        for idx, process in enumerate(processes[:max_displayable_processes], start=header_start_row + 2):
            pid, name, cpu_percent, memory_usage, disk_usage, _ = process
            
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
        if height > 1:  # Ensure there's space for the message
            stdscr.addstr(height - 2, 0, last_message.ljust(width - 1))

        stdscr.refresh()

        # Handle user input for filtering, sorting, and killing processes
        key = stdscr.getch()
        if key == ord('q'):  # Quit
            break
        try:
            if key == ord('f'):  # Filter by name
                stdscr.addstr(height - 3, 0, "Enter Process Name: ")
                curses.echo()
                name_input = stdscr.getstr(height - 3, 20, 30).decode('utf-8')
                filter_name = name_input.strip()
                curses.noecho()
                last_message = f"Filtering by process name: {filter_name}"
            elif key == ord('p'):  # Filter by PID
                stdscr.addstr(height - 3, 0, "Enter PID: ")
                curses.echo()
                pid_input = stdscr.getstr(height - 3, 10, 10).decode('utf-8')
                filter_pid = int(pid_input.strip()) if pid_input.isdigit() else None
                curses.noecho()
                last_message = ""
            elif key == ord('s'):  # Toggle sorting between CPU and Memory
                sort_by = "memory" if sort_by == "cpu" else "cpu"
                last_message = f"Sorting by {'CPU' if sort_by == 'cpu' else 'Memory'}"
            elif key == ord('a'):  # Toggle ascending/descending sort
                ascending = not ascending
                last_message = f"Sorting in {'ascending' if ascending else 'descending'} order"
            elif key == ord('k'):  # Kill a process
                stdscr.addstr(height - 3, 0, "Enter PID to kill: ")
                curses.echo()
                kill_pid = stdscr.getstr(height - 3, 20, 10).decode('utf-8')
                curses.noecho()
                try:
                    psutil.Process(int(kill_pid)).terminate()
                    last_message = f"Terminated process with PID {kill_pid}"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    last_message = f"Failed to terminate process with PID {kill_pid}"
        except curses.error:
            pass  # Safely ignore any input errors

# Run the curses application
curses.wrapper(monitor_processes)
