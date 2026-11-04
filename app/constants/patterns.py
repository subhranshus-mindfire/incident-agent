"""Regular expressions shared by the services."""

import re

# Strict identifier validation for PromQL label injection defense
SERVICE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


UUID_REGEX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
