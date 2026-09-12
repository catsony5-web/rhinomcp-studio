#!/bin/bash
exec bash "$(dirname -- "$0")/bootstrap.sh" doctor "$@"
