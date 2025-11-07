import base64
import logging
from io import BytesIO
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance

# Import your existing function to send attachments
from zoho_alarm_pvt_comment import add_private_comment_with_attachment

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def detect_system_type(raw_text: str) -> str:
    """
    Detects whether the system report is from Windows or Linux/Unix.
    """
    text_lower = raw_text.lower()
    if any(keyword in text_lower for keyword in ['windows', 'powershell', 'deviceid', 'windowsproductname']):
        return 'windows'
    elif any(keyword in text_lower for keyword in ['linux', 'ubuntu', 'centos', 'uname', 'lscpu', 'journalctl']):
        return 'linux'
    else:
        return 'generic'


def format_system_report(raw_text: str) -> str:
    """
    Formats the raw system report text for better visual presentation.
    Handles both Windows and Linux system reports.
    """
    if not raw_text.strip():
        return "<No data available>"
    
    system_type = detect_system_type(raw_text)
    lines = raw_text.split('\n')
    formatted_lines = []
    current_section = ""
    
    # Add system type indicator
    if system_type == 'windows':
        formatted_lines.append("🪟 MICROSOFT WINDOWS SYSTEM REPORT")
    elif system_type == 'linux':
        formatted_lines.append("🐧 LINUX/UNIX SYSTEM REPORT")
    else:
        formatted_lines.append("🖥️ SYSTEM REPORT")
    
    formatted_lines.append("═" * 50)
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Skip ANSI color codes and timestamps for Linux reports
        if line.startswith('\033[') or re.match(r'^\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2}', line):
            continue
            
        # Detect section headers
        if '=====' in line or line.startswith('=== ') or '---' in line:
            section_name = re.sub(r'[=\-\[\]]+', '', line).strip()
            # Remove timestamp patterns from section names
            section_name = re.sub(r'\s*-\s*\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2} \w+ \d{4}', '', section_name)
            
            if section_name:
                if formatted_lines and not formatted_lines[-1].startswith("═"):
                    formatted_lines.append("")
                formatted_lines.append(f"📊 {section_name.upper()}")
                formatted_lines.append("─" * min(60, len(section_name) + 4))
                current_section = section_name.lower()
            continue
        
        # Format based on system type and section
        if system_type == 'windows':
            formatted_lines.extend(format_windows_section(line, current_section))
        elif system_type == 'linux':
            formatted_lines.extend(format_linux_section(line, current_section))
        else:
            formatted_lines.extend(format_generic_section(line, current_section))
    
    return '\n'.join(formatted_lines)


