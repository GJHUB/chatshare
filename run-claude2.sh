#!/bin/bash
cd /root/projects/chatshare-proxy
claude -p --allowedTools Bash,Edit,Read,Write,MultiEdit \
  "Read TASK2.md and all source files in this project. Then improve the code according to TASK2.md instructions. Make sure to read the existing code first before making changes." \
  > /tmp/claude-proxy2-output.log 2>&1
echo "EXIT_CODE=$?" >> /tmp/claude-proxy2-output.log
openclaw system event --text "Done: Claude Code finished chatshare-proxy task2" --mode now
