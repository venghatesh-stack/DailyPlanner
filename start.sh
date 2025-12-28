#!/usr/bin/env bash
gunicorn --chdir DailyPlanner.app:app