def format_windows_section(line: str, current_section: str) -> list:
    """Format Windows-specific system information."""
    formatted = []
    
    if 'operating system' in current_section:
        if 'Windows' in line and any(arch in line for arch in ['64-bit', '32-bit', 'x64', 'x86']):
            parts = line.split()
            if len(parts) >= 3:
                os_name = ' '.join(parts[:-2])
                version = parts[-2] if len(parts) > 2 else ''
                arch = parts[-1]
                formatted.append(f"  🪟 OS: {os_name}")
                if version:
                    formatted.append(f"  📦 Version: {version}")
                formatted.append(f"  🏗️ Architecture: {arch}")
        elif line and not any(skip in line.lower() for skip in ['windowsproductname', 'windowsversion', '---']):
            formatted.append(f"  {line}")
    
    elif 'uptime' in current_section:
        if 'Last Boot Time' in line or 'Uptime (Days)' in line or '---' in line:
            return []
        parts = line.split()
        if len(parts) >= 3 and any(char.isdigit() for char in line):
            if '/' in parts[0]:  # Date format
                boot_time = ' '.join(parts[:-1])
                uptime_days = parts[-1]
                formatted.append(f"  🕐 Last Boot: {boot_time}")
                formatted.append(f"  ⏱️ Uptime: {uptime_days} days")
    
    elif 'cpu info' in current_section:
        if 'Name' in line and 'NumberOfCores' in line or '---' in line:
            return []
        if 'Intel' in line or 'AMD' in line:
            parts = line.split()
            cpu_name = ' '.join(parts[:-1]) if parts[-1].isdigit() else line
            cores = parts[-1] if parts[-1].isdigit() else ''
            formatted.append(f"  🔧 Processor: {cpu_name}")
            if cores:
                formatted.append(f"  🧮 Cores: {cores}")
        elif line.strip().isdigit():
            formatted.append(f"  🧮 Cores: {line}")
    
    elif 'disk usage' in current_section or 'top folders' in current_section:
        if any(skip in line.lower() for skip in ['folder', 'sizemb', '---']):
            return []
        parts = line.split()
        if len(parts) >= 2 and parts[-1].replace('.', '').isdigit():
            folder_name = parts[0]
            size = parts[-1]
            formatted.append(f"  📁 {folder_name:<20} {size:>10} MB")
    
    elif 'filesystem usage' in current_section:
        if any(skip in line.lower() for skip in ['deviceid', 'size', 'free', '---']):
            return []
        parts = line.split()
        if len(parts) >= 3:
            drive = parts[0]
            total_size = parts[1]
            free_space = parts[2]
            formatted.append(f"  💾 Drive {drive:<4} Total: {total_size:>8} GB  Free: {free_space:>8} GB")
    
    elif 'cpu processes' in current_section:
        if any(skip in line.lower() for skip in ['name', 'cpu', 'id', '---']):
            return []
        parts = line.split()
        if len(parts) >= 3:
            process_name = parts[0]
            pid = parts[1]
            cpu_usage = parts[2]
            formatted.append(f"  🔥 {process_name:<25} PID: {pid:<8} CPU: {cpu_usage}")
    
    elif 'memory processes' in current_section:
        if any(skip in line.lower() for skip in ['name', 'memory', 'id', '---']):
            return []
        parts = line.split()
        if len(parts) >= 3:
            process_name = parts[0]
            pid = parts[1]
            memory = parts[2]
            formatted.append(f"  🧠 {process_name:<25} PID: {pid:<8} RAM: {memory} MB")
    
    else:
        if line and not line.startswith('-') and '---' not in line:
            formatted.append(f"  {line}")
    
    return formatted


def format_linux_section(line: str, current_section: str) -> list:
    """Format Linux/Unix-specific system information."""
    formatted = []
    
    if 'os info' in current_section or 'system' in current_section:
        if line.startswith('Linux') or 'PRETTY_NAME' in line:
            if 'PRETTY_NAME=' in line:
                os_name = line.split('=')[1].strip('"')
                formatted.append(f"  🐧 OS: {os_name}")
            else:
                formatted.append(f"  🖥️ System: {line}")
    
    elif 'uptime' in current_section or 'load' in current_section:
        if 'up' in line and ('day' in line or 'min' in line or ':' in line):
            formatted.append(f"  ⏱️ {line}")
    
    elif 'cpu info' in current_section:
        if 'Model name' in line:
            cpu = line.split(':')[1].strip() if ':' in line else line
            formatted.append(f"  🔧 Processor: {cpu}")
        elif 'CPU(s)' in line:
            cores = line.split(':')[1].strip() if ':' in line else line
            formatted.append(f"  🧮 CPU Cores: {cores}")
    
    elif 'memory usage' in current_section:
        if 'Mem:' in line:
            parts = line.split()
            if len(parts) >= 4:
                total = parts[1]
                used = parts[2]
                free = parts[3]
                formatted.append(f"  🧠 Memory - Total: {total}  Used: {used}  Free: {free}")
    
    elif 'disk usage' in current_section:
        if 'total' in line.lower():
            parts = line.split()
            if len(parts) >= 6:
                filesystem = parts[0]
                size = parts[1]
                used = parts[2]
                avail = parts[3]
                use_percent = parts[4]
                formatted.append(f"  💾 Total Disk - Size: {size}  Used: {used} ({use_percent})  Available: {avail}")
    
    elif 'cpu processes' in current_section:
        if 'PID' in line and 'COMMAND' in line:
            return []
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            pid = parts[0]
            command = parts[1]
            cpu = parts[2]
            formatted.append(f"  🔥 {command:<25} PID: {pid:<8} CPU: {cpu}%")
    
    elif 'memory processes' in current_section:
        if 'PID' in line and 'COMMAND' in line:
            return []
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            pid = parts[0]
            command = parts[1]
            mem = parts[2]
            formatted.append(f"  🧠 {command:<25} PID: {pid:<8} RAM: {mem}%")
    
    elif 'logged-in users' in current_section:
        if line and not line.startswith('USER'):
            formatted.append(f"  👤 {line}")
    
    elif 'network' in current_section or 'listening ports' in current_section:
        if line and not any(skip in line for skip in ['State', 'Local Address', 'Proto']):
            formatted.append(f"  🌐 {line}")
    
    elif 'recent logs' in current_section:
        if line and not line.startswith('--'):
            formatted.append(f"  📝 {line}")
    
    elif 'eks' in current_section or 'kubernetes' in current_section:
        if line and not line.startswith('NAME'):
            formatted.append(f"  ☸️ {line}")
    
    elif 'failed' in current_section or 'ssh' in current_section:
        if line and 'Failed password' in line:
            formatted.append(f"  🚨 {line}")
    
    else:
        if line and not line.startswith('-'):
            formatted.append(f"  {line}")
    
    return formatted


