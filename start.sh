#!/usr/bin/env bash
echo "Starting on port: $PORT"
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000} --log-level debug