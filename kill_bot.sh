#!/bin/bash
PID=$(ps aux | grep 'main.py' | grep -v grep | awk '{print $2}')
if [ -n "$PID" ]; then
  kill -KILL $PID
  echo "Killed process $PID"
else
  echo "Process not found"
fi