def format_generic_section(line: str, current_section: str) -> list:
    """Format generic system information when type cannot be determined."""
    formatted = []
    if line and not line.startswith('-') and '---' not in line:
        formatted.append(f"  {line}")
    return formatted

def text_to_image(
    text: str,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    font_size: int = 18,
    padding: int = 50,    
    line_spacing: int = 10,  
    background_color: str = "#ffffff",  
    text_color: str = "#1a202c",       
    highlight_color: str = "#edf2f7",
    table_header_color: str = "#4a5568",
    table_row_colors: tuple = ("#f7fafc", "#edf2f7"),
    shadow_color: str = "#b7c4d6"
) -> bytes:
    """
    Converts multiline text to a PNG image with enhanced table-style formatting for better visibility.
    """
    if not text.strip():
        text = "📄 No data available"

    formatted_text = format_system_report(text)
    lines = formatted_text.split('\n')

    try:
        font = ImageFont.truetype(font_path, font_size)
        header_font = ImageFont.truetype(font_path, font_size + 6)  # Larger header font
    except OSError as e:
        logger.warning(f"Failed to load font {font_path}: {e}. Falling back to default font.")
        font = ImageFont.load_default()
        header_font = font

    line_metrics, max_width, total_height = [], 0, 0
    table_lines = []
    column_widths = []

    # Pass 1: Collect line metrics and measure columns
    for line in lines:
        is_main_header = line.startswith(('🪟', '🐧', '🖥️'))
        is_section_header = line.startswith('📊')
        is_separator = '─' in line or '═' in line
        current_font = header_font if (is_main_header or is_section_header) else font

        if re.search(r'\s{2,}|\t', line):
            cols = re.split(r'\s{2,}|\t+', line.strip())
            table_lines.append((line, cols, current_font))
            for i, col in enumerate(cols):
                col_width = current_font.getlength(col or " ")
                if i >= len(column_widths):
                    column_widths.append(col_width)
                else:
                    column_widths[i] = max(column_widths[i], col_width)
            text_width = sum(column_widths) + len(column_widths) * 30  # Increased column spacing
        else:
            text_width = current_font.getlength(line if line else " ")

        bbox = current_font.getbbox(line if line else " ")
        height = bbox[3] - bbox[1]

        line_metrics.append({
            'text': line,
            'is_table': bool(re.search(r'\s{2,}|\t', line)),
            'height': height,
            'font': current_font,
            'is_main_header': is_main_header,
            'is_section_header': is_section_header,
            'is_separator': is_separator
        })

        max_width = max(max_width, text_width)
        total_height += height + line_spacing

    image_width = int(max_width + 2 * padding + 150)  # Increased for better fit
    image_height = int(total_height + 2 * padding + 100)

    # Background
    try:
        bg_img = Image.open("os-image.webp").convert("RGBA")
        bg_img = ImageOps.fit(bg_img, (image_width, image_height))
        white_bg = Image.new("RGBA", bg_img.size, (255, 255, 255, 255))
        faded_bg = Image.blend(white_bg, bg_img, alpha=0.2)  # Reduced alpha for less distraction
        img = faded_bg.convert("RGB")
    except Exception as e:
        logger.warning(f"Failed to load background image os-image.webp: {e}. Using solid background color instead.")
        img = Image.new("RGB", (image_width, image_height), color=background_color)

    draw = ImageDraw.Draw(img)

    # Outer border with subtle shadow
    draw.rectangle([5, 5, image_width-5, image_height-5], outline=shadow_color, width=3)
    draw.rectangle([2, 2, image_width-2, image_height-2], outline="#e2e8f0", width=2)

    y = padding
    table_line_index = 0
    row_counter = 0

    for metric in line_metrics:
        if not metric['text']:
            y += line_spacing
            continue

        current_font = metric['font']

        if metric['is_table']:
            line, cols, _ = table_lines[table_line_index]
            table_line_index += 1
            x = padding
            row_top = y
            row_bottom = y + metric['height'] + line_spacing

            # Determine row background color
            if row_counter == 0:
                row_bg_color = table_header_color  # Darker header
            else:
                row_bg_color = table_row_colors[row_counter % 2]  # Alternating colors

            # Fill the entire row
            draw.rectangle(
                [padding - 5, y - 3,
                 padding + sum(column_widths) + len(column_widths) * 30 + 5, y + metric['height'] + 3],
                fill=row_bg_color
            )

            # Draw vertical grid lines
            for i in range(len(column_widths) + 1):
                x_pos = padding + sum(column_widths[:i]) + i * 30
                draw.line([(x_pos, row_top - 3), (x_pos, row_bottom + 3)], fill="#cbd5e0", width=2)

            # Draw horizontal lines
            draw.line([(padding, row_top - 3), (padding + sum(column_widths) + len(column_widths) * 30, row_top - 3)],
                      fill="#cbd5e0", width=2)
            draw.line([(padding, row_bottom + 3), (padding + sum(column_widths) + len(column_widths) * 30, row_bottom + 3)],
                      fill="#cbd5e0", width=2)

            # Draw cell content
            for i, col in enumerate(cols):
                col_text = col.strip()
                cell_x = x + 10
                draw.text((cell_x, y), col_text, fill=text_color, font=current_font)
                x += column_widths[i] + 30
            row_counter += 1
            y += metric['height'] + line_spacing
        else:
            text_bbox = current_font.getbbox(metric['text'])
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            # Add shadow for headers
            if metric['is_main_header'] or metric['is_section_header']:
                shadow_rect = [
                    padding - 8, y - 3,
                    padding + text_width + 8, y + text_height + 3
                ]
                draw.rectangle(shadow_rect, fill=shadow_color)
            highlight_rect = [
                padding - 5, y - 2,
                padding + text_width + 5, y + text_height + 2
            ]
            draw.rectangle(highlight_rect, fill=highlight_color)
            draw.text((padding, y), metric['text'], fill=text_color, font=current_font)
            y += metric['height'] + line_spacing

    output = BytesIO()
    img.save(output, format="PNG", optimize=True, quality=95)
    return output.getvalue()

def send_tree_output_to_zoho(
    ticket_id: str,
    clean_output: str,
    comment_text: str = "📊 System Health Report - Detailed analysis attached as image"
) -> dict:
    """
    Converts system report text to a beautiful image and sends it as an attachment to Zoho ticket.
    """
    logger.info("Converting system report to beautiful image...")
    image_bytes = text_to_image(clean_output)

    logger.info("Encoding image to base64...")
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    logger.info(f"Uploading enhanced system report image to Zoho ticket {ticket_id}...")
    response = add_private_comment_with_attachment(
        ticket_id=ticket_id,
        comment_text=comment_text,
        image_base64=image_base64,
        image_filename="system_health_report.png"
    )

    logger.info(f"Successfully posted enhanced system report to Zoho ticket {ticket_id}.")
    return response