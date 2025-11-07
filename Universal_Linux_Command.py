system_command="""
#!/bin/bash

print_header() {
  echo -e "\\n\033[1;34m=== $1 ===\033[0m"
}

print_section() {
  print_header "$1"
  eval "$2" || echo "Unable to fetch $1"
}

print_header "SYSTEM SNAPSHOT - $(date)"

print_section "OS INFO" "uname -a && cat /etc/os-release 2>/dev/null | grep PRETTY_NAME"
print_section "UPTIME & LOAD" "uptime"
print_section "CPU INFO" "lscpu | grep -E 'Model name|CPU\\(s\\)'"
print_section "MEMORY USAGE" "free -h"
print_section "DISK USAGE" "df -h --total | grep total"
print_section "TOP CPU PROCESSES" "ps -eo pid,comm,%cpu --sort=-%cpu | head -n 6"
print_section "TOP MEMORY PROCESSES" "ps -eo pid,comm,%mem --sort=-%mem | head -n 6"
print_section "LOGGED-IN USERS" "who"
print_section "NETWORK (First 10 Conns)" "ss -tuna | head -n 10"
print_section "LISTENING PORTS" "ss -tulwn | grep LISTEN"
print_section "RECENT LOGS" "journalctl -n 5 --no-pager 2>/dev/null || tail -n 5 /var/log/syslog"

# EKS summary (only crash/restart info)
if command -v kubectl >/dev/null 2>&1; then
  print_header "EKS SUMMARY"
  print_section "CrashLoop/Error Pods" "kubectl get pods --all-namespaces | grep -E 'CrashLoopBackOff|Error' || echo 'No crash/error pods'"
  print_section "Node Status" "kubectl get nodes -o wide"
else
  echo "kubectl not found. Skipping EKS diagnostics."
fi

# Minimal security check
print_section "FAILED SSH ATTEMPTS (last 5)" "
grep 'Failed password' /var/log/auth.log 2>/dev/null | tail -n 5 || \
grep 'Failed password' /var/log/secure 2>/dev/null | tail -n 5
"

print_header "END OF SHORT REPORT"
"""