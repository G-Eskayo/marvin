#!/bin/bash

# with_network_impairment.sh: Run a command with real OS-level network impairment via dummynet
#
# Usage: with_network_impairment.sh <loss-pct> -- <command>
#
# Requires sudo. Uses macOS pfctl and dnctl to inject packet loss on the loopback interface.
# Example: with_network_impairment.sh 5 -- node bench_cli.js --host 127.0.0.1
#
# WARNING: This modifies system firewall rules. Do NOT run on production systems.

set -e

LOSS_PCT="${1:?Usage: with_network_impairment.sh <loss-pct> -- <command>}"
shift

if [[ "$1" != "--" ]]; then
  echo "Usage: with_network_impairment.sh <loss-pct> -- <command>"
  exit 1
fi
shift

COMMAND=("$@")

# Check if running as root
if [[ $EUID -ne 0 ]]; then
  echo "This script requires sudo to modify pfctl rules"
  exit 1
fi

# Check macOS
if [[ ! "$OSTYPE" == "darwin"* ]]; then
  echo "This script only works on macOS"
  exit 1
fi

# Create a unique pipe number to avoid conflicts
PIPE_NUM=$RANDOM

# Clean up on exit
cleanup() {
  echo "Cleaning up network rules..."
  dnctl pipe delete $PIPE_NUM 2>/dev/null || true
  pfctl -f /etc/pf.conf 2>/dev/null || true
}
trap cleanup EXIT

# Configure the dummynet pipe
echo "Configuring network impairment: $LOSS_PCT% packet loss..."
dnctl pipe $PIPE_NUM config loss $((LOSS_PCT * 10))

# Load pf rules to route loopback through the pipe
PFRULES=$(mktemp)
cat > "$PFRULES" << EOF
pass in on lo0 proto tcp from any to any pipe $PIPE_NUM
pass in on lo0 proto udp from any to any pipe $PIPE_NUM
pass out on lo0 proto tcp from any to any pipe $PIPE_NUM
pass out on lo0 proto udp from any to any pipe $PIPE_NUM
EOF

pfctl -F all -f "$PFRULES"

# Run the command
echo "Running: ${COMMAND[@]}"
"${COMMAND[@]}"
EXIT_CODE=$?

rm -f "$PFRULES"
exit $EXIT_CODE
