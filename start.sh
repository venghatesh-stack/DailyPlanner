#!/usr/bin/env bash
echo "Starting on port: $PORT"
exec gunicorn app:app --bind 0.0.0.0:$PORT --log-level debug